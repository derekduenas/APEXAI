"""H5 — THE FORECAST CHALLENGER. Registered design, executed verbatim.

    Can pooled statistical estimation discover after-cost forward
    structure that the binary setup/gate system cannot?

Executes H5-FORECAST-CHALLENGER exactly as pre-registered on
2026-08-29, BEFORE the incumbent's historical refutation existed --
nothing here was engineered to beat a dead hunter:

    MODEL      regularized linear (ridge), pooled across symbols.
               The cleanest falsification instrument; GBT is the
               earned second step; deep learning is cargo cult here.
    TARGET     forward return exceeds the friction hurdle, judged in
               ATR-normalized space; horizons 15m and 60m, both
               registered, both reported.
    UNIVERSE   the certified survivorship-free ETF core
               (corpus 5c0d768b7ee2ea14).
    FEATURES   the dense boring families only -- returns/momentum,
               volatility, volume state, VWAP distance, day-range
               position, time-of-day, cross-sectional rank, index
               co-movement. Catalyst/PARALLAX/LLM features EXCLUDED.
    VALIDATION chronological expanding-window walk-forward by year;
               labels never cross the train/test boundary (year
               boundaries dwarf the 60m label horizon); features and
               normalization fit on train only.
    EVAL       rank IC + decile after-cost spread at 1x/2x/4x,
               per test year. Overlapping 15-min samples are
               autocorrelated: NO significance claims -- the evidence
               axis is per-year consistency, per the registration.
    KILL       pre-committed: ~zero OOS rank IC on the ETF core;
               decile spread dead at 2x costs; era sign flips.

Writes results/h5/ only. No trading imports. No capital surface.
decision_power: RESEARCH_ONLY_H5.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from apex.governance.chain_ledger import chain_append  # noqa: E402

CORPUS = Path("/apex-data/history-b/etf_continuous/bars")
CORPUS_VERSION = "5c0d768b7ee2ea14"
OUT = Path("results/h5")
DATASET = OUT / "dataset.npz"
SPREAD_BPS = 2.0                 # the incumbent's friction model
HORIZONS = (15, 60)
TICK_MIN = 15
ATR_LOOKBACK = 60

FEATURES = ("r5_atr", "r15_atr", "r30_atr", "r60_atr",
            "vwap_dist_atr", "day_range_pos", "atr_over_price",
            "vol_ratio_15m", "range_used_atr", "tod_sin", "tod_cos",
            "xsec_rank_r30", "spy_r30_atr", "resid_r30_atr")


def _minutes(bars):
    """(epoch_min, o, h, l, c, v) arrays for one session file."""
    import datetime as dt
    ts, o, h, lo, c, v = [], [], [], [], [], []
    for b in bars:
        t = dt.datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00"))
        ts.append(int(t.timestamp() // 60))
        o.append(b["open"]); h.append(b["high"])
        lo.append(b["low"]); c.append(b["close"])
        v.append(b.get("volume", 0))
    return (np.array(ts), np.array(o), np.array(h), np.array(lo),
            np.array(c), np.array(v, dtype=float))


def build_dataset() -> dict:
    """One causal pass over the corpus -> pooled feature matrix.
    Every feature at tick T uses bars <= T only; labels use bars
    strictly after T. Cross-sectional features are computed from the
    same-tick values of the other symbols -- same timestamp, no
    future."""
    sessions: dict[str, dict] = {}
    for f in sorted(CORPUS.glob("*.json")):
        sym, day = f.stem.rsplit("_", 1)
        sessions.setdefault(day, {})[sym] = f
    X, Y15, Y60, meta_year, meta_sym = [], [], [], [], []
    n_days = 0
    for day, symfiles in sorted(sessions.items()):
        n_days += 1
        per_sym = {}
        for sym, f in symfiles.items():
            bars = json.loads(f.read_text()).get("bars", [])
            bars = [b for b in bars
                    if str(b.get("event_time_utc", ""))[:10] == day]
            if len(bars) < 120:
                continue
            per_sym[sym] = _minutes(bars)
        if "SPY" not in per_sym:
            continue
        # tick grid from SPY's session minutes
        spy_ts = per_sym["SPY"][0]
        t_open = spy_ts[0]
        ticks = [t for t in range(t_open + 75, spy_ts[-1] - 60,
                                  TICK_MIN)]
        # per-symbol per-tick raw features
        rowbuf = {}
        for sym, (ts, o, h, lo, c, v) in per_sym.items():
            idx = np.searchsorted(ts, ticks, side="right") - 1
            for k, t in enumerate(ticks):
                i = idx[k]
                if i < 70 or ts[i] < t - 5:
                    continue                    # stale/insufficient
                px = c[i]
                w = slice(max(0, i - ATR_LOOKBACK), i + 1)
                atr = float(np.mean(h[w] - lo[w]))
                if atr <= 0 or px <= 0:
                    continue

                def rr(mins):
                    j = np.searchsorted(ts, t - mins,
                                        side="right") - 1
                    return (px - c[j]) / atr if j >= 0 else 0.0

                cum_v = np.cumsum(v[:i + 1])
                cum_pv = np.cumsum(c[:i + 1] * v[:i + 1])
                vwap = cum_pv[-1] / max(cum_v[-1], 1e-9)
                d_hi, d_lo = float(np.max(h[:i + 1])), \
                    float(np.min(lo[:i + 1]))
                mins_in = t - ts[0]
                feats = {
                    "r5_atr": rr(5), "r15_atr": rr(15),
                    "r30_atr": rr(30), "r60_atr": rr(60),
                    "vwap_dist_atr": (px - vwap) / atr,
                    "day_range_pos": ((px - d_lo)
                                      / max(d_hi - d_lo, 1e-9)),
                    "atr_over_price": atr / px,
                    "vol_ratio_15m": (float(np.mean(v[max(0, i - 14):
                                                      i + 1]))
                                      / max(float(np.median(
                                          v[:i + 1])), 1.0)),
                    "range_used_atr": (d_hi - d_lo) / atr,
                    "tod_sin": math.sin(2 * math.pi * mins_in / 390),
                    "tod_cos": math.cos(2 * math.pi * mins_in / 390),
                }
                # labels: forward return, ATR-normalized
                lab = {}
                for hz in HORIZONS:
                    j = np.searchsorted(ts, t + hz, side="right") - 1
                    lab[hz] = ((c[j] - px) / atr
                               if ts[j] >= t + hz - 3 and j > i
                               else None)
                rowbuf.setdefault(t, {})[sym] = (feats, lab, px, atr)
        # cross-sectional pass
        for t, symrows in rowbuf.items():
            if len(symrows) < 5:
                continue
            r30s = {s: fr[0]["r30_atr"] for s, fr in symrows.items()}
            order = sorted(r30s, key=r30s.get)
            spy30 = r30s.get("SPY", 0.0)
            for rank, s in enumerate(order):
                feats, lab, px, atr = symrows[s]
                if lab[15] is None or lab[60] is None:
                    continue
                feats["xsec_rank_r30"] = rank / max(len(order) - 1, 1)
                feats["spy_r30_atr"] = spy30
                feats["resid_r30_atr"] = feats["r30_atr"] - spy30
                X.append([feats[k] for k in FEATURES])
                Y15.append(lab[15]); Y60.append(lab[60])
                meta_year.append(int(day[:4])); meta_sym.append(s)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        DATASET, X=np.array(X, dtype=np.float32),
        y15=np.array(Y15, dtype=np.float32),
        y60=np.array(Y60, dtype=np.float32),
        year=np.array(meta_year, dtype=np.int16),
        sym=np.array(meta_sym))
    return {"rows": len(X), "days": n_days,
            "features": list(FEATURES)}


def _rank_ic(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    d = math.sqrt(float((ra @ ra)) * float((rb @ rb)))
    return float(ra @ rb) / d if d else 0.0


def walk_forward() -> dict:
    """Expanding yearly walk-forward, ridge, both horizons. Year
    boundaries dwarf the 60m label horizon, so purge/embargo are
    satisfied by construction and stated rather than simulated."""
    d = np.load(DATASET, allow_pickle=True)
    X, year = d["X"], d["year"]
    report = {"kind": "h5_walk_forward", "model": "ridge(lambda=10)",
              "corpus_version": CORPUS_VERSION,
              "features": list(FEATURES), "by_horizon": {},
              "law": "overlapping samples are autocorrelated: no "
                     "significance claims; the evidence axis is "
                     "per-year consistency, per the registration",
              "decision_power": "RESEARCH_ONLY_H5"}
    for hz, ykey in ((15, "y15"), (60, "y60")):
        y = d[ykey]
        # after-cost aligned label in ATR units: crossing the spread
        # twice, converted to ATR space per-row via atr_over_price
        cost_atr_1x = (2 * SPREAD_BPS / 1e4) / np.maximum(
            X[:, FEATURES.index("atr_over_price")], 1e-6)
        rows = {}
        for test_year in range(2018, 2027):
            tr = year < test_year
            te = year == test_year
            if tr.sum() < 50_000 or te.sum() < 5_000:
                continue
            mu = X[tr].mean(0)
            sd = X[tr].std(0) + 1e-9
            Xtr = (X[tr] - mu) / sd
            Xte = (X[te] - mu) / sd
            lam = 10.0
            A = Xtr.T @ Xtr + lam * np.eye(Xtr.shape[1])
            w = np.linalg.solve(A, Xtr.T @ y[tr])
            score = Xte @ w
            yt = y[te]
            ic = _rank_ic(score, yt)
            q = np.quantile(score, [0.1, 0.9])
            top, bot = score >= q[1], score <= q[0]
            spread = {}
            for m in (1, 2, 4):
                c = m * cost_atr_1x[te]
                # trade in the direction of the score: long top
                # decile, short bottom decile, each paying costs
                spread[f"{m}x"] = round(float(
                    (yt[top] - c[top]).mean()
                    + (-yt[bot] - c[bot]).mean()) / 2, 4)
            rows[test_year] = {
                "n_test": int(te.sum()), "rank_ic": round(ic, 4),
                "decile_spread_atr": spread,
                "top_decile_raw_mean_atr": round(
                    float(yt[top].mean()), 4)}
        ics = [r["rank_ic"] for r in rows.values()]
        pos_2x = sum(1 for r in rows.values()
                     if r["decile_spread_atr"]["2x"] > 0)
        report["by_horizon"][f"{hz}m"] = {
            "years": rows,
            "ic_mean": round(float(np.mean(ics)), 4) if ics else None,
            "ic_positive_years": f"{sum(1 for i in ics if i > 0)}"
                                 f"/{len(ics)}",
            "spread_positive_years_at_2x": f"{pos_2x}/{len(rows)}"}
    chain_append(OUT / "walk_forward.jsonl", report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--walk-forward", action="store_true")
    a = ap.parse_args()
    if a.build:
        print(json.dumps(build_dataset(), indent=1))
        return 0
    if a.walk_forward:
        print(json.dumps(walk_forward(), indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
