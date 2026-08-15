#!/usr/bin/env python
"""HTB-proxy scrutiny (operator challenge, 2026-08-15). In-sample, tagged.

THE QUESTION: rung 4 -> 5 removed 7,601 short candidates (over a third of
the bottom decile) and Sharpe ROSE (0.64 -> 0.69). Is that the specific
names the proxy removes, or merely the short book shrinking?

THE DECISIVE TEST: rerun rung 5 with the borrow proxy replaced by RANDOM
exclusion at the SAME per-date rate (borrow carry identical, only the
selection differs), across five seeds.

  * If random exclusion reproduces the improvement -> the uplift is short-
    book SHRINKAGE, the proxy's specific names are not load-bearing, and the
    honest attribution is "less shorting helps" (consistent with rung 2's
    finding that this signal has a weak short side).
  * If random exclusion does NOT reproduce it -> the proxy's specific names
    were genuinely harmful shorts -- real economics or a volatility filter
    in a borrow costume; either way it must be reported as doing real work.

evidence_class: engineering_measurement. No credit, no locked period.
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
from apex.portfolio import construction as C  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/004_htb_scrutiny.json")
SEEDS = (1, 2, 3, 4, 5)


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    in_start, in_end = cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    progress("building in-sample panel")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"), in_end)
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)
    grid = output.calendar.grid_formation_dates(in_start, in_end)
    grid = pd.DatetimeIndex([d for d in grid
                             if output.scores.apex_score.loc[d].notna().sum() >= 200])
    decile = output.scores.decile.where(output.universe.eligible)
    sector = panel.meta["sector"]
    addv = panel.dollar_volume.rolling(60, min_periods=1).mean()

    # per-date exclusion COUNT of the real proxy, to be matched exactly
    excl_count = {}
    for d in grid:
        row = decile.loc[d].dropna()
        bot = row[row == 10].index
        ok = ((addv.loc[d, bot] >= C.BORROW_MIN_ADDV)
              & (panel.close_unadj.loc[d, bot] >= C.BORROW_MIN_CLOSE))
        excl_count[d] = int((~ok.fillna(False)).sum())

    progress("running rung 4, real rung 5, and five random-exclusion variants")
    r4 = C.run_rung(4, "sector-neutral", grid, decile, sector, panel, addv)
    r5 = C.run_rung(5, "real HTB proxy", grid, decile, sector, panel, addv)

    randoms = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)

        def override(d, default_mask, _rng=rng):
            row = decile.loc[d].dropna()
            bot = list(row[row == 10].index)
            k = min(excl_count[d], len(bot))
            drop = set(_rng.choice(bot, size=k, replace=False)) if k else set()
            mask = pd.Series(True, index=default_mask.index)
            mask[list(drop)] = False
            return mask

        r = C.run_rung(5, f"random exclusion seed {seed}", grid, decile,
                       sector, panel, addv, shortable_override=override)
        randoms.append(r)
        progress(f"seed {seed}: sharpe {r.sharpe_net_20bp:+.3f} "
                 f"(excluded {r.borrow_excluded_total})")

    rand_sharpes = [r.sharpe_net_20bp for r in randoms]
    out = {
        "evidence_class": "engineering_measurement",
        "question": "is the rung4->5 uplift the proxy's names or book shrinkage?",
        "rung4_sharpe_net20": r4.sharpe_net_20bp,
        "rung5_real_proxy_sharpe_net20": r5.sharpe_net_20bp,
        "rung5_random_exclusion_sharpes": rand_sharpes,
        "random_mean": round(float(np.mean(rand_sharpes)), 4),
        "random_min_max": [min(rand_sharpes), max(rand_sharpes)],
        "matched_exclusions_per_variant": [r.borrow_excluded_total for r in randoms],
        "real_proxy_exclusions": r5.borrow_excluded_total,
        "ladder": C.results_table([r4.as_row(), r5.as_row()]
                                  + [r.as_row() for r in randoms]),
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"rung 4 (no exclusions):      {r4.sharpe_net_20bp:+.3f}")
    print(f"rung 5 (REAL proxy):         {r5.sharpe_net_20bp:+.3f}")
    print(f"rung 5 (RANDOM, 5 seeds):    mean {np.mean(rand_sharpes):+.3f}  "
          f"range [{min(rand_sharpes):+.3f}, {max(rand_sharpes):+.3f}]")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
