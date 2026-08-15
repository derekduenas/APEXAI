#!/usr/bin/env python
"""Run the v3.1 attribution ladder in-sample on the validated GP signal.

    python scripts/attribution_ladder_004.py

DESIGN-LAYER, IN-SAMPLE, NO CREDIT, NO LEDGER ENTRY. Every row passes the
results_table() gate and carries evidence_class='engineering_measurement'.
Nothing here is evidence of edge; the deliverable is ATTRIBUTION -- the
marginal delta each construction layer contributes, so a future full-stack
failure is diagnosable to a layer.

Rung 0 is the frozen §13 measuring stick, computed for reference only.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex003  # noqa: E402
from apex.portfolio.construction import results_table, run_ladder  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/004_attribution_ladder.json")


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    in_start, in_end = cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    assert pd.Timestamp(in_end) < pd.Timestamp(cfg.period("validation")["start"])

    progress("building in-sample panel (registered small-cap universe)")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"), in_end)
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)

    grid = output.calendar.grid_formation_dates(in_start, in_end)
    grid = pd.DatetimeIndex([d for d in grid
                             if output.scores.apex_score.loc[d].notna().sum() >= 200])
    decile = output.scores.decile.where(output.universe.eligible)
    sector = panel.meta["sector"]
    addv = panel.dollar_volume.rolling(60, min_periods=1).mean()

    progress(f"running rungs 0-5 over {len(grid)} grid dates")
    rungs = run_ladder(grid, decile, sector, panel, addv)
    rows = results_table([r.as_row() for r in rungs])

    marginals = []
    for a, b in zip(rungs[:-1], rungs[1:]):
        marginals.append({
            "from_rung": a.rung, "to_rung": b.rung,
            "delta_sharpe_net20": round(b.sharpe_net_20bp - a.sharpe_net_20bp, 4),
            "delta_ann_net20": round(b.ann_return_net_20bp - a.ann_return_net_20bp, 6),
            "evidence_class": "engineering_measurement",
        })

    out = {
        "purpose": "v3.1 Track 2 attribution ladder, in-sample, GP signal",
        "period": {"start": str(grid[0].date()), "end": str(grid[-1].date()),
                   "locked": False},
        "evidence_class": "engineering_measurement",
        "ladder": rows,
        "marginals": results_table(marginals),
        "hypothesis_check": ("v3.1 §3.5 stated HYPOTHESIS: rungs 2-3 roughly "
                             "double IR vs rung 1; dramatically larger uplift "
                             "means suspect a bug (leverage creep or free "
                             "shorts)"),
    }
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    for r in rungs:
        print(f"rung {r.rung}: {r.label}")
        print(f"  ann gross {r.ann_return_gross:+.2%}  net20 {r.ann_return_net_20bp:+.2%}"
              f"  sharpe(net20) {r.sharpe_net_20bp:+.2f}  vol {r.ann_vol:.2%}")
        print(f"  turnover/reb {r.turnover_per_rebalance:.1%}  beta real "
              f"{r.realized_beta:+.2f} exante {r.ex_ante_beta_mean:+.2f}  "
              f"maxDD {r.max_drawdown:.1%}  L/S {r.names_long_median}/"
              f"{r.names_short_median}  borrow-excl {r.borrow_excluded_total}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
