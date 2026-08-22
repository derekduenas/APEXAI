"""BIRTH / PROSPECTIVE LAW -- what counted as known, and when.

Anything the Observatory computed BEFORE its birth timestamp is
HISTORICAL_CONTEXT. Anything after may be PROSPECTIVE_OBSERVATION. There
is no third category and no backfill: a record reconstructed later can
never become prospective, however faithful the reconstruction.

This is the same law that made SessionAnchorEvidence trustworthy on
2026-08-19 while the rolling bar buffer erased the morning underneath it.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.pattern_observatory import OBSERVATORY_POWER, WRITE_ROOT

BIRTH_PATH = Path(WRITE_ROOT) / "birth.json"

HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"
PROSPECTIVE_OBSERVATION = "PROSPECTIVE_OBSERVATION"
BACKFILLED_NEVER_PROSPECTIVE = "BACKFILLED_NEVER_PROSPECTIVE"


class BirthError(RuntimeError):
    pass


def mint(*, now, code_lineage: str, families: int,
         path: Path | None = None) -> dict:
    """Mint once. A second mint is refused -- moving the birth forward
    would retroactively convert historical records into prospective ones,
    which is the single most valuable thing this file prevents."""
    p = path or BIRTH_PATH
    if p.exists():
        raise BirthError(
            f"birth already minted at {p}; re-minting would relabel "
            "historical observations as prospective")
    rec = {"kind": "pattern_observatory_birth",
           "birth_timestamp": str(now), "code_lineage": code_lineage,
           "families_registered": families,
           "law": "records before birth_timestamp are HISTORICAL_CONTEXT and "
                  "can never be counted as prospective evidence",
           "decision_power": OBSERVATORY_POWER}
    rec["birth_hash"] = hashlib.sha256(
        json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, indent=2))
    return rec


def load(path: Path | None = None) -> dict | None:
    p = path or BIRTH_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def classify(event_time, *, birth: dict | None = None,
             reconstructed: bool = False, path: Path | None = None) -> str:
    """The only function that may decide whether an observation counts."""
    if reconstructed:
        return BACKFILLED_NEVER_PROSPECTIVE
    b = birth if birth is not None else load(path)
    if b is None:
        return HISTORICAL_CONTEXT
    import pandas as pd
    return (PROSPECTIVE_OBSERVATION
            if pd.Timestamp(event_time) >= pd.Timestamp(b["birth_timestamp"])
            else HISTORICAL_CONTEXT)
