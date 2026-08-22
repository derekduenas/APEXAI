"""RARE_ASYMMETRIC_OPPORTUNITY — Doctrine section 11. A research-only
classification (no sizing authority) for the rare setup where strong
underlying intelligence, high transition quality, tight timing, a
surface advantage, clean execution, a defined loss, large payoff
asymmetry, and low model-break risk all coexist. Every one of the 8
criteria must be independently evidenced -- a strong thesis on 7 of 8
criteria is NOT_RARE, exactly the same "no narrative shortcuts" law
used throughout this package (refusal.py, scaling_potential.py).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

CRITERIA = (
    "STRONG_UNDERLYING_INTELLIGENCE",
    "HIGH_TRANSITION_QUALITY",
    "TIGHT_TIMING",
    "SURFACE_ADVANTAGE",
    "CLEAN_EXECUTION",
    "DEFINED_LOSS",
    "LARGE_PAYOFF_ASYMMETRY",
    "LOW_MODEL_BREAK_RISK",
)

VERDICTS = ("RARE_ASYMMETRIC_OPPORTUNITY", "NOT_RARE")

# named threshold for LARGE_PAYOFF_ASYMMETRY -- reuses the same bar as
# scaling_potential.py's HIGH tier, kept as its own constant here since
# the two concepts are allowed to diverge later.
LARGE_PAYOFF_ASYMMETRY_MIN_TAIL_MULTIPLE = 3.0


class RareOpportunityError(RuntimeError):
    pass


@dataclass(frozen=True)
class RareOpportunityVerdict:
    subject: str
    expression_type: str
    verdict: str
    criteria_met: tuple          # tuple of CRITERIA names that evaluated True
    criteria_failed: tuple       # tuple of CRITERIA names that evaluated False or unevidenced
    sizing_authority: str
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise RareOpportunityError(f"unknown verdict {self.verdict!r}")
        if self.sizing_authority != "NONE":
            raise RareOpportunityError(
                "a RareOpportunityVerdict may never carry sizing authority")
        if self.verdict == "RARE_ASYMMETRIC_OPPORTUNITY" and set(self.criteria_met) != set(CRITERIA):
            raise RareOpportunityError(
                "RARE_ASYMMETRIC_OPPORTUNITY requires ALL 8 criteria met -- "
                "no narrative shortcut on a partial match")

    def as_record(self) -> dict:
        return {"kind": "rare_opportunity_verdict", **asdict(self)}


def classify_rare_opportunity(*, subject: str, expression_type: str, known_from,
                              direction_quality: str | None,
                              transition_quality: str | None,
                              timing_tight: bool | None,
                              surface_advantage: bool | None,
                              clean_execution: bool | None,
                              loss_cap: float | None,
                              tail_payoff_multiple: float | None,
                              model_familiarity: str | None) -> RareOpportunityVerdict:
    """Every criterion input defaults to a value that FAILS the
    criterion when absent (None) -- missing evidence is never treated
    as passing evidence."""
    import pandas as pd
    checks = {
        "STRONG_UNDERLYING_INTELLIGENCE": direction_quality == "STRONG",
        "HIGH_TRANSITION_QUALITY": transition_quality in ("STRONG", "MODERATE") and transition_quality is not None,
        "TIGHT_TIMING": timing_tight is True,
        "SURFACE_ADVANTAGE": surface_advantage is True,
        "CLEAN_EXECUTION": clean_execution is True,
        "DEFINED_LOSS": loss_cap is not None,
        "LARGE_PAYOFF_ASYMMETRY": (tail_payoff_multiple is not None
                                   and tail_payoff_multiple >= LARGE_PAYOFF_ASYMMETRY_MIN_TAIL_MULTIPLE),
        "LOW_MODEL_BREAK_RISK": model_familiarity == "FAMILIAR",
    }
    met = tuple(c for c in CRITERIA if checks[c])
    failed = tuple(c for c in CRITERIA if not checks[c])
    verdict = "RARE_ASYMMETRIC_OPPORTUNITY" if not failed else "NOT_RARE"
    return RareOpportunityVerdict(
        subject=subject, expression_type=expression_type, verdict=verdict,
        criteria_met=met, criteria_failed=failed, sizing_authority="NONE",
        known_from=str(pd.Timestamp(known_from)))
