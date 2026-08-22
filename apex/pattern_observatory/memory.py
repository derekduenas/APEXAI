"""PATTERN MEMORY -- append-only, hash-chained, provenance-complete.

Five ledgers, one law: every record carries event_time, known_from, the
birth classification, and its source provenance. A record that cannot say
when it was knowable is not evidence.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.pattern_observatory import OBSERVATORY_POWER, WRITE_ROOT

ROOT = Path(WRITE_ROOT)
PATTERN_LEDGER = ROOT / "pattern_ledger.jsonl"
SEQUENCE_LEDGER = ROOT / "pattern_sequence_ledger.jsonl"
OUTCOME_LEDGER = ROOT / "pattern_outcomes.jsonl"
FAMILY_REGISTRY = ROOT / "pattern_family_registry.jsonl"
ASSASSIN_LEDGER = ROOT / "pattern_assassin_ledger.jsonl"
WORLD_LEDGER = ROOT / "pattern_world_state.jsonl"

LEDGERS = (PATTERN_LEDGER, SEQUENCE_LEDGER, OUTCOME_LEDGER,
           FAMILY_REGISTRY, ASSASSIN_LEDGER, WORLD_LEDGER)

GENESIS = "GENESIS"


def _tail_hash(path: Path) -> str:
    """Last entry_hash without reading the whole file -- the O(1) tail
    read LAB-03 established after a quadratic chain append stalled a
    campaign."""
    if not path.exists() or path.stat().st_size == 0:
        return GENESIS
    with path.open("rb") as fh:
        size = path.stat().st_size
        fh.seek(max(0, size - 262_144))
        tail = fh.read().decode(errors="ignore")
    for line in reversed(tail.splitlines()):
        if not line.strip():
            continue
        try:
            return json.loads(line).get("entry_hash", GENESIS)
        except json.JSONDecodeError:
            continue
    return GENESIS


def append(path: Path, record: dict, *, chain: bool = True) -> dict:
    """Never raises on a write failure -- a failed observation write must
    not kill the observation loop -- but it is recorded durably."""
    rec = dict(record)
    rec.setdefault("decision_power", OBSERVATORY_POWER)
    try:
        if chain:
            rec["prev_hash"] = _tail_hash(path)
            rec["entry_hash"] = hashlib.sha256(
                json.dumps(rec, sort_keys=True, default=str).encode()
            ).hexdigest()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:                                  # noqa: BLE001
        try:
            from apex.governance.ledger_error import record as _lerr
            _lerr(service="pattern_observatory", operation="LEDGER_WRITE",
                  exc=e, ledger=str(path),
                  recovery_action="observation cycle continues")
        except Exception:                                   # noqa: BLE001
            pass
    return rec


def read(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def verify_chain(path: Path) -> dict:
    rows = read(path)
    prev, breaks = GENESIS, 0
    for r in rows:
        if r.get("prev_hash") != prev:
            breaks += 1
        prev = r.get("entry_hash", prev)
    return {"kind": "pattern_chain_verification", "path": str(path),
            "rows": len(rows), "chain_breaks": breaks,
            "valid": breaks == 0, "decision_power": OBSERVATORY_POWER}
