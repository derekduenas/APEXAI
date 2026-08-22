"""ResearchMechanism — a claimed market mechanism, its evidence, and
its APEX testing status.

THE PROMOTION LAW: `apex_status` includes PROMOTED in its vocabulary
(a mechanism record must be able to REPRESENT that state once real
governance sets it), but `register_mechanism()` and
`update_mechanism_evidence()` -- the library's own mutation API --
mechanically REFUSE to ever write PROMOTED. Only a caller writing
directly to a Component/governance ledger outside this package could
ever produce that value; the library itself has no code path there.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.research_library import RESEARCH_LIBRARY_POWER

LEDGER = Path("results/research_library/mechanisms.jsonl")

EVIDENCE_STATUSES = ("UNASSESSED", "THEORETICAL", "EMPIRICALLY_SUPPORTED",
                     "MIXED", "WEAK", "CONTRADICTED")
APEX_STATUSES = ("UNTESTED", "OBSERVATIONAL", "DISCOVERY_TESTED",
                 "CONFIRMATORY_ELIGIBLE", "REJECTED", "PROMOTED")

# the one apex_status the library's own API is forbidden to write.
LIBRARY_FORBIDDEN_APEX_STATUS = "PROMOTED"


class MechanismError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchMechanism:
    mechanism_id: str
    name: str
    description: str
    market: str
    time_horizon: str
    claimed_mechanism: str
    why_it_might_exist: str
    supporting_documents: tuple
    contradicting_documents: tuple
    required_data: tuple
    observable_inputs: tuple
    expected_behavior: str
    falsification: str
    known_failure_modes: tuple
    evidence_status: str
    apex_status: str
    known_from: str
    as_of: str
    decision_power: str = RESEARCH_LIBRARY_POWER

    def __post_init__(self):
        if self.evidence_status not in EVIDENCE_STATUSES:
            raise MechanismError(f"unknown evidence_status {self.evidence_status!r}")
        if self.apex_status not in APEX_STATUSES:
            raise MechanismError(f"unknown apex_status {self.apex_status!r}")

    def as_record(self) -> dict:
        return asdict(self)


def _chain_write(rec: dict) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, rec)


def register_mechanism(*, mechanism_id: str, name: str, description: str,
                       market: str, time_horizon: str, claimed_mechanism: str,
                       why_it_might_exist: str, expected_behavior: str,
                       falsification: str, known_from, now,
                       supporting_documents: tuple = (),
                       contradicting_documents: tuple = (),
                       required_data: tuple = (), observable_inputs: tuple = (),
                       known_failure_modes: tuple = (),
                       evidence_status: str = "UNASSESSED",
                       apex_status: str = "UNTESTED") -> ResearchMechanism:
    if apex_status == LIBRARY_FORBIDDEN_APEX_STATUS:
        raise MechanismError(
            "the Research Library cannot promote a mechanism -- PROMOTED "
            "may only be set by existing APEX governance writing directly "
            "to its own ledger, never through this API")
    import pandas as pd
    now = pd.Timestamp(now)
    m = ResearchMechanism(
        mechanism_id=mechanism_id, name=name, description=description,
        market=market, time_horizon=time_horizon,
        claimed_mechanism=claimed_mechanism, why_it_might_exist=why_it_might_exist,
        supporting_documents=tuple(supporting_documents),
        contradicting_documents=tuple(contradicting_documents),
        required_data=tuple(required_data), observable_inputs=tuple(observable_inputs),
        expected_behavior=expected_behavior, falsification=falsification,
        known_failure_modes=tuple(known_failure_modes),
        evidence_status=evidence_status, apex_status=apex_status,
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))
    _chain_write(m.as_record())
    return m


def update_mechanism_evidence(prior: ResearchMechanism, *, now,
                              add_supporting: tuple = (),
                              add_contradicting: tuple = (),
                              evidence_status: str | None = None,
                              apex_status: str | None = None) -> ResearchMechanism:
    """Append-only: returns a NEW ResearchMechanism record (a new ledger
    row), the prior row is untouched. Same PROMOTED refusal as
    register_mechanism()."""
    new_apex_status = apex_status if apex_status is not None else prior.apex_status
    if new_apex_status == LIBRARY_FORBIDDEN_APEX_STATUS:
        raise MechanismError(
            "the Research Library cannot promote a mechanism -- PROMOTED "
            "may only be set by existing APEX governance")
    import pandas as pd
    now = pd.Timestamp(now)
    updated = ResearchMechanism(
        mechanism_id=prior.mechanism_id, name=prior.name, description=prior.description,
        market=prior.market, time_horizon=prior.time_horizon,
        claimed_mechanism=prior.claimed_mechanism,
        why_it_might_exist=prior.why_it_might_exist,
        supporting_documents=tuple(sorted(set(prior.supporting_documents) | set(add_supporting))),
        contradicting_documents=tuple(sorted(set(prior.contradicting_documents) | set(add_contradicting))),
        required_data=prior.required_data, observable_inputs=prior.observable_inputs,
        expected_behavior=prior.expected_behavior, falsification=prior.falsification,
        known_failure_modes=prior.known_failure_modes,
        evidence_status=(evidence_status or prior.evidence_status),
        apex_status=new_apex_status, known_from=prior.known_from, as_of=str(now))
    _chain_write(updated.as_record())
    return updated
