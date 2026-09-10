"""Receipts, chain verification and atomic transitions.

STATE CANONICALIZATION RECIPE (what every hash in this module is over):
  entry_hash  = sha256( json.dumps(body_without_entry_hash, sort_keys=True) )
                -- the chain_ledger recipe: default separators (", ", ": "),
                   sort_keys, UTF-8; `body` includes prev_hash. This hashes the
                   canonical RE-SERIALIZATION of the parsed object, not the
                   raw line bytes. Recomputed here with the same recipe.
  prev_hash   = the previous record's entry_hash, or "GENESIS".
  content hashes inside records (forecast_hash, intent_id, ...) use
  records.canonical_json: sort_keys, compact separators, allow_nan=False.

THREAT BOUNDARY (honest): these hashes detect INCONSISTENCY -- a record
that was altered, truncated, re-ordered, or spliced from another ledger --
against a reader that recomputes them. They are NOT tamper-proof: a writer
with the file and the recipe can rewrite the whole chain consistently.
Tamper-evidence against such a writer needs an external anchor (a signed
digest kept elsewhere), which this brick does not provide and does not
claim.

ATOMIC TRANSITIONS: `transaction(path)` takes a lock on `<path>.txn.lock`
(a process-level threading lock plus fcntl flock) that spans the READ of the
current ledger state, the CHECK, and the APPEND, so two workers cannot both
pass a "no fill yet" check. chain_append keeps its own lock and fsync inside.
`commit_once` is the idempotent transition primitive: keyed by txn_id, it
returns the existing record if the transition already committed (lost-ack
reconciliation) and appends exactly once otherwise."""
from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from apex.governance.chain_ledger import chain_append

from .records import strict_serializable, RecordRefused

ENTRY_HASH_RECIPE = "sha256(json.dumps(body_without_entry_hash, sort_keys=True)) -- chain_ledger recipe, default separators"

_TXN_GUARD = threading.Lock()
_TXN_LOCKS: dict = {}


class LedgerRefused(RuntimeError):
    """Persistence could not be proven. Nothing downstream may proceed."""


class ChainBroken(LedgerRefused):
    """The referenced history does not verify as one consistent chain."""


def read_all(path: Path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"kind": "UNPARSEABLE_LINE", "raw": line[:120]})
    return out


