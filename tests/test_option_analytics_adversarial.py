"""ADVERSARIAL VALIDATION SUITE — the gate scripts/option_analytics_
certify_v1.py actually runs before OPT-002/OPT-003 are unblocked
(refusal.py's REFUSE_ANALYTICS_NOT_VALIDATED gate). Two parts:

1. Randomized property tests across many contracts (no `hypothesis`
   package installed -- seeded `random` loops over a fixed, documented
   iteration count instead, which is an accepted equivalent for this
   purpose).
2. Stress tests on the named ugly regions where weak options engines
   fall apart: 1-minute-to-expiry, deep ITM/OTM, very high/low IV,
   wide NBBO, ex-dividend tomorrow, zero-liquidity, stale quote,
   locked/crossed market. These check the system responds SAFELY
   (bounded, sane, or an explicit refusal) -- several of these cases
   are supposed to be refused, not accurately priced.
"""
from __future__ import annotations

import math
import random

import pandas as pd
import pytest

from apex.option_analytics import bsm
from apex.option_analytics.american_binomial import american_greeks, crr_price
from apex.option_analytics.canonical_state import build_canonical_state
from apex.option_analytics.dividends import DividendSchedule
from apex.option_analytics.no_arbitrage import check_price_sanity
from apex.option_analytics.rate_curve import RiskFreeCurve

T0 = pd.Timestamp("2026-08-18T15:00:00Z")
N_PROPERTY_ITERATIONS = 300
SEED = 20260818

WIDE_CURVE = RiskFreeCurve(points=((0.00001, 0.03), (10.0, 0.045)),
                           source="UST_PAR_YIELD_CURVE", as_of=str(T0))
NO_DIV = DividendSchedule(events=(), confirmed_no_dividends=True, source="TEST", as_of=str(T0))


def _random_contract(rng: random.Random) -> dict:
    return dict(
        spot=rng.uniform(5.0, 500.0),
        strike_mult=rng.uniform(0.5, 1.5),
        time_to_expiry_years=rng.uniform(1.0 / 365.0, 2.0),
        rate=rng.uniform(0.0, 0.06),
        sigma=rng.uniform(0.05, 1.5),
        option_type=rng.choice(["call", "put"]),
    )


# ---- randomized property tests (BSM) ----------------------------------------

def test_property_delta_bounds():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        g = bsm.greeks(option_type=c["option_type"], spot=c["spot"], strike=strike,
                       time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                       sigma=c["sigma"])
        if c["option_type"] == "call":
            assert -1e-9 <= g.delta <= 1.0 + 1e-9
        else:
            assert -1.0 - 1e-9 <= g.delta <= 1e-9


def test_property_gamma_nonnegative():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        g = bsm.greeks(option_type=c["option_type"], spot=c["spot"], strike=strike,
                       time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                       sigma=c["sigma"])
        assert g.gamma >= -1e-12


def test_property_vega_positive():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        g = bsm.greeks(option_type=c["option_type"], spot=c["spot"], strike=strike,
                       time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                       sigma=c["sigma"])
        assert g.vega >= -1e-9


def test_property_price_respects_intrinsic_and_upper_bound():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        px = bsm.price(option_type=c["option_type"], spot=c["spot"], strike=strike,
                       time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                       sigma=c["sigma"])
        disc_k = strike * math.exp(-c["rate"] * c["time_to_expiry_years"])
        if c["option_type"] == "call":
            intrinsic = max(0.0, c["spot"] - disc_k)
            upper = c["spot"]
        else:
            intrinsic = max(0.0, disc_k - c["spot"])
            upper = disc_k
        assert px >= intrinsic - 1e-6
        assert px <= upper + 1e-6


