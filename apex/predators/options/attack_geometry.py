"""OPTIONS ATTACK GEOMETRY + ASSASSIN.

The equity faculty answers "is HERE and NOW the place to strike?" for
the underlying. Options must answer a harder question, because being
right about direction is not the same as making money:

    UNDERLYING GEOMETRY   is the stock at an attackable location?
            AND
    CONTRACT GEOMETRY     does the option market let me monetize it?

REUSE, DON'T DUPLICATE: underlying entry geometry comes from the
commissioned equity faculty. This module adds only the contract
dimension.

=====================================================================
RULE CLASSIFICATION LAW (operator, 2026-08-23)
=====================================================================
Every rule below is classified as exactly one of:

  STRUCTURAL_INVALIDITY      mathematics or market mechanics make the
                             state impossible/unexecutable. Permanent.
  EXPLORATORY_QUALITY_PRIOR  a provisional safety/quality heuristic
                             held BEFORE economic evidence. It may
                             DEGRADE, and it must never masquerade as
                             a proven profit threshold.
  LEARNED_ECONOMIC_THRESHOLD derived from governed prospective
                             evidence. **NONE ARE AUTHORIZED YET.**

THE MISTAKE THIS PREVENTS: a first draft of this module structurally
penalized every DTE < 14 -- inherited retail folklore ("short-dated is
dangerous"), not measurement. A genuinely elite Predator may well find
that a 3- or 7-DTE contract is the superior weapon for a fast intraday
mechanism because of gamma, capital efficiency, catalyst timing or a
tight invalidation. We do not ban a battlefield before studying it.
DTE is therefore represented ECONOMICALLY (theta burden, breakeven,
horizon fit) and never as a blanket penalty.

decision_power: NONE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"
CONTRACT_QUALITY = ("STRONG", "GOOD", "ACCEPTABLE", "POOR", "UNKNOWN")
EXECUTION_STATES = ("EXECUTION_IMPOSSIBLE", "EXECUTION_DEGRADED",
                    "EXECUTION_ACCEPTABLE", "UNKNOWN")
FORECAST_PEDIGREE = ("CALIBRATED", "ESTIMABLE_UNCALIBRATED",
                     "NOT_ESTIMABLE")

RULE_CLASSIFICATION = {
    "crossed_or_missing_executable_side": "STRUCTURAL_INVALIDITY",
    "expired_or_zero_dte_contract": "STRUCTURAL_INVALIDITY",
    "causally_impossible_state": "STRUCTURAL_INVALIDITY",
    "spread_pct_wide": "EXPLORATORY_QUALITY_PRIOR",
    "top_size_below_intended_order": "EXPLORATORY_QUALITY_PRIOR",
    "quote_staleness": "EXPLORATORY_QUALITY_PRIOR",
    "theta_burden_short_dte": "EXPLORATORY_QUALITY_PRIOR",
    "breakeven_reach_ratio": "EXPLORATORY_QUALITY_PRIOR",
    "_note": "no LEARNED_ECONOMIC_THRESHOLD is authorized at this "
             "stage; every numeric constant below is provisional and "
             "must be re-derived from governed prospective evidence "
             "before it may harden",
}

# ---- provisional priors (EXPLORATORY, not proven optima) ------------
WIDE_SPREAD_PCT = 0.25          # round trip ~2x this before thesis pays
DEGRADED_SPREAD_PCT = 0.10
STALE_QUOTE_S = 120.0           # far too lax for live; fine for replay
THETA_BURDEN_DTE = 21.0         # decay accelerates, NOT a ban
DEFAULT_INTENDED_CONTRACTS = 1  # a small account may need only one


@dataclass(frozen=True)
class OptionsAttackGeometry:
    subject: str
    direction: str
    expression: str
    underlying_entry_quality: str
    underlying_invalidation: float | None
    underlying_chase_risk: str
    contract_quality: str
    execution_state: str
    # continuous measurements preserved -- thresholds are downstream
    spread_abs: float | None
    spread_pct: float | None
    bid_size: int | None
    ask_size: int | None
    quote_age_s: float | None
    open_interest: int | None
    dte: float | None
    moneyness: float | None
    breakeven_move_pct: float | None
    breakeven_reach_ratio: float | str
    forecast_pedigree: str
    theta_burden: str
    attackable: bool
    rule_classification: dict = None
    reasoning: tuple = ()
    data_quality: str = "UNKNOWN"
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "options_attack_geometry", **asdict(self)}


def assess(*, subject: str, direction: str, candidate,
           underlying_geometry, expected_move_pct=NOT_ESTIMABLE,
           forecast_pedigree: str = "NOT_ESTIMABLE",
           quote_age_s: float | None = None,
           bid_size: int | None = None, ask_size: int | None = None,
           open_interest: int | None = None,
           intended_contracts: int = DEFAULT_INTENDED_CONTRACTS,
           dte: float | None = None, spot: float | None = None
           ) -> OptionsAttackGeometry:
    """Combine commissioned underlying geometry with contract
    economics. Both dimensions must be attackable; either may veto."""
    reasons = []
    strike = None
    for _action, right, k, _px in candidate.legs:
        if right != "STOCK":
            strike = k
            break
    moneyness = (strike / spot if strike and spot else None)

    spread_abs = candidate.quoted_spread_cost
    spread_pct = None
    if spread_abs is not None and candidate.debit:
        spread_pct = spread_abs / abs(candidate.debit)

    is_stock = candidate.expression == "STOCK"

    # ---------- EXECUTION STATE (continuous inputs -> ordinal state)
    if is_stock:
        execution = "EXECUTION_ACCEPTABLE"
    elif dte is not None and dte <= 0:
        execution = "EXECUTION_IMPOSSIBLE"        # STRUCTURAL
        reasons.append("expired contract: structurally unexecutable")
    elif spread_pct is None:
        execution = "UNKNOWN"
        reasons.append("spread not computable -> execution UNKNOWN")
    else:
        # size is judged against the order WE intend, not a universal
        # floor: one contract in a liquid name is a real order
        touch = min(x for x in (bid_size, ask_size) if x is not None) \
            if (bid_size is not None or ask_size is not None) else None
        if touch is not None and touch <= 0:
            execution = "EXECUTION_IMPOSSIBLE"    # STRUCTURAL
            reasons.append("no size at the touch: unexecutable")
        elif touch is not None and touch < intended_contracts:
            execution = "EXECUTION_DEGRADED"
            reasons.append(
                f"touch size {touch} < intended {intended_contracts} "
                f"(prior, not a universal floor)")
        elif spread_pct > WIDE_SPREAD_PCT:
            execution = "EXECUTION_DEGRADED"
            reasons.append(
                f"spread {spread_pct:.1%} of premium -- round trip "
                f"~{2 * spread_pct:.0%} before the thesis pays (prior)")
        elif quote_age_s is not None and quote_age_s > STALE_QUOTE_S:
            execution = "UNKNOWN"
            reasons.append(f"quote {quote_age_s:.0f}s stale (prior; a "
                           f"live session would demand far fresher)")
        else:
            execution = "EXECUTION_ACCEPTABLE"

    # ---------- DTE: economic representation, never a blanket penalty
    theta_burden = ("UNKNOWN" if dte is None else
                    "HIGH" if dte < THETA_BURDEN_DTE else
                    "MODERATE" if dte < 45 else "LOW")
    if theta_burden == "HIGH" and not is_stock:
        reasons.append(
            f"DTE {dte:.0f}d: theta burden HIGH -- an economic fact to "
            f"weigh against gamma/capital efficiency, NOT a ban")

    # ---------- breakeven reach, gated on forecast pedigree
    reach, be_severity = NOT_ESTIMABLE, None
    if forecast_pedigree not in FORECAST_PEDIGREE:
        raise ValueError(f"unknown forecast_pedigree {forecast_pedigree}")
    if (forecast_pedigree != "NOT_ESTIMABLE"
            and isinstance(expected_move_pct, (int, float))
            and expected_move_pct
            and candidate.breakeven_move_pct is not None):
        reach = round(abs(candidate.breakeven_move_pct) /
                      abs(expected_move_pct), 3)
        if reach > 1.0:
            if forecast_pedigree == "CALIBRATED":
                be_severity = "REFUSE"
                reasons.append(
                    f"breakeven needs {reach:.2f}x the CALIBRATED "
                    f"expected move -- correct direction still loses")
            else:
                be_severity = "CONCERN"
                reasons.append(
                    f"breakeven needs {reach:.2f}x an UNCALIBRATED "
                    f"expected move -- concern, not proof; no hard veto "
                    f"from an immature forecast")

    # ---------- contract quality (downgrade-only)
    if execution == "EXECUTION_IMPOSSIBLE":
        cq = "POOR"
    elif execution == "UNKNOWN":
        cq = "UNKNOWN"
    elif execution == "EXECUTION_DEGRADED":
        cq = "ACCEPTABLE"
    else:
        cq = "GOOD"
    if be_severity == "REFUSE":
        cq = "POOR"
    elif be_severity == "CONCERN" and cq == "GOOD":
        cq = "ACCEPTABLE"
    if spread_pct is not None and not is_stock and \
            DEGRADED_SPREAD_PCT < spread_pct <= WIDE_SPREAD_PCT \
            and cq == "GOOD":
        cq = "ACCEPTABLE"
        reasons.append(f"spread {spread_pct:.1%} is a real drag (prior)")

    ug = getattr(underlying_geometry, "entry_quality", "UNKNOWN")
    chase = getattr(underlying_geometry, "chase_risk", "UNKNOWN")
    inval = getattr(underlying_geometry, "invalidation", None)

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
        execution_state=execution,
        spread_abs=spread_abs,
        spread_pct=(round(spread_pct, 4) if spread_pct else None),
        bid_size=bid_size, ask_size=ask_size, quote_age_s=quote_age_s,
        open_interest=open_interest, dte=dte,
        moneyness=(round(moneyness, 4) if moneyness else None),
        breakeven_move_pct=candidate.breakeven_move_pct,
        breakeven_reach_ratio=reach, forecast_pedigree=forecast_pedigree,
        theta_burden=theta_burden, attackable=attackable,
        rule_classification=dict(RULE_CLASSIFICATION),
        reasoning=tuple(reasons),
        data_quality=("FULL" if cq != "UNKNOWN" else "PARTIAL"))


# ------------------------------------------------------- ASSASSIN

WOUND_FAMILIES = {
    # STRUCTURAL: mechanics make the trade impossible/incoherent
    "EXECUTION_IMPOSSIBLE": "STRUCTURAL",
    "EXPIRED_CONTRACT": "STRUCTURAL",
    "INSUFFICIENT_EVIDENCE": "STRUCTURAL",
    # PROVISIONAL: research priors, may soften or harden with evidence
    "DIRECTION_RIGHT_OPTION_WRONG": "PROVISIONAL",
    "IV_CRUSH_RISK": "PROVISIONAL",
    "THETA_BURDEN": "PROVISIONAL",
    "BAD_DTE": "PROVISIONAL",
    "BAD_STRIKE": "PROVISIONAL",
    "SPREAD_TOO_EXPENSIVE": "PROVISIONAL",
    "POOR_QUOTE_QUALITY": "PROVISIONAL",
    "BREAKEVEN_CONCERN": "PROVISIONAL",
    "BREAKEVEN_UNREALISTIC": "PROVISIONAL",
    "UNDERLYING_TOO_EXTENDED": "PROVISIONAL",
    "CHASE_RISK": "PROVISIONAL",
    "SURFACE_CONTRADICTS_THESIS": "PROVISIONAL",
    "EXPRESSION_INFERIOR_TO_STOCK": "PROVISIONAL",
}

VERDICTS = ("SURVIVED", "SURVIVED_WOUNDED", "DEGRADE", "REFUSE")


@dataclass(frozen=True)
class AssassinFinding:
    verdict: str
    wounds: tuple = ()
    structural_wounds: tuple = ()
    provisional_wounds: tuple = ()
    reasoning: tuple = ()
    law: str = ("may REFUSE / DEGRADE / WARN -- may NEVER manufacture "
                "confidence, and never sees outcomes. STRUCTURAL wounds "
                "reflect mechanics; PROVISIONAL wounds are research "
                "priors that may not masquerade as permanent laws")
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "options_assassin", **asdict(self)}


def assassinate(*, geometry, options_state, candidate,
                stock_candidate=None, event_risk: str = "UNKNOWN"
                ) -> AssassinFinding:
    """Hunt the ways this option loses while the thesis is right."""
    wounds, why = [], []

    if geometry.execution_state == "EXECUTION_IMPOSSIBLE":
        wounds.append("EXECUTION_IMPOSSIBLE")
        why.append("no executable market at T")
    if geometry.dte is not None and geometry.dte <= 0:
        wounds.append("EXPIRED_CONTRACT")
    if geometry.execution_state == "EXECUTION_DEGRADED":
        wounds.append("POOR_QUOTE_QUALITY")
    if geometry.spread_pct and geometry.spread_pct > WIDE_SPREAD_PCT:
        wounds.append("SPREAD_TOO_EXPENSIVE")
    if geometry.theta_burden == "HIGH":
        wounds.append("THETA_BURDEN")
        why.append("short tenor: decay is a daily headwind -- weighed "
                   "against gamma, not assumed fatal")
    if isinstance(geometry.breakeven_reach_ratio, (int, float)) and \
            geometry.breakeven_reach_ratio > 1.0:
        if geometry.forecast_pedigree == "CALIBRATED":
            wounds += ["BREAKEVEN_UNREALISTIC",
                       "DIRECTION_RIGHT_OPTION_WRONG"]
            why.append("calibrated forecast says breakeven exceeds the "
                       "expected move")
        else:
            wounds.append("BREAKEVEN_CONCERN")
            why.append("uncalibrated forecast suggests a distant "
                       "breakeven -- concern, not refusal")
    if geometry.underlying_chase_risk in ("HIGH", "EXTREME"):
        wounds += ["UNDERLYING_TOO_EXTENDED", "CHASE_RISK"]

    ivr = getattr(options_state, "iv_over_rv", NOT_ESTIMABLE)
    is_debit = (candidate.expression != "STOCK"
                and (candidate.debit or 0) > 0)
    if isinstance(ivr, (int, float)) and is_debit and ivr > 1.5:
        wounds.append("IV_CRUSH_RISK")
        why.append(f"paying premium at IV/RV {ivr:.2f} -- a correct "
                   f"move can be erased by vol repricing")

    if stock_candidate is not None and candidate.expression != "STOCK" \
            and isinstance(geometry.breakeven_reach_ratio, (int, float)) \
            and geometry.breakeven_reach_ratio > 1.0 \
            and geometry.forecast_pedigree == "CALIBRATED":
        wounds.append("EXPRESSION_INFERIOR_TO_STOCK")
        why.append("stock breaks even at zero move; this contract does "
                   "not, on a calibrated forecast")

    if getattr(options_state, "data_quality", "UNKNOWN") != "FULL":
        wounds.append("INSUFFICIENT_EVIDENCE")
        why.append("options state incomplete -- absence of a reason to "
                   "refuse is not a reason to attack")

    wounds = tuple(dict.fromkeys(wounds))
    structural = tuple(w for w in wounds
                       if WOUND_FAMILIES.get(w) == "STRUCTURAL")
    provisional = tuple(w for w in wounds
                        if WOUND_FAMILIES.get(w) == "PROVISIONAL")

    # ONLY structural wounds, or a calibrated-breakeven failure, refuse
    if structural or "BREAKEVEN_UNREALISTIC" in wounds:
        verdict = "REFUSE"
    elif len(provisional) >= 3:
        verdict = "DEGRADE"
    elif provisional:
        verdict = "SURVIVED_WOUNDED"
    else:
        verdict = "SURVIVED"
    return AssassinFinding(verdict=verdict, wounds=wounds,
                           structural_wounds=structural,
                           provisional_wounds=provisional,
                           reasoning=tuple(why))
