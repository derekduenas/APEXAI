"""FRONTIER DISCOVERY REGISTRY — no survivor-only memory.

Every experiment is registered at birth, before its result exists:
question, features, interaction form, dataset boundary, search method,
and -- the field that keeps the whole enterprise honest --
multiple_testing_family. Failures are recorded. Null findings are
recorded. Abandoned candidates are recorded.

A research program that remembers only its winners is a lottery
recounting its jackpots: the 200 dead siblings of one surviving
discovery are exactly what its significance must be judged against, and
this ledger is where those siblings stay visible.

The registry also enforces the source law: dataset boundaries must name
governed sources, and a boundary naming a superseded lineage is refused
at registration -- an experiment born on corrupted labels is dead on
arrival whatever its p-value says.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

NOT_ESTIMABLE = "NOT_ESTIMABLE"

DISCOVERY_STATUSES = ("REGISTERED", "RUNNING", "NULL_RESULT",
                      "CANDIDATE_EDGE", "CONTRADICTED", "ABANDONED")

FORBIDDEN_BOUNDARIES = ("SUPERSEDED", "DEFECTIVE", "MISLABELLED",
                        "V1_NO_FRICTION", "PRELAW")


class RegistryViolation(RuntimeError):
    pass


def register_discovery(ledger: Path, *, discovery_id: str,
                       research_question: str, feature_set: list,
                       interaction_form: str, dataset_boundary: str,
                       search_method: str,
                       multiple_testing_family: str) -> dict:
    """Birth record. Written BEFORE any result exists."""
    if not multiple_testing_family:
        raise RegistryViolation(
            "an experiment outside a multiple-testing family is a "
            "p-hacking machine with the label torn off")
    up = dataset_boundary.upper()
    if any(b in up for b in FORBIDDEN_BOUNDARIES):
        raise RegistryViolation(
            f"dataset boundary {dataset_boundary!r} names a superseded "
            f"or defective lineage -- an experiment born on corrupted "
            f"labels is dead on arrival")
    rec = {"kind": "discovery_registration",
           "discovery_id": discovery_id,
           "birth_timestamp": datetime.now(timezone.utc).isoformat(),
           "research_question": research_question,
           "feature_set": sorted(feature_set),
           "interaction_form": interaction_form,
           "dataset_boundary": dataset_boundary,
           "search_method": search_method,
           "multiple_testing_family": multiple_testing_family,
           "status": "REGISTERED",
           "decision_power": "NONE_RESEARCH"}
    chain_append(ledger, rec)
    return rec


def record_result(ledger: Path, *, discovery_id: str, status: str,
                  result: dict, why: str) -> dict:
    """Results append; they never edit the registration. NULL_RESULT
    and ABANDONED are first-class outcomes, not embarrassments."""
    if status not in DISCOVERY_STATUSES or status == "REGISTERED":
        raise RegistryViolation(f"invalid result status {status!r}")
    registered = False
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "discovery_registration" and \
                    r.get("discovery_id") == discovery_id:
                registered = True
    if not registered:
        raise RegistryViolation(
            f"{discovery_id} was never registered; a result without a "
            f"pre-registered question is a story told backwards")
    rec = {"kind": "discovery_result", "discovery_id": discovery_id,
           "status": status, "result": result, "why": why,
           "recorded_utc": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_RESEARCH"}
    chain_append(ledger, rec)
    return rec


def family_ledger(ledger: Path, family: str) -> dict:
    """Everything ever tried in one multiple-testing family -- the
    denominator a surviving discovery must be judged against."""
    regs, results = [], {}
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "discovery_registration" and \
                    r.get("multiple_testing_family") == family:
                regs.append(r["discovery_id"])
            if r.get("kind") == "discovery_result":
                results[r["discovery_id"]] = r["status"]
    statuses = {d: results.get(d, "REGISTERED") for d in regs}
    return {"kind": "family_ledger", "family": family,
            "n_experiments": len(regs), "statuses": statuses,
            "n_null_or_dead": sum(1 for s in statuses.values() if s in
                                  ("NULL_RESULT", "CONTRADICTED",
                                   "ABANDONED")),
            "law": "the dead siblings are the denominator"}
