"""Dependency birth timestamps — forward-evidence eligibility as pure math.

The operator's rule, verbatim intent: Monday's market-state archive is clean
prospective DATA, but a playbook/model claims an observation as forward
EVIDENCE only if that specific playbook/model/version was frozen before the
prediction was made. Anything predating a dependency's birth may inform
engineering, never prospective evidence — retroactivity is refused by
construction, no human judgment involved.

Births are append-only: a dependency is born when its frozen artifact is
hashed and registered. Re-freezing a changed artifact is a NEW birth under a
new version name; the old birth is never edited. Conservative by design —
when a birth time is uncertain, later is safer (it disqualifies, never
qualifies).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REGISTRY = Path("results/hunter/birth_registry.jsonl")

# every forward DECISION must carry all four; absence is ineligibility
REQUIRED_DEPENDENCIES = ("protocol", "feature_schema", "playbook", "model")

FORWARD_ELIGIBLE = "FORWARD_ELIGIBLE"
NOT_FORWARD_ELIGIBLE = "NOT_FORWARD_ELIGIBLE"


def load_births(registry: Path = REGISTRY) -> dict:
    """name -> {birth_time_utc, artifact_hash, kind}. First birth wins for a
    name; a duplicate name is a registration error surfaced loudly."""
    births: dict = {}
    if not registry.exists():
        return births
    for line in registry.read_text().splitlines():
        if not line.strip():
            continue
        # chain entries are FLAT: {**record, prev_hash, entry_hash}
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                             # torn line: reader survives
        if r.get("kind") != "birth":
            continue
        if r["name"] in births:
            raise ValueError(
                f"duplicate birth for {r['name']!r}: a changed artifact is a "
                f"new version under a new name, never a re-birth")
        births[r["name"]] = {"birth_time_utc": r["birth_time_utc"],
                             "artifact_hash": r["artifact_hash"],
                             "dependency_kind": r["dependency_kind"]}
    return births


def forward_eligibility(decision_time_utc, dependency_births: dict) -> tuple:
    """(status, reasons). Eligible iff every required dependency kind is
    present AND every named birth strictly precedes the decision time.
    Missing is ineligible (fail closed), never assumed frozen."""
    reasons = []
    kinds = {v.get("dependency_kind") for v in dependency_births.values()}
    for k in REQUIRED_DEPENDENCIES:
        if k not in kinds:
            reasons.append(f"missing dependency birth: {k}")
    t = pd.Timestamp(decision_time_utc)
    if t.tzinfo is None:
        raise ValueError("decision_time_utc must be tz-aware")
    for name, b in sorted(dependency_births.items()):
        born = pd.Timestamp(b["birth_time_utc"])
        if born.tzinfo is None:
            raise ValueError(f"birth of {name!r} must be tz-aware")
        if born >= t:
            reasons.append(f"{name} born {b['birth_time_utc']} "
                           f">= decision {decision_time_utc}")
    return ((NOT_FORWARD_ELIGIBLE, tuple(reasons)) if reasons
            else (FORWARD_ELIGIBLE, ()))


def birth_stamp(dependency_births: dict) -> dict:
    """The four *_birth_time fields every decision record carries, so the
    ledger is auditable without the registry in hand."""
    by_kind: dict = {}
    for name, b in dependency_births.items():
        by_kind.setdefault(b["dependency_kind"], {})[name] = b["birth_time_utc"]
    return {f"{k}_birth_time": by_kind.get(k) for k in REQUIRED_DEPENDENCIES}