def recompute_entry_hash(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "entry_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- chain verification

def verify_chain(path: Path, *, upto_seq: int | None = None, rows: list | None = None) -> list:
    """Verify records 1..upto_seq as one chain: each hashes to its own
    entry_hash and each prev_hash equals its predecessor's entry_hash
    (GENESIS for the first). Returns the rows. Raises ChainBroken."""
    rows = read_all(path) if rows is None else rows
    n = len(rows) if upto_seq is None else upto_seq
    if n > len(rows):
        raise ChainBroken("CHAIN_SHORT: asked for seq %d, ledger has %d" % (n, len(rows)))
    prev = "GENESIS"
    for i in range(n):
        rec = rows[i]
        seq = i + 1
        if rec.get("kind") == "UNPARSEABLE_LINE":
            raise ChainBroken("CHAIN_UNPARSEABLE at seq %d" % seq)
        if rec.get("prev_hash") != prev:
            raise ChainBroken("CHAIN_LINK_BROKEN at seq %d: prev_hash %r != predecessor %r"
                              % (seq, str(rec.get("prev_hash"))[:12], prev[:12]))
        if recompute_entry_hash(rec) != rec.get("entry_hash"):
            raise ChainBroken("CHAIN_RECORD_ALTERED at seq %d" % seq)
        prev = rec["entry_hash"]
    return rows


# ---------------------------------------------------------------- append with receipt

def append_with_receipt(path: Path, entry: dict) -> dict:
    """Strictly serialize, append via chain_append (locked + fsync), then
    prove the append by re-reading the tail and verifying its link."""
    path = Path(path)
    try:
        strict_serializable(entry, what=str(entry.get("kind")))
    except RecordRefused as e:
        raise LedgerRefused(str(e)) from e
    if "entry_hash" in entry or "prev_hash" in entry:
        raise LedgerRefused("ENTRY_CARRIES_CHAIN_FIELDS: caller may not supply entry_hash/prev_hash")
    try:
        written = chain_append(path, entry)
    except Exception as e:                                               # noqa: BLE001
        raise LedgerRefused("PERSISTENCE_FAILED: %s: %s" % (type(e).__name__, str(e)[:200])) from e
    rows = read_all(path)
    if not rows:
        raise LedgerRefused("PERSISTENCE_UNPROVEN: ledger empty after append")
    seq = len(rows)
    tail = rows[-1]
    if tail.get("entry_hash") != written.get("entry_hash"):
        raise LedgerRefused("PERSISTENCE_UNPROVEN: tail hash %r != written %r"
                            % (str(tail.get("entry_hash"))[:12], str(written.get("entry_hash"))[:12]))
    if recompute_entry_hash(tail) != tail["entry_hash"]:
        raise LedgerRefused("PERSISTENCE_UNPROVEN: tail does not hash to its own entry_hash")
    if seq > 1 and tail.get("prev_hash") != rows[-2].get("entry_hash"):
        raise LedgerRefused("PERSISTENCE_UNPROVEN: tail prev_hash does not link to seq %d" % (seq - 1))
    return {"path": str(path), "seq": seq, "entry_hash": tail["entry_hash"], "kind": tail.get("kind"),
            "receipt": "RE-READ from disk after append; seq is the 1-indexed line number; link to predecessor verified"}


def verify_receipt(path: Path, receipt: dict, *, expected_kind: str | None = None, chain: bool = True) -> dict:
    """Re-read the record a receipt points to and prove it is intact AND,
    with chain=True (default), that the whole history up to it verifies as
    one chain. Refuses: missing file, seq out of range, kind mismatch,
    entry_hash mismatch, altered record, broken predecessor link."""
    if not isinstance(receipt, dict) or not {"path", "seq", "entry_hash"} <= set(receipt):
        raise LedgerRefused("RECEIPT_MALFORMED: %r" % (sorted(receipt) if isinstance(receipt, dict) else type(receipt).__name__))
    if str(receipt["path"]) != str(Path(path)):
        raise LedgerRefused("RECEIPT_FOREIGN_LEDGER: %r" % receipt["path"])
    rows = read_all(path)
    seq = receipt["seq"]
    if type(seq) is not int or seq < 1 or seq > len(rows):
        raise LedgerRefused("RECEIPT_SEQ_UNKNOWN: seq=%r, ledger has %d records" % (seq, len(rows)))
    rec = rows[seq - 1]
    if rec.get("kind") == "UNPARSEABLE_LINE":
        raise LedgerRefused("RECORD_UNPARSEABLE at seq %d" % seq)
    if expected_kind and rec.get("kind") != expected_kind:
        raise LedgerRefused("RECORD_KIND_MISMATCH at seq %d: %r != %r" % (seq, rec.get("kind"), expected_kind))
    if rec.get("entry_hash") != receipt["entry_hash"]:
        raise LedgerRefused("RECORD_HASH_MISMATCH at seq %d: on disk %r, receipt %r"
                            % (seq, str(rec.get("entry_hash"))[:12], str(receipt["entry_hash"])[:12]))
    if recompute_entry_hash(rec) != rec["entry_hash"]:
        raise LedgerRefused("RECORD_ALTERED at seq %d: bytes do not hash to entry_hash" % seq)
    if chain:
        verify_chain(path, upto_seq=seq, rows=rows)
    return rec


def find(path: Path, *, kind: str, where, rows: list | None = None) -> list:
    """Records of `kind` satisfying `where(rec)`, with their seq."""
    rows = read_all(path) if rows is None else rows
    return [(i + 1, r) for i, r in enumerate(rows) if r.get("kind") == kind and where(r)]


# ---------------------------------------------------------------- atomic transitions

def _txn_lock(p: Path) -> threading.Lock:
    key = str(p.absolute())
    with _TXN_GUARD:
        if key not in _TXN_LOCKS:
            _TXN_LOCKS[key] = threading.Lock()
        return _TXN_LOCKS[key]


@contextmanager
def transaction(path: Path):
    """Serialize a check-and-commit against `path`: thread lock + fcntl
    flock on `<path>.txn.lock`. Reads made inside see the committed state;
    an append inside is the only append that can happen concurrently."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lockfile = path.with_suffix(path.suffix + ".txn.lock")
        lk = open(lockfile, "w")
    except OSError as e:
        raise LedgerRefused("PERSISTENCE_FAILED: transaction lock: %s: %s" % (type(e).__name__, str(e)[:160])) from e
    with _txn_lock(path):
        with lk:
            try:
                import fcntl
                fcntl.flock(lk, fcntl.LOCK_EX)
            except ImportError:
                pass
            yield


def commit_once(path: Path, *, txn_id: str, build, kind: str | None = None) -> tuple:
    """Idempotent transition. Inside the transaction lock:
        existing = the record carrying this txn_id (if any) -> (existing_receipt, False)
        else     -> append build(rows) once                   -> (receipt, True)
    `build(rows)` receives the committed rows and returns the record to
    append (it must include txn_id) or raises. Lost-ack reconciliation: a
    caller that crashed after the append but before it stored the receipt
    calls again with the same txn_id and gets the receipt of the record
    already on disk, never a second record."""
    path = Path(path)
    if not isinstance(txn_id, str) or len(txn_id) < 8:
        raise LedgerRefused("TXN_ID_INVALID: %r" % (txn_id,))
    with transaction(path):
        rows = read_all(path)
        for i, r in enumerate(rows):
            if r.get("txn_id") == txn_id and (kind is None or r.get("kind") == kind):
                receipt = {"path": str(path), "seq": i + 1, "entry_hash": r.get("entry_hash"), "kind": r.get("kind"),
                           "receipt": "RECONCILED: record with this txn_id already on disk; no second append"}
                if recompute_entry_hash(r) != r.get("entry_hash"):
                    raise LedgerRefused("RECONCILE_ALTERED: txn %s record at seq %d does not verify" % (txn_id, i + 1))
                return receipt, False
        rec = build(rows)
        if rec.get("txn_id") != txn_id:
            raise LedgerRefused("TXN_ID_NOT_STAMPED: build() must stamp txn_id")
        return append_with_receipt(path, rec), True