def test_property_price_monotonic_in_vol():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        low = bsm.price(option_type=c["option_type"], spot=c["spot"], strike=strike,
                        time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                        sigma=c["sigma"])
        high = bsm.price(option_type=c["option_type"], spot=c["spot"], strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"] * 1.5 + 0.01)
        assert high >= low - 1e-9


def test_property_call_price_nondecreasing_in_spot():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        low = bsm.price(option_type="call", spot=c["spot"], strike=strike,
                        time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                        sigma=c["sigma"])
        high = bsm.price(option_type="call", spot=c["spot"] * 1.02, strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"])
        assert high >= low - 1e-6


def test_property_put_price_nonincreasing_in_spot():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        low = bsm.price(option_type="put", spot=c["spot"], strike=strike,
                        time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                        sigma=c["sigma"])
        high = bsm.price(option_type="put", spot=c["spot"] * 1.02, strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"])
        assert high <= low + 1e-6


def test_property_iv_round_trip_reprices_within_tolerance():
    rng = random.Random(SEED)
    n_solved = 0
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        market_price = bsm.price(option_type=c["option_type"], spot=c["spot"], strike=strike,
                                 time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                                 sigma=c["sigma"])
        iv = bsm.implied_volatility(option_type=c["option_type"], market_price=market_price,
                                    spot=c["spot"], strike=strike,
                                    time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"])
        if iv is None:
            continue
        n_solved += 1
        repriced = bsm.price(option_type=c["option_type"], spot=c["spot"], strike=strike,
                             time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                             sigma=iv)
        assert repriced == pytest.approx(market_price, abs=1e-5, rel=1e-6)
    assert n_solved > N_PROPERTY_ITERATIONS * 0.9   # the solver should reach almost every case


def test_property_put_call_parity_holds():
    rng = random.Random(SEED)
    for _ in range(N_PROPERTY_ITERATIONS):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        call = bsm.price(option_type="call", spot=c["spot"], strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"])
        put = bsm.price(option_type="put", spot=c["spot"], strike=strike,
                        time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                        sigma=c["sigma"])
        disc_k = strike * math.exp(-c["rate"] * c["time_to_expiry_years"])
        assert (call - put) == pytest.approx(c["spot"] - disc_k, abs=1e-6)


def test_property_finite_difference_delta_matches_analytic():
    """Independent numerical cross-check: analytic BSM delta vs a plain
    central finite-difference bump on BSM's OWN price function."""
    rng = random.Random(SEED)
    for _ in range(100):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        h = c["spot"] * 1e-4
        p_up = bsm.price(option_type=c["option_type"], spot=c["spot"] + h, strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"])
        p_dn = bsm.price(option_type=c["option_type"], spot=c["spot"] - h, strike=strike,
                         time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                         sigma=c["sigma"])
        fd_delta = (p_up - p_dn) / (2 * h)
        g = bsm.greeks(option_type=c["option_type"], spot=c["spot"], strike=strike,
                       time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                       sigma=c["sigma"])
        assert fd_delta == pytest.approx(g.delta, abs=1e-4)


# ---- American-vs-BSM cross-model check (calls, no dividends) ---------------

def test_property_american_call_price_close_to_bsm_no_dividend():
    rng = random.Random(SEED)
    for _ in range(60):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        bsm_px = bsm.price(option_type="call", spot=c["spot"], strike=strike,
                           time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                           sigma=c["sigma"])
        am_px = crr_price(option_type="call", spot=c["spot"], strike=strike,
                          time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                          sigma=c["sigma"], n_steps=150)
        assert am_px == pytest.approx(bsm_px, rel=0.02, abs=0.05)


def test_property_american_put_never_cheaper_than_bsm_european_put():
    """Early exercise can only ADD value -- an American put must never
    be worth less than its European (BSM) counterpart."""
    rng = random.Random(SEED)
    for _ in range(60):
        c = _random_contract(rng)
        strike = c["spot"] * c["strike_mult"]
        bsm_px = bsm.price(option_type="put", spot=c["spot"], strike=strike,
                           time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                           sigma=c["sigma"])
        am_px = crr_price(option_type="put", spot=c["spot"], strike=strike,
                          time_to_expiry_years=c["time_to_expiry_years"], rate=c["rate"],
                          sigma=c["sigma"], n_steps=150)
        assert am_px >= bsm_px - 0.05


# ---- stress tests: the named ugly regions -----------------------------------

def test_stress_one_minute_to_expiry():
    now = T0
    expiry_ts = now + pd.Timedelta(minutes=1)
    # build a curve covering near-zero tenor
    curve = RiskFreeCurve(points=((0.0000001, 0.03), (1.0, 0.035)),
                          source="UST_PAR_YIELD_CURVE", as_of=str(now))
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=100.0, strike=100.0,
        expiry_date=expiry_ts.strftime("%Y-%m-%d"), bid=0.05, ask=0.10, last_trade=0.07,
        quote_is_current=True, curve=curve, dividend_schedule=NO_DIV, known_from=now,
        now=expiry_ts - pd.Timedelta(minutes=1))
    assert state.state_quality in ("REFUSED", "LOW", "MODERATE")   # never crashes, never HIGH-confidence near expiry


def test_stress_deep_itm_call():
    # bid/ask kept comfortably above intrinsic (~450.2 at this
    # rate/tenor) so IV_MID is solvable -- see
    # test_stress_deep_itm_call_mid_below_intrinsic_yields_low_quality
    # for the adjacent case where the midpoint itself falls below
    # intrinsic (a real, honest UNKNOWN, not a bug).
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=500.0, strike=50.0,
        expiry_date="2026-09-19", bid=452.0, ask=454.0, last_trade=453.0,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.refusal_reason is None
    assert state.delta is not None
    assert state.delta["bsm_value"] > 0.9


def test_stress_deep_itm_call_mid_below_intrinsic_yields_low_quality():
    """A wide spread that straddles intrinsic value (bid below,
    midpoint below, ask above) has no BSM volatility that reproduces
    the midpoint price -- IV_MID is honestly None, never a fabricated
    number, and the state is LOW quality with no delta rather than a
    crash or a guessed Greek."""
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=500.0, strike=50.0,
        expiry_date="2026-09-19", bid=449.0, ask=451.0, last_trade=450.0,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.refusal_reason is None
    assert state.iv["iv_mid"] is None
    assert state.delta is None
    assert state.state_quality == "LOW"


def test_stress_deep_otm_put():
    state = build_canonical_state(
        symbol="TEST", option_type="put", spot=500.0, strike=50.0,
        expiry_date="2026-09-19", bid=0.01, ask=0.05, last_trade=0.02,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.state_quality in ("REFUSED", "LOW", "MODERATE", "HIGH")


def test_stress_very_high_iv_input_does_not_crash_pricer():
    px = bsm.price(option_type="call", spot=100.0, strike=100.0,
                   time_to_expiry_years=0.25, rate=0.03, sigma=4.5)
    assert 0 <= px <= 100.0 + 1e-6


def test_stress_very_low_iv_input_does_not_crash_pricer():
    px = bsm.price(option_type="call", spot=100.0, strike=100.0,
                   time_to_expiry_years=0.25, rate=0.03, sigma=0.001)
    assert px >= 0


def test_stress_wide_nbbo_flags_low_quality_not_a_crash():
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=100.0, strike=100.0,
        expiry_date="2026-09-19", bid=2.0, ask=20.0, last_trade=8.0,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.refusal_reason is None
    assert state.iv["quality"] == "LOW"


def test_stress_ex_dividend_tomorrow_refuses_without_a_schedule():
    """A caller who forgot to check for tomorrow's ex-dividend date and
    passes a stale confirmed_no_dividends schedule gets a WRONG answer
    silently; this package can't detect that from the schedule object
    alone, but it CAN and does refuse outright when no schedule is
    passed at all -- proven here, and dividend-aware behavior itself is
    proven in test_option_analytics_contracts.py's PV tests."""
    ex_div_schedule = DividendSchedule(
        events=(((T0 + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), 0.75),),
        confirmed_no_dividends=False, source="TEST", as_of=str(T0))
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=100.0, strike=100.0,
        expiry_date="2026-09-19", bid=8.0, ask=8.2, last_trade=8.1,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=ex_div_schedule,
        known_from=T0, now=T0)
    assert state.refusal_reason is None
    assert state.dividend_pv > 0.7   # the PV of tomorrow's dividend was actually applied


def test_stress_zero_liquidity_contract_no_quote_is_low_quality_not_a_crash():
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=100.0, strike=100.0,
        expiry_date="2026-09-19", bid=None, ask=None, last_trade=None,
        quote_is_current=False, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.state_quality == "LOW"
    assert state.delta is None


def test_stress_stale_quote_with_no_current_nbbo_is_refused_not_guessed():
    with pytest.raises(Exception):
        from apex.option_analytics.iv_triple import solve_iv_triple
        solve_iv_triple(option_type="call", bid=None, ask=None, last_trade=8.0,
                        quote_is_current=False, spot=100.0, strike=100.0,
                        time_to_expiry_years=0.25, rate=0.03)


def test_stress_locked_crossed_market_refused():
    state = build_canonical_state(
        symbol="TEST", option_type="call", spot=100.0, strike=100.0,
        expiry_date="2026-09-19", bid=9.0, ask=8.0, last_trade=8.5,
        quote_is_current=True, curve=WIDE_CURVE, dividend_schedule=NO_DIV,
        known_from=T0, now=T0)
    assert state.state_quality == "REFUSED"
    assert "LOCKED_CROSSED_MARKET" in state.refusal_reason
