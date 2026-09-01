"""EVENT-ALPHA-SPRINT-V1 -- event dataset builder.

One row per qualifying earnings event: quantified surprise (EXPECTED vs
ACTUAL, information not sentiment), pre-event state, and the reaction
path at every pre-registered horizon (30m/60m/close/1/2/5/10/20
sessions), raw and SPY-residualized (declared beta=1 residual).

Qualification (causal, sealed in the registration):
  - consensus estimate AND actual EPS present
  - report date in the dense-coverage era (2018-07-01+)
  - symbol was a PIT high-liquidity member in the reaction month
    (asof rule -- the organism could only have watched members)

No economics computed here. decision_power: NONE_DATA_PREP.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

EVENTS = Path("exports/earnings_events_raw.jsonl")
MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/membership_v1.jsonl")
SN_BARS = Path("/apex-data/history-b/pit_singlename/bars")
ETF_BARS = Path("/apex-data/history-b/etf_continuous/bars")
OUT = Path("exports/event_dataset.jsonl")
NY = ZoneInfo("America/New_York")

DENSE_START = "2018-07-01"
HORIZON_SESSIONS = (1, 2, 5, 10, 20)


def load_membership():
    m = defaultdict(set)          # month -> set(symbols)
    for l in MEMBERSHIP.read_text().splitlines():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("kind") != "pit_membership":
            continue
        m[r["member_month"]].update(r["symbols"])
    return m


def index_bars(d):
    idx = defaultdict(list)       # sym -> sorted [dates]
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        sym, _, date = name[:-5].rpartition("_")
        if sym:
            idx[sym].append(date)
    for s in idx:
        idx[s].sort()
    return idx


_day_cache = {}


def load_day(base, sym, date):
    key = (str(base), sym, date)
    if key in _day_cache:
        return _day_cache[key]
    if len(_day_cache) > 4000:
        _day_cache.clear()
    p = base / f"{sym}_{date}.json"
    try:
        bars = json.loads(p.read_text())["bars"]
    except Exception:
        _day_cache[key] = None
        return None
    rth = []
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        mins = t.hour * 60 + t.minute
        if 570 <= mins < 960:     # 09:30 <= t < 16:00 ET
            rth.append((mins, b))
    _day_cache[key] = rth or None
    return _day_cache[key]


def px_at(rth, minute):
    """close of last bar at-or-before ET minute-of-day; None if none."""
    last = None
    for m, b in rth:
        if m <= minute:
            last = b["close"]
        else:
            break
    return last


def session_close(base, sym, date):
    rth = load_day(base, sym, date)
    return rth[-1][1]["close"] if rth else None


def main():
    membership = load_membership()
    sn_idx = index_bars(SN_BARS)
    spy_dates = sorted(index_bars(ETF_BARS).get("SPY", []))
    spy_pos = {d: i for i, d in enumerate(spy_dates)}

    n_in = n_est = n_dense = n_member = n_built = 0
    skipped = defaultdict(int)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = OUT.open("w")

    for line in EVENTS.read_text().splitlines():
        ev = json.loads(line)
        n_in += 1
        est, act = ev["eps_estimate"], ev["eps_actual"]
        if est is None or act is None:
            continue
        try:
            est, act = float(est), float(act)
        except (TypeError, ValueError):
            continue
        n_est += 1
        rdate = ev["report_date"]
        if rdate < DENSE_START:
            continue
        n_dense += 1
        sym = ev["symbol"]
        timing = ev.get("report_timing") or "am"

        # reaction session on the SPY trading calendar
        if rdate not in spy_pos:
            # weekend/holiday-dated report: roll to next trading day
            later = [d for d in spy_dates if d > rdate]
            if not later:
                skipped["no_calendar"] += 1
                continue
            base_date = later[0]
            base_i = spy_pos[base_date]
            reaction_i = base_i if timing == "am" else base_i
            # a pm report on a non-trading day still opens next session
            reaction_i = base_i
        else:
            i = spy_pos[rdate]
            reaction_i = i if timing == "am" else i + 1
        if reaction_i >= len(spy_dates) or reaction_i < 1:
            skipped["calendar_edge"] += 1
            continue
        r_date = spy_dates[reaction_i]
        p_date = spy_dates[reaction_i - 1]

        if sym not in membership.get(r_date[:7], set()):
            skipped["not_member"] += 1
            continue
        n_member += 1

        sym_days = sn_idx.get(sym, [])
        if r_date not in sym_days or p_date not in sym_days:
            skipped["missing_bars"] += 1
            continue

        prev_rth = load_day(SN_BARS, sym, p_date)
        rth = load_day(SN_BARS, sym, r_date)
        if not prev_rth or not rth:
            skipped["empty_rth"] += 1
            continue
        prev_close = prev_rth[-1][1]["close"]
        open_px = rth[0][1]["open"]
        if not prev_close or not open_px or prev_close <= 0:
            skipped["bad_px"] += 1
            continue

        p600 = px_at(rth, 600)    # 10:00 ET
        p630 = px_at(rth, 630)    # 10:30 ET
        close0 = rth[-1][1]["close"]

        spy_prev = load_day(ETF_BARS, "SPY", p_date)
        spy_rth = load_day(ETF_BARS, "SPY", r_date)
        if not spy_prev or not spy_rth:
            skipped["no_spy"] += 1
            continue
        s_prev_close = spy_prev[-1][1]["close"]
        s_open = spy_rth[0][1]["open"]
        s600, s630 = px_at(spy_rth, 600), px_at(spy_rth, 630)
        s_close0 = spy_rth[-1][1]["close"]

        # multi-session closes on the SPY calendar
        fwd, s_fwd = {}, {}
        for k in HORIZON_SESSIONS:
            j = reaction_i + k
            if j < len(spy_dates):
                dj = spy_dates[j]
                fwd[k] = session_close(SN_BARS, sym, dj) \
                    if dj in sym_days else None
                s_fwd[k] = session_close(ETF_BARS, "SPY", dj)
            else:
                fwd[k] = s_fwd[k] = None

        # pre-event state: trailing 20 symbol sessions before p_date
        hist = [d for d in sym_days if d <= p_date][-21:]
        closes = [session_close(SN_BARS, sym, d) for d in hist]
        closes = [c for c in closes if c]
        vol20 = mom20 = None
        if len(closes) >= 15:
            rets = [math.log(closes[i] / closes[i - 1])
                    for i in range(1, len(closes))
                    if closes[i - 1] > 0]
            if len(rets) >= 10:
                mu = sum(rets) / len(rets)
                vol20 = (sum((r - mu) ** 2 for r in rets)
                         / (len(rets) - 1)) ** 0.5
                mom20 = closes[-1] / closes[0] - 1.0

        def rel(a, b):
            return (a / b - 1.0) if (a and b and b > 0) else None

        def resid(x, y):
            return (x - y) if (x is not None and y is not None) else None

        surprise = act - est
        row = {
            "symbol": sym, "report_date": rdate, "timing": timing,
            "fiscal_year": ev["fiscal_year"],
            "fiscal_quarter": ev["fiscal_quarter"],
            "reaction_session": r_date, "prev_session": p_date,
            "eps_estimate": est, "eps_actual": act,
            "surprise": round(surprise, 6),
            "sue_price": round(surprise / prev_close, 8),
            "sue_absest": round(
                surprise / max(abs(est), 0.10), 6),
            "prev_close": prev_close, "open": open_px,
            "vol20": round(vol20, 6) if vol20 else None,
            "mom20": round(mom20, 6) if mom20 is not None else None,
            "gap": rel(open_px, prev_close),
            "r30": rel(p600, open_px), "r60": rel(p630, open_px),
            "r_close": rel(close0, open_px),
            "spy_gap": rel(s_open, s_prev_close),
            "spy_r30": rel(s600, s_open), "spy_r60": rel(s630, s_open),
            "spy_r_close": rel(s_close0, s_open),
        }
        row["gap_res"] = resid(row["gap"], row["spy_gap"])
        row["r30_res"] = resid(row["r30"], row["spy_r30"])
        row["r60_res"] = resid(row["r60"], row["spy_r60"])
        row["r_close_res"] = resid(row["r_close"], row["spy_r_close"])
        for k in HORIZON_SESSIONS:
            rk = rel(fwd[k], close0)
            sk = rel(s_fwd[k], s_close0)
            row[f"r{k}s"] = rk
            row[f"r{k}s_res"] = resid(rk, sk)
        out.write(json.dumps(row) + "\n")
        n_built += 1
        if n_built % 2000 == 0:
            print(json.dumps({"built": n_built, "seen": n_in}),
                  flush=True)

    out.close()
    print(json.dumps({
        "events_in": n_in, "with_est_actual": n_est,
        "dense_era": n_dense, "pit_member": n_member,
        "rows_built": n_built, "skipped": dict(skipped),
        "out": str(OUT)}, indent=1), flush=True)


if __name__ == "__main__":
    main()
