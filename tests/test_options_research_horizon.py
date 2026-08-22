"""Horizon matching law — DTE_REQUIRED > realization + timing + buffer;
0DTE structurally refused regardless of the math.
"""
from __future__ import annotations

from apex.options_research.horizon import dte_bucket, horizon_eligible


def test_dte_bucket_boundaries():
    assert dte_bucket(0) == "0DTE"
    assert dte_bucket(1) == "1_2_DTE"
    assert dte_bucket(2) == "1_2_DTE"
    assert dte_bucket(3) == "3_7_DTE"
    assert dte_bucket(7) == "3_7_DTE"
    assert dte_bucket(8) == "8_30_DTE"
    assert dte_bucket(30) == "8_30_DTE"
    assert dte_bucket(31) == "OVER_30_DTE"


def test_0dte_always_refused_regardless_of_math():
    r = horizon_eligible(dte=0, expected_realization_minutes=1,
                         timing_uncertainty_minutes=1)
    assert r["eligible"] is False
    assert r["bucket"] == "0DTE"
    assert "NOT_ACTIVE_V1" in r["reason"]


def test_unknown_realization_estimate_is_not_eligible():
    r = horizon_eligible(dte=5, expected_realization_minutes=None,
                         timing_uncertainty_minutes=30)
    assert r["eligible"] is False
    assert "UNKNOWN" in r["reason"]


def test_sufficient_dte_is_eligible():
    r = horizon_eligible(dte=7, expected_realization_minutes=60,
                         timing_uncertainty_minutes=30)
    assert r["eligible"] is True
    assert r["bucket"] == "3_7_DTE"


def test_insufficient_dte_is_refused():
    r = horizon_eligible(dte=1, expected_realization_minutes=60 * 20,
                         timing_uncertainty_minutes=60 * 10)
    assert r["eligible"] is False
    assert r["reason"] == "REFUSE_HORIZON_MISMATCH"


def test_decision_power_stamped():
    r = horizon_eligible(dte=7, expected_realization_minutes=60,
                         timing_uncertainty_minutes=30)
    assert r["decision_power"] == "NONE_OPTIONS_RESEARCH"
