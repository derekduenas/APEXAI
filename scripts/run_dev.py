#!/usr/bin/env python
"""DEVELOPMENT execution test. NOT a signal test. NOT validation.

    python scripts/run_dev.py --stooq <dir> [--n 400]

In-sample only. Spends no credit, writes no ledger entry, computes no verdict,
never touches the holdout -- all four enforced in code, not by this docstring.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import load_config  # noqa: E402
from apex.dev.namespace import development_banner  # noqa: E402
from apex.dev.source import DevelopmentSource  # noqa: E402
from apex.report.smoke import smoke_run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stooq", type=Path, required=True)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--out", type=Path, default=Path("results/dev_run.txt"))
    args = ap.parse_args()

    config = load_config("experiment", "costs", "synthetic")
    lake_start = config.get("calendar.lake_start")
    in_sample_end = config.period("in_sample")["end"]

    print(f"building development panel: {lake_start} .. {in_sample_end}", flush=True)
    source = DevelopmentSource(args.stooq, lake_start, in_sample_end, args.n)
    r = source.report

    lines = [development_banner(source.dataset_fingerprint), ""]
    lines.append("--- DATASET CONSTRUCTION " + "-" * 52)
    lines.append(f"  stooq files indexed      : {r.stooq_files_indexed:,}")
    lines.append(f"  securities in panel      : {r.stooq_selected:,}")
    lines.append(f"  price rows loaded        : {r.stooq_rows:,}")
    lines.append(f"  date range               : {r.date_range[0]} .. {r.date_range[1]}")
    lines.append(f"  EDGAR requests           : {r.edgar_requests:,}")
    lines.append("")
    lines.append("  IDENTITY (EDGAR CIK <- Stooq ticker; NO price cross-verification possible)")
    lines.append(f"    matched                : {r.identity_matched:,}")
    lines.append(f"    excluded, no CIK       : {r.identity_no_cik:,}")
    lines.append(f"    excluded, ambiguous    : {r.identity_ambiguous:,}")
    lines.append(f"    excluded, no overlap   : {r.identity_no_window_overlap:,}")
    lines.append("")
    lines.append("  POINT-IN-TIME SHARES OUTSTANDING (knowledge date = SEC filing date)")
    lines.append(f"    issuers with XBRL data : {r.shares_with_data:,}")
    lines.append(f"    issuers with none      : {r.shares_absent:,}")
    lines.append(f"    total observations     : {r.shares_observations:,}")
    lines.append("")
    lines.append("  DELISTING")
    lines.append(f"    detected (corroborated): {r.delistings_detected:,}")
    lines.append(f"    Form 25 but still listed: {r.form25_but_still_listed:,}")
    lines.append("")
    lines.append("  CONTAMINATION FLAGS")
    lines.append(f"    price adjustment       : {r.price_adjustment}")
    lines.append(f"    unadjusted available   : {r.unadjusted_available}  "
                 f"<-- $5 close and $1B mcap filters run on ADJUSTED prices (CONVENTIONS 4.4 violation)")
    lines.append(f"    VIX available          : {r.vix_available}  <-- B5 regime reporting DISABLED")
    lines.append(f"    adapter failures       : {len(r.failures)}")
    for f in r.failures[:5]:
        lines.append(f"      {f}")
    lines.append("")

    print("\n".join(lines), flush=True)

    print("running in-sample smoke pipeline + both audits ...", flush=True)
    report, output = smoke_run(source, config, "in_sample")

    text = "\n".join(lines) + "\n" + report.render()
    text += "\n\n" + development_banner(source.dataset_fingerprint)
    text += (
        "\n\nNO verdict computed. NO ledger entry. NO credit spent. Holdout untouched.\n"
        "GROSS ONLY -- COST SIMULATION NOT YET EXECUTED (Stage 6 unbuilt).\n"
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(report.render())
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
