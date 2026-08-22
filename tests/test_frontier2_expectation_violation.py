"""ExpectationViolationState — F2. Proves the honesty law: only
pre-registered deterministic relationships are ever evaluated, three of
the five stay structurally NO_EXPECTATION_MODEL until real inputs exist,
and residual is always observed-minus-expected arithmetic, never a
fitted quantity.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.expectation_violation import (
    UNSUPPORTED_RELATIONSHIPS, ExpectationViolationError, evaluate,
    evaluate_buy_pressure_declining_response,
    evaluate_index_move_high_beta_refusal)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_unknown_relationship_type_refused():
    with pytest.raises(ExpectationViolationError):
        evaluate("NOT_A_REAL_RELATIONSHIP", "AAPL", event_time=T0,
                known_from=T0, now=T0)


@pytest.mark.parametrize("rel", UNSUPPORTED_RELATIONSHIPS)
def test_unsupported_relationships_always_no_expectation_model(rel):
    """Even with perfectly good-looking numbers supplied, an
    unsupported relationship type must never produce a real verdict."""
    st = evaluate(rel, "AAPL", event_time=T0, known_from=T0, now=T0,
                  expected_response=0.0, observed_response=0.05)
    assert st.state == "NO_EXPECTATION_MODEL"
    assert st.coverage == UNSUPPORTED_RELATIONSHIPS[rel]


def test_missing_context_on_a_supported_relationship_is_insufficient_context():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0)
    assert st.state == "INSUFFICIENT_CONTEXT"


def test_residual_is_observed_minus_expected_arithmetic():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0, expected_response=0.01,
                  observed_response=-0.02)
    assert st.residual == pytest.approx(-0.03)
    assert st.residual_direction == "NEGATIVE"
    assert st.state == "OBSERVABLE_VIOLATION"


def test_tiny_residual_is_no_violation_not_a_false_alarm():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0, expected_response=0.01,
                  observed_response=0.0101)
    assert st.residual_direction == "NONE"
    assert st.state == "NO_VIOLATION"


def test_single_observation_is_never_persistent():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0, expected_response=0.0,
                  observed_response=0.05)
    assert st.persistence == "SINGLE_OBSERVATION"


def test_two_matching_priors_makes_it_persistent():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0, expected_response=0.0,
                  observed_response=0.05,
                  residual_history=("POSITIVE", "POSITIVE"))
    assert st.persistence == "PERSISTENT"


def test_flip_flopping_history_is_transient_not_persistent():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL", event_time=T0,
                  known_from=T0, now=T0, expected_response=0.0,
                  observed_response=0.05,
                  residual_history=("NEGATIVE", "POSITIVE"))
    assert st.persistence == "TRANSIENT"


# ---- concrete relationship evaluators ------------------------------------

def test_index_move_high_beta_refusal_uses_excess_market_as_residual():
    st = evaluate_index_move_high_beta_refusal(
        "TSLA", market_day_return=0.02, symbol_day_return=-0.01,
        excess_market_60m=-0.03, event_time=T0, known_from=T0, now=T0)
    assert st.residual == -0.03
    assert st.state == "OBSERVABLE_VIOLATION"
    assert "excess_market_60m" in st.support


def test_index_move_high_beta_refusal_missing_excess_is_insufficient_context():
    st = evaluate_index_move_high_beta_refusal(
        "TSLA", market_day_return=0.02, symbol_day_return=-0.01,
        excess_market_60m=None, event_time=T0, known_from=T0, now=T0)
    assert st.state == "INSUFFICIENT_CONTEXT"


def test_buy_pressure_declining_response_requires_elevated_rvol():
    """Not-elevated rvol means there was never a real expectation to
    violate -- must not fabricate one."""
    st = evaluate_buy_pressure_declining_response(
        "AAPL", rvol_tod=1.2, trend_slope=-0.5, event_time=T0,
        known_from=T0, now=T0)
    assert st.state == "INSUFFICIENT_CONTEXT"


def test_buy_pressure_declining_response_fires_on_elevated_rvol_negative_slope():
    st = evaluate_buy_pressure_declining_response(
        "AAPL", rvol_tod=3.0, trend_slope=-0.02, event_time=T0,
        known_from=T0, now=T0)
    assert st.state == "OBSERVABLE_VIOLATION"
    assert st.residual_direction == "NEGATIVE"


def test_buy_pressure_elevated_and_rising_is_no_violation():
    st = evaluate_buy_pressure_declining_response(
        "AAPL", rvol_tod=3.0, trend_slope=0.05, event_time=T0,
        known_from=T0, now=T0)
    assert st.state == "NO_VIOLATION"


def test_missing_rvol_is_unknown_not_a_crash():
    st = evaluate_buy_pressure_declining_response(
        "AAPL", rvol_tod=None, trend_slope=0.05, event_time=T0,
        known_from=T0, now=T0)
    assert st.state in ("NO_EXPECTATION_MODEL", "INSUFFICIENT_CONTEXT",
                        "UNKNOWN")


# ---- contract + determinism + persistence --------------------------------

def test_freshness_computed_from_event_time_not_wall_clock():
    st = evaluate("INDEX_MOVE_HIGH_BETA_REFUSAL", "AAPL",
                  event_time=T0, known_from=T0,
                  now=T0 + pd.Timedelta(minutes=5), expected_response=0.0,
                  observed_response=0.01)
    assert st.freshness_s == 300.0


def test_determinism_same_inputs_twice_byte_identical():
    a = evaluate_index_move_high_beta_refusal(
        "TSLA", market_day_return=0.02, symbol_day_return=-0.01,
        excess_market_60m=-0.03, event_time=T0, known_from=T0, now=T0)
    b = evaluate_index_move_high_beta_refusal(
        "TSLA", market_day_return=0.02, symbol_day_return=-0.01,
        excess_market_60m=-0.03, event_time=T0, known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.expectation_violation as ev
    monkeypatch.setattr(ev, "LEDGER", tmp_path / "ev.jsonl")
    st = evaluate_index_move_high_beta_refusal(
        "TSLA", market_day_return=0.02, symbol_day_return=-0.01,
        excess_market_60m=-0.03, event_time=T0, known_from=T0, now=T0)
    rec1 = ev.persist(st)
    rec2 = ev.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
