#!/usr/bin/env python
"""APEX-004 section 5a: STRUCTURAL breadth census of the small-cap universe.

    python scripts/census_004_universe.py --snapshot data/snapshots/sharadar/current

WHAT THIS READS: eligibility counts and data AVAILABILITY (is a value present),
on the UNLOCKED in-sample period only.

WHAT THIS NEVER READS: signal magnitudes, forward returns, ICs, spreads --
nothing that could rank a security or preview a result. The census informs the
STRUCTURAL calibration of the draft protocol's universe floors (is there
enough breadth to run the experiment at all); it must be useless for deciding
whether the experiment would PASS.

The universe floors are overridden IN MEMORY, transparently (the same
precedent as the 003 dry run's identity override): the draft protocol is
unsigned, so nothing on disk may change, and the in-sample period is unlocked
and free.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.production_source import ProductionSource  # noqa: E402
from apex.features.factory import build_features  # noqa: E402
from apex.features.registry import built_specs  # noqa: E402
from apex.universe import build_universe  # noqa: E402

# Draft section 3 floors (PROVISIONAL -- this census is what firms them up).
SMALLCAP_FLOORS = {
    "min_market_cap_usd": 100e6,
    "min_addv_usd": 1e6,
    "min_close_usd": 2.0,
}
MARKET_CAP_CEILING_USD = 2e9
IN_SAMPLE = ("2005-01-01", "2017-12-31")
FEATURE_ID = "prof_gross_profitability"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--out", type=Path,
                    default=Path("results/004_universe_census.json"))
    ap.add_argument("--start", default=IN_SAMPLE[0])
    ap.add_argument("--end", default=IN_SAMPLE[1])
    ap.add_argument("--min-mcap", type=float, default=None)
    ap.add_argument("--max-mcap", type=float, default=None)
    ap.add_argument("--min-addv", type=float, default=None)
    ap.add_argument("--min-close", type=float, default=None)
    args = ap.parse_args()

    base = load_config("experiment", "costs", "synthetic", "sharadar")
    if pd.Timestamp(args.end) > pd.Timestamp(base.period("in_sample")["end"]):
        raise SystemExit("census is in-sample only; refusing a later end date")

    floors = dict(SMALLCAP_FLOORS)
    ceiling = MARKET_CAP_CEILING_USD
    if args.min_mcap is not None:
        floors["min_market_cap_usd"] = args.min_mcap
    if args.min_addv is not None:
        floors["min_addv_usd"] = args.min_addv
    if args.min_close is not None:
        floors["min_close_usd"] = args.min_close
    if args.max_mcap is not None:
        ceiling = args.max_mcap
    # The ceiling goes through the CONFIG (build_universe supports it since
    # the 004 registration). Overriding only the floor while the registered
    # config carries max_market_cap_usd=2e9 produced an EMPTY band [2B,2B)
    # in the first mid-cap run -- caught because zero breadth is impossible.
    floors["max_market_cap_usd"] = ceiling
    data = copy.deepcopy(base.data)
    data["universe"].update(floors)
    cfg = type(base)(data=data, sources=base.sources)

    print(f"loading panel {args.start}..{args.end} (small-cap floors, in memory)")
    source = ProductionSource(args.snapshot, cfg, args.start, args.end)
    panel = source.load()

    universe = build_universe(panel, cfg)
    # The draft's ceiling: keep names BELOW $2B. Applied here as a census
    # mask; a signed protocol would carry it in the certified universe path.
    below_ceiling = panel.market_cap < ceiling
    eligible = universe.eligible & below_ceiling.reindex_like(universe.eligible).fillna(False)

    # Feature AVAILABILITY only: where does a PIT-admissible value exist?
    spec = next(x for x in built_specs() if x.feature_id == FEATURE_ID)
    values, known, report = build_features(args.snapshot, panel, (spec,))
    available = values[FEATURE_ID].notna()  # presence, never magnitude

    names_per_day = eligible.sum(axis=1)
    covered_per_day = (eligible & available.reindex_like(eligible).fillna(False)).sum(axis=1)
    yearly = pd.DataFrame({
        "eligible_median": names_per_day.groupby(names_per_day.index.year).median(),
        "gp_covered_median": covered_per_day.groupby(covered_per_day.index.year).median(),
    })

    census = {
        "purpose": "APEX-004 draft section 5a structural breadth census",
        "period": {"start": args.start, "end": args.end, "locked": False},
        "floors": {**floors, "market_cap_ceiling_usd": ceiling},
        "dataset_fingerprint": source.dataset_fingerprint,
        "eligible_names_per_day": {
            "median": float(names_per_day.median()),
            "p10": float(names_per_day.quantile(0.10)),
            "p90": float(names_per_day.quantile(0.90)),
            "min": int(names_per_day.min()),
        },
        "gp_availability_within_eligible": {
            "median_names": float(covered_per_day.median()),
            "median_fraction": float(
                (covered_per_day / names_per_day.replace(0, pd.NA)).median()
            ),
        },
        "by_year": {
            str(y): {"eligible_median": float(r.eligible_median),
                     "gp_covered_median": float(r.gp_covered_median)}
            for y, r in yearly.iterrows()
        },
        "reads": "eligibility + availability only; no magnitudes, no returns",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(census, indent=2))
    print(json.dumps({k: census[k] for k in
                      ("eligible_names_per_day", "gp_availability_within_eligible")},
                     indent=2))
    print(f"census written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
