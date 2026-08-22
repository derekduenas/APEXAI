"""Hunter/Frontier-2 cohort classification — F O19. Four cohorts
describe whether Hunter and Frontier-2 currently carry state on a
subject; HUNTER_REFUSED_INSUFFICIENT_STATE is its OWN class, checked
first, and must never be collapsed into NO_MATCH/cohort D -- "Hunter
looked and its own state was insufficient" is a materially different
fact from "Hunter never looked."
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

HUNTER_REFUSED_INSUFFICIENT_STATE = "HUNTER_REFUSED_INSUFFICIENT_STATE"

COHORTS = (
    "COHORT_A_HUNTER_ACTIVE_FRONTIER_CONFIRMING",
    "COHORT_B_HUNTER_ACTIVE_FRONTIER_SILENT",
    "COHORT_C_HUNTER_SILENT_FRONTIER_ACTIVE",
    "COHORT_D_HUNTER_SILENT_FRONTIER_SILENT",
    HUNTER_REFUSED_INSUFFICIENT_STATE,
)


class CohortError(RuntimeError):
    pass


@dataclass(frozen=True)
class CohortVerdict:
    cohort: str
    subject: str
    hunter_present: bool
    hunter_state_sufficient: bool | None
    frontier_present: bool
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.cohort not in COHORTS:
            raise CohortError(f"unknown cohort {self.cohort!r}")

    def as_record(self) -> dict:
        return {"kind": "option_cohort_verdict", **asdict(self)}


def classify_cohort(*, subject: str, hunter_present: bool,
                    frontier_present: bool, known_from,
                    hunter_state_sufficient: bool | None = None) -> CohortVerdict:
    """`hunter_state_sufficient` is None when Hunter is not present at
    all (the question does not apply); it is a real bool only when
    hunter_present is True."""
    import pandas as pd
    if hunter_present and hunter_state_sufficient is False:
        cohort = HUNTER_REFUSED_INSUFFICIENT_STATE
    elif hunter_present and frontier_present:
        cohort = "COHORT_A_HUNTER_ACTIVE_FRONTIER_CONFIRMING"
    elif hunter_present and not frontier_present:
        cohort = "COHORT_B_HUNTER_ACTIVE_FRONTIER_SILENT"
    elif (not hunter_present) and frontier_present:
        cohort = "COHORT_C_HUNTER_SILENT_FRONTIER_ACTIVE"
    else:
        cohort = "COHORT_D_HUNTER_SILENT_FRONTIER_SILENT"
    return CohortVerdict(
        cohort=cohort, subject=subject, hunter_present=hunter_present,
        hunter_state_sufficient=hunter_state_sufficient,
        frontier_present=frontier_present, known_from=str(pd.Timestamp(known_from)))
