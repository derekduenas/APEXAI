#!/usr/bin/env python
"""APEX-004 IN-SAMPLE instrument study: match the instrument to the signal.

    python scripts/instrument_study_004.py

WHY THIS EXISTS
---------------
Validation (recorded, closed) said: signal VALIDATED (t=3.278), declared
long-top-decile instrument NOT VIABLE (net +0.46% vs the 2% gate). The IC
strength lives in the broad ranking; the extreme deciles are noisy. This
study asks, ON IN-SAMPLE DATA ONLY (2005-2017, unlocked, no statistical
standing), which pre-specified long-only construction best monetises the
ranking -- and MEASURES realized turnover instead of assuming it.

CONTAMINATION DISCLOSURE (recorded, not laundered)
--------------------------------------------------
The motivation for this study is the VALIDATION result -- the operator and
the system have seen validation deciles. That peek is why the final
instrument must be judged on the UNTOUCHED holdout, which is exactly what
holdout exists for. The unforgivable act would be iterating on holdout;
this script cannot touch it (assertion below).

THE CANDIDATE SET IS FROZEN HERE, BEFORE ANY NUMBER IS COMPUTED
---------------------------------------------------------------
Six candidates, quarterly rebalance (every 3rd grid date), long-only:

  A  top-decile equal-weight            (the section-9 baseline, as declared)
  B  top-3-deciles equal-weight        (broader sleeve, monotonic bulk)
  C  top-decile score-weighted         (tilt within the top)
  D  A + banding: hold until decile>3  (hysteresis to cut turnover)
  E  B + banding: hold until decile>5
  F  top-30 by score, equal-weight     (the concentrated deployable sleeve)

DENOMINATOR = 6. No candidate may be added after results are seen; a wider
search is a NEW study with its own recorded denominator. Every candidate's
result is reported -- no file drawer.

All excess returns are computed as candidate-minus-equal-weight-universe on
the SAME return matrix, so any common baseline cancels. Costs: the declared
50bp one-way; turnover MEASURED per rebalance (one-sided L1/2).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex003  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
COST_ONE_WAY = 0.0050          # declared, protocol section 9
REBALANCE_EVERY = 3            # grid steps (~quarterly)
DENOMINATOR = 6


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def weights_for(name, score_row, decile_row, prev_w):
    """Target weights for one rebalance date. Long-only, sum to 1."""
    held = prev_w[prev_w > 0].index if prev_w is not None else pd.Index([])
    if name == "A":
        pick = decile_row[decile_row == 1].index
        w = pd.Series(1.0, index=pick)
    elif name == "B":
        pick = decile_row[decile_row <= 3].index
        w = pd.Series(1.0, index=pick)
    elif name == "C":
        pick = decile_row[decile_row == 1].index
        w = score_row.loc[pick]
    elif name == "D":                     # enter decile 1, exit when decile > 3
        keep = [s for s in held if decile_row.get(s, 99) <= 3]
        enter = [s for s in decile_row[decile_row == 1].index if s not in keep]
        w = pd.Series(1.0, index=pd.Index(keep + enter))
    elif name == "E":                     # enter deciles 1-3, exit when decile > 5
        keep = [s for s in held if decile_row.get(s, 99) <= 5]
        enter = [s for s in decile_row[decile_row <= 3].index if s not in keep]
        w = pd.Series(1.0, index=pd.Index(keep + enter))
    elif name == "F":
        pick = score_row.nlargest(30).index
        w = pd.Series(1.0, index=pick)
    else:
        raise ValueError(name)
    return w / w.sum() if len(w) else pd.Series(dtype=float)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    in_end = cfg.period("in_sample")["end"]
    # The study is IN-SAMPLE ONLY. Refuse to exist past its end.
    assert pd.Timestamp(in_end) < pd.Timestamp(cfg.period("validation")["start"])

    progress("building in-sample panel (registered small-cap universe)")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"), in_end)
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)

    grid = output.calendar.grid_formation_dates(cfg.period("in_sample")["start"], in_end)
    grid = pd.DatetimeIndex([d for d in grid
                             if output.scores.apex_score.loc[d].notna().sum() >= 200])
    assert grid.max() <= pd.Timestamp(in_end), "study leaked past in-sample"
    progress(f"{len(grid)} usable grid dates; rebalance every {REBALANCE_EVERY}")

    score = output.scores.apex_score
    decile = output.scores.decile
    ret = output.forward_returns.excess          # per 20-day grid period
    eligible = output.universe.eligible
    years = (grid[-1] - grid[0]).days / 365.25
    periods_per_year = len(grid) / years

    results = {}
    for name in ("A", "B", "C", "D", "E", "F"):
        prev_w = None
        pr, turns, names_held = [], [], []
        for i, d in enumerate(grid):
            elig = eligible.loc[d]
            r_row = ret.loc[d].where(elig)
            univ = r_row.mean()
            if i % REBALANCE_EVERY == 0:
                w = weights_for(name, score.loc[d].where(elig).dropna(),
                                decile.loc[d].where(elig).dropna(), prev_w)
                if prev_w is not None:
                    both = w.index.union(prev_w.index)
                    turns.append(float((w.reindex(both, fill_value=0.0)
                                        - prev_w.reindex(both, fill_value=0.0)
                                        ).abs().sum() / 2))
                prev_w = w
            names_held.append(len(prev_w))
            got = r_row.reindex(prev_w.index)
            # a name that stopped trading mid-hold contributes its last return
            # as NaN -> treated as universe (conservative neutral)
            pr.append(float((prev_w * got.fillna(univ)).sum() - univ))

        pr = pd.Series(pr, index=grid)
        gross_annual = pr.mean() * periods_per_year
        rebalances_per_year = (len(grid) / REBALANCE_EVERY) / years
        turn = float(np.mean(turns))
        drag = rebalances_per_year * turn * 2 * COST_ONE_WAY
        results[name] = {
            "gross_excess_annualised": round(gross_annual, 6),
            "measured_turnover_per_rebalance": round(turn, 4),
            "rebalances_per_year": round(rebalances_per_year, 2),
            "annual_cost_drag": round(drag, 6),
            "net_excess_annualised": round(gross_annual - drag, 6),
            "degradation": round(drag / gross_annual, 4) if gross_annual > 0 else None,
            "median_names_held": int(np.median(names_held)),
            "period_excess_t_stat_naive": round(
                float(pr.mean() / pr.std() * np.sqrt(len(pr))), 2),
        }
        progress(f"{name}: gross {gross_annual:+.2%}  turn {turn:.0%}/reb  "
                 f"net {gross_annual - drag:+.2%}  names {int(np.median(names_held))}")

    out = {
        "purpose": "APEX-004 in-sample instrument study (design, no standing)",
        "period": {"start": str(grid[0].date()), "end": str(grid[-1].date()),
                   "locked": False},
        "candidate_denominator": DENOMINATOR,
        "cost_one_way": COST_ONE_WAY,
        "contamination_disclosure": (
            "Motivated by the recorded APEX-004 validation result; validation "
            "deciles were seen before this design. The final declared "
            "instrument is judged on the untouched holdout."
        ),
        "candidates": results,
    }
    Path("results/004_instrument_study.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2))
    print("written: results/004_instrument_study.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
