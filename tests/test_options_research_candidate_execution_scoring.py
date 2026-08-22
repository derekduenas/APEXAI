"""OptionExpressionCandidate, OptionExecutionModel, risk-matching
panels, and the scorecard's Pareto dominance -- combined for the
expression-comparison layer.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research.execution_model import (ExecutionModelError,
                                                    FillEstimate,
                                                    conservative_taker_single_leg,
                                                    diagnostic_midpoint_single_leg,
                                                    vertical_conservative_fill)
from apex.options_research.expression_candidate import (
    ExpressionCandidateError, no_trade_candidate, stock_candidate)
from apex.options_research.risk_matching import all_three_panels
from apex.options_research.scorecard import OptionExpressionScorecard

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


# ---- expression candidate --------------------------------------------

def test_no_trade_is_first_class_not_an_error():
    c = no_trade_candidate("THESIS-1", known_from=T0, now=T0,
                           reason="surface too rich")
    assert c.expression_type == "NO_TRADE"
    assert c.decision_power == "NONE_OPTIONS_RESEARCH"


def test_stock_is_first_class():
    c = stock_candidate("THESIS-1", known_from=T0, now=T0, entry_price=230.0,
                        shares=10)
    assert c.expression_type == "STOCK"
    assert c.capital_required == 2300.0


def test_unknown_expression_type_refused():
    from apex.options_research.expression_candidate import OptionExpressionCandidate
    with pytest.raises(ExpressionCandidateError):
        OptionExpressionCandidate(
            expression_type="SHORT_NAKED_CALL", underlying_thesis_id="T1",
            known_from=str(T0), entry_structure="x", expiry=None, strikes=(),
            legs=(), net_debit_or_credit=None, max_loss=None, max_gain_if_defined=None,
            initial_delta=None, gamma=None, theta=None, vega=None, spread_cost=None,
            estimated_slippage=None, fees=None, capital_required=None,
            risk_capital_required=None, thesis_horizon="UNKNOWN", break_even=(),
            surface_context="x", liquidity_context="x", data_quality="x",
            research_mechanism_ids=(), as_of=str(T0))


def test_out_of_scope_mechanism_refused():
    from apex.options_research.expression_candidate import OptionExpressionCandidate
    with pytest.raises(ExpressionCandidateError):
        OptionExpressionCandidate(
            expression_type="LONG_CALL", underlying_thesis_id="T1",
            known_from=str(T0), entry_structure="x", expiry="2026-08-19",
            strikes=(210.0,), legs=(), net_debit_or_credit=1.0, max_loss=1.0,
            max_gain_if_defined=None, initial_delta=0.5, gamma=0.1, theta=-0.1,
            vega=0.2, spread_cost=0.1, estimated_slippage=0.0, fees=0.65,
            capital_required=100.0, risk_capital_required=100.0,
            thesis_horizon="60m", break_even=(211.0,), surface_context="normal",
            liquidity_context="liquid", data_quality="FULL",
            research_mechanism_ids=("OPT-008-GAMMA-SCALPING",), as_of=str(T0))


def test_active_mechanism_reference_is_allowed():
    from apex.options_research.expression_candidate import OptionExpressionCandidate
    c = OptionExpressionCandidate(
        expression_type="LONG_CALL", underlying_thesis_id="T1", known_from=str(T0),
        entry_structure="x", expiry="2026-08-19", strikes=(210.0,), legs=(),
        net_debit_or_credit=1.0, max_loss=1.0, max_gain_if_defined=None,
        initial_delta=0.5, gamma=0.1, theta=-0.1, vega=0.2, spread_cost=0.1,
        estimated_slippage=0.0, fees=0.65, capital_required=100.0,
        risk_capital_required=100.0, thesis_horizon="60m", break_even=(211.0,),
        surface_context="normal", liquidity_context="liquid", data_quality="FULL",
        research_mechanism_ids=("OPT-001-DIRECTIONAL-CONVEXITY",), as_of=str(T0))
    assert c.research_mechanism_ids == ("OPT-001-DIRECTIONAL-CONVEXITY",)


# ---- execution model ---------------------------------------------------

def test_conservative_taker_buys_ask_sells_bid():
    buy = conservative_taker_single_leg(bid=1.0, ask=1.2, side="BUY",
                                        fee_per_contract=0.65, known_from=T0)
    sell = conservative_taker_single_leg(bid=1.0, ask=1.2, side="SELL",
                                         fee_per_contract=0.65, known_from=T0)
    assert buy.entry_price == 1.2 and buy.is_canonical is True
    assert sell.entry_price == 1.0
    assert buy.fill_mode == "CONSERVATIVE_TAKER"


def test_missing_quote_side_is_unknown_not_zero():
    buy = conservative_taker_single_leg(bid=None, ask=None, side="BUY",
                                        fee_per_contract=0.65, known_from=T0)
    assert buy.entry_price is None


def test_diagnostic_midpoint_is_never_canonical():
    mid = diagnostic_midpoint_single_leg(bid=1.0, ask=1.2, fee_per_contract=0.65,
                                         known_from=T0)
    assert mid.is_canonical is False
    assert mid.fill_mode == "DIAGNOSTIC_MIDPOINT"


def test_unreachable_fill_modes_refused():
    with pytest.raises(ExecutionModelError):
        FillEstimate(fill_mode="EMPIRICALLY_CALIBRATED", leg_fill_type="COMBO_FILL",
                    entry_price=1.0, exit_price=None, spread_cost=0.1, fees=0.65,
                    slippage=0.0, is_canonical=True, known_from=str(T0))


def test_vertical_legged_fill_marks_legging_risk():
    v = vertical_conservative_fill(long_bid=2.0, long_ask=2.2, short_bid=0.9,
                                   short_ask=1.0, fee_per_contract=0.65,
                                   known_from=T0, legged=True)
    assert v.leg_fill_type == "LEGGED_FILL"
    assert v.entry_price == pytest.approx(2.2 - 0.9)


def test_vertical_combo_fill_no_simultaneous_midpoint_assumption():
    v = vertical_conservative_fill(long_bid=2.0, long_ask=2.2, short_bid=0.9,
                                   short_ask=1.0, fee_per_contract=0.65,
                                   known_from=T0)
    assert v.entry_price == pytest.approx(1.3)   # ask - bid, never midpoints


# ---- risk matching -------------------------------------------------------

def test_all_three_panels_run_together():
    panels = all_three_panels(
        max_loss={"LONG_CALL": 100.0, "STOCK": 500.0},
        delta={"LONG_CALL": 50.0, "STOCK": 50.0},
        capital={"LONG_CALL": 100.0, "STOCK": 5000.0})
    assert {p.panel for p in panels} == {"RISK_MATCHED", "DELTA_MATCHED", "CAPITAL_MATCHED"}


def test_no_superiority_from_one_panel_alone():
    """Structural check: comparing on ONE dimension only (e.g. capital)
    can favor a DIFFERENT expression than risk-matching -- both panels
    must be inspectable independently, never collapsed."""
    panels = all_three_panels(
        max_loss={"LONG_CALL": 100.0, "STOCK": 500.0},
        delta={"LONG_CALL": 50.0, "STOCK": 50.0},
        capital={"LONG_CALL": 100.0, "STOCK": 5000.0})
    risk_panel = [p for p in panels if p.panel == "RISK_MATCHED"][0]
    cap_panel = [p for p in panels if p.panel == "CAPITAL_MATCHED"][0]
    assert risk_panel.matched_values != cap_panel.matched_values


# ---- scorecard Pareto dominance -----------------------------------------

def _sc(expression_type, **overrides):
    base = dict(expression_type=expression_type, mean_net_expectancy=10.0,
               median_net_outcome=8.0, expected_shortfall=-20.0,
               maximum_drawdown=-15.0, probability_of_loss=0.4, worst_loss=-30.0,
               return_on_risk_capital=0.1, capital_required=1000.0,
               spread_fee_drag=1.0, latency_sensitivity=0.5, iv_sensitivity=0.5,
               tail_concentration=0.3, option_minus_stock_net=2.0,
               option_minus_no_trade_net=5.0, sample_size=1, known_from=str(T0))
    base.update(overrides)
    return OptionExpressionScorecard(**base)


def test_strictly_better_on_every_axis_is_dominant():
    good = _sc("LONG_CALL")
    bad = _sc("STOCK", mean_net_expectancy=1.0, median_net_outcome=1.0,
             expected_shortfall=-40.0, maximum_drawdown=-30.0,
             probability_of_loss=0.6, worst_loss=-60.0,
             return_on_risk_capital=0.01, spread_fee_drag=2.0,
             latency_sensitivity=1.0, iv_sensitivity=1.0, tail_concentration=0.6)
    assert good.is_dominant_over(bad) is True


def test_mixed_result_is_not_dominant():
    a = _sc("LONG_CALL", mean_net_expectancy=10.0, maximum_drawdown=-30.0)
    b = _sc("STOCK", mean_net_expectancy=5.0, maximum_drawdown=-10.0)
    assert a.is_dominant_over(b) is False


def test_too_few_comparable_dimensions_is_unknown_not_false():
    a = _sc("LONG_CALL", mean_net_expectancy=None, median_net_outcome=None,
           expected_shortfall=None, maximum_drawdown=None,
           probability_of_loss=None, worst_loss=None,
           return_on_risk_capital=None, capital_required=None,
           spread_fee_drag=None, latency_sensitivity=None,
           iv_sensitivity=None, tail_concentration=None)
    b = _sc("STOCK")
    assert a.is_dominant_over(b) is None


def test_no_single_magic_score_field_exists():
    fields = set(OptionExpressionScorecard.__dataclass_fields__)
    assert not (fields & {"score", "rank", "weighted_score"})


def test_decision_power_stamped():
    sc = _sc("LONG_CALL")
    assert sc.decision_power == "NONE_OPTIONS_RESEARCH"
