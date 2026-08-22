"""ResearchHypothesisCandidate — what research MAY generate. The
library's own `propose()` has no `status` parameter at all: every
candidate it can mint is PROPOSED_ONLY, mechanically, the same
discipline apex.frontier2.research_scientist uses for
RESEARCH_PROPOSAL_ONLY. APPROVED_FOR_DISCOVERY, APPROVED_FOR_CONFIRMATION
and REJECTED exist in the vocabulary for the EXISTING scientific
governance pipeline (apex.research / apex.governance) to write, never
for this library to write itself.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.research_library import RESEARCH_LIBRARY_POWER

LEDGER = Path("results/research_library/hypotheses.jsonl")

STATUSES = ("PROPOSED_ONLY", "APPROVED_FOR_DISCOVERY",
           "APPROVED_FOR_CONFIRMATION", "REJECTED")
LIBRARY_ONLY_STATUS = "PROPOSED_ONLY"


class HypothesisError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchHypothesisCandidate:
    hypothesis_id: str
    mechanism_id: str
    statement: str
    market: str
    primary_metric: str
    secondary_metrics: tuple
    required_data: tuple
    minimum_sample: str
    falsification: str
    regime_requirements: str
    cost_requirements: str
    prospective_test_design: str
    status: str
    known_from: str
    as_of: str
    decision_power: str = RESEARCH_LIBRARY_POWER

    def __post_init__(self):
        if self.status not in STATUSES:
            raise HypothesisError(f"unknown status {self.status!r}")

    def as_record(self) -> dict:
        return asdict(self)


def propose(*, hypothesis_id: str, mechanism_id: str, statement: str, market: str,
           primary_metric: str, minimum_sample: str, falsification: str,
           regime_requirements: str, cost_requirements: str,
           prospective_test_design: str, known_from, now,
           secondary_metrics: tuple = (), required_data: tuple = ()
           ) -> ResearchHypothesisCandidate:
    """No `status` parameter exists -- every candidate this function can
    ever produce is PROPOSED_ONLY. Approval/rejection is a governance
    act performed elsewhere, on this record's hypothesis_id, never by
    calling back into this library."""
    import pandas as pd
    now = pd.Timestamp(now)
    h = ResearchHypothesisCandidate(
        hypothesis_id=hypothesis_id, mechanism_id=mechanism_id, statement=statement,
        market=market, primary_metric=primary_metric,
        secondary_metrics=tuple(secondary_metrics), required_data=tuple(required_data),
        minimum_sample=minimum_sample, falsification=falsification,
        regime_requirements=regime_requirements, cost_requirements=cost_requirements,
        prospective_test_design=prospective_test_design, status=LIBRARY_ONLY_STATUS,
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, h.as_record())
    return h
