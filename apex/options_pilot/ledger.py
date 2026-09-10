"""Receipts, not hash-shaped strings.

`append_with_receipt` writes through the hash-chained ledger and then RE-READS
the file to prove the record landed: the receipt names the file, the sequence
number, and the entry hash actually on disk. `verify_receipt` re-reads again
and recomputes the entry hash from the record's own bytes, so an altered,
truncated, or foreign record is detected rather than trusted.

Event ORDER is proven by ledger sequence numbers assigned by the append, never
by caller-supplied timestamps."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.governance.chain_ledger import chain_append


class LedgerRefused(RuntimeError):
    """Persistence could not be proven. Nothing downstream may proceed."""


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


def append_with_receipt(path: Path, entry: dict) -> dict:
    """Append, then prove the append by re-reading the tail."""
    path = Path(path)
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
    return {"path": str(path), "seq": seq, "entry_hash": tail["entry_hash"], "kind": tail.get("kind"),
            "receipt": "RE-READ from disk after append; seq is the 1-indexed line number"}


def verify_receipt(path: Path, receipt: dict, *, expected_kind: str | None = None) -> dict:
    """Re-read the record a receipt points to and prove it is intact.

    Refuses: missing file, seq out of range, kind mismatch, entry_hash
    mismatch, or a record whose bytes no longer hash to its entry_hash."""
    if not isinstance(receipt, dict) or not {"path", "seq", "entry_hash"} <= set(receipt):
        raise LedgerRefused("RECEIPT_MALFORMED: %r" % (sorted(receipt) if isinstance(receipt, dict) else type(receipt).__name__))
    if str(receipt["path"]) != str(Path(path)):
        raise LedgerRefused("RECEIPT_FOREIGN_LEDGER: %r" % receipt["path"])
    rows = read_all(path)
    seq = receipt["seq"]
    if not isinstance(seq, int) or seq < 1 or seq > len(rows):
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
    return rec


def find(path: Path, *, kind: str, where) -> list:
    """Records of `kind` satisfying `where(rec)`, with their seq."""
    return [(i + 1, r) for i, r in enumerate(read_all(path)) if r.get("kind") == kind and where(r)]
