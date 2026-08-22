"""Surface physics: cross-sectional skew/smile/term-structure/forward-
variance/implied-move (real from a single snapshot) and time-derivative
fields (honestly None without real history, never estimated from one
point in time).
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.option_analytics.surface_physics import (SurfacePhysicsError,
                                                     build_cross_sectional,
                                                     compute_time_derivatives)

T0 = pd.Timestamp("2026-08-18T15:00:00Z")


def test_no_strikes_gives_none_skew_and_smile():
    snap = build_cross_sectional("AAPL", known_from=T0)
    assert snap.local_skew_slope is None
    assert snap.smile_curvature is None


def test_skew_slope_from_two_strikes():
    pairs = ((-0.1, 0.35), (0.1, 0.25))   # downside skew: lower strike, higher IV
    snap = build_cross_sectional("AAPL", known_from=T0, strike_log_moneyness_iv=pairs)
    assert snap.local_skew_slope is not None
    assert snap.local_skew_slope < 0   # IV decreasing as log-moneyness increases


def test_smile_curvature_needs_at_least_three_points():
    pairs = ((-0.1, 0.35), (0.1, 0.25))
    snap = build_cross_sectional("AAPL", known_from=T0, strike_log_moneyness_iv=pairs)
    assert snap.smile_curvature is None
    pairs3 = pairs + ((0.0, 0.20),)
    snap3 = build_cross_sectional("AAPL", known_from=T0, strike_log_moneyness_iv=pairs3)
    assert snap3.smile_curvature is not None


def test_term_structure_slope_from_two_tenors():
    tenors = ((0.1, 0.20), (0.5, 0.30))
    snap = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=tenors)
    assert snap.term_structure_slope == pytest.approx((0.30 - 0.20) / (0.5 - 0.1))


def test_forward_variance_computed_between_two_tenors():
    tenors = ((0.25, 0.30), (0.5, 0.35))
    snap = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=tenors)
    t1, s1 = tenors[0]
    t2, s2 = tenors[1]
    expected = (s2 ** 2 * t2 - s1 ** 2 * t1) / (t2 - t1)
    assert snap.forward_variance == pytest.approx(expected)


def test_forward_variance_none_when_negative():
    tenors = ((0.25, 0.50), (0.5, 0.05))   # steep enough inversion to force negative fwd var
    snap = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=tenors)
    assert snap.forward_variance is None


def test_duplicate_tenors_refused():
    with pytest.raises(SurfacePhysicsError):
        build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=((0.5, 0.3), (0.5, 0.4)))


def test_implied_move_from_straddle_and_spot():
    snap = build_cross_sectional("AAPL", known_from=T0, atm_straddle_price=10.0, spot=200.0)
    assert snap.implied_move_pct == pytest.approx(0.05)


def test_implied_move_none_without_both_inputs():
    snap = build_cross_sectional("AAPL", known_from=T0, atm_straddle_price=10.0, spot=None)
    assert snap.implied_move_pct is None


def test_iv_uncertainty_averages_spreads():
    snap = build_cross_sectional("AAPL", known_from=T0, iv_bid_ask_spreads=(0.02, 0.04, 0.06))
    assert snap.iv_bid_ask_uncertainty == pytest.approx(0.04)


def test_time_derivative_fields_none_without_prior_snapshot():
    current = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=((0.25, 0.3), (0.5, 0.35)))
    result = compute_time_derivatives(subject="AAPL", known_from=T0, prior=None, current=current)
    assert result.surface_velocity is None
    assert result.skew_change is None
    assert result.term_structure_change is None


def test_surface_velocity_computed_from_real_prior_snapshot():
    prior = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=((0.25, 0.30), (0.5, 0.32)))
    current = build_cross_sectional("AAPL", known_from=T0, tenor_iv_pairs=((0.25, 0.30), (0.5, 0.40)))
    result = compute_time_derivatives(subject="AAPL", known_from=T0, prior=prior,
                                      current=current, dt_years=1.0 / 365.0)
    assert result.surface_velocity is not None
    assert result.term_structure_change is not None


def test_realized_vs_implied_gap_computed_when_realized_move_supplied():
    current = build_cross_sectional("AAPL", known_from=T0, atm_straddle_price=10.0, spot=200.0)
    result = compute_time_derivatives(subject="AAPL", known_from=T0, prior=None,
                                      current=current, realized_move_pct=0.08)
    assert result.realized_vs_implied_gap == pytest.approx(0.03)


def test_decision_power_stamped():
    snap = build_cross_sectional("AAPL", known_from=T0)
    assert snap.decision_power == "NONE_OPTION_ANALYTICS"
