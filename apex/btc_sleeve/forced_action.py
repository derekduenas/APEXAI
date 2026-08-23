"""BTC-L3 — FORCED-ACTION THESIS.

Participant state says what positioning looks like. This asks the
question that actually pays: is there someone who MUST act, rather than
someone who merely wants to?

WHAT WE CANNOT SEE, AND WILL NOT PRETEND TO
Forced action is caused by margin calls, stop orders and mandate
limits. APEX observes none of these. We see price, open interest,
funding and the book. So a thesis of the form "longs will be
liquidated at X" is not available to us, and building one would be
fabrication dressed as insight.

WHAT WE CAN SEE
The CONSEQUENCES of forced action, while they happen: positions
destroyed rapidly, into a thinning book, against the side that was
paying to hold. That signature is observable, and distinguishing it
from ordinary two-way trade is a real skill.

WHERE THE EDGE PLAUSIBLY IS -- AND IT IS NOT PREDICTION
A small account cannot front-run a cascade; the giants own that
battlefield on latency. What a small account CAN do is be patient
liquidity when forced flow EXHAUSTS -- the moment supply that had to
sell has finished selling. That is a capacity-limited, low-footprint,
forced-participant edge, which is exactly the terrain the small-capital
doctrine points at.

So the states below are deliberately ordered around observation and
exhaustion, not prediction:

    SUSCEPTIBLE_NOT_TRIGGERED  conditions exist; nothing is happening
    DELEVERAGING_IN_PROGRESS   the signature is present NOW
    DELEVERAGING_EXHAUSTING    the flow is decaying
    NONE_OBSERVED              ordinary two-way trade
    NOT_ESTIMABLE              the inputs cannot carry the question

FALSIFIABILITY IS PART OF THE OUTPUT. Every thesis states what would
disprove it, before any outcome is known. A thesis that cannot be
wrong is not a thesis.

decision_power: NONE -- interpretation. Sizes nothing, authorizes
nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

FORCED_ACTION_STATES = (
    "NONE_OBSERVED",
    "SUSCEPTIBLE_NOT_TRIGGERED",
    "DELEVERAGING_IN_PROGRESS",
    "DELEVERAGING_EXHAUSTING",
    NOT_ESTIMABLE,
)

UNOBSERVABLE = (
    "margin balances", "liquidation prices", "stop-order placement",
    "mandate constraints", "participant identity",
)

# Pre-declared structural floors. Sign tests on what "rapid" means,
# not thresholds fitted to any outcome.
RAPID_OI_DESTRUCTION_PCT = -2.0
DECAYING_FRACTION = 0.5          # this window vs the previous one


@dataclass(frozen=True)
class ForcedActionThesis:
    symbol: str
    T: str
    state: str
    pressured_side: str = NOT_ESTIMABLE
    because: tuple = ()
    falsified_by: tuple = ()
    unobservable: tuple = UNOBSERVABLE
    competing_explanations: tuple = ()
    tradeable_moment: str = "NONE"
    limiting_factor: str | None = None
    calibration: str = "NONE_FITTED"
    evidence_class: str = "PROSPECTIVE_LIVE_CAPTURE"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "btc_forced_action_thesis", **asdict(self)}


def _support(ps, name: str) -> str:
    r = ps.by_name(name)
    return r.support if r else NOT_ESTIMABLE


def assess(*, participant_state, inputs,
           prior_oi_change_pct: float | None = None
           ) -> ForcedActionThesis:
    """Judge whether forced flow is visible, and if so whether it is
    decaying. `prior_oi_change_pct` is the previous window's change --
    exhaustion is a comparison, not a level."""
    ps, inp = participant_state, inputs
    sym, T = ps.symbol, ps.T

    crowd = _support(ps, "FUNDING_CROWDING")
    thin = _support(ps, "BOOK_WITHDRAWAL")
    lever_dn = _support(ps, "LEVERAGE_CONTRACTION")
    cascade = _support(ps, "CASCADE_SUSCEPTIBILITY")

    if lever_dn == NOT_ESTIMABLE and cascade == NOT_ESTIMABLE:
        return ForcedActionThesis(
            symbol=sym, T=T, state=NOT_ESTIMABLE,
            limiting_factor=("neither positioning change nor cascade "
                             "conditions are estimable from these "
                             "inputs"),
            because=("the question cannot be asked of this data, which "
                     "is different from answering 'no'",))

    oi = inp.oi_change_pct
    px = inp.price_change_pct
    f = inp.funding_rate_annualized

    rapid = oi is not None and oi <= RAPID_OI_DESTRUCTION_PCT
    # which side was paying to hold, and did price move against it?
    pressured, against = NOT_ESTIMABLE, False
    if f is not None and px is not None:
        if f > 0:
            pressured, against = "LONGS", px < 0
        elif f < 0:
            pressured, against = "SHORTS", px > 0

    common_alternatives = (
        "scheduled expiry and roll activity destroy open interest with "
        "nobody being forced",
        "a large discretionary participant reducing risk looks "
        "identical to a forced one from outside",
        "we cannot see margin or stops, so 'forced' is inferred from "
        "consequences and never observed directly")

    # ---- is the signature present NOW?
    if rapid and against and thin == "CONSISTENT":
        decaying = (prior_oi_change_pct is not None
                    and prior_oi_change_pct < 0
                    and abs(oi) < abs(prior_oi_change_pct)
                    * DECAYING_FRACTION)
        if decaying:
            return ForcedActionThesis(
                symbol=sym, T=T, state="DELEVERAGING_EXHAUSTING",
                pressured_side=pressured,
                because=(
                    f"{pressured} were paying funding ({f:+.2%}) and "
                    f"price moved against them ({px:+.2f}%)",
                    f"open interest fell {oi:+.2f}% after "
                    f"{prior_oi_change_pct:+.2f}% -- the destruction "
                    f"rate is decaying, which is what supply running "
                    f"out looks like"),
                falsified_by=(
                    "open-interest destruction re-accelerating in the "
                    "next window",
                    "price making a further extreme against the "
                    "pressured side",
                    "book depth continuing to fall rather than "
                    "rebuilding"),
                competing_explanations=common_alternatives + (
                    "a pause is indistinguishable from exhaustion until "
                    "afterwards",),
                tradeable_moment=(
                    "PATIENT_LIQUIDITY_INTO_EXHAUSTION -- the only "
                    "forced-participant edge a small account can hold, "
                    "because it needs no latency advantage and little "
                    "capacity. Still unproven; requires prospective "
                    "evidence before any authority above OBSERVE."))
        return ForcedActionThesis(
            symbol=sym, T=T, state="DELEVERAGING_IN_PROGRESS",
            pressured_side=pressured,
            because=(
                f"open interest fell {oi:+.2f}% (rapid)",
                f"{pressured} were paying funding ({f:+.2%}) and price "
                f"moved against them ({px:+.2f}%)",
                "resting depth withdrew at the same time"),
            falsified_by=(
                "open interest stabilising while price continues to "
                "fall -- that would be repositioning, not unwinding",
                "funding flipping sign, which would mean the pressured "
                "side is no longer the one paying"),
            competing_explanations=common_alternatives,
            tradeable_moment=(
                "NONE -- do not attack flow that is still arriving. The "
                "moment of interest is exhaustion, not the middle of a "
                "cascade, and front-running one is a latency battle "
                "against giants."))

    # ---- conditions without the event
    if cascade == "CONSISTENT" or (crowd in ("CONSISTENT",
                                             "WEAKLY_CONSISTENT")
                                   and thin == "CONSISTENT"):
        return ForcedActionThesis(
            symbol=sym, T=T, state="SUSCEPTIBLE_NOT_TRIGGERED",
            pressured_side=pressured,
            because=("crowded funding and a thinned book are both "
                     "present, but positions are not being destroyed",),
            falsified_by=("the book rebuilding",
                          "funding normalising toward zero"),
            competing_explanations=common_alternatives + (
                "most susceptible states never become cascades, so this "
                "is a description of fragility, not a forecast of "
                "breakage",),
            tradeable_moment=("NONE -- susceptibility is not an event "
                              "and must never be traded as one."))

    return ForcedActionThesis(
        symbol=sym, T=T, state="NONE_OBSERVED",
        pressured_side=pressured,
        because=("no forced-flow signature: positions are not being "
                 "rapidly destroyed against the paying side into a "
                 "thinning book",),
        falsified_by=("rapid open-interest destruction appearing "
                      "against the funding-paying side",),
        competing_explanations=(
            "absence of a visible signature is not proof that nobody is "
            "being forced -- a slow, well-managed unwind would not "
            "register here",),
        tradeable_moment="NONE")
