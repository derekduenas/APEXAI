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
import os
import threading
from pathlib import Path

# ATOMICITY LAW (2026-08-23, Defect B): the append transaction --
# read-authoritative-prev -> construct -> hash -> append -> flush/fsync
# -- must be one critical section. Two natural chain breaks occurred
# when the WS daemon's watchdog and reader threads interleaved here
# (both children of one parent, sub-ms apart; reproduced determin-
# istically with a barrier). Serialization is TWO-LAYER: a per-path
# thread lock (same process) plus an OS-level fcntl flock on a
# sidecar .lock file (accidental multi-process writers on one host).
# The historical broken ledgers stay forensic; they are never repaired.
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict = {}


def _path_lock(p: Path) -> threading.Lock:
    key = str(p.resolve() if p.exists() else p.absolute())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def chain_append(log_path: Path, entry: dict) -> dict:
    """Append one hash-chained record; returns the record as written.
    Thread-safe and (per-host) multi-process-safe."""
    log_path = Path(log_path)
    with _path_lock(log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lockfile = log_path.with_suffix(log_path.suffix + ".lock")
        with open(lockfile, "w") as lk:
            try:
                import fcntl
                fcntl.flock(lk, fcntl.LOCK_EX)
            except ImportError:                       # non-POSIX: thread
                pass                                  # lock still holds
            return _chain_append_locked(log_path, entry)


def _chain_append_locked(log_path: Path, entry: dict) -> dict:
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
        fh.flush()
        os.fsync(fh.fileno())
    return body
