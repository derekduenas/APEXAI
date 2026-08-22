"""Supporting contracts: no-arbitrage gates, risk-free rate curve,
dividend schedule, exact time-to-expiry, model disagreement
classification, and the IV_BID/MID/ASK triple.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.option_analytics.dividends import (DividendSchedule,
                                              DividendScheduleError,
                                              pv_of_dividends)
from apex.option_analytics.iv_triple import IVTripleError, solve_iv_triple
from apex.option_analytics.model_disagreement import (build_range,
                                                        classify_disagreement)
from apex.option_analytics.no_arbitrage import (NoArbitrageError,
                                                 check_price_sanity)
from apex.option_analytics.rate_curve import (RateCurveError, RiskFreeCurve,
                                               rate_for_tenor)
from apex.option_analytics.time_to_expiry import (TimeToExpiryError,
                                                   year_fraction)

T0 = pd.Timestamp("2026-08-18T15:00:00Z")


# ---- no-arbitrage -----------------------------------------------------------

def test_valid_quote_passes():
    v = check_price_sanity(option_type="call", spot=100.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=7.5, ask=7.7,
                           known_from=T0)
    assert v.passed is True
    assert v.violations == ()


def test_locked_crossed_market_detected():
    v = check_price_sanity(option_type="call", spot=100.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=8.0, ask=7.5,
                           known_from=T0)
    assert v.passed is False
    assert "LOCKED_CROSSED_MARKET" in v.violations


def test_below_intrinsic_detected():
    v = check_price_sanity(option_type="call", spot=150.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=1.0, ask=2.0,
                           known_from=T0)
    assert "BELOW_INTRINSIC" in v.violations


def test_above_upper_bound_detected():
    v = check_price_sanity(option_type="call", spot=100.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=150.0, ask=160.0,
                           known_from=T0)
    assert "ABOVE_UPPER_BOUND" in v.violations


def test_negative_price_detected():
    v = check_price_sanity(option_type="put", spot=100.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=-1.0, ask=2.0,
                           known_from=T0)
    assert "NEGATIVE_PRICE" in v.violations


def test_unknown_option_type_refused():
    with pytest.raises(NoArbitrageError):
        check_price_sanity(option_type="collar", spot=100.0, strike=100.0,
                           time_to_expiry_years=0.5, rate=0.03, bid=1.0, ask=2.0,
                           known_from=T0)


# ---- rate curve -----------------------------------------------------------

def test_curve_interpolates_between_points():
    curve = RiskFreeCurve(points=((0.25, 0.02), (1.0, 0.04)), source="UST", as_of=str(T0))
    r = rate_for_tenor(curve, 0.625)
    assert r == pytest.approx(0.03, abs=1e-9)


def test_no_curve_returns_none():
    assert rate_for_tenor(None, 0.5) is None


def test_tenor_outside_range_returns_none():
    curve = RiskFreeCurve(points=((0.25, 0.02), (1.0, 0.04)), source="UST", as_of=str(T0))
    assert rate_for_tenor(curve, 5.0) is None


def test_assumed_source_refused():
    with pytest.raises(RateCurveError):
        RiskFreeCurve(points=((0.5, 0.03),), source="ASSUMED", as_of=str(T0))


def test_unsorted_points_refused():
    with pytest.raises(RateCurveError):
        RiskFreeCurve(points=((1.0, 0.04), (0.25, 0.02)), source="UST", as_of=str(T0))


# ---- dividends --------------------------------------------------------------

def test_confirmed_no_dividends_with_events_refused():
    with pytest.raises(DividendScheduleError):
        DividendSchedule(events=(("2026-09-01", 0.5),), confirmed_no_dividends=True,
                         source="TEST", as_of=str(T0))


def test_unconfirmed_empty_schedule_refused():
    with pytest.raises(DividendScheduleError):
        DividendSchedule(events=(), confirmed_no_dividends=False,
                         source="TEST", as_of=str(T0))


def test_pv_of_dividends_zero_when_confirmed_none():
    sched = DividendSchedule(events=(), confirmed_no_dividends=True, source="TEST",
                             as_of=str(T0))
    pv = pv_of_dividends(sched, now=T0, expiry="2026-09-19", rate=0.03)
    assert pv == 0.0


def test_pv_of_dividends_none_when_schedule_is_none():
    assert pv_of_dividends(None, now=T0, expiry="2026-09-19", rate=0.03) is None


def test_pv_of_dividends_real_computation():
    sched = DividendSchedule(events=(("2026-09-01", 1.0),), confirmed_no_dividends=False,
                             source="TEST", as_of=str(T0))
    pv = pv_of_dividends(sched, now=T0, expiry="2026-09-19", rate=0.03)
    assert 0.98 < pv < 1.0


def test_dividend_after_expiry_excluded():
    sched = DividendSchedule(events=(("2026-12-01", 1.0),), confirmed_no_dividends=False,
                             source="TEST", as_of=str(T0))
    pv = pv_of_dividends(sched, now=T0, expiry="2026-09-19", rate=0.03)
    assert pv == 0.0


# ---- time to expiry ----------------------------------------------------------

def test_year_fraction_is_fractional_not_integer_dte():
    yf = year_fraction(T0, "2026-08-19")
    assert 0 < yf < 1.0 / 365.0 * 2   # about half a day away from expiry close


def test_already_expired_refused():
    with pytest.raises(TimeToExpiryError):
        year_fraction(T0, "2026-08-01")


def test_one_minute_to_expiry_produces_tiny_positive_fraction():
    now = pd.Timestamp("2026-08-19T19:59:00Z")   # 1 min before 16:00 ET close
    yf = year_fraction(now, "2026-08-19")
    assert 0 < yf < (2.0 / (365.0 * 24 * 60))


# ---- model disagreement -----------------------------------------------------

def test_low_disagreement_classified_correctly():
    assert classify_disagreement(0.60, 0.61) == "LOW"


def test_high_disagreement_classified_correctly():
    assert classify_disagreement(0.20, 0.50) == "HIGH"


def test_unknown_when_either_value_missing():
    assert classify_disagreement(None, 0.5) == "UNKNOWN"
    assert classify_disagreement(0.5, None) == "UNKNOWN"


def test_canonical_value_averages_both_models():
    r = build_range("delta", bsm_value=0.60, american_value=0.62)
    assert r.canonical_value() == pytest.approx(0.61)


def test_tiny_gamma_disagreement_not_manufactured_high_from_noise():
    r = build_range("gamma", bsm_value=1e-7, american_value=3e-7)
    assert r.disagreement_level in ("LOW", "MODERATE")   # absolute floor prevents false HIGH


# ---- IV triple ---------------------------------------------------------------

def test_stale_trade_only_refused():
    with pytest.raises(IVTripleError):
        solve_iv_triple(option_type="call", bid=None, ask=None, last_trade=7.5,
                        quote_is_current=False, spot=100.0, strike=100.0,
                        time_to_expiry_years=0.5, rate=0.03)


def test_no_quote_at_all_returns_unknown_not_error():
    triple = solve_iv_triple(option_type="call", bid=None, ask=None, last_trade=None,
                             quote_is_current=False, spot=100.0, strike=100.0,
                             time_to_expiry_years=0.5, rate=0.03)
    assert triple.quality == "UNKNOWN"
    assert triple.iv_mid is None


def test_tight_spread_is_high_quality():
    triple = solve_iv_triple(option_type="call", bid=7.5, ask=7.55, last_trade=7.52,
                             quote_is_current=True, spot=100.0, strike=100.0,
                             time_to_expiry_years=0.5, rate=0.03)
    assert triple.quality == "HIGH"
    assert triple.iv_bid < triple.iv_mid < triple.iv_ask


def test_wide_spread_is_low_quality():
    triple = solve_iv_triple(option_type="call", bid=5.0, ask=10.0, last_trade=7.0,
                             quote_is_current=True, spot=100.0, strike=100.0,
                             time_to_expiry_years=0.5, rate=0.03)
    assert triple.quality == "LOW"


def test_used_stale_trade_flag_is_always_false_from_solver():
    triple = solve_iv_triple(option_type="call", bid=7.5, ask=7.7, last_trade=None,
                             quote_is_current=True, spot=100.0, strike=100.0,
                             time_to_expiry_years=0.5, rate=0.03)
    assert triple.used_stale_trade is False
