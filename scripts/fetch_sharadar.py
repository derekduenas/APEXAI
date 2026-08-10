#!/usr/bin/env python
"""Acquire a frozen Sharadar snapshot from the Nasdaq Data Link API.

    NASDAQ_DATA_LINK_API_KEY='...' python scripts/fetch_sharadar.py --probe
    NASDAQ_DATA_LINK_API_KEY='...' python scripts/fetch_sharadar.py --fetch --confirm

--probe (default) asks one yes/no question per table and downloads nothing.
--fetch refuses unless EVERY required table is entitled, then writes a
timestamped snapshot plus a manifest recording dataset name, endpoint,
retrieval time, row count, columns, date range and SHA-256 per file.

The key is read from the environment and nowhere else. It is stripped from
every URL before anything is written or printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import load_config  # noqa: E402
from apex.data.nasdaq_api import (  # noqa: E402
    ApiKeyMissing,
    NasdaqDataLinkClient,
    NotEntitled,
    RateLimited,
    api_key,
    write_snapshot_file,
)

# Experiment #001 needs exactly these. TICKERS carries identity, category,
# exchange and delisting; SEP carries OHLCV; DAILY carries PIT market cap;
# ACTIONS carries the M&A-vs-performance delisting classification.
REQUIRED_TABLES = ("TICKERS", "SEP", "DAILY", "ACTIONS")
# TICKERS is a security master, not a time series -- no date filter applies.
UNDATED_TABLES = {"TICKERS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="entitlement only (default)")
    mode.add_argument("--fetch", action="store_true", help="download and write a snapshot")
    parser.add_argument("--start", default=None, help="default: config calendar.lake_start")
    parser.add_argument("--end", default=None, help="default: config calendar.lake_end")
    parser.add_argument(
        "--confirm", action="store_true",
        help="required for --fetch; acknowledges the estimated download volume",
    )
    parser.add_argument("--root", type=Path, default=Path("data/snapshots/sharadar"))
    args = parser.parse_args()

    config = load_config("experiment", "costs", "synthetic", "sharadar")
    start = args.start or config.get("calendar.lake_start")
    end = args.end or config.get("calendar.lake_end")

    try:
        client = NasdaqDataLinkClient(api_key())
    except ApiKeyMissing as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"probing entitlement for {list(REQUIRED_TABLES)} ...", flush=True)
    try:
        report = client.require_entitled(REQUIRED_TABLES)
    except (NotEntitled, RateLimited) as exc:
        print("\nDATA ACCESS RESULT")
        print(f"Status: BLOCKED")
        print(exc)
        print("\nResearch credit consumed: 0")
        print("Holdout opened: No")
        return 3

    print(report.render())
    if not args.fetch:
        print("\nprobe only; nothing downloaded. Re-run with --fetch --confirm to acquire.")
        return 0

    if not args.confirm:
        print(
            f"\nREFUSED: --fetch requires --confirm.\n"
            f"  Range {start} to {end}. SEP and DAILY are daily-by-security tables;\n"
            f"  over this range they are millions of rows and hundreds of API calls.\n"
            f"  Re-run with --confirm once you accept the quota cost.",
            file=sys.stderr,
        )
        return 2

    snapshot_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = args.root / snapshot_id
    entries = []

    for table in REQUIRED_TABLES:
        params = {} if table in UNDATED_TABLES else {"date.gte": start, "date.lte": end}
        print(f"  downloading {table} ...", flush=True)
        columns, rows, meta = client.fetch_table(table, params)
        entry = write_snapshot_file(
            directory, table, columns, rows,
            endpoint=f"https://data.nasdaq.com/api/v3/datatables/SHARADAR/{table}.json",
        )
        entry["request_params"] = params
        entry["pages"] = meta["pages"]
        entries.append(entry)
        print(f"    {entry['rows']:,} rows, {len(entry['columns'])} cols, "
              f"sha256 {entry['sha256'][:12]}")

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "vendor": "SHARADAR",
        "source": "Nasdaq Data Link datatables API v3",
        "requested_range": {"start": start, "end": end},
        "entitlement": report.as_dict(),
        "api_calls": client.calls_made,
        "endpoints": client.endpoints_used,
        "files": entries,
    }
    manifest["snapshot_digest"] = hashlib.sha256(
        json.dumps([e["sha256"] for e in entries], sort_keys=True).encode()
    ).hexdigest()

    (directory / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nsnapshot written: {directory}")
    print(f"snapshot digest : {manifest['snapshot_digest']}")
    print(
        "\nNOTE: VIX is not a Sharadar table. The regime breakdown (B5) needs a\n"
        "separately sourced VIX.csv in this directory. Its absence is a\n"
        "REGIME-REPORTING limitation only; it does not affect any pass/fail criterion."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
