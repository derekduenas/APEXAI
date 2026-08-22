"""Horizon matching — F O9: DTE_REQUIRED > EXPECTED_REALIZATION_HORIZON
+ TIMING_UNCERTAINTY + EXECUTION_BUFFER. No favorite DTE. 0DTE is a
separate, NOT_ACTIVE_V1 research bucket -- never pooled with ordinary
expiries.
"""
from __future__ import annotations

from apex.options_research import OPTIONS_RESEARCH_POWER

DTE_BUCKETS = ("0DTE", "1_2_DTE", "3_7_DTE", "8_30_DTE", "OVER_30_DTE")
ZERO_DTE_STATUS = "SEPARATE_RESEARCH_BUCKET_NOT_ACTIVE_V1"

EXECUTION_BUFFER_MINUTES = 15.0    # named, documented, not a favorite DTE


class HorizonError(RuntimeError):
    pass


def dte_bucket(dte: int) -> str:
    if dte == 0:
        return "0DTE"
    if dte <= 2:
        return "1_2_DTE"
    if dte <= 7:
        return "3_7_DTE"
    if dte <= 30:
        return "8_30_DTE"
    return "OVER_30_DTE"


def required_dte_minutes(*, expected_realization_minutes: float | None,
                         timing_uncertainty_minutes: float | None) -> float | None:
    """Returns None (UNKNOWN, not a guess) when either input is
    unavailable -- the horizon law cannot be applied without both."""
    if expected_realization_minutes is None or timing_uncertainty_minutes is None:
        return None
    return (expected_realization_minutes + timing_uncertainty_minutes
           + EXECUTION_BUFFER_MINUTES)


def horizon_eligible(*, dte: int, expected_realization_minutes: float | None,
                     timing_uncertainty_minutes: float | None) -> dict:
    """The one law: candidate expiry's minutes-to-expiry must exceed
    the required minimum. 0DTE is refused structurally, regardless of
    the math, because it is a separate, not-yet-active bucket."""
    bucket = dte_bucket(dte)
    if bucket == "0DTE":
        return {"eligible": False, "bucket": bucket, "reason": ZERO_DTE_STATUS,
               "decision_power": OPTIONS_RESEARCH_POWER}

    required_minutes = required_dte_minutes(
        expected_realization_minutes=expected_realization_minutes,
        timing_uncertainty_minutes=timing_uncertainty_minutes)
    if required_minutes is None:
        return {"eligible": False, "bucket": bucket,
               "reason": "HORIZON_UNKNOWN_NO_REALIZATION_OR_TIMING_ESTIMATE",
               "decision_power": OPTIONS_RESEARCH_POWER}

    dte_minutes = dte * 24 * 60
    eligible = dte_minutes > required_minutes
    return {"eligible": eligible, "bucket": bucket, "required_minutes": required_minutes,
           "dte_minutes": dte_minutes,
           "reason": None if eligible else "REFUSE_HORIZON_MISMATCH",
           "decision_power": OPTIONS_RESEARCH_POWER}
