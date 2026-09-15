#!/usr/bin/env python
"""Ruling 2 -- the mandatory in-sample smoke run, before validation.

    python scripts/run_smoke.py --snapshot /path/to/sharadar-export

Structural and unit validation only. Spends no research credit; in-sample is
unlocked by design (protocol section 7) and can be re-run freely while the
vendor export is shaken out.

`--synthetic` runs the same harness against the generated null world. That is
NOT the smoke run -- it proves the harness itself works, on data whose answers
are already known.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import load_config  # noqa: E402
from apex.report.smoke import smoke_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--snapshot", type=Path, help="frozen Sharadar bulk export directory")
    group.add_argument(
        "--synthetic", action="store_true", help="harness self-test on the null world"
    )
    parser.add_argument("--out", type=Path, default=Path("results/smoke_in_sample.txt"))
    args = parser.parse_args()

    if args.synthetic:
        config = load_config("experiment", "costs", "synthetic")
        from apex.data.synthetic import SyntheticSource

        source = SyntheticSource(
            config=config,
            seed=20260809,
            alpha=0.0,
            overrides={
                "panel.n_securities": 600,
                # Smoke fixture follows the active small-cap universe, with tails
                # on BOTH sides to exercise exclusion. Do not change the registered
                # universe or rank-count assertion to fit an obsolete large-cap DGP.
                "market_cap.initial_min_usd": float(config.get("universe.min_market_cap_usd")) / 2,
                "market_cap.initial_max_usd": float(config.get("universe.max_market_cap_usd")) * 2,
                "panel.start": "2004-01-01",
                "panel.end": "2008-12-31",
            },
        )
        banner = (
            "HARNESS SELF-TEST ON SYNTHETIC DATA -- this is NOT the smoke run.\n"
            "The panel is a null world by construction, so a mean IC near zero is\n"
            "the correct answer and says nothing about the real experiment.\n"
        )
    else:
        config = load_config("experiment", "costs", "synthetic", "sharadar")
        from apex.data.sharadar import SharadarSnapshot

        source = SharadarSnapshot(args.snapshot, config)
        banner = ""

    report, _ = smoke_run(source, config, "in_sample")

    text = (banner + "\n" if banner else "") + report.render()
    print(text)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"\nwritten to {args.out}")

    return 0 if report.clear_to_proceed else 1


if __name__ == "__main__":
    raise SystemExit(main())
