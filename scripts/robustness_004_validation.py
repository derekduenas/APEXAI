#!/usr/bin/env python
"""APEX-004 section-7 DECLARED robustness on the recorded validation look.

Part of the SAME single evaluation Credit 4 paid for -- the protocol declared
bootstrap + permutation + subperiod diagnostics (block 20, 2000/2000, seed
20260814) before validation. The verdict (SUCCESS, t=3.278 >= 2.92) is
recorded and CANNOT change here; section 13 does not read these numbers.
Reproduction-gated: aborts unless the recomputed IC series matches the
recorded artifact at 1e-12.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np, pandas as pd
from apex.config import load_config
from apex.data.production_source import build_production_panel
from apex.evaluate.ic import cross_sectional_ic, newey_west_tstat
from apex.experiments import apex003
from apex.stats import robustness as R

ROOT = Path("data/snapshots/sharadar/current")
SEED = 20260814   # protocol section 7, declared before any small-cap statistic
rec_ic = json.loads(Path("results/validation_APEX-004.json").read_text())["raw"]["ic_daily_newey_west"]

cfg = load_config("experiment", "costs", "synthetic", "sharadar")
panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"),
                                  cfg.period("validation")["end"])
output, _ = apex003.build_gp_output(panel, cfg, ROOT)
daily = output.calendar.daily_formation_dates(
    cfg.period("validation")["start"], cfg.period("validation")["end"])
ic, _ = cross_sectional_ic(
    output.scores.apex_score.loc[daily], output.forward_returns.excess.loc[daily],
    output.universe.eligible.loc[daily], int(cfg.get("evaluation.min_names_for_ic")))
ic = ic.dropna()
t, p = newey_west_tstat(ic, int(cfg.get("evaluation.newey_west_lag")))

# REPRODUCTION GATE
for name, got, want in (("mean", ic.mean(), rec_ic["mean_ic"]),
                        ("t", t, rec_ic["t_stat"]),
                        ("n", float(len(ic)), float(rec_ic["n_periods"]))):
    assert abs(got - want) < 1e-12, f"REPRODUCTION FAILED on {name}: {got} != {want}"
print(f"reproduction gate: MATCH (mean {ic.mean():+.12f}, t {t:+.6f}, n {len(ic)})")

b = R.moving_block_bootstrap_mean(ic, block_size=20, n_resamples=2000, seed=SEED)
perm = R.block_sign_permutation(ic, block_size=20, n_permutations=2000, seed=SEED)
sub_y = R.subperiod_means(ic, scheme="calendar_year")
out = {"reproduction": "MATCH", "verdict_unchanged": "SUCCESS (recorded)",
       "seed": SEED,
       "bootstrap": b.as_dict(), "permutation": perm.as_dict(),
       "subperiod_calendar_year": sub_y.as_dict()}
Path("results/004_robustness.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(f"bootstrap 95% CI  : [{b.ci_low:+.6f}, {b.ci_high:+.6f}]  excludes 0: {b.ci_low > 0}")
print(f"permutation p     : {perm.p_value_two_sided:.4f}")
print("subperiods (year -> mean IC, share):")
for y, d in sorted(sub_y.per_subperiod.items()):
    print(f"  {y}: mean {d['mean']:+.6f}  n={d['n']}  share {d['share_of_total']:+.1%}")
print("DIAGNOSTIC ONLY -- the recorded SUCCESS verdict is unchanged.")
