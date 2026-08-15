"""Track 3's six mandated test families (v4.0 §1.5), one section each:
payoff correctness / stock-wins / spread+theta costs / distribution
sensitivity / no live wiring / distribution_source propagation.
"""

from __future__ import annotations

import numpy as np
import pytest

from apex.config import load_config
from apex.expression.engine import (
    Candidate, DistributionSource, ExpressionError, ExpressionInput,
    NotARecommendation, OptionQuote, Structure, build_structures, evaluate,
)

CFG = load_config("expression")
S = 100.0


def q(kind, strike, expiry=20, bid=None, ask=None, iv=0.30, oi=1000):
    return OptionQuote(kind=kind, strike=strike, expiry_days=expiry,
                       bid=bid, ask=ask, iv=iv, open_interest=oi, volume=500)


def make_input(returns, probs, chain, source=DistributionSource.SYNTHETIC,
               horizon=20):
    return ExpressionInput(horizon_days=horizon, returns=np.array(returns),
                           probs=np.array(probs), distribution_source=source,
                           chain=tuple(chain), spot=S)


# --- 1. payoff correctness (held to expiry: horizon == expiry) --------------

def test_long_call_payoff_hand_computed_at_expiry():
    call = q("call", 100, bid=3.0, ask=3.2)
    st = Structure("long_call", buys=(call,))
    # spot 110 at expiry: intrinsic 10, paid 3.2 (ASK) -> pnl 6.8
    assert st.pnl_at_horizon(S, 110.0, 20) == pytest.approx(10 - 3.2)
    # deep OTM: worthless, lose the ask
    assert st.pnl_at_horizon(S, 80.0, 20) == pytest.approx(-3.2)
    # exactly ATM edge: zero intrinsic
    assert st.pnl_at_horizon(S, 100.0, 20) == pytest.approx(-3.2)


def test_call_debit_spread_payoff_hand_computed():
    lo, hi = q("call", 100, bid=3.0, ask=3.2), q("call", 105, bid=1.2, ask=1.4)
    st = Structure("call_debit_spread", buys=(lo,), sells=(hi,))
    # entry: pay 3.2, receive 1.2 -> net 2.0
    assert st.entry_cost(S) == pytest.approx(2.0)
    # spot 110: long leg 10, short leg -5 -> 5 - 2 = 3 (capped)
    assert st.pnl_at_horizon(S, 110.0, 20) == pytest.approx(3.0)
    assert st.pnl_at_horizon(S, 200.0, 20) == pytest.approx(3.0)
    assert st.pnl_at_horizon(S, 90.0, 20) == pytest.approx(-2.0)


def test_collar_payoff_hand_computed():
    put, call = q("put", 95, bid=1.0, ask=1.2), q("call", 105, bid=1.1, ask=1.3)
    st = Structure("collar", buys=(put,), sells=(call,), stock_shares=1.0)
    entry = S + 1.2 - 1.1
    # crash to 80: stock 80 + put 15 - 0 -> 95 - entry
    assert st.pnl_at_horizon(S, 80.0, 20) == pytest.approx(95 - entry)
    # rally to 120: stock 120 + 0 - 15 -> 105 - entry (capped)
    assert st.pnl_at_horizon(S, 120.0, 20) == pytest.approx(105 - entry)


def test_defined_risk_only_no_naked_shorts():
    chain = [q("call", 100, bid=3, ask=3.2), q("call", 105, bid=1.2, ask=1.4),
             q("put", 100, bid=3, ask=3.2), q("put", 95, bid=1.2, ask=1.4)]
    for st in build_structures(make_input([0.0], [1.0], chain)):
        if st.sells and not st.buys and st.stock_shares == 0:
            raise AssertionError(f"{st.name} is a naked short")
        # every short call is covered by stock or a long call
        for s_ in st.sells:
            covered = st.stock_shares > 0 or any(
                b.kind == s_.kind for b in st.buys)
            assert covered, f"{st.name} sells an uncovered {s_.kind}"


# --- 2. stock wins when it should -------------------------------------------

def _modest_edge_pmf():
    """Believed distribution: +2% mean, 8% sd -- MODEST edge, calm view."""
    grid = np.linspace(-0.30, 0.34, 65)
    p = np.exp(-0.5 * ((grid - 0.02) / 0.08) ** 2)
    return grid, p / p.sum()


def test_stock_wins_on_modest_edge_high_iv_wide_spread():
    """The exact configuration where retail buys the call anyway: options
    priced at 60% IV (rich vs the believed 8%-sd view), spreads wide."""
    grid, p = _modest_edge_pmf()
    chain = [q("call", 100, bid=5.0, ask=6.2, iv=0.60, oi=200),
             q("call", 105, bid=3.0, ask=4.0, iv=0.62, oi=150),
             q("put", 100, bid=5.0, ask=6.2, iv=0.60, oi=200),
             q("put", 95, bid=2.9, ask=3.9, iv=0.62, oi=150)]
    report = evaluate(make_input(grid, p, chain), CFG)
    assert report.selection == "common_stock", (
        f"selected {report.selection}; rich premium + wide spread must lose "
        f"to stock on a modest-edge calm view")


