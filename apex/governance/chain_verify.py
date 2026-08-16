"""SAC1-08 — one verifier for the chain format the evidence actually uses.

Two canonicalizations existed for one conceptual chain:

    _canon (apex/hunter/statemachine.py)
        json.dumps(sort_keys=True, separators=(",",":"), default=str)
    _chain_append (scripts/nightly_pull.py)
        json.dumps(sort_keys=True)

`TradeLifecycle.verify_ledger()` therefore reports EVERY record written by
`_chain_append` as tampered -- and `_chain_append` is what writes the
forward ledger, the crypto arena, the execution ledgers, and the birth
registry. The integrity tool did not apply to the evidence.

This module verifies the `_chain_append` format using `_chain_append`'s own
rule. It deliberately does NOT unify the two hashes: re-canonicalizing
would invalidate every hash already committed to disk, which is a far worse
cure than the disease. Instead each writer keeps its rule and each rule has
a verifier that declares which format it speaks.

Torn fragments are DAMAGE (recorded, stepped over). Hash mismatches are
TAMPERING (reported as such). The distinction is the whole point.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

FORMAT = "chain_append_v1"


def canonical_hash(body: dict) -> str:
    """Byte-for-byte the rule `_chain_append` uses to mint entry_hash."""
    return hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()


def verify(path: str | Path) -> dict:
    """Verify a `_chain_append` ledger.

    Returns a report; raises nothing. A verifier that crashes on the
    condition it exists to describe is not a verifier (SAC1-06).
    """
    p = Path(path)
    if not p.exists():
        return {"format": FORMAT, "path": str(p), "status": "ABSENT",
                "valid_records": 0, "damage": [], "tampering": []}

    rows, damage = [], []
    for i, line in enumerate(p.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            rows.append((i, json.loads(line)))
        except json.JSONDecodeError:
            damage.append({"line": i, "bytes": len(line),
                           "classification": "TORN_FRAGMENT"})

    tampering, prev = [], "GENESIS"
    for i, r in rows:
        body = {k: v for k, v in r.items() if k != "entry_hash"}
        if canonical_hash(body) != r.get("entry_hash"):
            tampering.append({"line": i, "classification": "BODY_HASH_MISMATCH"})
        elif r.get("prev_hash") != prev and not r.get("recovered_from_torn_tail"):
            # linking past a tear is recovery and says so on the record;
            # anything else is a broken chain.
            tampering.append({"line": i, "classification": "LINKAGE_BREAK"})
        prev = r.get("entry_hash", prev)

    status = ("INTEGRITY_FAILURE" if tampering
              else "VALID_WITH_DAMAGE" if damage else "VALID")
    return {"format": FORMAT, "path": str(p), "status": status,
            "valid_records": len(rows), "damage": damage,
            "tampering": tampering}


def verify_all(paths) -> dict:
    reports = {str(p): verify(p) for p in paths}
    worst = "VALID"
    for r in reports.values():
        if r["status"] == "INTEGRITY_FAILURE":
            worst = "INTEGRITY_FAILURE"
        elif r["status"] == "VALID_WITH_DAMAGE" and worst == "VALID":
            worst = "VALID_WITH_DAMAGE"
    return {"overall": worst, "ledgers": reports}
