"""APEX OPTIONS -- ASYMMETRIC GROWTH DOCTRINE (operator directive,
2026-08-18): NO YOLO law, asymmetry profiling, account scaling
potential, evidence-earned aggression ladder, growth-scenario research
panel, and rare-opportunity classification. Every concept here is
research-only -- no sizing or Capital authority is ever produced.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research.asymmetric_growth_doctrine import (
    DoctrineViolation, NO_YOLO_PROHIBITIONS, assert_no_yolo_violation,
    doctrine_stamp)
from apex.options_research.asymmetry_profile import (
    AsymmetryProfileError, build_from_outcomes, classify_risk_character)
from apex.options_research.edge_maturity import build as build_edge_maturity
from apex.options_research.edge_maturity import classify_edge_maturity
from apex.options_research.growth_panel import (GrowthPanelError,
                                                 simulate_growth_panel)
from apex.options_research.rare_opportunity import classify_rare_opportunity
from apex.options_research.scaling_potential import (ScalingPotentialError,
                                                       build as build_scaling,
                                                       classify_scaling_status)

T0 = pd.Timestamp("2026-08-18T15:00:00Z")


# ---- NO YOLO law -----------------------------------------------------------

def test_no_yolo_prohibitions_are_named():
    assert len(NO_YOLO_PROHIBITIONS) == 9


def test_no_yolo_violation_raises():
    with pytest.raises(DoctrineViolation):
        assert_no_yolo_violation(claimed_practices=("ZERO_DTE_BY_DEFAULT",),
                                 subject="AAPL LONG_CALL")


def test_clean_practices_pass():
    assert_no_yolo_violation(claimed_practices=("DEFINED_LOSS_ONLY",), subject="AAPL")


def test_doctrine_stamp_carries_no_sizing_authority():
    stamp = doctrine_stamp()
    assert stamp["sizing_authority"] == "NONE"
    assert stamp["capital_authority"] == "NONE"
    assert stamp["decision_power"] == "NONE_OPTIONS_RESEARCH"


# ---- asymmetry profile ------------------------------------------------------

def test_defined_loss_is_bounded_volatility_not_ruin():
    assert classify_risk_character(loss_cap=200.0) == "BOUNDED_VOLATILITY"


def test_undefined_loss_is_ruin_exposure():
    assert classify_risk_character(loss_cap=None) == "UNDEFINED_RUIN_EXPOSURE"


def test_zero_sample_yields_insufficient_sample_not_fabricated():
    profile = build_from_outcomes(subject="AAPL", expression_type="LONG_CALL",
                                  loss_cap=200.0, payoff_convexity="CONVEX",
                                  r_multiples=(), known_from=T0)
    assert profile.sample_size == 0
    assert profile.expectancy_r is None
    assert profile.tail_dependence_flag == "UNKNOWN"


def test_real_sample_computes_real_expectancy():
    r_multiples = (2.0, -1.0, 3.0, -1.0, 1.5, -1.0, 4.0, -1.0, 0.5, -1.0)
    profile = build_from_outcomes(subject="AAPL", expression_type="LONG_CALL",
                                  loss_cap=200.0, payoff_convexity="CONVEX",
                                  r_multiples=r_multiples, known_from=T0)
    assert profile.sample_size == 10
    assert profile.expectancy_r == pytest.approx(sum(r_multiples) / 10)
    assert profile.win_rate == pytest.approx(0.5)


def test_unknown_risk_character_refused():
    with pytest.raises(AsymmetryProfileError):
        from apex.options_research.asymmetry_profile import AsymmetryProfile
        AsymmetryProfile(subject="AAPL", expression_type="LONG_CALL",
                        risk_character="MADE_UP", loss_cap=None,
                        payoff_convexity="CONVEX",
                        probability_of_total_premium_loss=None, capital_efficiency=None,
                        return_on_risk_capital=None, sample_size=0, expectancy_r=None,
                        median_r=None, win_rate=None, avg_win_r=None, avg_loss_r=None,
                        payoff_ratio=None, right_tail_contribution=None,
                        left_tail_contribution=None, p_r_ge_2=None, p_r_ge_3=None,
                        p_r_ge_5=None, p_r_ge_10=None, tail_dependence_flag="UNKNOWN",
                        known_from=str(T0))


# ---- account scaling potential ----------------------------------------------

def test_exceptional_unproven_requires_all_evidence():
    status = classify_scaling_status(tail_payoff_multiple=None, liquidity_capacity=1000.0,
                                     spread_capacity=1000.0, contract_capacity=500,
                                     concentration_risk=0.1)
    assert status == "LOW"


def test_exceptional_unproven_reachable_with_full_evidence():
    status = classify_scaling_status(tail_payoff_multiple=6.0, liquidity_capacity=1000.0,
                                     spread_capacity=1000.0, contract_capacity=500,
                                     concentration_risk=0.1)
    assert status == "EXCEPTIONAL_UNPROVEN"


def test_scaling_build_never_carries_bad_status(tmp_path):
    with pytest.raises(ScalingPotentialError):
        from apex.options_research.scaling_potential import AccountScalingPotential
        AccountScalingPotential(subject="AAPL", expression_type="LONG_CALL",
                                risk_unit_required=None, capital_required=None,
                                maximum_loss=None, expected_payoff_multiple=None,
                                tail_payoff_multiple=None, liquidity_capacity=None,
                                spread_capacity=None, contract_capacity=None,
                                position_scalability="NO_SUPPORT", concentration_risk=None,
                                correlation_with_existing_risk=None,
                                scaling_status="MADE_UP", known_from=str(T0))


def test_scaling_build_end_to_end():
    scaling = build_scaling(subject="AAPL", expression_type="LONG_CALL", known_from=T0,
                            tail_payoff_multiple=1.0, liquidity_capacity=500.0,
                            spread_capacity=500.0, contract_capacity=200,
                            concentration_risk=0.2)
    assert scaling.scaling_status == "MODERATE"


# ---- evidence-earned aggression ladder -------------------------------------

def test_zero_evidence_is_unproven():
    assert classify_edge_maturity(resolved_outcome_count=0, positive_expectancy_streak=0) == "UNPROVEN"


def test_hundred_resolved_with_streak_is_scalable():
    assert classify_edge_maturity(resolved_outcome_count=150, positive_expectancy_streak=5) == "SCALABLE_EDGE"


def test_edge_maturity_verdict_never_carries_sizing_authority():
    verdict = build_edge_maturity(mechanism_id="OPT-001-DIRECTIONAL-CONVEXITY",
                                  resolved_outcome_count=5, positive_expectancy_streak=1,
                                  known_from=T0)
    assert verdict.sizing_authority == "NONE"
    assert verdict.rung == "OBSERVATIONAL"


# ---- growth research panel ---------------------------------------------------

def test_growth_panel_covers_all_six_risk_tiers():
    scenarios = simulate_growth_panel(r_multiples=(), known_from=T0)
    assert len(scenarios) == 6
    assert all(s.sample_size == 0 for s in scenarios)
    assert all(s.sizing_authority == "NONE" for s in scenarios)


def test_growth_panel_with_real_sample_computes_real_stats():
    r_multiples = (2.0, -1.0, 3.0, -1.0, -1.0, 1.0, -1.0, 4.0, -1.0, -1.0)
    scenarios = simulate_growth_panel(r_multiples=r_multiples, known_from=T0,
                                      n_bootstrap=100)
    assert len(scenarios) == 6
    for s in scenarios:
        assert s.sample_size == 10
        assert s.n_bootstrap_paths == 100
        assert s.geometric_growth_rate_per_trade is not None
        assert 0.0 <= s.risk_of_ruin <= 1.0


def test_growth_panel_higher_risk_tier_shows_more_ruin_risk():
    r_multiples = (-1.0,) * 8 + (5.0, 5.0)
    scenarios = simulate_growth_panel(r_multiples=r_multiples, known_from=T0,
                                      n_bootstrap=200)
    low_risk = [s for s in scenarios if s.risk_pct == 0.25][0]
    high_risk = [s for s in scenarios if s.risk_pct == 2.00][0]
    assert high_risk.risk_of_ruin >= low_risk.risk_of_ruin


def test_growth_scenario_wrong_label_refused():
    with pytest.raises(GrowthPanelError):
        from apex.options_research.growth_panel import GrowthScenario
        GrowthScenario(risk_pct=1.0, sample_size=0, n_bootstrap_paths=0,
                      geometric_growth_rate_per_trade=None, maximum_drawdown=None,
                      expected_shortfall=None, risk_of_10pct_drawdown=None,
                      risk_of_20pct_drawdown=None, risk_of_30pct_drawdown=None,
                      risk_of_ruin=None, loss_streak_behavior=None,
                      time_to_recovery_trades=None, capital_utilization=1.0,
                      label="WRONG_LABEL", sizing_authority="NONE", known_from=str(T0))


# ---- rare opportunity classification -----------------------------------------

def test_all_eight_criteria_met_is_rare():
    verdict = classify_rare_opportunity(
        subject="AAPL", expression_type="LONG_CALL", known_from=T0,
        direction_quality="STRONG", transition_quality="STRONG", timing_tight=True,
        surface_advantage=True, clean_execution=True, loss_cap=200.0,
        tail_payoff_multiple=5.0, model_familiarity="FAMILIAR")
    assert verdict.verdict == "RARE_ASYMMETRIC_OPPORTUNITY"
    assert len(verdict.criteria_met) == 8


def test_one_missing_criterion_is_not_rare():
    verdict = classify_rare_opportunity(
        subject="AAPL", expression_type="LONG_CALL", known_from=T0,
        direction_quality="STRONG", transition_quality="STRONG", timing_tight=True,
        surface_advantage=True, clean_execution=True, loss_cap=200.0,
        tail_payoff_multiple=1.0,   # below the LARGE_PAYOFF_ASYMMETRY bar
        model_familiarity="FAMILIAR")
    assert verdict.verdict == "NOT_RARE"
    assert "LARGE_PAYOFF_ASYMMETRY" in verdict.criteria_failed


def test_missing_evidence_fails_the_criterion_not_defaults_to_pass():
    verdict = classify_rare_opportunity(
        subject="AAPL", expression_type="LONG_CALL", known_from=T0,
        direction_quality="STRONG", transition_quality="STRONG", timing_tight=None,
        surface_advantage=True, clean_execution=True, loss_cap=200.0,
        tail_payoff_multiple=5.0, model_familiarity="FAMILIAR")
    assert verdict.verdict == "NOT_RARE"
    assert "TIGHT_TIMING" in verdict.criteria_failed


def test_rare_verdict_carries_no_sizing_authority():
    verdict = classify_rare_opportunity(
        subject="AAPL", expression_type="LONG_CALL", known_from=T0,
        direction_quality="STRONG", transition_quality="STRONG", timing_tight=True,
        surface_advantage=True, clean_execution=True, loss_cap=200.0,
        tail_payoff_multiple=5.0, model_familiarity="FAMILIAR")
    assert verdict.sizing_authority == "NONE"
