"""ALPHA DISCOVERY DATASET — E1 foundation for the sprint.

One row per (member symbol, session, 15-minute formation tick,
10:00–15:30 ET). Every state field uses bars <= tick (known_from
discipline); every forward field uses bars strictly after; forward
fields never appear in the state vector.

STATE: trailing returns (raw + ATR units), SPY same-horizon returns,
beta-adjusted residual (trailing 60-day PIT beta), correlation-matched
sector ETF return, RVOL (cum volume vs same-minute trailing-20-session
median), VWAP distance + slope, opening-range position, overnight gap
in ATR, realized vol, day-range use, spread (Layer A observed surface
with provenance), cross-sectional breadth + rank, time of day.

FORWARD: 15/30/60/90m raw returns, MFE/MAE + timing over 90m.
Net returns are computed by the EXPERIMENTS at OPTIMISTIC/BASE/STRESS,
never baked into the dataset.

Output: results/alpha_discovery/dataset.npz + spread surface + schema.
decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

PIT_BARS = Path("/apex-data/history-b/pit_singlename/bars")
ETF_BARS = Path("/apex-data/history-b/etf_continuous/bars")
MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/"
                  "membership_v1.jsonl")
TOLL_OBS = Path("/apex-data/history-b/pit_singlename/"
                "movement_toll_obs.jsonl")
OUT = Path("results/alpha_discovery")
NY = ZoneInfo("America/New_York")
SECTOR_ETFS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
               "XLRE", "XLU", "XLV", "XLY")
TICKS_ET = [(h, m) for h in range(10, 16) for m in (0, 15, 30, 45)
            if (h, m) <= (15, 30)]

FIELDS = ("r5", "r15", "r30", "r60",
          "r30_atr", "r60_atr",
          "spy_r30", "spy_r60", "sector_r30", "sector_r60",
          "resid_r30", "resid_r60",
          "rvol", "vwap_dist_atr", "vwap_slope_atr",
          "or_position", "gap_atr", "atr_over_price",
          "range_used_atr", "spread_bps", "spread_observed",
          "breadth_above_vwap", "xsec_rank_resid30",
          "minute_of_day", "day_ret_spy")
FWD = ("f15", "f30", "f60", "f90", "mfe90", "mae90",
       "t_mfe", "t_mae")


def load_day(root: Path, sym: str, day: str):
    f = root / f"{sym}_{day}.json"
    if not f.exists():
        return None
    bars = [b for b in json.loads(f.read_text()).get("bars", [])
            if str(b.get("event_time_utc", ""))[:10] == day
            or True]
    import datetime as dt
    ts, o, h, lo, c, v = [], [], [], [], [], []
    for b in bars:
        t = dt.datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00"))
        te = t.astimezone(NY)
        if not ((9, 30) <= (te.hour, te.minute) <= (16, 0)):
            continue
        ts.append(te.hour * 60 + te.minute)
        o.append(b["open"]); h.append(b["high"])
        lo.append(b["low"]); c.append(b["close"])
        v.append(float(b.get("volume", 0)))
    if len(ts) < 60:
        return None
    return (np.array(ts), np.array(o), np.array(h),
            np.array(lo), np.array(c), np.array(v))


def spread_surface():
    """(sym, month) -> median observed spread bps; month cohort
    median as fallback (flagged)."""
    per = defaultdict(list)
    monthly = defaultdict(list)
    if TOLL_OBS.exists():
        for l in TOLL_OBS.read_text().splitlines():
            try:
                o = json.loads(l)
            except Exception:                          # noqa: BLE001
                continue
            if o.get("cohort") == "SINGLE" and o.get("toll"):
                m = o["day"][:7]
                per[(o["symbol"], m)].append(o["toll"] * 1e4)
                monthly[m].append(o["toll"] * 1e4)
    return ({k: st.median(v) for k, v in per.items()},
            {m: st.median(v) for m, v in monthly.items()})


def build(limit_sessions: int | None = None) -> dict:
    mem_months = defaultdict(list)
    for l in MEMBERSHIP.read_text().splitlines():
        try:
            r = json.loads(l)
        except Exception:                              # noqa: BLE001
            continue
        if r.get("kind") == "pit_membership":
            mem_months[r["member_month"]] = r["symbols"]
    sp_sym, sp_month = spread_surface()

    sessions = sorted({f.stem.rsplit("_", 1)[1]
                       for f in ETF_BARS.glob("SPY_*.json")})
    sessions = [s for s in sessions if s[:7] in mem_months]
    if limit_sessions:
        sessions = sessions[:limit_sessions]

    # rolling PIT state (per symbol): daily closes for beta/sector
    # correlation; cum-volume-at-minute for RVOL; prior close for gap
    daily_close: dict[str, deque] = defaultdict(
        lambda: deque(maxlen=70))
    spy_daily: deque = deque(maxlen=70)
    sector_daily: dict[str, deque] = {s: deque(maxlen=70)
                                      for s in SECTOR_ETFS}
    cumvol_hist: dict[str, deque] = defaultdict(
        lambda: deque(maxlen=20))
    prior_close: dict[str, float] = {}

    rows, meta = [], []
    n_sessions = 0
    for day in sessions:
        month = day[:7]
        members = mem_months.get(month, [])
        spy = load_day(ETF_BARS, "SPY", day)
        if spy is None:
            continue
        etf = {"SPY": spy}
        for s in SECTOR_ETFS:
            etf[s] = load_day(ETF_BARS, s, day)
        loaded = {}
        for sym in members:
            d = load_day(PIT_BARS, sym, day)
            if d is not None:
                loaded[sym] = d
        n_sessions += 1

        # PIT beta + sector match from trailing dailies
        def beta_and_sector(sym):
            dc = daily_close[sym]
            if len(dc) < 30 or len(spy_daily) < 30:
                return 1.0, None
            n = min(len(dc), len(spy_daily))
            r_s = np.diff(np.log(np.array(list(dc))[-n:]))
            r_m = np.diff(np.log(np.array(list(spy_daily))[-n:]))
            var = float(r_m.var())
            beta = float(np.cov(r_s, r_m)[0, 1] / var) \
                if var > 0 else 1.0
            best, bc = None, -2.0
            for sec, dq in sector_daily.items():
                if len(dq) < n:
                    continue
                r_e = np.diff(np.log(np.array(list(dq))[-n:]))
                if r_e.std() == 0 or r_s.std() == 0:
                    continue
                cc = float(np.corrcoef(r_s, r_e)[0, 1])
                if cc > bc:
                    bc, best = cc, sec
            return beta, best

        bs_cache = {sym: beta_and_sector(sym) for sym in loaded}

        def ret(arr_ts, arr_c, tick_min, back, idx):
            j = np.searchsorted(arr_ts, tick_min - back,
                                side="right") - 1
            if j < 0:
                return 0.0
            return float((arr_c[idx] - arr_c[j])
                         / max(arr_c[j], 1e-9))

        day_rows = defaultdict(dict)     # tick -> sym -> partial row
        for sym, (ts, o, h, lo, c, v) in loaded.items():
            beta, sector = bs_cache[sym]
            cum_v = np.cumsum(v)
            cum_pv = np.cumsum(c * v)
            or_end = np.searchsorted(ts, 10 * 60, side="right")
            or_hi = float(h[:or_end].max()) if or_end else None
            or_lo = float(lo[:or_end].min()) if or_end else None
            pc = prior_close.get(sym)
            for hh, mm in TICKS_ET:
                tick = hh * 60 + mm
                i = np.searchsorted(ts, tick, side="right") - 1
                if i < 30 or ts[i] < tick - 5:
                    continue
                px = float(c[i])
                w = slice(max(0, i - 60), i + 1)
                atr = float(np.mean(h[w] - lo[w]))
                if atr <= 0:
                    continue
                vwap = float(cum_pv[i] / max(cum_v[i], 1e-9))
                j30 = np.searchsorted(ts, tick - 30,
                                      side="right") - 1
                vwap30 = float(cum_pv[j30]
                               / max(cum_v[j30], 1e-9)) \
                    if j30 > 5 else vwap
                spy_ts, _, _, _, spy_c, _ = etf["SPY"]
                si = np.searchsorted(spy_ts, tick,
                                     side="right") - 1
                spy_r30 = ret(spy_ts, spy_c, tick, 30, si)
                spy_r60 = ret(spy_ts, spy_c, tick, 60, si)
                sec_r30 = sec_r60 = 0.0
                if sector and etf.get(sector) is not None:
                    e_ts, _, _, _, e_c, _ = etf[sector]
                    ei = np.searchsorted(e_ts, tick,
                                         side="right") - 1
                    if ei > 5:
                        sec_r30 = ret(e_ts, e_c, tick, 30, ei)
                        sec_r60 = ret(e_ts, e_c, tick, 60, ei)
                r30 = ret(ts, c, tick, 30, i)
                r60 = ret(ts, c, tick, 60, i)
                hist = [cv.get(tick) for cv in cumvol_hist[sym]
                        if cv.get(tick)]
                rvol = (float(cum_v[i]) / st.median(hist)) \
                    if len(hist) >= 10 else 1.0
                spb = sp_sym.get((sym, month))
                observed = 1.0
                if spb is None:
                    spb = sp_month.get(month, 3.0)
                    observed = 0.0
                row = {
                    "r5": ret(ts, c, tick, 5, i),
                    "r15": ret(ts, c, tick, 15, i),
                    "r30": r30, "r60": r60,
                    "r30_atr": r30 * px / atr,
                    "r60_atr": r60 * px / atr,
                    "spy_r30": spy_r30, "spy_r60": spy_r60,
                    "sector_r30": sec_r30, "sector_r60": sec_r60,
                    "resid_r30": r30 - beta * spy_r30,
                    "resid_r60": r60 - beta * spy_r60,
                    "rvol": min(rvol, 20.0),
                    "vwap_dist_atr": (px - vwap) / atr,
                    "vwap_slope_atr": (vwap - vwap30) / atr,
                    "or_position": ((px - or_lo)
                                    / max(or_hi - or_lo, 1e-9))
                    if or_hi else 0.5,
                    "gap_atr": ((float(o[0]) - pc) / atr)
                    if pc else 0.0,
                    "atr_over_price": atr / px,
                    "range_used_atr": (float(h[:i + 1].max())
                                       - float(lo[:i + 1].min()))
                    / atr,
                    "spread_bps": spb,
                    "spread_observed": observed,
                    "minute_of_day": (tick - 570) / 390.0,
                    "day_ret_spy": float(
                        (spy_c[si] - spy_c[0]) / spy_c[0]),
                }
                # forwards -- strictly after the tick
                fut = {}
                ok = True
                for fh in (15, 30, 60, 90):
                    k = np.searchsorted(ts, tick + fh,
                                        side="right") - 1
                    if k <= i or ts[k] < tick + fh - 6:
                        ok = False
                        break
                    fut[f"f{fh}"] = float((c[k] - px) / px)
                if not ok:
                    continue
                k90 = np.searchsorted(ts, tick + 90,
                                      side="right")
                w_hi = h[i + 1:k90]
                w_lo = lo[i + 1:k90]
                if not len(w_hi):
                    continue
                mfe = float((w_hi.max() - px) / px)
                mae = float((w_lo.min() - px) / px)
                fut.update(mfe90=mfe, mae90=mae,
                           t_mfe=float(np.argmax(w_hi) + 1),
                           t_mae=float(np.argmin(w_lo) + 1))
                row.update(fut)
                day_rows[tick][sym] = row

        # cross-sectional pass: breadth + residual rank
        for tick, symrows in day_rows.items():
            if len(symrows) < 10:
                continue
            resids = {s: r["resid_r30"] for s, r in symrows.items()}
            order = sorted(resids, key=resids.get)
            above = sum(1 for r in symrows.values()
                        if r["vwap_dist_atr"] > 0)
            for rank, s in enumerate(order):
                r = symrows[s]
                r["breadth_above_vwap"] = above / len(symrows)
                r["xsec_rank_resid30"] = rank / max(
                    len(order) - 1, 1)
                rows.append([r[k] for k in FIELDS]
                            + [r[k] for k in FWD])
                meta.append((day, s, tick))

        # roll state forward
        for sym, (ts, o, h, lo, c, v) in loaded.items():
            daily_close[sym].append(float(c[-1]))
            prior_close[sym] = float(c[-1])
            cum = np.cumsum(v)
            cumvol_hist[sym].append(
                {int(t): float(cv) for t, cv in zip(ts, cum)
                 if t % 15 == 0})
        spy_daily.append(float(spy[4][-1]))
        for s in SECTOR_ETFS:
            if etf.get(s) is not None:
                sector_daily[s].append(float(etf[s][4][-1]))
        if n_sessions % 100 == 0:
            print(json.dumps({"sessions": n_sessions,
                              "rows": len(rows)}), flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    X = np.array(rows, dtype=np.float32)
    np.savez_compressed(
        OUT / "dataset.npz", X=X,
        day=np.array([m[0] for m in meta]),
        sym=np.array([m[1] for m in meta]),
        tick=np.array([m[2] for m in meta], dtype=np.int16),
        fields=np.array(list(FIELDS) + list(FWD)))
    rep = {"rows": len(rows), "sessions": n_sessions,
           "fields": list(FIELDS) + list(FWD)}
    (OUT / "schema.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.build:
        build(limit_sessions=a.limit)
