"""OPTIONS ATTACK GEOMETRY + ASSASSIN.

The equity faculty answers "is HERE and NOW the place to strike?" for
the underlying. Options must answer a harder question, because being
right about direction is not the same as making money:

    UNDERLYING GEOMETRY   is the stock at an attackable location?
            AND
    CONTRACT GEOMETRY     does the option market let me monetize it?

Both must hold. A perfect pullback expressed through a wide-spread,
short-dated, far-breakeven contract is a losing trade with a correct
thesis -- the single most common way an options trader is right and
still pays for it.

REUSE, DON'T DUPLICATE: underlying entry geometry comes from the
commissioned equity faculty (apex.predators.equities.attack_geometry).
This module adds only the contract dimension.

The ASSASSIN here may REFUSE, DEGRADE or WARN. It may never manufacture
confidence, and it never sees outcomes.

decision_power: NONE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"
CONTRACT_QUALITY = ("STRONG", "GOOD", "ACCEPTABLE", "POOR", "UNKNOWN")

# pre-registered 2026-08-23, before any outcome was inspected.
# Rationale is structural, not fitted:
#   spread    -- what you pay to enter AND exit, twice
#   DTE       -- theta burden accelerates inside ~3 weeks
#   size      -- a quote you cannot fill is not a quote
MAX_SPREAD_PCT_ATTACKABLE = 0.10     # 10% of mid, round trip ~20%
WIDE_SPREAD_PCT = 0.25
MIN_TOP_SIZE = 5                     # contracts at the touch
MIN_DTE_ATTACKABLE = 14.0
THETA_BURDEN_DTE = 21.0              # below this, decay dominates
MAX_QUOTE_AGE_S = 120.0


@dataclass(frozen=True)
class OptionsAttackGeometry:
    subject: str
    direction: str
    expression: str
    underlying_entry_quality: str        # from the equity faculty
    underlying_invalidation: float | None
    underlying_chase_risk: str
    contract_quality: str
    spread_pct: float | None
    top_size: int | None
    quote_age_s: float | None
    dte: float | None
    moneyness: float | None
    breakeven_move_pct: float | None
    breakeven_reach_ratio: float | str
    theta_burden: str
    execution_feasibility: str
    attackable: bool
    reasoning: tuple = ()
    data_quality: str = "UNKNOWN"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "options_attack_geometry", **asdict(self)}


def assess(*, subject: str, direction: str, candidate,
           underlying_geometry, expected_move_pct=NOT_ESTIMABLE,
           quote_age_s: float | None = None, top_size: int | None = None,
           dte: float | None = None, spot: float | None = None
           ) -> OptionsAttackGeometry:
    """Combine the commissioned underlying geometry with contract
    economics. Both dimensions must be attackable; either one can veto."""
    reasons = []
    strike = None
    for action, right, k, _px in candidate.legs:
        if right != "STOCK":
            strike = k
            break
    moneyness = (strike / spot if strike and spot else None)

    spread_pct = None
    if candidate.quoted_spread_cost is not None and candidate.debit:
        spread_pct = candidate.quoted_spread_cost / abs(candidate.debit)

    # ---- contract quality (each condition can only DOWNGRADE)
    cq = "GOOD"
    if candidate.expression == "STOCK":
        cq = "GOOD"
        reasons.append("underlying expression: no contract friction")
    else:
        if spread_pct is None:
            cq = "UNKNOWN"
            reasons.append("spread not computable -> contract UNKNOWN")
        elif spread_pct > WIDE_SPREAD_PCT:
            cq = "POOR"
            reasons.append(
                f"spread {spread_pct:.1%} of premium -- round trip "
                f"costs ~{2 * spread_pct:.0%} before the thesis pays")
        elif spread_pct > MAX_SPREAD_PCT_ATTACKABLE:
            cq = "ACCEPTABLE"
            reasons.append(f"spread {spread_pct:.1%} is a real drag")
        if top_size is not None and top_size < MIN_TOP_SIZE:
            cq = "POOR"
            reasons.append(
                f"top-of-book {top_size} contracts -- a quote you "
                f"cannot fill is not a quote")
        if dte is not None:
            if dte < MIN_DTE_ATTACKABLE:
                cq = "POOR"
                reasons.append(f"DTE {dte:.0f}d below attackable floor")
            elif dte < THETA_BURDEN_DTE:
                cq = "ACCEPTABLE" if cq == "GOOD" else cq
                reasons.append(f"DTE {dte:.0f}d: decay dominates")
        if quote_age_s is not None and quote_age_s > MAX_QUOTE_AGE_S:
            cq = "UNKNOWN"
            reasons.append(f"quote {quote_age_s:.0f}s stale")

    theta_burden = ("UNKNOWN" if dte is None else
                    "HIGH" if dte < THETA_BURDEN_DTE else
                    "MODERATE" if dte < 45 else "LOW")

    reach = NOT_ESTIMABLE
    if isinstance(expected_move_pct, (int, float)) and \
            candidate.breakeven_move_pct is not None and expected_move_pct:
        reach = round(abs(candidate.breakeven_move_pct) /
                      abs(expected_move_pct), 3)
        if reach > 1.0:
            cq = "POOR"
            reasons.append(
                f"breakeven needs {reach:.2f}x the expected move -- "
                f"correct direction would still lose")

    ug = getattr(underlying_geometry, "entry_quality", "UNKNOWN")
    chase = getattr(underlying_geometry, "chase_risk", "UNKNOWN")
    inval = getattr(underlying_geometry, "invalidation", None)

    # ---- BOTH dimensions must hold
    attackable = (ug in ("STRONG", "GOOD") and cq in ("STRONG", "GOOD"))
    if ug not in ("STRONG", "GOOD"):
        reasons.append(f"underlying entry {ug}: not an attackable "
                       f"location regardless of the contract")
    if attackable:
        reasons.append("underlying location AND contract economics "
                       "both attackable")

    return OptionsAttackGeometry(
        subject=subject, direction=direction,
        expression=candidate.expression,
        underlying_entry_quality=ug, underlying_invalidation=inval,
        underlying_chase_risk=chase, contract_quality=cq,
        spread_pct=(round(spread_pct, 4) if spread_pct else None),
        top_size=top_size, quote_age_s=quote_age_s, dte=dte,
        moneyness=(round(moneyness, 4) if moneyness else None),
        breakeven_move_pct=candidate.breakeven_move_pct,
        breakeven_reach_ratio=reach, theta_burden=theta_burden,
        execution_feasibility=("FEASIBLE" if cq in
                               ("STRONG", "GOOD", "ACCEPTABLE")
                               else "QUESTIONABLE"),
        attackable=attackable, reasoning=tuple(reasons),
        data_quality=("FULL" if cq != "UNKNOWN" else "PARTIAL"))


# ------------------------------------------------------- ASSASSIN

WOUND_FAMILIES = (
    "DIRECTION_RIGHT_OPTION_WRONG", "IV_CRUSH_RISK", "THETA_BURDEN",
    "BAD_DTE", "BAD_STRIKE", "SPREAD_TOO_EXPENSIVE", "POOR_QUOTE_QUALITY",
    "BREAKEVEN_UNREALISTIC", "UNDERLYING_TOO_EXTENDED", "CHASE_RISK",
    "SURFACE_CONTRADICTS_THESIS", "EXPRESSION_INFERIOR_TO_STOCK",
    "INSUFFICIENT_EVIDENCE")

VERDICTS = ("SURVIVED", "SURVIVED_WOUNDED", "DEGRADE", "REFUSE")


@dataclass(frozen=True)
class AssassinFinding:
    verdict: str
    wounds: tuple = ()
    reasoning: tuple = ()
    law: str = ("may REFUSE / DEGRADE / WARN -- may NEVER manufacture "
                "confidence, and never sees outcomes")
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "options_assassin", **asdict(self)}


def assassinate(*, geometry, options_state, candidate,
                stock_candidate=None, event_risk: str = "UNKNOWN"
                ) -> AssassinFinding:
    """Hunt for the ways this specific option trade loses while the
    thesis is right."""
    wounds, why = [], []

    if geometry.contract_quality == "POOR":
        wounds.append("POOR_QUOTE_QUALITY")
        why.append("contract economics rated POOR")
    if geometry.spread_pct and geometry.spread_pct > WIDE_SPREAD_PCT:
        wounds.append("SPREAD_TOO_EXPENSIVE")
    if geometry.theta_burden == "HIGH":
        wounds.append("THETA_BURDEN")
        why.append("short tenor: time decay is a headwind every day "
                   "the thesis takes to work")
    if geometry.dte is not None and geometry.dte < MIN_DTE_ATTACKABLE:
        wounds.append("BAD_DTE")
    if isinstance(geometry.breakeven_reach_ratio, (int, float)) and \
            geometry.breakeven_reach_ratio > 1.0:
        wounds.append("BREAKEVEN_UNREALISTIC")
        wounds.append("DIRECTION_RIGHT_OPTION_WRONG")
        why.append("the move required merely to break even exceeds the "
                   "move expected")
    if geometry.underlying_chase_risk in ("HIGH", "EXTREME"):
        wounds.append("UNDERLYING_TOO_EXTENDED")
        wounds.append("CHASE_RISK")

    # IV crush: buying premium when IV sits far above realized
    ivr = getattr(options_state, "iv_over_rv", NOT_ESTIMABLE)
    is_debit = candidate.expression != "STOCK" and (candidate.debit or 0) > 0
    if isinstance(ivr, (int, float)) and is_debit and ivr > 1.5:
        wounds.append("IV_CRUSH_RISK")
        why.append(f"paying premium at IV/RV {ivr:.2f} -- a correct "
                   f"move can be erased by the vol repricing")

    # is the option actually worse than simply owning the stock?
    if stock_candidate is not None and candidate.expression != "STOCK":
        if isinstance(geometry.breakeven_reach_ratio, (int, float)) and \
                geometry.breakeven_reach_ratio > 1.0:
            wounds.append("EXPRESSION_INFERIOR_TO_STOCK")
            why.append("stock breaks even at zero move; this contract "
                       "does not")

    if getattr(options_state, "data_quality", "UNKNOWN") != "FULL":
        wounds.append("INSUFFICIENT_EVIDENCE")
        why.append("options state incomplete -- absence of a reason to "
                   "refuse is not a reason to attack")

    lethal = {"BREAKEVEN_UNREALISTIC", "POOR_QUOTE_QUALITY", "BAD_DTE",
              "INSUFFICIENT_EVIDENCE"}
    wounds = tuple(dict.fromkeys(wounds))
    if any(w in lethal for w in wounds):
        verdict = "REFUSE"
    elif len(wounds) >= 3:
        verdict = "DEGRADE"
    elif wounds:
        verdict = "SURVIVED_WOUNDED"
    else:
        verdict = "SURVIVED"
    return AssassinFinding(verdict=verdict, wounds=wounds,
                           reasoning=tuple(why))
