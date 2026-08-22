"""Live input-quality gate: model correctness is necessary, but market-
input correctness dominates. Unmeasured inputs impose no cap (backward
compatible with synthetic test-driven calls); measured-but-weak inputs
degrade state_quality, never a precise-looking number over a bad input.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.option_analytics.canonical_state import build_canonical_state
from apex.option_analytics.dividends import DividendSchedule
from apex.option_analytics.live_quality import (LiveQualityError,
                                                  classify_live_quality)
from apex.option_analytics.rate_curve import RiskFreeCurve

T0 = pd.Timestamp("2026-08-18T15:00:00Z")
CURVE = RiskFreeCurve(points=((0.08, 0.03), (1.0, 0.035)), source="UST_PAR_YIELD_CURVE",
                      as_of=str(T0))
NO_DIV = DividendSchedule(events=(), confirmed_no_dividends=True, source="TEST", as_of=str(T0))


def test_no_measurements_imposes_no_cap():
    q = classify_live_quality(known_from=T0)
    assert q.cap is None


def test_fresh_quote_deep_liquid_dividend_confirmed_is_high():
    q = classify_live_quality(known_from=T0, quote_age_s=1.0, underlying_age_s=1.0,
                              rate_source_age_days=1.0, bid_size=50, ask_size=50,
                              dividend_confidence="CONFIRMED_NONE")
    assert q.cap == "HIGH"


def test_stale_quote_caps_low():
    q = classify_live_quality(known_from=T0, quote_age_s=120.0)
    assert q.cap == "LOW"


def test_thin_depth_caps_low():
    q = classify_live_quality(known_from=T0, bid_size=0, ask_size=0)
    assert q.cap == "LOW"


def test_unknown_dividend_confidence_caps_low():
    q = classify_live_quality(known_from=T0, quote_age_s=1.0, dividend_confidence="UNKNOWN")
    assert q.cap == "LOW"


def test_moderate_staleness_caps_moderate_not_low():
    # isolate quote staleness: every other category held at its best
    # score so only quote_age_s's MODERATE tier drives the result.
    q = classify_live_quality(known_from=T0, quote_age_s=15.0, underlying_age_s=1.0,
                              rate_source_age_days=1.0, bid_size=50, ask_size=50,
                              dividend_confidence="CONFIRMED_NONE")
    assert q.cap == "MODERATE"


def test_unknown_dividend_confidence_value_refused():
    with pytest.raises(LiveQualityError):
        from apex.option_analytics.live_quality import LiveQuoteQuality
        LiveQuoteQuality(quote_age_s=None, underlying_age_s=None,
                         rate_source_age_days=None, bid_size=None, ask_size=None,
                         dividend_confidence="MADE_UP", cap=None, known_from=str(T0))


# ---- wiring into canonical_state.py -----------------------------------------

def _build(**overrides):
    kwargs = dict(symbol="AAPL260919C00230000", option_type="call", spot=230.0,
                  strike=230.0, expiry_date="2026-09-19", bid=8.5, ask=8.9,
                  last_trade=8.7, quote_is_current=True, curve=CURVE,
                  dividend_schedule=NO_DIV, known_from=T0, now=T0)
    kwargs.update(overrides)
    return build_canonical_state(**kwargs)


def test_unmeasured_live_quality_does_not_degrade_existing_behavior():
    state = _build()
    assert state.state_quality in ("HIGH", "MODERATE")
    assert state.live_quality["cap"] is None


def test_stale_live_quote_degrades_state_quality_to_low():
    state = _build(quote_age_s=300.0, underlying_age_s=1.0, rate_source_age_days=1.0,
                   bid_size=50, ask_size=50, dividend_confidence="CONFIRMED_NONE")
    assert state.state_quality == "LOW"
    assert state.live_quality["cap"] == "LOW"


def test_good_live_inputs_permit_high_quality():
    state = _build(quote_age_s=1.0, underlying_age_s=1.0, rate_source_age_days=1.0,
                   bid_size=50, ask_size=50, dividend_confidence="CONFIRMED_NONE")
    assert state.live_quality["cap"] == "HIGH"
    assert state.state_quality in ("HIGH", "MODERATE")
