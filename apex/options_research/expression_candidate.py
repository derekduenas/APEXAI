"""OptionExpressionCandidate — F O10: one candidate expression of an
underlying thesis. No candidate carries trade authority; this is a
description of a structure and its research-grade economics, never an
order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

EXPRESSION_TYPES = ("NO_TRADE", "STOCK", "LONG_CALL", "LONG_PUT",
                   "CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD", "LONG_STRADDLE",
                   "LONG_STRANGLE")

# only these mechanisms are wired into the v1 candidate generator --
# OPT-004..010 are REGISTERED_NOT_ACTIVE (see the mechanism registry).
ACTIVE_MECHANISM_IDS = ("OPT-001-DIRECTIONAL-CONVEXITY",
                        "OPT-002-RICH-WING-VERTICALIZATION",
                        "OPT-003-APEX-FORWARD-VOL-GAP")
NO_OPTION_ADVANTAGE = "NO_OPTION_ADVANTAGE_MECHANISM"


class ExpressionCandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionExpressionCandidate:
    expression_type: str
    underlying_thesis_id: str
    known_from: str

    entry_structure: str
    expiry: str | None
    strikes: tuple
    legs: tuple

    net_debit_or_credit: float | None
    max_loss: float | None
    max_gain_if_defined: float | None

    initial_delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None

    spread_cost: float | None
    estimated_slippage: float | None
    fees: float | None

    capital_required: float | None
    risk_capital_required: float | None

    thesis_horizon: str
    break_even: tuple

    surface_context: str
    liquidity_context: str
    data_quality: str

    research_mechanism_ids: tuple
    as_of: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.expression_type not in EXPRESSION_TYPES:
            raise ExpressionCandidateError(
                f"unknown expression_type {self.expression_type!r}")
        bad_mechs = set(self.research_mechanism_ids) - set(ACTIVE_MECHANISM_IDS) - {NO_OPTION_ADVANTAGE}
        if bad_mechs:
            raise ExpressionCandidateError(
                f"mechanism(s) not in the v1 active set: {bad_mechs} -- "
                f"OPT-004..010 are REGISTERED_NOT_ACTIVE, out of scope tonight")

    def as_record(self) -> dict:
        return {"kind": "option_expression_candidate", **asdict(self)}


def no_trade_candidate(underlying_thesis_id: str, *, known_from, now,
                       reason: str) -> OptionExpressionCandidate:
    """NO_TRADE is a first-class, successful candidate -- constructing
    one is not an error path."""
    import pandas as pd
    return OptionExpressionCandidate(
        expression_type="NO_TRADE", underlying_thesis_id=underlying_thesis_id,
        known_from=str(pd.Timestamp(known_from)), entry_structure=reason,
        expiry=None, strikes=(), legs=(), net_debit_or_credit=None, max_loss=None,
        max_gain_if_defined=None, initial_delta=None, gamma=None, theta=None,
        vega=None, spread_cost=None, estimated_slippage=None, fees=None,
        capital_required=None, risk_capital_required=None, thesis_horizon="UNKNOWN",
        break_even=(), surface_context="N/A", liquidity_context="N/A",
        data_quality="N/A", research_mechanism_ids=(),
        as_of=str(pd.Timestamp(now)))


def stock_candidate(underlying_thesis_id: str, *, known_from, now,
                    entry_price: float, shares: int,
                    surface_context: str = "N/A") -> OptionExpressionCandidate:
    """STOCK is a first-class expression, not an option-failure state."""
    import pandas as pd
    return OptionExpressionCandidate(
        expression_type="STOCK", underlying_thesis_id=underlying_thesis_id,
        known_from=str(pd.Timestamp(known_from)),
        entry_structure=f"{shares} shares @ {entry_price}", expiry=None,
        strikes=(), legs=(), net_debit_or_credit=None,
        max_loss=entry_price * shares, max_gain_if_defined=None,
        initial_delta=float(shares), gamma=0.0, theta=0.0, vega=0.0,
        spread_cost=None, estimated_slippage=None, fees=None,
        capital_required=entry_price * shares, risk_capital_required=None,
        thesis_horizon="UNKNOWN", break_even=(entry_price,),
        surface_context=surface_context, liquidity_context="N/A",
        data_quality="N/A", research_mechanism_ids=(), as_of=str(pd.Timestamp(now)))
