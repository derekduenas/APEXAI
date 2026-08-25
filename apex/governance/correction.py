"""CORRECTION RECORDS — append, never rewrite.

Immutability does not mean preserving a false interpretation as current
truth. It means the original stands untouched AND the corrected reading
is reachable, with lineage joining them.

Two truths are kept apart on purpose:

    HISTORICAL TRUTH   what APEX actually produced, at that commit,
                       from that data, including its errors.
    ANALYTICAL TRUTH   what those observations mean once a resolver
                       defect is understood.

Collapsing them either way is a failure. Editing the original hides
that the system erred. Refusing to correct forces every downstream
faculty to learn from labels we know are wrong -- and for a system
about to train an edge-discovery layer, that is the more expensive
mistake.

A corrected record therefore carries the original's hash. If the
original is ever altered, the lineage breaks loudly.

decision_power: NONE -- a governance primitive.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

CORRECTION_TYPES = ("RESOLUTION_DEFECT", "SEMANTIC_DEFECT",
                    "DATA_DEFECT", "CLASSIFICATION_DEFECT")

ORIGINAL_STATUS = "SUPERSEDED_BY_CORRECTION"


class CorrectionViolation(RuntimeError):
    pass


def record_hash(rec: dict) -> str:
    """Content hash of a record, excluding chain bookkeeping."""
    body = {k: v for k, v in rec.items()
            if k not in ("prev_hash", "entry_hash")}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def append_correction(ledger: Path, *, correction_type: str,
                      supersedes_record_id: str,
                      original_record: dict,
                      defect_ids: list,
                      corrected_resolver_version: str,
                      corrected_fields: dict,
                      unchanged_fields_verified: list,
                      why: str) -> dict:
    """Append a correction that supersedes an original's INTERPRETATION.

    The original is never touched. `unchanged_fields_verified` is not
    decoration: stating which numbers were audited and found unaffected
    is what stops a correction from quietly widening its own scope."""
    if correction_type not in CORRECTION_TYPES:
        raise CorrectionViolation(
            f"unknown correction_type {correction_type!r}")
    if not defect_ids:
        raise CorrectionViolation(
            "a correction must name the defect(s) that justify it")
    overlap = set(corrected_fields) & set(unchanged_fields_verified)
    if overlap:
        raise CorrectionViolation(
            f"fields {sorted(overlap)} are claimed both corrected and "
            f"unchanged -- a correction may not contradict itself")

    rec = {
        "kind": "record_correction",
        "correction_type": correction_type,
        "supersedes_record_id": supersedes_record_id,
        "original_record_hash": record_hash(original_record),
        "original_status": ORIGINAL_STATUS,
        "defect_ids": sorted(defect_ids),
        "corrected_resolver_version": corrected_resolver_version,
        "corrected_fields": corrected_fields,
        "unchanged_fields_verified": sorted(unchanged_fields_verified),
        "why": why,
        "correction_timestamp": datetime.now(timezone.utc).isoformat(),
        "law": "the original is preserved untouched; this record "
               "supersedes its INTERPRETATION only, and carries the "
               "original's hash so tampering breaks the lineage",
        "eligibility": "corrected records are the ONLY ones eligible "
                       "for V2 / EdgeForge training; superseded "
                       "originals are historical evidence, not labels",
        "decision_power": "NONE",
    }
    return chain_append(ledger, rec)


def verify_lineage(ledger: Path, originals: dict) -> dict:
    """Confirm every correction still matches its original's hash."""
    broken, ok = [], 0
    if not ledger.exists():
        return {"kind": "lineage_verification", "corrections": 0,
                "verdict": "NO_CORRECTIONS"}
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") != "record_correction":
            continue
        rid = r["supersedes_record_id"]
        orig = originals.get(rid)
        if orig is None:
            broken.append(f"{rid}: original not found")
        elif record_hash(orig) != r["original_record_hash"]:
            broken.append(f"{rid}: original has been ALTERED since "
                          f"correction")
        else:
            ok += 1
    return {"kind": "lineage_verification", "corrections": ok + len(broken),
            "intact": ok, "broken": broken,
            "verdict": "LINEAGE_INTACT" if not broken else "LINEAGE_BROKEN"}
