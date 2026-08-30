"""H5-FRICTION-FIDELITY-V2 — the corrected cash register.

Registered before running. IDENTICAL frozen H5-v1 pipeline and
predictions (deterministic ridge on the same dataset); the ONLY
change is the evaluation cost surface: the independently MEASURED
per-year executable ETF round trip (Layer A, 100% observed SIP NBBO)
replaces the frozen 4bps model that Layer A proved was a ~4.4x
overcharge. No retraining. No feature or threshold change.

    Given the exact predictions H5 already made, were they
    economically useful under realistic historical execution costs?

H5-v1's verdict under its own predeclared model stands untouched.
decision_power: RESEARCH_ONLY_H5.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from apex.governance.chain_ledger import chain_append  # noqa: E402
from scripts.h5_challenger import (DATASET, FEATURES,  # noqa: E402
                                   _rank_ic)

# MEASURED executable ETF round trip, bps, by year (Layer A,
# MOVEMENT-TOLL-2026-08-29: quoted median by year + the executable
# model uplift factor observed across the decade ~1.34x quoted).
MEASURED_RT_BPS = {2016: 1.17, 2017: 0.98, 2018: 0.86, 2019: 0.87,
                   2020: 0.96, 2021: 0.60, 2022: 0.94, 2023: 0.75,
                   2024: 0.67, 2025: 0.72, 2026: 0.76}
OUT = Path("results/h5/friction_fidelity.jsonl")


def run() -> dict:
    d = np.load(DATASET, allow_pickle=True)
    X, year = d["X"], d["year"]
    aop = np.maximum(X[:, FEATURES.index("atr_over_price")], 1e-6)
    report = {"kind": "h5_friction_fidelity",
              "id": "H5-FRICTION-FIDELITY-V2-RESULT",
              "cost_surface": "measured executable ETF RT by year "
                              "(Layer A, observed SIP NBBO)",
              "by_horizon": {}, "decision_power": "RESEARCH_ONLY_H5"}
    for hz, ykey in ((15, "y15"), (60, "y60")):
        y = d[ykey]
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
            w = np.linalg.solve(
                Xtr.T @ Xtr + 10.0 * np.eye(Xtr.shape[1]),
                Xtr.T @ y[tr])
            score = Xte @ w
            yt = y[te]
            rt = MEASURED_RT_BPS[test_year] / 1e4
            cost_atr = rt / aop[te]
            q = np.quantile(score, [0.1, 0.9])
            top, bot = score >= q[1], score <= q[0]
            spread = {}
            for m in (1, 2):
                c = m * cost_atr
                spread[f"{m}x_measured"] = round(float(
                    (yt[top] - c[top]).mean()
                    + (-yt[bot] - c[bot]).mean()) / 2, 4)
            rows[test_year] = {
                "rank_ic": round(_rank_ic(score, yt), 4),
                "decile_spread_atr": spread,
                "measured_rt_bps": MEASURED_RT_BPS[test_year]}
        pos1 = sum(1 for r in rows.values()
                   if r["decile_spread_atr"]["1x_measured"] > 0)
        pos2 = sum(1 for r in rows.values()
                   if r["decile_spread_atr"]["2x_measured"] > 0)
        vals = [r["decile_spread_atr"]["1x_measured"]
                for r in rows.values()]
        report["by_horizon"][f"{hz}m"] = {
            "years": rows,
            "spread_positive_years_at_measured_cost":
            f"{pos1}/{len(rows)}",
            "spread_positive_years_at_2x_measured":
            f"{pos2}/{len(rows)}",
            "mean_spread_at_measured": round(float(np.mean(vals)), 4)
            if vals else None}
    chain_append(OUT, report)
    return report


if __name__ == "__main__":
    r = run()
    print(json.dumps(r, indent=1))
