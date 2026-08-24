"""BTC-L3 — ATTACK GEOMETRY.

The question this answers, and nothing wider:

    When the participant / forced-action thesis is plausible, is there a
    PRICE LOCATION offering tight invalidation, workable liquidity, a
    favourable tail, limited chase, and credible forced flow -- such
    that a SMALL account has an asymmetric attack?

BOTH DIMENSIONS LAW (inherited from the equity and options sleeves).
A plausible thesis at a terrible location is not an attack, and a
beautiful location with no thesis is not an attack either. Either
dimension may veto.

WHY "SMALL ACCOUNT" IS LOAD-BEARING, NOT FLATTERY
The small-capital doctrine says: never fight giants where giants are
strong. That has a concrete meaning here.

  - We do NOT race a cascade. Front-running forced liquidation is a
    latency contest, and we lose it by construction.
  - We DO consider being the liquidity that forced sellers must trade
    against once their flow is exhausting. That needs patience and
    small size, not speed -- the one asymmetry we actually own.
  - Our size is judged against the ACTUAL book. Depth that is
    irrelevant to a fund is decisive for us, and a location we can
    genuinely fill is worth more than a better-looking one we cannot.

This module reaches the L2 book directly, which is only legitimate
because L2 passed acceptance and froze. Everything it reads is trusted
state.

RULE CLASSIFICATION. Every rule below is either STRUCTURAL_INVALIDITY
(refuse: the attack is impossible or unmeasurable) or an
EXPLORATORY_QUALITY_PRIOR (downgrade: judgement we have not earned the
right to call a threshold). No LEARNED_ECONOMIC_THRESHOLD is authorized
at this authority, because no outcome data exists to learn from.

decision_power: NONE. This proposes geometry. It sizes nothing, orders
nothing, and authorizes nothing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

RULE_CLASSIFICATION = {
    "BOOK_NOT_VALID": "STRUCTURAL_INVALIDITY",
    "NO_EXECUTABLE_SIDE": "STRUCTURAL_INVALIDITY",
    "CROSSED_OR_LOCKED": "STRUCTURAL_INVALIDITY",
    "NO_INVALIDATION_LEVEL": "STRUCTURAL_INVALIDITY",
    "THESIS_NOT_ESTIMABLE": "STRUCTURAL_INVALIDITY",
    "MID_CASCADE_NO_ATTACK": "STRUCTURAL_INVALIDITY",
    "SIZE_EXCEEDS_BOOK": "EXPLORATORY_QUALITY_PRIOR",
    "WIDE_SPREAD": "EXPLORATORY_QUALITY_PRIOR",
    "THIN_TOP": "EXPLORATORY_QUALITY_PRIOR",
    "EXTENDED_CHASE": "EXPLORATORY_QUALITY_PRIOR",
    "WIDE_INVALIDATION": "EXPLORATORY_QUALITY_PRIOR",
    "UNFAVOURABLE_TAIL": "EXPLORATORY_QUALITY_PRIOR",
}

EXECUTION_STATES = ("EXECUTION_IMPOSSIBLE", "EXECUTION_DEGRADED",
                    "EXECUTION_ACCEPTABLE", "EXECUTION_UNKNOWN")

# Pre-declared exploratory priors. Structural statements about what the
# words mean -- never fitted to any outcome, because there are none.
CHASE_ATR_LIMITS = {"LOW": 0.5, "MODERATE": 1.5, "HIGH": 3.0}
WIDE_SPREAD_TICKS = 10          # relative to the instrument's own tick
MIN_TAIL_RATIO = 1.5            # reward must exceed risk to be asymmetric
INVALIDATION_GOOD_ATR = 1.0
INVALIDATION_POOR_ATR = 3.0


@dataclass(frozen=True)
class BTCAttackGeometry:
    subject: str
    T: str
    direction: str
    # ---- the thesis half
    forced_action_state: str = NOT_ESTIMABLE
    pressured_side: str = NOT_ESTIMABLE
    thesis_credible: bool | str = NOT_ESTIMABLE
    # ---- the location half (continuous measurements preserved)
    reference_price: float | None = None
    invalidation: float | None = None
    invalidation_distance: float | None = None
    invalidation_distance_atr: float | str = NOT_ESTIMABLE
    target: float | None = None
    tail_ratio: float | str = NOT_ESTIMABLE
    chase_state: str = "UNKNOWN"
    extension_atr: float | str = NOT_ESTIMABLE
    # ---- can we actually transact
    execution_state: str = "EXECUTION_UNKNOWN"
    best_bid: float | None = None
    best_ask: float | None = None
    spread_ticks: float | None = None
    executable_size: int | str = NOT_ESTIMABLE
    intended_size: int = 1
    size_vs_book: float | str = NOT_ESTIMABLE
    # ---- verdict
    attackable: bool = False
    wounds: tuple = ()
    structural_wounds: tuple = ()
    reasoning: tuple = ()
    small_account_note: str | None = None
    rule_classification: dict = None
    calibration: str = "NONE_FITTED"
    evidence_class: str = "PROSPECTIVE_LIVE_CAPTURE"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "btc_attack_geometry", **asdict(self)}


def _structural(wounds) -> list:
    return [w for w in wounds
            if RULE_CLASSIFICATION.get(w) == "STRUCTURAL_INVALIDITY"]


def assess(*, subject: str, T: str, thesis, book_top: dict | None,
           atr: float | None = None, reference_price: float | None = None,
           recent_extreme: float | None = None,
           intended_size: int = 1, tick_size: float = 1.0
           ) -> BTCAttackGeometry:
    """Judge one potential attack.

    `thesis` is a ForcedActionThesis. `book_top` is BookState.top().
    Nothing is inferred where the inputs are silent."""
    wounds, reasons = [], []

    # ---------------- THE THESIS HALF
    state = getattr(thesis, "state", NOT_ESTIMABLE)
    pressured = getattr(thesis, "pressured_side", NOT_ESTIMABLE)
    tradeable = getattr(thesis, "tradeable_moment", "NONE") or "NONE"

    if state == NOT_ESTIMABLE:
        wounds.append("THESIS_NOT_ESTIMABLE")
        reasons.append("the forced-action question could not be asked "
                       "of this data; absence of a reason to refuse is "
                       "not a reason to attack")
    elif state == "DELEVERAGING_IN_PROGRESS":
        wounds.append("MID_CASCADE_NO_ATTACK")
        reasons.append(
            "flow is still arriving: entering mid-cascade is a latency "
            "race against liquidation engines, which a small account "
            "loses by construction")
    thesis_credible = (state == "DELEVERAGING_EXHAUSTING"
                       and tradeable.startswith(
                           "PATIENT_LIQUIDITY_INTO_EXHAUSTION"))
    if state == "DELEVERAGING_EXHAUSTING":
        reasons.append(
            f"forced flow against {pressured} is decaying -- the only "
            f"forced-participant moment a small account can hold, "
            f"because it needs patience rather than speed")

    # DIRECTION follows the pressured side: we are the counterparty to
    # exhausted forced flow, never its companion.
    direction = ("LONG" if pressured == "LONGS" else
                 "SHORT" if pressured == "SHORTS" else NOT_ESTIMABLE)
    if direction != NOT_ESTIMABLE:
        reasons.append(
            f"{pressured} were forced sellers of the move; the attack "
            f"is the OTHER side of their exhaustion, not a continuation")

    # ---------------- THE LOCATION HALF
    bb = ba = spread_t = None
    exec_state = "EXECUTION_UNKNOWN"
    executable = NOT_ESTIMABLE
    if not book_top:
        wounds.append("BOOK_NOT_VALID")
        reasons.append("no book state supplied; a location cannot be "
                       "judged without one")
    elif book_top.get("book_quality") != "VALID":
        wounds.append("BOOK_NOT_VALID")
        exec_state = "EXECUTION_IMPOSSIBLE"
        reasons.append(f"book quality {book_top.get('book_quality')}: "
                       f"an invalid book is not a market we may act on")
    else:
        bb, ba = book_top.get("best_bid_raw"), book_top.get("best_ask_raw")
        if bb is None or ba is None:
            wounds.append("NO_EXECUTABLE_SIDE")
            exec_state = "EXECUTION_IMPOSSIBLE"
        elif ba <= bb:
            wounds.append("CROSSED_OR_LOCKED")
            exec_state = "EXECUTION_IMPOSSIBLE"
        else:
            spread_t = (ba - bb) / tick_size if tick_size else None
            # the size we could actually take, on OUR side
            executable = (book_top.get("best_ask_qty") if direction == "LONG"
                          else book_top.get("best_bid_qty"))
            executable = executable if executable is not None \
                else NOT_ESTIMABLE
            if isinstance(executable, (int, float)) and executable > 0:
                if executable >= intended_size:
                    exec_state = "EXECUTION_ACCEPTABLE"
                else:
                    exec_state = "EXECUTION_DEGRADED"
                    wounds.append("SIZE_EXCEEDS_BOOK")
                    reasons.append(
                        f"intended {intended_size} vs {executable} "
                        f"available at touch")
            else:
                exec_state = "EXECUTION_IMPOSSIBLE"
                wounds.append("NO_EXECUTABLE_SIDE")
            if spread_t is not None and spread_t > WIDE_SPREAD_TICKS:
                wounds.append("WIDE_SPREAD")
                reasons.append(
                    f"spread is {spread_t:.0f} ticks -- the round trip "
                    f"is paid twice before the thesis pays once")

    ref = reference_price
    if ref is None and bb is not None and ba is not None:
        ref = (bb + ba) / 2.0

    # ---- invalidation: where is the thesis WRONG?
    inval = inval_dist = None
    inval_atr = NOT_ESTIMABLE
    if recent_extreme is not None and ref is not None:
        # exhaustion is falsified by a new extreme against us
        inval = recent_extreme
        inval_dist = abs(ref - inval)
        if atr and atr > 0:
            inval_atr = round(inval_dist / atr, 3)
            if inval_atr > INVALIDATION_POOR_ATR:
                wounds.append("WIDE_INVALIDATION")
                reasons.append(
                    f"invalidation is {inval_atr} ATR away: risk cannot "
                    f"be bounded tightly enough to be asymmetric")
    else:
        wounds.append("NO_INVALIDATION_LEVEL")
        reasons.append("no level at which the thesis would be wrong -- "
                       "an attack without an invalidation is a hope")

    # ---- chase: are we arriving after the move?
    chase = "UNKNOWN"
    ext_atr = NOT_ESTIMABLE
    if ref is not None and recent_extreme is not None and atr and atr > 0:
        ext = abs(ref - recent_extreme) / atr
        ext_atr = round(ext, 3)
        chase = ("LOW" if ext <= CHASE_ATR_LIMITS["LOW"] else
                 "MODERATE" if ext <= CHASE_ATR_LIMITS["MODERATE"] else
                 "HIGH" if ext <= CHASE_ATR_LIMITS["HIGH"] else "EXTREME")
        if chase in ("HIGH", "EXTREME"):
            wounds.append("EXTENDED_CHASE")
            reasons.append(
                f"price is {ext_atr} ATR from the extreme: most of the "
                f"reversion we would be paying for has already happened")

    # ---- tail: is the payoff asymmetric?
    tail = NOT_ESTIMABLE
    target = None
    if inval_dist and inval_dist > 0 and ref is not None and atr:
        # pre-declared: the reversion objective is the prior extreme's
        # mirror, one ATR back toward where the flow came from
        target = (ref + atr if direction == "LONG" else
                  ref - atr if direction == "SHORT" else None)
        if target is not None:
            tail = round(abs(target - ref) / inval_dist, 3)
            if tail < MIN_TAIL_RATIO:
                wounds.append("UNFAVOURABLE_TAIL")
                reasons.append(
                    f"reward/risk {tail} is below {MIN_TAIL_RATIO}: "
                    f"being right would not pay for being wrong")

    structural = _structural(wounds)
    attackable = bool(thesis_credible) and not structural and \
        exec_state in ("EXECUTION_ACCEPTABLE", "EXECUTION_DEGRADED")

    note = None
    if isinstance(executable, (int, float)) and executable >= \
            intended_size * 10:
        note = (f"the touch holds {executable} against our "
                f"{intended_size}: our footprint is negligible here, "
                f"which is precisely the asymmetry a small account owns "
                f"and a fund does not")

    if not thesis_credible and not structural:
        reasons.append("no credible forced-flow thesis at this instant; "
                       "location quality alone is not a reason to act")

    return BTCAttackGeometry(
        subject=subject, T=T, direction=direction,
        forced_action_state=state, pressured_side=pressured,
        thesis_credible=thesis_credible,
        reference_price=ref, invalidation=inval,
        invalidation_distance=(round(inval_dist, 4) if inval_dist
                               else None),
        invalidation_distance_atr=inval_atr,
        target=target, tail_ratio=tail,
        chase_state=chase, extension_atr=ext_atr,
        execution_state=exec_state, best_bid=bb, best_ask=ba,
        spread_ticks=(round(spread_t, 2) if spread_t is not None
                      else None),
        executable_size=executable, intended_size=intended_size,
        size_vs_book=(round(intended_size / executable, 4)
                      if isinstance(executable, (int, float))
                      and executable else NOT_ESTIMABLE),
        attackable=attackable, wounds=tuple(wounds),
        structural_wounds=tuple(structural), reasoning=tuple(reasons),
        small_account_note=note,
        rule_classification=dict(RULE_CLASSIFICATION))
