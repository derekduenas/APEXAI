"""American binomial: CRR tree pricing + finite-difference Greeks,
cross-validated against BSM in the no-dividend equivalence case (where
theory says American call == European call, and disagreement should be
small), and checked for the correct DIRECTIONAL early-exercise premium
on puts (where real disagreement with BSM is expected, not a bug).

Tolerances here reflect measured CRR numerical precision (see the
american_binomial.py module docstring) -- not aspirational exactness.
"""
from __future__ import annotations

import pytest

from apex.option_analytics import bsm
from apex.option_analytics.american_binomial import (AmericanBinomialError,
                                                       american_greeks,
                                                       crr_price)

BASE = dict(spot=100.0, strike=100.0, time_to_expiry_years=0.5, rate=0.03, sigma=0.25)


def test_american_call_converges_to_bsm_in_no_dividend_limit():
    bsm_call = bsm.price(option_type="call", **BASE)
    am_call = crr_price(option_type="call", n_steps=300, **BASE)
    assert am_call == pytest.approx(bsm_call, rel=0.01)


def test_american_put_never_below_european_binomial_put():
    euro_put = crr_price(option_type="put", n_steps=300, american=False, **BASE)
    am_put = crr_price(option_type="put", n_steps=300, american=True, **BASE)
    assert am_put >= euro_put - 1e-9


def test_deep_itm_put_has_meaningful_early_exercise_premium():
    deep_itm = {**BASE, "strike": 150.0}
    euro_put = crr_price(option_type="put", n_steps=300, american=False, **deep_itm)
    am_put = crr_price(option_type="put", n_steps=300, american=True, **deep_itm)
    assert am_put > euro_put + 0.01


def test_unknown_option_type_refused():
    with pytest.raises(AmericanBinomialError):
        crr_price(option_type="collar", n_steps=100, **BASE)


def test_nonpositive_n_steps_refused():
    with pytest.raises(AmericanBinomialError):
        crr_price(option_type="call", n_steps=0, **BASE)


def test_call_delta_close_to_bsm_no_dividend():
    bsm_g = bsm.greeks(option_type="call", **BASE)
    am_g = american_greeks(option_type="call", n_steps=300, **BASE)
    assert am_g.delta == pytest.approx(bsm_g.delta, abs=0.05)


def test_call_gamma_close_to_bsm_no_dividend():
    bsm_g = bsm.greeks(option_type="call", **BASE)
    am_g = american_greeks(option_type="call", n_steps=300, **BASE)
    assert am_g.gamma == pytest.approx(bsm_g.gamma, abs=0.01)


def test_call_vega_close_to_bsm_no_dividend():
    bsm_g = bsm.greeks(option_type="call", **BASE)
    am_g = american_greeks(option_type="call", n_steps=300, **BASE)
    assert am_g.vega == pytest.approx(bsm_g.vega, rel=0.10)


def test_call_theta_same_sign_as_bsm():
    """The classic sign bug this suite exists to catch: a flipped
    calendar-time-vs-time-to-expiry derivative would put theta on the
    wrong side of zero relative to BSM for an ordinary long call."""
    bsm_g = bsm.greeks(option_type="call", **BASE)
    am_g = american_greeks(option_type="call", n_steps=300, **BASE)
    assert (bsm_g.theta < 0) == (am_g.theta < 0)


def test_greeks_all_five_fields_present():
    g = american_greeks(option_type="put", n_steps=200, **BASE)
    for field in ("delta", "gamma", "theta", "vega", "rho"):
        assert getattr(g, field) is not None
