"""event_bus2 — F14: typed STATE-CHANGE events for the Frontier-2 organs.

Deliberately a SIBLING of apex.frontier.senses.emit(), not a
replacement: senses.py's bus carries raw OBSERVATIONS (a trade printed,
a symbol went stale). This bus carries CHANGES IN A COMPUTED STATE
(Curve moved from NO_INFLECTION to EARLY_NEGATIVE_CURVATURE). Conflating
the two would make "how many events fired" ambiguous between "how much
data arrived" and "how much did our understanding change" -- two very
different, both useful, numbers.

Same laws as the original bus, restated here rather than imported,
because this package must not import apex.frontier:
  - known_from may never precede event_time.
  - transport must be named honestly.
  - every event is hash-chained, append-only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/event_bus2.jsonl")

EVENT_TYPES = (
    "CURVATURE_CHANGE", "EXPECTATION_VIOLATION", "PARTICIPANT_PRESSURE_CHANGE",
    "PROPAGATION_CHANGE", "LEADING_EDGE_CHANGE", "MODEL_CONFLICT",
    "OOD_STATE", "DATA_DISAGREEMENT", "SYSTEM_DEGRADATION",
    "WORLD_LAB_SCENARIO_CHANGE", "CAPTAIN_STATE_CHANGE",
    "OPPORTUNITY_RANK_CHANGE",
)

TRANSPORTS = ("INTERNAL_COMPUTE",)   # every source here is a Frontier-2
                                     # organ computing over ledgers it has
                                     # already read -- never a raw feed


class EventBus2Violation(RuntimeError):
    pass


@dataclass(frozen=True)
class TypedEvent:
    event_type: str
    subject: str                     # symbol, or "MARKET" for breadth-level
    event_time: str
    known_from: str
    source: str                      # the frontier2 module name
    prior_state: str | None
    new_state: str
    material_change: bool
    quality: str                     # from ObservationIntegrityState.quality
    lineage: tuple                   # entry_hash(es) this event derives from
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "frontier2_event", **asdict(self)}


def emit(event_type: str, subject: str, *, event_time, known_from,
        source: str, prior_state: str | None, new_state: str,
        quality: str, lineage: tuple = (),
        transport: str = "INTERNAL_COMPUTE") -> dict:
    import pandas as pd
    if event_type not in EVENT_TYPES:
        raise EventBus2Violation(f"unknown event type {event_type!r}")
    if transport not in TRANSPORTS:
        raise EventBus2Violation(f"transport {transport!r} not in {TRANSPORTS}")
    et, kf = pd.Timestamp(event_time), pd.Timestamp(known_from)
    if kf < et:
        raise EventBus2Violation(
            "known_from precedes event_time: a state change cannot be "
            "known before it happened")
    material = prior_state != new_state
    ev = TypedEvent(
        event_type=event_type, subject=subject, event_time=str(et),
        known_from=str(kf), source=source, prior_state=prior_state,
        new_state=new_state, material_change=material, quality=quality,
        lineage=tuple(lineage))
    rec = ev.as_record()
    rec["event_id"] = hashlib.sha256(
        f"{event_type}|{subject}|{et}|{kf}|{source}".encode()
    ).hexdigest()[:16]
    rec["payload_hash"] = hashlib.sha256(
        json.dumps(rec, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, rec)
    return rec


def read_all() -> list:
    """Consumer read: every event ever emitted, in ledger order.
    Absent ledger -> empty list, never a crash."""
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def latest_for(subject: str, event_type: str | None = None) -> dict | None:
    """Most recent event for a subject (optionally filtered by type),
    or None if it has never fired -- never a fabricated default."""
    matches = [e for e in read_all() if e.get("subject") == subject
              and (event_type is None or e.get("event_type") == event_type)]
    return matches[-1] if matches else None
