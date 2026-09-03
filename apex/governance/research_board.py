"""RESEARCH_BOARD_V2 -- the single authoritative research board.

WHY THIS EXISTS
---------------
On 2026-09-03 two research boards were found on this host, each a valid
hash chain from its OWN genesis, with zero overlapping record ids:

    /apex-data/core/edgeforge/research_board.jsonl      56 records
    /opt/apex-repo/results/edgeforge/research_board.jsonl  129 records

Nothing detected it for four days. The cause was not a race: it was a
RELATIVE PATH. chain_append() was called with
`results/edgeforge/research_board.jsonl`, resolved against the process
working directory --

    cwd=/apex-data/runtime  (services)  results/ -> /apex-data/core
    cwd=/opt/apex-repo      (sessions)  results/ is a real directory
                                        on the root disk

-- so the same call, with the same string, wrote to two filesystems.

WHAT THIS MODULE DOES ABOUT IT
------------------------------
1. The canonical board is an ABSOLUTE path. It is a module constant,
   never derived from cwd, and board_append() refuses a relative path.
2. Both legacy boards are frozen READ-ONLY and preserved byte-for-byte.
   They are never merged, renumbered or rewritten: they are two real
   histories and pretending otherwise would be a forgery.
3. V2 opens with RESEARCH_BOARD_RECONCILIATION_V1, whose HASHED BODY
   commits to both legacy boards via a domain-separated Merkle root.
   Altering either legacy file after the fact breaks that commitment.

WHAT THE RECONCILIATION RECORD MEANS
------------------------------------
    "Both legacy histories existed and are preserved exactly. From this
     point forward this V2 chain is the sole authoritative research
     board continuation."

It does NOT mean the two legacy chains were ever one linear history,
and this module deliberately manufactures no ordering between records
across them -- there is no trustworthy chronology to do it with. The
volume board carries ZERO explicit write timestamps in any of its 56
records.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.pulse.packet_root import leaf_digest, merkle_root

BOARD_VERSION = "RESEARCH_BOARD_V2"
RECONCILIATION_RECORD_ID = "RESEARCH_BOARD_RECONCILIATION_V1"

# ABSOLUTE, by construction. This is the whole point: a board location
# that cannot change because of where a process happened to be started.
CANONICAL_BOARD_DIR = Path("/apex-data/core/edgeforge")
CANONICAL_BOARD = CANONICAL_BOARD_DIR / "research_board_v2.jsonl"

LEGACY_BOARDS = {
    "LEGACY_RESEARCH_BOARD_VOLUME_V0":
        Path("/apex-data/core/edgeforge/research_board.jsonl"),
    "LEGACY_RESEARCH_BOARD_REPOLOCAL_V0":
        Path("/opt/apex-repo/results/edgeforge/research_board.jsonl"),
}

# Only fields that are an explicit statement of WHEN THE RECORD WAS
# WRITTEN. Dates quoted inside a record's prose describe the subject,
# not the write, and using them would fabricate a chronology.
WRITE_STAMP_FIELDS = ("recorded_utc", "utc", "recorded_at", "created_utc",
                      "observed_utc")


class ResearchBoardViolation(Exception):
    """An authoritative board write was attempted somewhere it may not
    happen -- a relative path, or a frozen legacy board."""


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def verify_chain(path: Path) -> dict:
    """Verify one board end-to-end without loading it as authority."""
    lines = [ln for ln in path.read_text().split("\n") if ln.strip()]
    prev = "GENESIS"
    for i, ln in enumerate(lines):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            return {"intact": False, "records": len(lines),
                    "broken_at": i + 1, "reason": "unparseable record"}
        body = dict(r)
        h = body.pop("entry_hash", None)
        if hashlib.sha256(json.dumps(body, sort_keys=True).encode()
                          ).hexdigest() != h:
            return {"intact": False, "records": len(lines),
                    "broken_at": i + 1, "reason": "entry_hash mismatch"}
        if r.get("prev_hash") != prev:
            return {"intact": False, "records": len(lines),
                    "broken_at": i + 1, "reason": "prev_hash break"}
        prev = h
    return {"intact": True, "records": len(lines), "broken_at": None,
            "head": prev}


def legacy_manifest(identity: str, path: Path) -> dict:
    """An immutable commitment to one legacy board, as it stands now."""
    raw = path.read_bytes()
    lines = [ln for ln in raw.decode().split("\n") if ln.strip()]
    recs = [json.loads(ln) for ln in lines]
    st = path.stat()
    stamps = []
    for r in recs:
        for k in WRITE_STAMP_FIELDS:
            v = r.get(k)
            if isinstance(v, str) and v[:2] == "20":
                stamps.append(v[:19])
                break
    ver = verify_chain(path)
    return {
        "identity": identity,
        "original_path": str(path),
        "record_count": len(recs),
        "file_bytes": len(raw),
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "first_record_id": recs[0].get("id") if recs else None,
        "first_record_hash": recs[0].get("entry_hash") if recs else None,
        "final_record_id": recs[-1].get("id") if recs else None,
        "final_head_hash": recs[-1].get("entry_hash") if recs else None,
        "chain_verification": ("INTACT_FROM_GENESIS" if ver["intact"]
                               else "BROKEN_AT_%s" % ver["broken_at"]),
        # honest about how much chronology actually exists
        "records_with_explicit_write_stamp": len(stamps),
        "trustworthy_write_time_range": (
            {"earliest": min(stamps), "latest": max(stamps)}
            if stamps else None),
        "write_time_note": (
            "no record carries an explicit write timestamp; the only "
            "temporal evidence is the filesystem mtime below"
            if not stamps else
            "derived ONLY from explicit write-stamp fields, never from "
            "dates quoted inside record prose"),
        "filesystem": {"st_dev": st.st_dev, "st_ino": st.st_ino,
                       "mtime_utc": __import__("datetime").datetime
                       .fromtimestamp(st.st_mtime,
                                      __import__("datetime").timezone.utc)
                       .isoformat()},
        "authority": "FROZEN_READ_ONLY_NO_NEW_AUTHORITY",
    }


def legacy_commitment(manifest: dict) -> str:
    """The hash this board is committed by. Covers identity, exact file
    content and chain head together, so neither swapping files nor
    editing one in place can go unnoticed."""
    return hashlib.sha256(_canonical({
        "identity": manifest["identity"],
        "file_sha256": manifest["file_sha256"],
        "final_head_hash": manifest["final_head_hash"],
        "record_count": manifest["record_count"],
        "file_bytes": manifest["file_bytes"],
    })).hexdigest()


def legacy_reconciliation_root(manifests: list) -> str:
    """Deterministic Merkle root over the legacy commitments.

    Ordered by identity so the root does not depend on the order the
    boards were discovered in, and domain-separated per the house
    convention (leaf_digest binds identity to content, so swapping two
    boards' contents while keeping both hashes present still changes
    the root)."""
    leaves = [leaf_digest(m["identity"], legacy_commitment(m))
              for m in sorted(manifests, key=lambda m: m["identity"])]
    return merkle_root(leaves)


def board_append(entry: dict, *, board: Path | None = None) -> dict:
    """THE authoritative research-board write.

    Refuses a relative path outright: that is the exact defect this
    module exists to close, and accepting one 'just this once' is how
    it would come back."""
    b = Path(board) if board is not None else CANONICAL_BOARD
    if not b.is_absolute():
        raise ResearchBoardViolation(
            "authoritative board writes must use an ABSOLUTE path; got "
            "%r. A relative path resolves against the working directory, "
            "which is what split the board on 2026-08-31." % str(b))
    for ident, legacy in LEGACY_BOARDS.items():
        try:
            same = b.exists() and legacy.exists() and b.samefile(legacy)
        except OSError:
            same = False
        if same or b == legacy:
            raise ResearchBoardViolation(
                "%s is FROZEN read-only; V2 is the sole future "
                "authority. Legacy boards are preserved for audit and "
                "never appended to." % ident)
    return chain_append(b, entry)
