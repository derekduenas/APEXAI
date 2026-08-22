"""Black-Scholes-Merton: analytic pricing, Greeks, and IV solving."""
from __future__ import annotations

import math

import pytest

from apex.option_analytics.bsm import (BSMError, greeks,
                                       implied_volatility, price)

BASE = dict(spot=100.0, strike=100.0, time_to_expiry_years=0.5, rate=0.03, sigma=0.25)


def test_call_price_positive_and_bounded_by_spot():
    p = price(option_type="call", **BASE)
    assert 0 < p < BASE["spot"]


def test_put_call_parity():
    c = price(option_type="call", **BASE)
    p = price(option_type="put", **BASE)
    disc_k = BASE["strike"] * math.exp(-BASE["rate"] * BASE["time_to_expiry_years"])
    assert c - p == pytest.approx(BASE["spot"] - disc_k, abs=1e-9)


def test_unknown_option_type_refused():
    with pytest.raises(BSMError):
        price(option_type="straddle", **BASE)


def test_nonpositive_sigma_refused():
    with pytest.raises(BSMError):
        price(option_type="call", **{**BASE, "sigma": 0.0})


def test_nonpositive_time_refused():
    with pytest.raises(BSMError):
        price(option_type="call", **{**BASE, "time_to_expiry_years": 0.0})


def test_call_delta_bounded_zero_one():
    g = greeks(option_type="call", **BASE)
    assert 0.0 <= g.delta <= 1.0


def test_put_delta_bounded_neg_one_zero():
    g = greeks(option_type="put", **BASE)
    assert -1.0 <= g.delta <= 0.0


def test_gamma_nonnegative():
    for opt_type in ("call", "put"):
        g = greeks(option_type=opt_type, **BASE)
        assert g.gamma >= 0


def test_vega_positive():
    for opt_type in ("call", "put"):
        g = greeks(option_type=opt_type, **BASE)
        assert g.vega > 0


def test_price_monotonic_in_spot_for_call():
    p_low = price(option_type="call", **{**BASE, "spot": 90.0})
    p_high = price(option_type="call", **{**BASE, "spot": 110.0})
    assert p_high > p_low


def test_price_monotonic_decreasing_in_spot_for_put():
    p_low = price(option_type="put", **{**BASE, "spot": 90.0})
    p_high = price(option_type="put", **{**BASE, "spot": 110.0})
    assert p_high < p_low


def test_price_monotonic_in_vol():
    p_low_vol = price(option_type="call", **{**BASE, "sigma": 0.10})
    p_high_vol = price(option_type="call", **{**BASE, "sigma": 0.50})
    assert p_high_vol > p_low_vol


def test_iv_round_trip_reproduces_input_sigma():
    market_price = price(option_type="call", **BASE)
    iv = implied_volatility(option_type="call", market_price=market_price,
                            spot=BASE["spot"], strike=BASE["strike"],
                            time_to_expiry_years=BASE["time_to_expiry_years"],
                            rate=BASE["rate"])
    assert iv == pytest.approx(BASE["sigma"], abs=1e-6)


def test_iv_round_trip_reprices_within_tolerance():
    market_price = price(option_type="put", **BASE)
    iv = implied_volatility(option_type="put", market_price=market_price,
                            spot=BASE["spot"], strike=BASE["strike"],
                            time_to_expiry_years=BASE["time_to_expiry_years"],
                            rate=BASE["rate"])
    repriced = price(option_type="put", **{**BASE, "sigma": iv})
    assert repriced == pytest.approx(market_price, abs=1e-6)


def test_iv_unreachable_price_returns_none_not_fabricated():
    # a price above the achievable max (deep in the money beyond spot bound)
    iv = implied_volatility(option_type="call", market_price=1000.0,
                            spot=BASE["spot"], strike=BASE["strike"],
                            time_to_expiry_years=BASE["time_to_expiry_years"],
                            rate=BASE["rate"])
    assert iv is None


def test_iv_unknown_option_type_refused():
    with pytest.raises(BSMError):
        implied_volatility(option_type="strangle", market_price=5.0, spot=100.0,
                           strike=100.0, time_to_expiry_years=0.5, rate=0.03)