# --- 3. spread and theta cannot be bypassed ---------------------------------

def test_wider_spread_strictly_worsens_the_candidate():
    grid, p = _modest_edge_pmf()
    tight = [q("call", 100, bid=3.10, ask=3.20, iv=0.30)]
    wide = [q("call", 100, bid=2.40, ask=3.90, iv=0.30)]
    r_tight = evaluate(make_input(grid, p, tight), CFG)
    r_wide = evaluate(make_input(grid, p, wide), CFG)
    ut = {c.name: c.utility for c in r_tight.candidates}["long_call"]
    uw = {c.name: c.utility for c in r_wide.candidates}["long_call"]
    assert uw < ut, "a wider spread must strictly lower the option's utility"
    sc = {c.name: c.spread_cost for c in r_wide.candidates}["long_call"]
    assert sc == pytest.approx(3.90 - (2.40 + 3.90) / 2), "cost vs mid recorded"


def test_theta_is_integrated_over_the_holding_period():
    """A 40d call held 20d at a FLAT spot loses time value -- the horizon
    re-pricing cannot be zeroed or defaulted away."""
    call = q("call", 100, expiry=40, bid=4.6, ask=4.8, iv=0.30)
    st = Structure("long_call", buys=(call,))
    flat = st.pnl_at_horizon(S, 100.0, 20)
    assert flat < 0, "holding through theta at a flat spot must cost money"
    # and the loss is LESS than the full premium: 20d of life remains
    assert flat > -4.8, "remaining life must retain some value"


# --- 4. distribution sensitivity --------------------------------------------

def test_an_overconfident_distribution_changes_the_selection():
    """Same chain; a fat right-tail view flips the choice away from stock --
    proving the engine consumes the DISTRIBUTION, not IV pattern-matching."""
    chain = [q("call", 100, bid=3.0, ask=3.1, iv=0.30, oi=2000),
             q("call", 105, bid=1.2, ask=1.3, iv=0.31, oi=2000),
             q("put", 100, bid=3.0, ask=3.1, iv=0.30, oi=2000),
             q("put", 95, bid=1.2, ask=1.3, iv=0.31, oi=2000)]
    grid, p_calm = _modest_edge_pmf()
    calm = evaluate(make_input(grid, p_calm, chain), CFG)

    # crash-or-moon: heavy mass at both -25% and +25%. A holder of stock
    # eats the crash; defined-risk structures cap it. If the selection does
    # not move, the engine is ignoring the pmf.
    p_bimodal = (np.exp(-0.5 * ((grid + 0.25) / 0.03) ** 2)
                 + 1.3 * np.exp(-0.5 * ((grid - 0.25) / 0.03) ** 2))
    p_bimodal = p_bimodal / p_bimodal.sum()
    wild = evaluate(make_input(grid, p_bimodal, chain), CFG)
    assert wild.selection != calm.selection, (
        f"calm and crash-or-moon views both chose {calm.selection}; the "
        f"distribution is not being consumed")
    assert wild.selection != "common_stock"


# --- 5. no live wiring ------------------------------------------------------

def test_no_code_path_reaches_live_data_or_orders():
    import inspect

    import apex.expression.engine as E
    src = inspect.getsource(E)
    for banned in ("requests", "urllib", "http", "websocket", "broker",
                   "order(", "submit", "subprocess"):
        assert banned not in src, f"expression engine references {banned!r}"


# --- 6. distribution_source propagation -------------------------------------

def test_uncalibrated_output_cannot_become_a_recommendation():
    grid, p = _modest_edge_pmf()
    chain = [q("call", 100, bid=3.0, ask=3.2)]
    for src in (DistributionSource.SYNTHETIC, DistributionSource.UNCALIBRATED_MODEL):
        rep = evaluate(make_input(grid, p, chain, source=src), CFG)
        assert rep.distribution_source == src.value
        assert all(c.distribution_source == src.value for c in rep.candidates)
        with pytest.raises(NotARecommendation, match="infrastructure"):
            rep.as_recommendation()


def test_counterexample_a_calibrated_output_may_recommend():
    """If everything is refused, the refusal above proves nothing."""
    grid, p = _modest_edge_pmf()
    rep = evaluate(make_input(grid, p, [q("call", 100, bid=3.0, ask=3.2)],
                              source=DistributionSource.CALIBRATED), CFG)
    assert rep.as_recommendation()["selection"] == rep.selection


def test_contract_violations_are_refused():
    with pytest.raises(ExpressionError, match="integrate to 1"):
        make_input([0.0, 0.1], [0.6, 0.6], [])
    with pytest.raises(ExpressionError, match="inside the"):
        make_input([0.0], [1.0], [q("call", 100, expiry=10, bid=1, ask=1.1)],
                   horizon=20)
