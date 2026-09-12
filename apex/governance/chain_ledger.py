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

ORCHESTRATOR-OOM-001-R1 (2026-09-06). The tail read was only O(1) when it
succeeded. When no entry_hash appeared in the fixed 256 KiB window it fell
back to log_path.read_text() over the WHOLE ledger, so the cost of one
append became proportional to the whole file. On 2026-09-06 the
orchestrator ledger's final record reached 262275 bytes -- 131 past the
window -- and no complete record could ever sit inside it again. Every
append then read all 438 MB, needing 1267 MiB (measured) against that
service's 512 MiB cap, and the daemon was killed about a second after
every start for sixteen hours.

The search is now BOUNDED: it widens from 256 KiB to MAX_TAIL_SEARCH_BYTES
and then refuses, so no ledger's size can decide how much memory an append
takes. Four other chain ledgers on this host run from 65 MB to 688 MB and
were one oversized record away from the same failure.
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

# BOUNDED TAIL SEARCH (ORCHESTRATOR-OOM-001-R1). The first window is the
# historical one, so the overwhelmingly common case reads exactly what it
# always did. Beyond it the window doubles, and at the ceiling the append
# REFUSES rather than growing without limit.
INITIAL_TAIL_BYTES = 262144
MAX_TAIL_SEARCH_BYTES = 8 * 1024 * 1024


class ChainTailUnresolved(RuntimeError):
    """No previous hash within MAX_TAIL_SEARCH_BYTES of the end.

    Raised BEFORE anything is written, so the ledger is left byte-for-byte
    unchanged. It is never downgraded to GENESIS: silently restarting a
    chain because its tail was inconvenient to read would forge continuity
    that does not exist.
    """


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


def _prev_hash_bounded(log_path: Path, size: int) -> tuple:
    """The previous entry_hash, found by a BOUNDED backward search.

    Returns (prev_hash, torn). Reads at most MAX_TAIL_SEARCH_BYTES.

    Behaviour, stated so it cannot drift:
      empty / absent file   -> ("GENESIS", False); the caller never gets here
      valid final record    -> its entry_hash, torn False
      torn final fragment   -> the last VALID record's hash, torn True
                               (SAC1-06: link past the fragment, not to it)
      malformed final record-> identical to a torn one: unparseable is
                               unparseable, and the tear is recorded
      no usable record ANY-
      where in the file     -> ("GENESIS", torn); unchanged from before,
                               because the search covered every byte
      nothing within the
      ceiling               -> ChainTailUnresolved, raised before any write

    The last case is the one deliberate semantic change. Previously such a
    ledger was walked end to end, at a cost set by its size; that is the
    defect being removed. Refusing loudly, with the ledger untouched, is
    the honest replacement for an allocation that kills the process.
    """
    window = INITIAL_TAIL_BYTES
    while True:
        start = max(0, size - window)
        with log_path.open("rb") as fh:
            # A window starting at byte 0, or immediately after a newline,
            # begins exactly ON a record boundary -- its first line is
            # COMPLETE and must not be discarded as a cut fragment.
            if start == 0:
                aligned = True
            else:
                fh.seek(start - 1)
                aligned = fh.read(1) == b"\n"
            fh.seek(start)
            raw = fh.read(size - start)
        # errors="replace" only ever touches a multibyte character split by
        # the window edge, which lies inside the leading partial line that
        # an unaligned window discards anyway.
        lines = [ln for ln in raw.decode("utf-8", errors="replace").splitlines()
                 if ln.strip()]
        if not aligned and lines:
            lines = lines[1:]                    # this one really was cut
        torn = False
        for line in reversed(lines):
            try:
                return json.loads(line)["entry_hash"], torn
            except (json.JSONDecodeError, KeyError):
                torn = True
        if start == 0:                           # the whole file, no record
            return "GENESIS", torn
        if window >= MAX_TAIL_SEARCH_BYTES:
            raise ChainTailUnresolved(
                "%s: no parseable entry_hash within the last %d bytes of a "
                "%d byte ledger. Nothing was written. Either the final record "
                "is larger than the search ceiling, or the tail is damaged "
                "beyond it; both need a decision, not a guess."
                % (log_path, window, size))
        window = min(window * 2, MAX_TAIL_SEARCH_BYTES)


def _chain_append_locked(log_path: Path, entry: dict) -> dict:
    prev, torn = "GENESIS", False
    if log_path.exists() and log_path.stat().st_size > 0:
        prev, torn = _prev_hash_bounded(log_path, log_path.stat().st_size)
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
