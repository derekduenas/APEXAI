"""OptionAnalyticsState — end-to-end assembly of the whole pipeline,
including every named refusal path (bad expiry, no rate coverage, no
dividend schedule, price-sanity violation) and the short-dated quality
cap.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.option_analytics.canonical_state import (CanonicalStateError,
                                                     build_canonical_state)
from apex.option_analytics.dividends import DividendSchedule
from apex.option_analytics.rate_curve import RiskFreeCurve

T0 = pd.Timestamp("2026-08-18T15:00:00Z")
CURVE = RiskFreeCurve(points=((0.08, 0.03), (1.0, 0.035)), source="UST_PAR_YIELD_CURVE",
                      as_of=str(T0))
NO_DIV = DividendSchedule(events=(), confirmed_no_dividends=True, source="TEST", as_of=str(T0))


def _build(**overrides):
    kwargs = dict(symbol="AAPL260919C00230000", option_type="call", spot=230.0,
                  strike=230.0, expiry_date="2026-09-19", bid=8.5, ask=8.9,
                  last_trade=8.7, quote_is_current=True, curve=CURVE,
                  dividend_schedule=NO_DIV, known_from=T0, now=T0)
    kwargs.update(overrides)
    return build_canonical_state(**kwargs)


def test_happy_path_produces_high_quality_state():
    state = _build()
    assert state.state_quality in ("HIGH", "MODERATE")
    assert state.refusal_reason is None
    assert state.delta is not None
    assert state.iv["iv_mid"] is not None


def test_already_expired_refused_not_crashed():
    state = _build(expiry_date="2026-08-01")
    assert state.state_quality == "REFUSED"
    assert "TIME_TO_EXPIRY_ERROR" in state.refusal_reason


def test_no_rate_curve_coverage_refused():
    far_curve = RiskFreeCurve(points=((5.0, 0.04), (10.0, 0.045)), source="UST", as_of=str(T0))
    state = _build(curve=far_curve)
    assert state.state_quality == "REFUSED"
    assert state.refusal_reason == "NO_RATE_CURVE_COVERAGE_FOR_TENOR"


def test_no_curve_at_all_refused():
    state = _build(curve=None)
    assert state.state_quality == "REFUSED"


def test_no_dividend_schedule_refused():
    state = _build(dividend_schedule=None)
    assert state.state_quality == "REFUSED"
    assert state.refusal_reason == "NO_DIVIDEND_SCHEDULE_SUPPLIED"


def test_price_sanity_violation_refused():
    state = _build(bid=1000.0, ask=1001.0)   # way above upper bound for spot=230
    assert state.state_quality == "REFUSED"
    assert "PRICE_SANITY_VIOLATION" in state.refusal_reason


def test_locked_market_refused():
    state = _build(bid=9.0, ask=8.0)
    assert state.state_quality == "REFUSED"


def test_short_dated_flag_and_quality_cap():
    short_curve = RiskFreeCurve(points=((0.0001, 0.03), (1.0, 0.035)),
                                source="UST_PAR_YIELD_CURVE", as_of=str(T0))
    near = T0 + pd.Timedelta(minutes=30)
    state = _build(known_from=near, now=near, expiry_date="2026-08-18", curve=short_curve)
    assert state.refusal_reason is None
    assert state.short_dated is True
    assert state.state_quality in ("MODERATE", "LOW")


def test_missing_quote_yields_low_quality_not_refused():
    state = _build(bid=None, ask=None, last_trade=None, quote_is_current=False)
    assert state.state_quality == "LOW"
    assert state.delta is None


def test_unknown_state_quality_refused_at_construction():
    with pytest.raises(CanonicalStateError):
        from apex.option_analytics.canonical_state import OptionAnalyticsState
        OptionAnalyticsState(symbol="X", option_type="call", spot=1.0, strike=1.0,
                             expiry_date="2026-09-19", time_to_expiry_years=0.1,
                             short_dated=False, rate=0.03, dividend_pv=0.0,
                             price_sanity={}, iv=None, delta=None, gamma=None,
                             theta=None, vega=None, rho=None, state_quality="MADE_UP",
                             refusal_reason=None, known_from=str(T0), as_of=str(T0))


def test_refused_state_must_carry_reason():
    with pytest.raises(CanonicalStateError):
        from apex.option_analytics.canonical_state import OptionAnalyticsState
        OptionAnalyticsState(symbol="X", option_type="call", spot=1.0, strike=1.0,
                             expiry_date="2026-09-19", time_to_expiry_years=0.1,
                             short_dated=False, rate=None, dividend_pv=None,
                             price_sanity={}, iv=None, delta=None, gamma=None,
                             theta=None, vega=None, rho=None, state_quality="REFUSED",
                             refusal_reason=None, known_from=str(T0), as_of=str(T0))


def test_decision_power_stamped_throughout():
    state = _build()
    assert state.decision_power == "NONE_OPTION_ANALYTICS"
    assert state.delta["decision_power"] == "NONE_OPTION_ANALYTICS"
