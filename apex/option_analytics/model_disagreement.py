"""Model disagreement — Greeks are model sensitivities, not physical
constants. Two defensible models (BSM vs American binomial) can and do
give different Greeks because of early exercise, numerical treatment,
or volatility assumptions. This module persists that disagreement as a
first-class, classified fact -- delta=0.61 alone is never reported when
BSM says 0.604 and American says 0.617; both are kept, with a
disagreement classification, rather than silently picking whichever
number "looks nicer."
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER

DISAGREEMENT_LEVELS = ("LOW", "MODERATE", "HIGH", "UNKNOWN")
QUALITY_LEVELS = ("HIGH", "MODERATE", "LOW", "UNKNOWN")

# named thresholds -- a fraction of the larger of the two model values,
# with a small absolute floor so tiny Greeks (e.g. gamma ~1e-4) don't
# manufacture spurious HIGH disagreement from noise alone.
MODERATE_REL_THRESHOLD = 0.10
HIGH_REL_THRESHOLD = 0.30
ABS_FLOOR = 1e-6


class ModelDisagreementError(RuntimeError):
    pass


@dataclass(frozen=True)
class GreekModelRange:
    greek_name: str
    bsm_value: float | None
    american_value: float | None
    disagreement_level: str
    quality: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.disagreement_level not in DISAGREEMENT_LEVELS:
            raise ModelDisagreementError(f"unknown disagreement_level {self.disagreement_level!r}")
        if self.quality not in QUALITY_LEVELS:
            raise ModelDisagreementError(f"unknown quality {self.quality!r}")

    def as_record(self) -> dict:
        return asdict(self)

    def canonical_value(self) -> float | None:
        """The reported single value when a caller needs one -- the
        AVERAGE of both models, never a hidden pick-one. Callers that
        need the full picture should read bsm_value/american_value
        directly, never this alone."""
        if self.bsm_value is None or self.american_value is None:
            return self.bsm_value if self.american_value is None else self.american_value
        return (self.bsm_value + self.american_value) / 2.0


def classify_disagreement(bsm_value: float | None, american_value: float | None) -> str:
    if bsm_value is None or american_value is None:
        return "UNKNOWN"
    denom = max(abs(bsm_value), abs(american_value), ABS_FLOOR)
    rel = abs(bsm_value - american_value) / denom
    if rel <= MODERATE_REL_THRESHOLD:
        return "LOW"
    if rel <= HIGH_REL_THRESHOLD:
        return "MODERATE"
    return "HIGH"


def build_range(greek_name: str, *, bsm_value: float | None,
                american_value: float | None) -> GreekModelRange:
    level = classify_disagreement(bsm_value, american_value)
    quality = ("UNKNOWN" if level == "UNKNOWN" else
              "HIGH" if level == "LOW" else
              "MODERATE" if level == "MODERATE" else "LOW")
    return GreekModelRange(greek_name=greek_name, bsm_value=bsm_value,
                           american_value=american_value,
                           disagreement_level=level, quality=quality)
