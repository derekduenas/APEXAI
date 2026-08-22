#!/usr/bin/env python
"""CURVE STRUCTURAL REACHABILITY REPLAY (Predator v2 Phase 2 §12).

Question: with the previously-dark dimensions honestly fed, does Curve
HIGH become REACHABLE at all?

This is NOT a performance backtest. No outcome, return, or P&L is read
anywhere in this file. No constant is tuned. There is no target firing
rate -- zero natural HIGH in a quiet sample is an acceptable result;
the requirement is only that HIGH be mathematically and semantically
reachable when several independent dimensions genuinely elevate.

    python scripts/curve_reachability_replay.py [--date 2026-08-21]

Writes results/frontier2/curve_reachability_shadow.json
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.frontier2 import curve  # noqa: E402
from apex.predators.equities import curve_feeds as cf  # noqa: E402

BARS = Path("data/live/alpaca_fabric/bars")
OUT = Path("results/frontier2/curve_reachability_shadow.json")


def _load(sym: str, day: str) -> list:
    p = BARS / f"{sym}_{day}.json"
    if not p.exists():
        return []
    b = json.load(open(p)).get("bars", [])
    return [x for x in b if x.get("close")]


def replay(day: str, max_symbols: int = 60) -> dict:
    import pandas as pd
    syms = sorted({Path(f).name.split("_")[0]
                   for f in glob.glob(str(BARS / f"*_{day}.json"))})
    market = _load(cf.MARKET_PROXY, day)
    complex_bars = {s: _load(s, day) for s in cf.EQUITY_COMPLEX}
    subjects = [s for s in syms
                if s not in cf.EQUITY_COMPLEX][:max_symbols]

    like = Counter()
    max_elev, max_groups = 0, 0
    dim_support = Counter()
    per_state = []
    complex_pts = cf.cross_equity_complex_points(complex_bars)

    for sym in subjects:
        bars = _load(sym, day)
        if len(bars) < 40:
            continue
        feeds = {
            "price": [(pd.Timestamp(b["event_time_utc"]), b["close"])
                      for b in bars],
            "volatility": cf.volatility_points(bars),
            "correlation": cf.correlation_points(bars, market),
        }
        # relative strength: subject vs market excess (existing semantic)
        mk = {b["event_time_utc"]: b["close"] for b in market}
        rs = [(pd.Timestamp(b["event_time_utc"]),
               b["close"] / mk[b["event_time_utc"]])
              for b in bars if b["event_time_utc"] in mk
              and mk[b["event_time_utc"]]]
        feeds["relative_strength"] = rs

        # evaluate at a few points through the session (structure only)
        times = [b["event_time_utc"] for b in bars]
        for cut in range(60, len(times), 30):
            now = pd.Timestamp(times[cut])
            dims = {}
            for name in curve.DIMENSIONS:
                pts = [(pd.Timestamp(p[0]), p[1])
                       for p in feeds.get(name, [])
                       if pd.Timestamp(p[0]) <= now]
                if name == "cross_asset":
                    pts = []          # stays dark, by law
                d = curve.compute_dimension(
                    name, pts, now=now, known_from=str(now))
                dims[name] = d
                if d.status == curve.SUPPORTED:
                    dim_support[name] += 1
            elevated = [k for k, v in dims.items() if v.elevated()]
            groups = {curve.DEPENDENCY_GROUPS[k] for k in elevated}
            max_elev = max(max_elev, len(elevated))
            max_groups = max(max_groups, len(groups))
            cls = curve._classify(dims, breadth_usable=False)
            like[cls["transition_likelihood"]] += 1
            if len(elevated) >= 2:
                per_state.append(
                    {"subject": sym, "as_of": str(now),
                     "elevated": elevated, "groups": sorted(groups),
                     "likelihood": cls["transition_likelihood"]})

    return {"kind": "curve_reachability_shadow",
            "law": "structural reachability only -- no outcomes read, "
                   "no constants tuned, no target firing rate",
            "decision_power": cf.SHADOW_POWER,
            "date": day, "subjects_replayed": len(subjects),
            "likelihood_counts": dict(like.most_common()),
            "max_elevated_dimensions": max_elev,
            "max_independent_elevated_groups": max_groups,
            "dimension_support_counts": dict(dim_support.most_common()),
            "HIGH_natural_occurrences": like.get("HIGH", 0),
            "multi_elevated_examples": per_state[:10],
            "dark_dimensions": cf.DARK_DIMENSIONS}


def synthetic_proof() -> dict:
    """Controlled proof that HIGH is reachable when >=3 dimensions
    across >=2 groups genuinely elevate -- a single decisive bend
    injected into three independent series."""
    import pandas as pd
    t0 = pd.Timestamp("2026-08-21 14:00:00", tz="UTC")
    times = [str(t0 + pd.Timedelta(minutes=i)) for i in range(40)]

    def bend(flat_v, bend_v):
        """Quiet drift, then ONE decisive break at the final bar.

        V2 curvature is the return-normalized SECOND difference, so a
        linear ramp is flat curvature everywhere except its first
        point. A first attempt ramped from bar 30 and evaluated at bar
        39 -- by then the second difference was ~0 and nothing
        elevated. The break must land AT the evaluation instant.
        """
        vals = []
        for i in range(40):
            drift = flat_v * (1.0 + 0.0004 * ((-1) ** i))   # tiny noise
            vals.append(drift)
        vals[-1] = vals[-2] + bend_v          # the decisive break
        return [(pd.Timestamp(times[i]), vals[i]) for i in range(40)]

    dims = {}
    feeds = {"price": bend(100.0, 0.9),
             "volatility": bend(0.01, 0.004),
             "correlation": bend(0.8, -0.05),
             "relative_strength": bend(1.0, 0.01)}
    now = pd.Timestamp(times[-1])
    for name in curve.DIMENSIONS:
        dims[name] = curve.compute_dimension(
            name, feeds.get(name, []), now=now, known_from=str(now))
    elevated = [k for k, v in dims.items() if v.elevated()]
    groups = sorted({curve.DEPENDENCY_GROUPS[k] for k in elevated})
    cls = curve._classify(dims, breadth_usable=False)
    return {"elevated": elevated, "groups": groups,
            "likelihood": cls["transition_likelihood"],
            "HIGH_reachable": cls["transition_likelihood"] == "HIGH"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-21")
    a = ap.parse_args()
    rep = replay(a.date)
    rep["synthetic_proof"] = synthetic_proof()
    rep["HIGH_STRUCTURALLY_REACHABLE"] = (
        "YES" if (rep["synthetic_proof"]["HIGH_reachable"] or
                  rep["HIGH_natural_occurrences"] > 0) else "NO")
    OUT.write_text(json.dumps(rep, indent=1))
    slim = {k: v for k, v in rep.items()
            if k not in ("multi_elevated_examples", "dark_dimensions")}
    print(json.dumps(slim, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
