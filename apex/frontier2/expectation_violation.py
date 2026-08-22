"""ExpectationViolationState — F2: observed market reactions are
sometimes more informative than the stimulus itself.

THE HONESTY LAW THIS MODULE ENFORCES: an "expectation" is only ever a
named, PRE-REGISTERED, deterministic reference relationship -- never an
LLM-invented number, never a fitted model. `RELATIONSHIP_TYPES` is the
closed registry. Of the five relationship classes the operator named,
this build can HONESTLY evaluate two tonight with real canonical
inputs (index-vs-symbol excess return, and buy-pressure-vs-price-
response); the other three require inputs APEX does not have wired
yet (a sector constituent map, a peer-group definition, a timestamped
catalyst source) and are declared in the registry but always resolve
NO_EXPECTATION_MODEL until that input exists -- see
FRONTIER_NEXTGEN_BUILD_MAP.md's "what current data cannot support
honestly", which named this exact gap before any code was written.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/expectation_violation_ledger.jsonl")

STATES = ("NO_EXPECTATION_MODEL", "INSUFFICIENT_CONTEXT",
         "OBSERVABLE_VIOLATION", "NO_VIOLATION", "UNKNOWN")

DIRECTIONS = ("POSITIVE", "NEGATIVE", "NONE", "UNKNOWN")
STRENGTHS = ("WEAK", "MODERATE", "STRONG", "UNKNOWN")
PERSISTENCE = ("SINGLE_OBSERVATION", "TRANSIENT", "PERSISTENT", "UNKNOWN")

RELATIONSHIP_TYPES = (
    "SECTOR_MOVE_CONSTITUENT_REFUSAL", "INDEX_MOVE_HIGH_BETA_REFUSAL",
    "RS_GROUP_STRONG_SYMBOL_WEAK", "BUY_PRESSURE_DECLINING_PRICE_RESPONSE",
    "EVENT_STIMULUS_SURPRISE_RESPONSE")

# name -> reason it cannot be honestly evaluated tonight. Absent from
# this dict means the relationship IS implemented below.
UNSUPPORTED_RELATIONSHIPS = {
    "SECTOR_MOVE_CONSTITUENT_REFUSAL": "DORMANT_NO_CONSTITUENT_MAP",
    "RS_GROUP_STRONG_SYMBOL_WEAK": "NO_PEER_GROUP_DEFINITION",
    "EVENT_STIMULUS_SURPRISE_RESPONSE": "NO_TIMESTAMPED_CATALYST_SOURCE_WIRED",
}

# Named, documented, un-fitted thresholds (same style as curve.py's
# ELEVATED_CURVATURE).
RVOL_ELEVATED = 2.0                  # matches senses.py's own convention
MATERIAL_RESIDUAL_FRAC = 0.01        # 1% excess is "worth naming"


class ExpectationViolationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExpectationViolationState:
    subject: str
    stimulus_type: str
    stimulus: float | None
    expected_response: float | None
    observed_response: float | None
    residual: float | None
    residual_direction: str
    residual_strength: str
    persistence: str
    support: tuple
    contradictions: tuple
    context: dict
    quality: str
    coverage: str
    freshness_s: float | None
    event_time: str
    known_from: str
    as_of: str
    state: str = "UNKNOWN"
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.state not in STATES:
            raise ExpectationViolationError(f"unknown state {self.state!r}")
        if self.residual_direction not in DIRECTIONS:
            raise ExpectationViolationError("bad residual_direction")
        if self.residual_strength not in STRENGTHS:
            raise ExpectationViolationError("bad residual_strength")
        if self.persistence not in PERSISTENCE:
            raise ExpectationViolationError("bad persistence")

    def as_record(self) -> dict:
        return {"kind": "expectation_violation_state", **asdict(self)}


def _direction(residual: float | None) -> str:
    if residual is None:
        return "UNKNOWN"
    if abs(residual) < MATERIAL_RESIDUAL_FRAC / 5:
        return "NONE"
    return "POSITIVE" if residual > 0 else "NEGATIVE"


def _strength(residual: float | None) -> str:
    if residual is None:
        return "UNKNOWN"
    a = abs(residual)
    if a < MATERIAL_RESIDUAL_FRAC:
        return "WEAK"
    if a < MATERIAL_RESIDUAL_FRAC * 3:
        return "MODERATE"
    return "STRONG"


def _persistence(residual_direction: str, history: tuple) -> str:
    """`history`: prior residual_direction values, oldest first, for the
    SAME (subject, stimulus_type) pair. A single observation with no
    history is SINGLE_OBSERVATION -- never PERSISTENT on n=1."""
    if not history:
        return "SINGLE_OBSERVATION"
    if residual_direction in ("UNKNOWN",):
        return "UNKNOWN"
    recent = history[-2:]
    if all(h == residual_direction for h in recent) and residual_direction != "NONE":
        return "PERSISTENT"
    return "TRANSIENT"


def _base_state(*, relationship_supported: bool, unsupported_reason,
                context_ok: bool, residual, direction) -> str:
    if not relationship_supported:
        return "NO_EXPECTATION_MODEL"
    if not context_ok:
        return "INSUFFICIENT_CONTEXT"
    if residual is None or direction == "UNKNOWN":
        return "UNKNOWN"
    return "OBSERVABLE_VIOLATION" if direction != "NONE" else "NO_VIOLATION"


def evaluate(relationship_type: str, subject: str, *, event_time, known_from,
            now, stimulus: float | None = None,
            expected_response: float | None = None,
            observed_response: float | None = None,
            residual: float | None = None,
            residual_history: tuple = (), quality: str = "UNKNOWN",
            context: dict | None = None) -> ExpectationViolationState:
    """The one entry point. If `residual` is not supplied directly it is
    computed as observed - expected (deterministic subtraction -- never
    a fitted quantity). `residual_history`: tuple of prior
    residual_direction strings for this (subject, relationship_type),
    oldest first."""
    import pandas as pd
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ExpectationViolationError(
            f"unknown relationship type {relationship_type!r}")

    now = pd.Timestamp(now)
    context = context or {}
    unsupported_reason = UNSUPPORTED_RELATIONSHIPS.get(relationship_type)
    supported = unsupported_reason is None

    if residual is None and expected_response is not None and observed_response is not None:
        residual = observed_response - expected_response

    context_ok = supported and expected_response is not None and observed_response is not None
    direction = _direction(residual) if context_ok else "UNKNOWN"
    strength = _strength(residual) if context_ok else "UNKNOWN"
    persistence = _persistence(direction, residual_history) if context_ok else "UNKNOWN"
    state = _base_state(relationship_supported=supported,
                        unsupported_reason=unsupported_reason,
                        context_ok=context_ok, residual=residual,
                        direction=direction)

    coverage = (unsupported_reason if not supported else
               "context_present" if context_ok else "MISSING_EXPECTED_OR_OBSERVED")
    freshness = None
    et = pd.Timestamp(event_time)
    freshness = round((now - et).total_seconds(), 1)

    return ExpectationViolationState(
        subject=subject, stimulus_type=relationship_type, stimulus=stimulus,
        expected_response=expected_response, observed_response=observed_response,
        residual=residual, residual_direction=direction,
        residual_strength=strength, persistence=persistence,
        support=tuple(context.get("support", ())),
        contradictions=tuple(context.get("contradictions", ())),
        context=context, quality=quality, coverage=coverage,
        freshness_s=freshness, event_time=str(et),
        known_from=str(pd.Timestamp(known_from)), as_of=str(now), state=state)


def evaluate_index_move_high_beta_refusal(
        subject: str, *, market_day_return: float | None,
        symbol_day_return: float | None, excess_market_60m: float | None,
        event_time, known_from, now, quality: str = "UNKNOWN",
        residual_history: tuple = ()) -> ExpectationViolationState:
    """A concrete, real, tonight-supportable relationship: the market
    moved, does the symbol's excess (already computed by
    apex.hunter.relstrength, never refit here) show a refusal? The
    naive reference expectation is 'moves with the market' --
    expected_response = market_day_return, a declared reference, not a
    fitted beta."""
    if excess_market_60m is None:
        # the ONLY residual source for this relationship is the already
        # -computed excess measure; without it there is no honest
        # residual to derive, even though the raw returns exist.
        return evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", subject,
                        event_time=event_time, known_from=known_from, now=now,
                        stimulus=market_day_return, quality=quality)
    return evaluate(
        "INDEX_MOVE_HIGH_BETA_REFUSAL", subject, event_time=event_time,
        known_from=known_from, now=now, stimulus=market_day_return,
        expected_response=market_day_return, observed_response=symbol_day_return,
        residual=excess_market_60m, residual_history=residual_history,
        quality=quality, context={"support": ("excess_market_60m",)})


def evaluate_buy_pressure_declining_response(
        subject: str, *, rvol_tod: float | None, trend_slope: float | None,
        event_time, known_from, now, quality: str = "UNKNOWN",
        residual_history: tuple = ()) -> ExpectationViolationState:
    """Elevated participation (rvol) creates a declared reference
    expectation of a NON-NEGATIVE price velocity -- a rising or flat
    trend under buy pressure is CONFIRMATION, not a violation, so the
    residual is one-sided: min(trend_slope, 0). Only a genuine shortfall
    (negative trend_slope despite elevated rvol) registers; exceeding
    the qualitative "should not decline" bar earns no extra residual
    the way a symmetric subtraction against a 0.0 baseline would have
    wrongly implied."""
    import pandas as pd
    if rvol_tod is None or trend_slope is None:
        return evaluate("BUY_PRESSURE_DECLINING_PRICE_RESPONSE", subject,
                        event_time=event_time, known_from=known_from, now=now,
                        quality=quality)
    elevated = rvol_tod >= RVOL_ELEVATED
    if not elevated:
        # no elevated participation -> no expectation was ever created.
        return evaluate("BUY_PRESSURE_DECLINING_PRICE_RESPONSE", subject,
                        event_time=event_time, known_from=known_from, now=now,
                        stimulus=rvol_tod, quality=quality)
    deficit = min(trend_slope, 0.0)
    return evaluate(
        "BUY_PRESSURE_DECLINING_PRICE_RESPONSE", subject, event_time=event_time,
        known_from=known_from, now=now, stimulus=rvol_tod,
        expected_response=0.0, observed_response=trend_slope, residual=deficit,
        residual_history=residual_history, quality=quality,
        context={"support": ("rvol_tod", "trend_slope")})


def persist(state: ExpectationViolationState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
