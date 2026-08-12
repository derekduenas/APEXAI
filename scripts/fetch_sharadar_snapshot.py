#!/usr/bin/env python
"""Build the frozen production Sharadar snapshot.

    NASDAQ_DATA_LINK_API_KEY='...' python scripts/fetch_sharadar_snapshot.py --canary
    NASDAQ_DATA_LINK_API_KEY='...' python scripts/fetch_sharadar_snapshot.py --run

DOWNLOAD RULES, all measured rather than assumed (2026-08-11):

  * NEVER `page` with `limit` -- `page` is ignored when `limit` is set, and three
    consecutive "pages" return byte-identical rows.
  * A response whose row count EQUALS the limit is TRUNCATED, not complete. The
    API signals truncation with HTTP 200 and nothing else.
  * Only a response strictly SHORTER than the limit proves a slice complete.
  * A slice that truncates even at the maximum limit is SPLIT in half and
    retried, bounded -- never accepted, never silently shortened.
  * Every completed slice is hashed to disk with a sidecar. A rerun verifies the
    hash and skips the work: resumable and idempotent.
  * Rate budget is read from X-RateLimit-* headers, never guessed.

The API key is read from the environment and is stripped from every URL before
anything is written or shown. It appears in no artifact, manifest, filename,
log, exception or hash.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.sharadar_api import (  # noqa: E402
    MAX_LIMIT,
    SharadarClient,
    SilentTruncation,
    api_key,
)

LAKE_START, LAKE_END = "2004-01-01", "2026-06-30"

# Chunk widths chosen from measured density (~5,930 SEP rows/trading day) so a
# slice lands far below MAX_LIMIT. Truncation still splits adaptively if wrong.
TABLES = {
    "SEP":     {"table": "sep",     "chunk_days": 14,  "dated": True},
    "DAILY":   {"table": "daily",   "chunk_days": 14,  "dated": True},
    "ACTIONS": {"table": "actions", "chunk_days": 365, "dated": True},
    "TICKERS": {"table": "tickers", "chunk_days": None, "dated": False},
    # A-005: as-filed shares outstanding for APEX-002 only. `date` is the FILING
    # date, so date-range chunking selects on knowledge date, not period end.
    "SF1": {"table": "sf1", "chunk_days": 180, "dated": True},
}
MAX_SPLIT_DEPTH = 6


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _slice_path(root: Path, name: str, lo: str, hi: str) -> Path:
    stem = f"{name}_{lo}_{hi}" if lo else name
    return root / "raw" / name / f"{stem}.csv"


def _verified(path: Path) -> bool:
    """Idempotence: an existing slice counts only if its sidecar hash matches."""
    sidecar = path.with_suffix(".sha256")
    if not (path.exists() and sidecar.exists()):
        return False
    return sha256_file(path) == sidecar.read_text().strip()


def _write_slice(path: Path, columns, rows) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(path, index=False)
    digest = sha256_file(path)
    path.with_suffix(".sha256").write_text(digest)
    return digest


def fetch_slice(client, name, spec, lo, hi, root, stats, depth=0):
    """One date slice, split adaptively if it truncates. Returns list of records."""
    path = _slice_path(root, name, lo, hi)
    if _verified(path):
        stats["skipped"] += 1
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        return [{"file": path, "rows": len(frame), "sha256": sha256_file(path),
                 "lo": lo, "hi": hi, "columns": list(frame.columns)}]

    params = {"date.gte": lo, "date.lte": hi} if spec["dated"] else {}
    try:
        columns, rows = client.fetch_table(spec["table"], params, limit=MAX_LIMIT)
    except SilentTruncation:
        if depth >= MAX_SPLIT_DEPTH:
            raise SilentTruncation(
                f"{name} {lo}..{hi} still truncates at limit={MAX_LIMIT:,} after "
                f"{depth} splits. Refusing to accept a shortened slice."
            )
        stats["splits"] += 1
        mid = (pd.Timestamp(lo) + (pd.Timestamp(hi) - pd.Timestamp(lo)) / 2).normalize()
        left = fetch_slice(client, name, spec, lo, str(mid.date()), root, stats, depth + 1)
        right = fetch_slice(
            client, name, spec, str((mid + pd.Timedelta(days=1)).date()), hi, root, stats, depth + 1
        )
        return left + right

    digest = _write_slice(path, columns, rows)
    stats["fetched"] += 1
    stats["rows"] += len(rows)
    return [{"file": path, "rows": len(rows), "sha256": digest, "lo": lo, "hi": hi,
             "columns": columns}]


def canary(client, root: Path) -> bool:
    """Exact production code path, on a slice whose true size is known."""
    print("=== CANARY (production downloader, known 5-day slice) ===")
    params = {"date.gte": "2015-06-15", "date.lte": "2015-06-19"}

    cols, rows, truncated = client.fetch_chunk("sep", params, 10_000)
    print(f"  1. limit=10,000  -> {len(rows):,} rows, truncated flag = {truncated}")
    assert truncated, "CANARY FAILED: truncation not detected"

    try:
        client.fetch_table("sep", params, limit=10_000)
        print("  2. FAILED: fetch_table accepted a truncated slice")
        return False
    except SilentTruncation:
        print("  2. fetch_table correctly REJECTED the truncated slice")

    cols, rows = client.fetch_table("sep", params, limit=MAX_LIMIT)
    print(f"  3. limit={MAX_LIMIT:,} -> {len(rows):,} rows (expected 29,642)")
    if len(rows) != 29_642:
        print("     CANARY FAILED: unexpected row count")
        return False

    frame = pd.DataFrame(rows, columns=cols)
    dupes = frame.duplicated(subset=["ticker", "date"]).sum()
    print(f"  4. duplicate (ticker,date) records: {dupes}")
    if dupes:
        return False

    path = root / "canary" / "sep_canary.csv"
    digest = _write_slice(path, cols, rows)
    print(f"  5. artifact hash: {digest[:32]}...")
    print(f"  6. idempotence re-verify: {_verified(path)}")
    print("  CANARY PASSED\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canary", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--start", default=LAKE_START)
    ap.add_argument("--end", default=LAKE_END)
    ap.add_argument("--root", type=Path, default=Path("data/snapshots/sharadar/current"))
    args = ap.parse_args()

    config = load_config("experiment", "costs", "synthetic", "sharadar")
    client = SharadarClient(api_key())
    args.root.mkdir(parents=True, exist_ok=True)

    if args.canary or not args.run:
        ok = canary(client, args.root)
        if not args.run:
            return 0 if ok else 1
        if not ok:
            print("refusing to launch the full snapshot after a failed canary", file=sys.stderr)
            return 1

    stats = {"fetched": 0, "skipped": 0, "splits": 0, "rows": 0}
    manifest_tables = {}

    for name, spec in TABLES.items():
        print(f"=== {name} ===", flush=True)
        records = []
        if spec["dated"]:
            cursor = pd.Timestamp(args.start)
            end = pd.Timestamp(args.end)
            while cursor <= end:
                stop = min(cursor + pd.Timedelta(days=spec["chunk_days"] - 1), end)
                records += fetch_slice(
                    client, name, spec, str(cursor.date()), str(stop.date()), args.root, stats
                )
                cursor = stop + pd.Timedelta(days=1)
                if stats["fetched"] % 25 == 0 and stats["fetched"]:
                    print(f"  {name}: {stats['rows']:,} rows, {stats['fetched']} slices, "
                          f"weighted {client.rate.weighted_remaining:,} left", flush=True)
        else:
            records += fetch_slice(client, name, spec, "", "", args.root, stats)

        total = sum(r["rows"] for r in records)
        manifest_tables[name] = {
            "slices": len(records),
            "rows": total,
            "columns": records[0]["columns"] if records else [],
            "slice_hashes": {r["file"].name: r["sha256"] for r in records},
        }
        print(f"  {name}: {total:,} rows across {len(records)} verified slices\n", flush=True)

    manifest = {
        "snapshot_id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "Sharadar API v1.0 (api.sharadar.com)",
        "requested_range": {"start": args.start, "end": args.end},
        "tables": manifest_tables,
        "request_stats": {**stats, **client.log.as_dict()},
        "protocol_hash": (Path(config.get("experiment.protocol_file"))).read_bytes(),
    }
    manifest["protocol_hash"] = hashlib.sha256(manifest["protocol_hash"]).hexdigest()
    manifest["conventions_hash"] = hashlib.sha256(
        Path(config.get("experiment.conventions_file")).read_bytes()
    ).hexdigest()
    manifest["schema_fingerprint"] = hashlib.sha256(
        json.dumps({k: v["columns"] for k, v in manifest_tables.items()}, sort_keys=True).encode()
    ).hexdigest()
    manifest["dataset_fingerprint"] = hashlib.sha256(
        json.dumps(
            sorted(h for t in manifest_tables.values() for h in t["slice_hashes"].values())
        ).encode()
    ).hexdigest()

    (args.root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(f"snapshot: {args.root}")
    print(f"dataset fingerprint: {manifest['dataset_fingerprint']}")
    print(f"schema  fingerprint: {manifest['schema_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
