#!/usr/bin/env python
"""Track 4 runner: label history online, measure lag, read the live state.

    python scripts/world_state_run.py

Answers the operator's ten questions with artifacts, not prose:
  Q1/Q2  online labels for every SPY trading date (weekly grid), each from
         data <= t only, appended to a never-revised store
  Q3     detection lag vs a self-confessed contaminated hindsight reference
         (diagnostic only)
  Q4     pairwise correlation of the index state variables (independence)
  Q5     regime occupancy by year (stability)
  Q6/Q7  REFUSED here -- conditional-alpha behavior is a NEW HYPOTHESIS for
         the registration machinery, recorded as such
  Q8     every label carries its as-of date; consumers read the store,
         never the classifier's future
  Q9     the `uncertain` flag on boundary states
  Q10    the same functions run on the live lake (current state, printed)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.world.state import (  # noqa: E402
    LabelStore, classify_online, cross_sectional_state_variables,
    detection_lag_days, index_state_variables,
)

SNAPSHOT = Path("data/snapshots/sharadar/current")
PAPER_ROOT = Path("data/live/paper_root")
OUT = Path("results/world_state_report.json")
LABELS = Path("results/world/labels.jsonl")


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def load_spy() -> pd.Series:
    root = PAPER_ROOT if (PAPER_ROOT / "raw" / "SFP" / "SFP_SPY.csv").exists() \
        else SNAPSHOT
    spy = pd.read_csv(root / "raw" / "SFP" / "SFP_SPY.csv",
                      usecols=["date", "closeadj"], parse_dates=["date"]
                      ).set_index("date")["closeadj"].astype(float).sort_index()
    return spy[~spy.index.duplicated()]


def main() -> int:
    spy = load_spy()
    progress(f"SPY series {spy.index[0].date()} .. {spy.index[-1].date()}")

    store = LabelStore(LABELS)
    grid = spy.index[1000::5]                       # weekly-ish, post warm-up
    progress(f"labelling {len(grid)} dates ONLINE (data <= t only)")
    for t in grid:
        lab = classify_online(spy, t)
        store.assign(lab)
    labels = store.series()

    lag = detection_lag_days(labels, spy)

    # Q4: independence of the index state variables over history
    rows = []
    for t in grid[::4]:
        v = index_state_variables(spy, t)
        rows.append({k: var.value for k, var in v.items()})
    var_frame = pd.DataFrame(rows)
    independence = var_frame.corr().round(3).to_dict()

    # Q5: stability -- occupancy by year
    occupancy = (labels.groupby(labels.index.year)
                 .value_counts(normalize=True).round(3))
    occupancy_by_year = {f"{y}:{r}": float(v)
                         for (y, r), v in occupancy.items()}

    # Q10: the live state, from the lake (index + cross-sectional)
    live = {"index": {k: v.__dict__ for k, v in
                      index_state_variables(spy, spy.index[-1]).items()},
            "classification": classify_online(spy, spy.index[-1])}
    try:
        import pickle  # noqa: F401  (not used; placeholder guard)
        from apex.config import load_config
        from apex.data.production_source import build_production_panel
        cfg = load_config("experiment", "costs", "synthetic", "sharadar")
        if (PAPER_ROOT / "MANIFEST.json").exists():
            progress("loading short live panel for cross-sectional state")
            panel, _ = build_production_panel(PAPER_ROOT, cfg, "2025-06-01",
                                              str(spy.index[-1].date()),
                                              slim_high_low=True)
            xs = cross_sectional_state_variables(
                panel.close_adj, panel.dollar_volume, panel.dates[-1])
            live["cross_sectional"] = {k: v.__dict__ for k, v in xs.items()}
    except Exception as e:                          # noqa: BLE001
        live["cross_sectional"] = {"unavailable": str(e)[:200]}

    report = {
        "labels_assigned": int(len(labels)),
        "label_store": str(LABELS),
        "detection_lag_diagnostic": lag,
        "variable_independence_corr": independence,
        "occupancy_by_year": occupancy_by_year,
        "uncertain_fraction": round(float(np.mean(
            [json.loads(l)["uncertain"] for l in
             LABELS.read_text().strip().splitlines()])), 3),
        "live_state": live,
        "q6_q7_conditional_alpha": (
            "REFUSED at this layer. 'Signal S has positive expectancy only in "
            "state X' is a NEW HYPOTHESIS: it enters discovery, survives the "
            "screen, and pays for its own confirmatory look. The state layer "
            "describes; it never selects."),
        "macro_variables": (
            "PENDING vendor: first-release vintages require FRED/ALFRED (free "
            "key, operator signup). The vintage store and REVISED_ONLY guard "
            "are built and counterexampled; no macro series is faked "
            "meanwhile."),
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: report[k] for k in
                      ("detection_lag_diagnostic", "occupancy_by_year",
                       "uncertain_fraction")}, indent=2))
    print("live:", json.dumps(live["classification"]))
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
