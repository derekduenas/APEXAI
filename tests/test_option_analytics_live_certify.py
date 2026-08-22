"""option_analytics_live_certify_v1.py -- pure analysis-function checks
against synthetic (clearly-labeled, in-memory only) state records, so
the certification script's own arithmetic is verified before it's
trusted against the real live ledger.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest

import option_analytics_live_certify_v1 as cert


def _state(**overrides):
    base = {
        "symbol": "AAPL260919C00230000", "option_type": "call", "spot": 230.0,
        "strike": 230.0, "time_to_expiry_years": 0.1, "rate": 0.04, "dividend_pv": 0.0,
        "state_quality": "HIGH", "refusal_reason": None, "short_dated": False,
        "as_of": "2026-08-18 15:00:00+00:00",
        "iv": {"iv_bid": 0.24, "iv_mid": 0.25, "iv_ask": 0.26, "quality": "HIGH"},
        "delta": {"bsm_value": 0.5, "american_value": 0.51, "disagreement_level": "LOW"},
        "gamma": {"bsm_value": 0.02, "american_value": 0.021, "disagreement_level": "LOW"},
        "theta": {"bsm_value": -8.0, "american_value": -8.1, "disagreement_level": "LOW"},
        "vega": {"bsm_value": 27.0, "american_value": 27.5, "disagreement_level": "LOW"},
        "rho": {"bsm_value": 10.0, "american_value": 10.1, "disagreement_level": "LOW"},
        "vendor_iv": None, "vendor_delta": None, "vendor_gamma": None,
        "vendor_theta": None, "vendor_vega": None, "vendor_rho": None,
        "market_bid": 8.4, "market_ask": 8.6, "market_mid": 8.5,
    }
    base.update(overrides)
    return base


def test_iv_round_trip_computes_real_error():
    import apex.option_analytics.bsm as bsm_mod
    s = _state()
    market_mid = bsm_mod.price(option_type="call", spot=230.0, strike=230.0,
                               time_to_expiry_years=0.1, rate=0.04, sigma=0.25)
    s["market_mid"] = market_mid
    result = cert.iv_round_trip_errors([s])
    assert result["n_round_trips_computed"] == 1
    assert result["mean_abs_round_trip_error"] == pytest.approx(0.0, abs=1e-9)


def test_iv_round_trip_skips_refused_states():
    s = _state(state_quality="REFUSED")
    result = cert.iv_round_trip_errors([s])
    assert result["n_round_trips_computed"] == 0


def test_iv_round_trip_counts_missing_market_mid():
    s = _state(market_mid=None)
    result = cert.iv_round_trip_errors([s])
    assert result["n_missing_market_mid_on_record"] == 1
    assert result["n_round_trips_computed"] == 0


def test_vendor_disagreement_stats_with_real_vendor_data():
    s = _state(vendor_delta=0.49, vendor_iv=0.245)
    result = cert.vendor_disagreement_stats([s])
    assert result["contracts_with_vendor_greeks"] == 1
    assert result["mean_abs_delta_disagreement_vendor_vs_bsm"] == pytest.approx(0.01)
    assert result["mean_abs_iv_disagreement_vendor_vs_apex"] == pytest.approx(0.005)


def test_vendor_disagreement_stats_none_when_no_vendor_data():
    s = _state()
    result = cert.vendor_disagreement_stats([s])
    assert result["contracts_with_vendor_greeks"] == 0
    assert result["mean_abs_delta_disagreement_vendor_vs_bsm"] is None


def test_bsm_vs_american_disagreement_distribution_counts_levels():
    states = [_state(), _state(delta={"bsm_value": 0.5, "american_value": 0.7,
                                      "disagreement_level": "HIGH"})]
    result = cert.bsm_vs_american_disagreement_stats(states)
    assert result["delta_LOW"] == 1
    assert result["delta_HIGH"] == 1


def test_stability_across_snapshots_measures_drift():
    s1 = _state(as_of="2026-08-18 15:00:00+00:00",
               iv={"iv_bid": 0.24, "iv_mid": 0.25, "iv_ask": 0.26, "quality": "HIGH"})
    s2 = _state(as_of="2026-08-18 15:01:00+00:00",
               iv={"iv_bid": 0.25, "iv_mid": 0.27, "iv_ask": 0.28, "quality": "HIGH"})
    result = cert.stability_across_snapshots([s1, s2])
    assert result["n_consecutive_pairs"] == 1
    assert result["mean_abs_iv_mid_drift_between_consecutive_cycles"] == pytest.approx(0.02)


def test_stability_ignores_single_observation_contracts():
    s1 = _state()
    result = cert.stability_across_snapshots([s1])
    assert result["n_consecutive_pairs"] == 0


def test_dividend_gate_stats_categorizes_correctly():
    refused = _state(state_quality="REFUSED",
                     refusal_reason="NO_DIVIDEND_SCHEDULE_SUPPLIED")
    real_div = _state(dividend_pv=1.5)
    confirmed_none = _state(dividend_pv=0.0)
    result = cert.dividend_gate_stats([refused, real_div, confirmed_none])
    assert result["refused_no_dividend_schedule"] == 1
    assert result["priced_with_real_dividend_pv"] == 1
    assert result["priced_confirmed_no_dividend"] == 1


def test_latency_stats_computes_mean_and_max():
    cycles = [{"symbols": {"AAPL": {"fetch_latency_s": 1.0},
                          "SPY": {"fetch_latency_s": 3.0}}}]
    result = cert.latency_stats(cycles)
    assert result["n_symbol_cycles"] == 2
    assert result["mean_fetch_plus_compute_latency_s"] == pytest.approx(2.0)
    assert result["max_fetch_plus_compute_latency_s"] == pytest.approx(3.0)
