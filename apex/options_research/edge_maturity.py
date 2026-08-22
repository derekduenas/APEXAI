"""Evidence-earned aggression ladder — Doctrine section 6. Aggression
may only increase as evidence increases: UNPROVEN -> OBSERVATIONAL ->
PROSPECTIVE_EDGE -> STABLE_EDGE -> SCALABLE_EDGE. This module only
RESEARCHES/LABELS a mechanism's current rung from real counts (Discovery
observations, prospective resolved outcomes, positive-expectancy
streak length); it grants no sizing authority at any rung -- Capital
retains sovereignty, enforced by hardcoding sizing_authority="NONE" on
every verdict this module can produce.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER
from apex.options_research.asymmetric_growth_doctrine import (
    EVIDENCE_EARNED_AGGRESSION_LADDER)

# named, conservative thresholds -- a rung is earned by real counts,
# never granted from a narrative-strong thesis.
MIN_OBSERVATIONS_FOR_OBSERVATIONAL = 1
MIN_RESOLVED_FOR_PROSPECTIVE_EDGE = 10
MIN_RESOLVED_FOR_STABLE_EDGE = 30
MIN_RESOLVED_FOR_SCALABLE_EDGE = 100


class EdgeMaturityError(RuntimeError):
    pass


@dataclass(frozen=True)
class EdgeMaturityVerdict:
    mechanism_id: str
    rung: str
    resolved_outcome_count: int
    positive_expectancy_streak: int
    evidence_summary: str
    sizing_authority: str            # ALWAYS "NONE" -- Capital retains sovereignty
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.rung not in EVIDENCE_EARNED_AGGRESSION_LADDER:
            raise EdgeMaturityError(f"unknown rung {self.rung!r}")
        if self.sizing_authority != "NONE":
            raise EdgeMaturityError(
                "edge maturity verdicts may never carry sizing authority")

    def as_record(self) -> dict:
        return {"kind": "edge_maturity_verdict", **asdict(self)}


def classify_edge_maturity(*, resolved_outcome_count: int,
                           positive_expectancy_streak: int) -> str:
    """The ladder can only be climbed by real resolved-outcome counts
    -- a mechanism with zero prospective observations is UNPROVEN no
    matter how strong its underlying thesis narrative reads."""
    if resolved_outcome_count >= MIN_RESOLVED_FOR_SCALABLE_EDGE and positive_expectancy_streak > 0:
        return "SCALABLE_EDGE"
    if resolved_outcome_count >= MIN_RESOLVED_FOR_STABLE_EDGE and positive_expectancy_streak > 0:
        return "STABLE_EDGE"
    if resolved_outcome_count >= MIN_RESOLVED_FOR_PROSPECTIVE_EDGE and positive_expectancy_streak > 0:
        return "PROSPECTIVE_EDGE"
    if resolved_outcome_count >= MIN_OBSERVATIONS_FOR_OBSERVATIONAL:
        return "OBSERVATIONAL"
    return "UNPROVEN"


def build(*, mechanism_id: str, resolved_outcome_count: int,
         positive_expectancy_streak: int, known_from,
         evidence_summary: str | None = None) -> EdgeMaturityVerdict:
    import pandas as pd
    rung = classify_edge_maturity(resolved_outcome_count=resolved_outcome_count,
                                  positive_expectancy_streak=positive_expectancy_streak)
    return EdgeMaturityVerdict(
        mechanism_id=mechanism_id, rung=rung,
        resolved_outcome_count=resolved_outcome_count,
        positive_expectancy_streak=positive_expectancy_streak,
        evidence_summary=(evidence_summary or
                          f"{resolved_outcome_count} resolved outcomes, "
                          f"{positive_expectancy_streak} consecutive positive-expectancy"),
        sizing_authority="NONE", known_from=str(pd.Timestamp(known_from)))
