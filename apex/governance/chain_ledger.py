"""CANONICAL HASH-CHAIN APPEND -- the shared ledger primitive.

Until 2026-08-20 this lived only as scripts/nightly_pull._chain_append,
and every package that needed it (reconnect_ledger, watchlist,
daily_market_memory, subscription_allocator, research documents,
leading_edge_map, curve) reached it through a sys.path.insert("scripts")
shim -- a library importing from a script, fragile against any cwd or
packaging change, and invisible to import-closure tooling.

This module is now the single home. scripts/nightly_pull re-exports it
for its many existing callers; new code imports from HERE.

The semantics are battle-hardened and must not drift:
  * O(1) tail read for the previous hash (LAB-03)
  * torn-tail recovery recorded IN the entry, never hidden
  * a torn final line is terminated before appending (SAC1-06) so the
    fragment stays visibly damaged instead of corrupting the new record
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def chain_append(log_path: Path, entry: dict) -> dict:
    """Append one hash-chained record; returns the record as written."""
    log_path = Path(log_path)
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
    needs_nl = False
    if log_path.exists() and log_path.stat().st_size > 0:
        with log_path.open("rb") as fh:
            fh.seek(-1, 2)
            needs_nl = fh.read(1) != b"\n"
    with log_path.open("a") as fh:
        if needs_nl:
            fh.write("\n")
        fh.write(json.dumps(body, sort_keys=True) + "\n")
    return body
