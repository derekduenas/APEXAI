"""Model/strategy lifecycle with MECHANICAL calibration gating.

Two DIFFERENT axes, deliberately not merged (gap analysis contradiction #1):
  * ModelState -- the LIFECYCLE of a model/playbook (this module);
  * distribution provenance -- apex.distribution.CalibrationStatus.

Gating is mechanical: eligibility is a pure function of state; there is no
API for overriding it, which is exactly how "an LLM cannot change
calibration status" is enforced -- structurally, not by prompt.

Promotion path:  IDEA -> RESEARCH -> BACKTEST -> PAPER_GRADE -> PAPER ->
CALIBRATED -> SHADOW -> LIVE_ELIGIBLE -> LIMITED_LIVE -> LIVE
Degradation:     any live-side state -> DEGRADED -> PAUSED -> RESEARCH_REVIEW
A DEGRADED model loses live eligibility in the same instant, structurally.
"""

from __future__ import annotations

from enum import Enum


class ModelState(Enum):
    IDEA = "IDEA"
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    PAPER_GRADE = "PAPER_GRADE"
    PAPER = "PAPER"
    CALIBRATED = "CALIBRATED"
    SHADOW = "SHADOW"
    LIVE_ELIGIBLE = "LIVE_ELIGIBLE"
    LIMITED_LIVE = "LIMITED_LIVE"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    RESEARCH_REVIEW = "RESEARCH_REVIEW"


_PROMOTION = {
    ModelState.IDEA: ModelState.RESEARCH,
    ModelState.RESEARCH: ModelState.BACKTEST,
    ModelState.BACKTEST: ModelState.PAPER_GRADE,
    ModelState.PAPER_GRADE: ModelState.PAPER,
    ModelState.PAPER: ModelState.CALIBRATED,
    ModelState.CALIBRATED: ModelState.SHADOW,
    ModelState.SHADOW: ModelState.LIVE_ELIGIBLE,
    ModelState.LIVE_ELIGIBLE: ModelState.LIMITED_LIVE,
    ModelState.LIMITED_LIVE: ModelState.LIVE,
}
_DEGRADATION = {
    ModelState.DEGRADED: ModelState.PAUSED,
    ModelState.PAUSED: ModelState.RESEARCH_REVIEW,
    ModelState.RESEARCH_REVIEW: ModelState.RESEARCH,
}
_LIVE_SIDE = {ModelState.SHADOW, ModelState.LIVE_ELIGIBLE,
              ModelState.LIMITED_LIVE, ModelState.LIVE}


class LifecycleError(ValueError):
    """An illegal lifecycle transition was attempted."""


def promote(state: ModelState, evidence: dict) -> ModelState:
    """One rung, mechanically. Promotion past PAPER requires the declared
    calibration evidence -- 'this looks really good, turn it on' is not an
    argument this function can parse."""
    if state not in _PROMOTION:
        raise LifecycleError(f"{state.value} has no promotion path")
    nxt = _PROMOTION[state]
    if nxt in (ModelState.CALIBRATED, *_LIVE_SIDE):
        n = int(evidence.get("n_effective_dates", 0))
        rel = evidence.get("reliability")
        if n < 20 or rel is None or rel > 0.01:
            raise LifecycleError(
                f"promotion to {nxt.value} requires >=20 effective dates and "
                f"reliability <=0.01; got n={n}, reliability={rel!r}. "
                f"Calibration is forward evidence and cannot be asserted.")
    return nxt


def degrade(state: ModelState) -> ModelState:
    """Degradation is always legal from any live-side or calibrated state,
    and only ever moves TOWARD review."""
    if state in _LIVE_SIDE or state is ModelState.CALIBRATED:
        return ModelState.DEGRADED
    if state in _DEGRADATION:
        return _DEGRADATION[state]
    raise LifecycleError(f"{state.value} cannot degrade further")


def live_eligible(state: ModelState) -> bool:
    """PURE function of state. There is no override parameter, no force
    flag, no context argument -- which is the entire point."""
    return state in (ModelState.LIVE_ELIGIBLE, ModelState.LIMITED_LIVE,
                     ModelState.LIVE)


def paper_eligible(state: ModelState) -> bool:
    return state in (ModelState.PAPER_GRADE, ModelState.PAPER,
                     ModelState.CALIBRATED, *_LIVE_SIDE)
