"""PATTERN ASSASSIN -- attacks the PATTERN, not a trade.

DELIBERATELY NOT Assassin2. On 2026-08-19 the production Assassin fired
PREDICTION_RESIDUAL_BREAK on 1,986 of 1,989 reviews (99.8%), with a
median absolute curvature of 1,061 against an absolute threshold of 5.0
and not a single observation below it. Raw price-scale curvature versus a
constant cannot discriminate between a $30 stock and a $770 index, so it
emitted a constant. That wound is NOT reused here, and a test enforces
its absence.

Every wound below is SCALE-FREE or STRUCTURAL by construction: it either
normalises by the quantity it measures, or it asks a question about the
evidence rather than about the price.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

SURVIVED = "SURVIVED"
SURVIVED_WOUNDED = "SURVIVED_WOUNDED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
INVALIDATED = "INVALIDATED"
VERDICTS = (SURVIVED, SURVIVED_WOUNDED, INSUFFICIENT_EVIDENCE, INVALIDATED)

# Explicitly banned: the production wound that emitted a constant.
FORBIDDEN_WOUNDS = ("PREDICTION_RESIDUAL_BREAK",)

WOUNDS = (
    "SINGLE_MECHANISM_RESTATED",      # five views of price
    "INPUT_QUALITY_INSUFFICIENT",     # built on damaged sensors
    "POSITIONING_STALE",              # weekly data, intraday claim
    "SOURCE_LAG_EXCEEDS_HORIZON",     # the input is older than the move
    "FLOW_COULD_BE_HEDGING",          # directional read of a hedge
    "OPTIONS_ACTIVITY_COULD_BE_SPREAD",
    "OUT_OF_DISTRIBUTION",
    "SAMPLE_SUPPORT_TRIVIAL",
    "SINGLE_REGIME_ONLY",
    "MOVE_ALREADY_OCCURRED",
    "SEQUENCE_ORDER_COINCIDENTAL",
    "CLOCK_INTEGRITY_VIOLATION",
)

# LETHAL wounds invalidate outright: they mean the observation cannot be
# evidence at all, as distinct from being weak evidence.
LETHAL = ("INPUT_QUALITY_INSUFFICIENT", "CLOCK_INTEGRITY_VIOLATION",
          "SINGLE_MECHANISM_RESTATED")

STALE_POSITIONING_DAYS = 5.0
TRIVIAL_SUPPORT_N = 10
COINCIDENCE_MIN_STEPS = 3


@dataclass(frozen=True)
class PatternAssassinReview:
    pattern_id: str
    family_id: str
    subject: str
    as_of: str
    known_from: str
    wounds_attempted: tuple
    wounds_landed: tuple
    wounds_unreachable: tuple
    verdict: str
    lethal: bool
    reasoning: tuple

    def as_dict(self) -> dict:
        return {"kind": "pattern_assassin_review", **self.__dict__,
                "wounds_attempted": list(self.wounds_attempted),
                "wounds_landed": [w.__dict__ if hasattr(w, "__dict__") else w
                                  for w in self.wounds_landed],
                "wounds_unreachable": list(self.wounds_unreachable),
                "reasoning": list(self.reasoning),
                "reuses_production_curvature_wound": False,
                "decision_power": OBSERVATORY_POWER}


def review(state, *, positioning_freshness_days: float | None = None,
           clock_violation: bool = False,
           move_already_occurred: bool | None = None,
           sequence_state=None, as_of=None, known_from=None
           ) -> PatternAssassinReview:
    landed, unreachable, reasoning = [], [], []

    def wound(name, detail):
        landed.append({"wound": name, "detail": detail,
                       "lethal": name in LETHAL})

    ind = state.independence or {}
    n_ind = ind.get("independent_mechanism_count", 0)
    if n_ind <= 1:
        wound("SINGLE_MECHANISM_RESTATED",
              f"all {ind.get('n_components')} components derive from "
              f"{list(ind.get('groups', {}))} -- one witness, restated")
    elif ind.get("inflation_ratio", 1) >= 2.0:
        reasoning.append(f"evidence inflated {ind['inflation_ratio']}x by "
                         f"duplicated mechanisms")

    q = state.input_quality or {}
    if not q.get("estimable", False):
        wound("INPUT_QUALITY_INSUFFICIENT",
              f"blocking features {q.get('blocking_features')}")
    elif q.get("combined_quality") in ("DEGRADED",):
        reasoning.append("inputs are DEGRADED but the pattern is estimable")

    if clock_violation:
        wound("CLOCK_INTEGRITY_VIOLATION",
              "an input carried a timestamp ahead of the clock")

    if positioning_freshness_days is None:
        unreachable.append("POSITIONING_STALE")
        unreachable.append("FLOW_COULD_BE_HEDGING")
    elif positioning_freshness_days > STALE_POSITIONING_DAYS:
        wound("POSITIONING_STALE",
              f"positioning is {positioning_freshness_days:.1f} days old and "
              f"is being used for an intraday claim")

    n = state.prospective_n
    if n <= TRIVIAL_SUPPORT_N:
        wound("SAMPLE_SUPPORT_TRIVIAL",
              f"prospective_n={n} -- below the threshold at which any "
              f"forward claim is meaningful")
    if state.distinct_regimes <= 1:
        wound("SINGLE_REGIME_ONLY",
              f"observed in {state.distinct_regimes} regime(s)")

    if state.ood == "NOT_ESTIMABLE":
        unreachable.append("OUT_OF_DISTRIBUTION")
    elif state.ood == "OOD":
        wound("OUT_OF_DISTRIBUTION", "state lies outside observed history")

    if move_already_occurred is None:
        unreachable.append("MOVE_ALREADY_OCCURRED")
    elif move_already_occurred:
        wound("MOVE_ALREADY_OCCURRED",
              "the anticipated move is already in the price")

    if sequence_state is None:
        unreachable.append("SEQUENCE_ORDER_COINCIDENTAL")
    else:
        seen = len([s for s in sequence_state.steps if s.observed_at])
        if seen < COINCIDENCE_MIN_STEPS:
            wound("SEQUENCE_ORDER_COINCIDENTAL",
                  f"only {seen} ordered steps observed -- an order this "
                  f"short is not distinguishable from coincidence")

    unreachable.append("OPTIONS_ACTIVITY_COULD_BE_SPREAD")   # no OI/flow feed
    unreachable.append("SOURCE_LAG_EXCEEDS_HORIZON")         # no horizon yet

    lethal = any(w["lethal"] for w in landed)
    if lethal:
        verdict = INVALIDATED
    elif not landed:
        verdict = SURVIVED
    elif len(landed) >= 3:
        verdict = INSUFFICIENT_EVIDENCE
    else:
        verdict = SURVIVED_WOUNDED

    if verdict == SURVIVED:
        reasoning.append("no wound landed -- this is not evidence of edge, "
                         "only absence of a detected defect")

    return PatternAssassinReview(
        pattern_id=state.pattern_id, family_id=state.family_id,
        subject=state.subject, as_of=str(as_of or state.last_updated),
        known_from=str(known_from or state.known_from),
        wounds_attempted=WOUNDS, wounds_landed=tuple(landed),
        wounds_unreachable=tuple(sorted(set(unreachable))),
        verdict=verdict, lethal=lethal, reasoning=tuple(reasoning))
