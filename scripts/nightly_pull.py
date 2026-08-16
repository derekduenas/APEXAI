#!/usr/bin/env python
"""Nightly incremental Sharadar pull -- the LIVE data path.

    NASDAQ_DATA_LINK_API_KEY='...' python scripts/nightly_pull.py --run

WHAT THIS IS
------------
The deployment-facing data feed. It extends an append-only LIVE LAKE at
`data/live/sharadar/` forward from where the frozen confirmatory snapshot ends
(2026-06-30), one incremental range per night. It reuses the snapshot
downloader's slice machinery unchanged -- truncation detection, adaptive
splitting, hash sidecars, resumable idempotence -- because that code is already
certified and a second downloader would be a second source of truth.

WHAT THIS IS NOT -- THE GOVERNANCE LINE
---------------------------------------
Live data is NOT confirmatory evidence. Its manifest fingerprint is minted with
`dev_fingerprint("live", ...)`, which places it permanently inside the
development namespace. All four existing refusal points (verdict, ledger,
period gate, banner) therefore refuse it without a single new guard being
written: a live-lake dataset structurally CANNOT open a locked period, spend a
credit, or back a promotion verdict. Experiments read frozen snapshots;
deployment and monitoring read the lake. The two cannot be confused because
the identity itself carries the refusal.

THE KEY: environment variable only, exactly as the snapshot fetcher -- never
written to config, logs, manifests, URLs-at-rest, or error text.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS.parent))
sys.path.insert(0, str(_SCRIPTS))

import pandas as pd  # noqa: E402

import fetch_sharadar_snapshot as snap  # noqa: E402  (certified slice machinery)
from apex.data.sharadar_api import SharadarClient, api_key  # noqa: E402
from apex.dev.namespace import dev_fingerprint, is_development  # noqa: E402

# Where the frozen confirmatory snapshot ends: the lake begins the next day.
FROZEN_SNAPSHOT_END = "2026-06-30"

# The lake pulls the same dated tables as the snapshot, same chunk widths.
LAKE_TABLES = {k: v for k, v in snap.TABLES.items() if v["dated"]}

DEFAULT_ROOT = Path("data/live/sharadar")


class LiveLakeError(RuntimeError):
    """A live-lake invariant was violated."""


def require_outside_snapshots(root: Path) -> Path:
    """The lake must NEVER live inside data/snapshots/**.

    The frozen snapshot is the confirmatory substrate; a lake that wrote into
    it would mutate evidence in place. Refused structurally, not documented.
    """
    resolved = root.resolve()
    if "snapshots" in resolved.parts:
        raise LiveLakeError(
            f"live lake root {resolved} is inside a snapshots directory. "
            f"The frozen snapshot is immutable evidence; the live lake is "
            f"append-only deployment data. They must not share a root."
        )
    return resolved


def state_path(root: Path) -> Path:
    return root / "state.json"


def lake_through(root: Path) -> str:
    """Last date the lake covers. Before the first pull, the frozen end."""
    p = state_path(root)
    if not p.exists():
        return FROZEN_SNAPSHOT_END
    return json.loads(p.read_text())["lake_through"]


def _chain_append(log_path: Path, entry: dict) -> dict:
    """Append one hash-chained record. Same discipline as the research ledger:
    every night's pull is a fact with a position in a sequence, not a loose log
    line that can be edited."""
    # a torn write (crash mid-append) must never kill the archive: walk
    # back to the last parseable entry, link past the tear, and RECORD the
    # recovery in the new entry so the anomaly is visible, not hidden.
    # LAB-03: read only the file TAIL (O(1)), not the whole ledger — the
    # full-file read made appends quadratic on large replay ledgers. The
    # tail chunk is far larger than any single record; if no line in it
    # parses, fall back to a full walk (correctness over speed).
    prev, torn = "GENESIS", False
    if log_path.exists() and log_path.stat().st_size > 0:
        size = log_path.stat().st_size
        with log_path.open("rb") as fh:
            fh.seek(max(0, size - 262144))
            tail = fh.read().decode("utf-8", errors="replace")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if size > 262144 and lines:
            lines = lines[1:]                    # first tail line may be cut
        found = False
        for line in reversed(lines):
            try:
                prev = json.loads(line)["entry_hash"]
                found = True
                break
            except (json.JSONDecodeError, KeyError):
                torn = True
        if not found:                            # pathological: full walk
            for line in reversed(
                    log_path.read_text().strip().splitlines()):
                try:
                    prev = json.loads(line)["entry_hash"]
                    break
                except (json.JSONDecodeError, KeyError):
                    torn = True
    body = {**entry, "prev_hash": prev}
    if torn:
        body["recovered_from_torn_tail"] = True
    body["entry_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()
    ).hexdigest()
    with log_path.open("a") as fh:
        fh.write(json.dumps(body, sort_keys=True) + "\n")
    return body


def _pull_spy(client, root: Path, lo: str, hi: str) -> dict:
    """SFP benchmark slice (SPY only). The panel builder needs the benchmark
    series to extend with the lake; without it, live-paper marks would price
    portfolios against a benchmark frozen at the snapshot end."""
    columns, rows = client.fetch_table(
        "sfp", {"ticker": "SPY", "date.gte": lo, "date.lte": hi},
        limit=snap.MAX_LIMIT)
    path = root / "raw" / "SFP" / f"SFP_SPY_{lo}_{hi}.csv"
    digest = snap._write_slice(path, columns, rows)
    return {"file": path.name, "rows": len(rows), "sha256": digest}


def _refresh_tickers(client, root: Path, pull_date: str) -> dict:
    """TICKERS is a full nightly refresh, dated by pull date so history keeps.

    Unlike the dated tables it has no date column to slice on; each night's
    copy is a distinct hashed artifact, so metadata drift (name changes,
    delistings, exchange moves) is itself observable over time.
    """
    columns, rows = client.fetch_table("tickers", {}, limit=snap.MAX_LIMIT)
    path = root / "raw" / "TICKERS" / f"TICKERS_{pull_date}.csv"
    digest = snap._write_slice(path, columns, rows)
    return {"file": path.name, "rows": len(rows), "sha256": digest}


def pull_range(root: Path) -> tuple[str, str] | None:
    """The incremental range: day after the lake ends, through yesterday UTC.

    None when the lake is already current -- a clean no-op, because the job
    runs every night whether or not there was a trading day.
    """
    start = pd.Timestamp(lake_through(root)) + pd.Timedelta(days=1)
    end = pd.Timestamp(dt.datetime.now(dt.timezone.utc).date()) - pd.Timedelta(days=1)
    if start > end:
        return None
    return str(start.date()), str(end.date())


def run_pull(client, root: Path, lo: str, hi: str) -> dict:
    """One incremental pull. Slices are verified-or-fetched (idempotent), the
    manifest is rewritten from the FULL lake state, and the state file advances
    only after everything else has succeeded."""
    root = require_outside_snapshots(root)
    root.mkdir(parents=True, exist_ok=True)
    stats = {"fetched": 0, "skipped": 0, "splits": 0, "rows": 0}
    tables: dict[str, list] = {}

    for name, spec in LAKE_TABLES.items():
        records = []
        cursor, end = pd.Timestamp(lo), pd.Timestamp(hi)
        while cursor <= end:
            stop = min(cursor + pd.Timedelta(days=spec["chunk_days"] - 1), end)
            records += snap.fetch_slice(
                client, name, spec, str(cursor.date()), str(stop.date()), root, stats
            )
            cursor = stop + pd.Timedelta(days=1)
        tables[name] = records

    tickers = _refresh_tickers(client, root, hi)
    spy = _pull_spy(client, root, lo, hi)

    # Fingerprint over EVERY slice sidecar in the lake, then deliberately
    # minted into the development namespace: this dataset must be refused by
    # every confirmatory gate, forever, without those gates changing.
    all_hashes = sorted(
        p.read_text().strip() for p in (root / "raw").rglob("*.sha256")
    )
    digest = hashlib.sha256(json.dumps(all_hashes).encode()).hexdigest()
    fingerprint = dev_fingerprint("live", digest)
    assert is_development(fingerprint)  # the refusal is the identity

    manifest = {
        "role": "LIVE_LAKE -- deployment and monitoring only, NEVER evidence",
        "lake_start": FROZEN_SNAPSHOT_END,
        "lake_through": hi,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "Sharadar API v1.0 (api.sharadar.com)",
        "dataset_fingerprint": fingerprint,
        "slice_count": len(all_hashes),
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))

    entry = _chain_append(root / "pull_log.jsonl", {
        "pulled_at": manifest["updated_at"],
        "range": {"start": lo, "end": hi},
        "rows": {name: sum(r["rows"] for r in recs) for name, recs in tables.items()},
        "tickers_refresh": tickers,
        "spy_benchmark": spy,
        "stats": stats,
        "dataset_fingerprint": fingerprint,
    })

    # State advances LAST: a crashed pull re-runs the same range next night,
    # and verified slices make the re-run cheap.
    state_path(root).write_text(json.dumps({"lake_through": hi}))
    return {"manifest": manifest, "log_entry": entry, "stats": stats}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--through", default=None,
                    help="override end date (default: yesterday UTC)")
    args = ap.parse_args()

    root = require_outside_snapshots(args.root)
    rng = pull_range(root)
    if args.through is not None and rng is not None:
        rng = (rng[0], args.through)

    if rng is None:
        print(f"lake already current through {lake_through(root)} -- no-op")
        return 0
    if not args.run:
        print(f"would pull {rng[0]} .. {rng[1]} into {root} (pass --run)")
        return 0

    client = SharadarClient(api_key())
    result = run_pull(client, root, *rng)
    print(f"pulled {rng[0]} .. {rng[1]}")
    print(f"rows: {json.dumps(result['log_entry']['rows'])}")
    print(f"lake fingerprint: {result['manifest']['dataset_fingerprint']}")
    print(f"lake through: {result['manifest']['lake_through']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
