"""OPTIONS PAPER EXECUTION + OUTCOME RESOLVER property tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.options.expression import (  # noqa: E402
    ExpressionCandidate)
from apex.predators.options.paper_execution import (  # noqa: E402
    NOT_ESTIMABLE, ExecutionRefused, counterfactual_expressions,
    resolve, simulate_entry)

CARD = "a" * 64
T = "2024-05-22T14:00:00"


def _call(strike=100.0, ask=3.0, bid=2.8):
    return ExpressionCandidate(
        expression="LONG_CALL", direction="LONG",
        legs=(("BUY", "C", strike, ask),), debit=ask * 100,
        max_loss=ask * 100, max_gain="UNBOUNDED",
        breakeven=strike + ask, breakeven_move_pct=3.0,
        quoted_spread_cost=(ask - bid) * 100, liquidity="QUOTED",
        capital_required=ask * 100)


def _vertical():
    return ExpressionCandidate(
        expression="CALL_VERTICAL", direction="LONG",
        legs=(("BUY", "C", 100.0, 3.0), ("SELL", "C", 105.0, 1.2)),
        debit=180.0, max_loss=180.0, max_gain=320.0, breakeven=101.8,
        breakeven_move_pct=1.8, quoted_spread_cost=20.0,
        liquidity="QUOTED", capital_required=180.0)


def _stock():
    return ExpressionCandidate(
        expression="STOCK", direction="LONG",
        legs=(("BUY", "STOCK", 100.0, 100.0),), debit=10000.0,
        max_loss=None, max_gain="UNBOUNDED", breakeven=100.0,
        breakeven_move_pct=0.0, quoted_spread_cost=None,
        liquidity="UNDERLYING", capital_required=10000.0)


def _future(path):
    t0 = pd.Timestamp("2024-05-22T14:01:00Z")
    return [{"t": str(t0 + pd.Timedelta(minutes=i)), "c": c}
            for i, c in enumerate(path)]


def _quotes(mapping):
    def lookup(strike, right):
        return mapping.get((strike, right))
    return lookup


# ------------------------------------------------ sequence law

def test_execution_refuses_without_a_sealed_card():
    with pytest.raises(ExecutionRefused, match="sealed BEFORE card"):
        simulate_entry(_call(), T=T, sealed_card_hash=None)
    with pytest.raises(ExecutionRefused):
        simulate_entry(_call(), T=T, sealed_card_hash="short")


def test_resolution_refuses_without_a_sealed_card():
    f = simulate_entry(_call(), T=T, sealed_card_hash=CARD)
    with pytest.raises(ExecutionRefused):
        resolve(fill=f, sealed_card_hash="", future_underlying=[],
                future_quote_lookup=_quotes({}))


# ------------------------------------------------ fill law

def test_single_leg_crosses_the_ask_with_pedigree():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    action, right, strike, price, side = f.legs[0]
    assert (action, side, price) == ("BUY", "ASK", 3.0)
    assert f.net_debit == 300.0
    assert "ASK = 3.0" in " ".join(f.fill_pedigree)


def test_vertical_pays_ask_and_receives_bid():
    f = simulate_entry(_vertical(), T=T, sealed_card_hash=CARD)
    long_leg, short_leg = f.legs
    assert long_leg[0] == "BUY" and long_leg[4] == "ASK"
    assert short_leg[0] == "SELL" and short_leg[4] == "BID"
    # net = (3.0 paid - 1.2 received) * 100
    assert f.net_debit == 180.0
    ped = " ".join(f.fill_pedigree)
    assert "ASK = 3.0" in ped and "BID = 1.2" in ped


def test_no_midpoint_or_model_price_anywhere():
    for cand in (_call(), _vertical()):
        f = simulate_entry(cand, T=T, sealed_card_hash=CARD)
        for _a, _r, _k, price, side in f.legs:
            assert side in ("ASK", "BID", "ASK_SIDE", "BID_SIDE")
        assert "no midpoint" in f.law


def test_contracts_scale_capital_linearly():
    one = simulate_entry(_call(), T=T, contracts=1,
                         sealed_card_hash=CARD)
    three = simulate_entry(_call(), T=T, contracts=3,
                           sealed_card_hash=CARD)
    assert three.net_debit == one.net_debit * 3


# ------------------------------------------------ outcome resolution

def test_exit_marks_out_at_quoted_sides_not_mid():
    """Closing a long hits the BID -- the honest round trip."""
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    # option worth 5.00/4.80 at exit: we receive the BID
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([101, 103, 105]),
                  future_quote_lookup=_quotes({(100.0, "C"): (4.8, 5.0)}),
                  entry_underlying=100.0)
    assert out.exit["net_credit_received"] == 480.0     # BID, not mid
    assert out.pnl == 180.0                             # 480 - 300
    assert "sell longs at BID" in out.exit["method"]


def test_vertical_exit_buys_back_the_short_at_ask():
    f = simulate_entry(_vertical(), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([104]),
                  future_quote_lookup=_quotes({
                      (100.0, "C"): (4.5, 4.7),
                      (105.0, "C"): (1.0, 1.3)}),
                  entry_underlying=100.0)
    # receive 4.5 (bid) on the long, pay 1.3 (ask) to close the short
    assert out.exit["net_credit_received"] == 320.0
    assert out.pnl == 140.0                             # 320 - 180


def test_mfe_mae_and_timings_measured_from_the_path():
    f = simulate_entry(_call(), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([102, 106, 98, 101]),
                  future_quote_lookup=_quotes({(100.0, "C"): (3.0, 3.2)}),
                  entry_underlying=100.0, invalidation=99.0,
                  target=105.0)
    assert out.mfe == 6.0 and out.mae == -2.0
    assert out.time_to_mfe_min == 1.0      # bar index 1
    assert out.time_to_mae_min == 2.0
    assert out.time_to_target_min == 1.0   # 106 >= 105
    assert out.time_to_invalidation_min == 2.0   # 98 <= 99
    assert out.underlying_return_pct == 1.0


def test_short_direction_mfe_is_sign_corrected():
    c = _call()
    short = ExpressionCandidate(**{**c.__dict__, "direction": "SHORT"})
    f = simulate_entry(short, T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([98, 95]),
                  future_quote_lookup=_quotes({(100.0, "C"): (5.0, 5.2)}),
                  entry_underlying=100.0)
    assert out.mfe == 5.0        # price FELL: favorable for a short
    assert out.mae == 2.0


def test_r_multiple_uses_capital_actually_at_risk():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=_quotes({(100.0, "C"): (6.0, 6.2)}),
                  entry_underlying=100.0)
    assert out.pnl == 300.0
    assert out.r_multiple == 1.0        # 300 gained on 300 at risk


def test_missing_exit_quote_yields_not_estimable_not_zero():
    f = simulate_entry(_call(), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([105]),
                  future_quote_lookup=_quotes({}),   # contract gone
                  entry_underlying=100.0)
    assert out.pnl == NOT_ESTIMABLE
    assert out.r_multiple == NOT_ESTIMABLE


def test_outcome_is_marked_replay_not_prospective():
    f = simulate_entry(_call(), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD, future_underlying=[],
                  future_quote_lookup=_quotes({}))
    assert out.evidence_class == "HISTORICAL_DEVELOPMENT_REPLAY"


# ------------------------------------------------ counterfactuals

def test_counterfactuals_compare_every_weapon_and_stay_measurement():
    cf = counterfactual_expressions(
        candidates=[_stock(), _call(), _vertical()], T=T,
        sealed_card_hash=CARD,
        future_underlying=_future([104]),
        future_quote_lookup=_quotes({(100.0, "C"): (4.5, 4.7),
                                     (105.0, "C"): (1.0, 1.3)}),
        entry_underlying=100.0)
    assert {"STOCK", "LONG_CALL", "CALL_VERTICAL"} <= set(cf)
    assert "measurement only" in cf["_law"]
    # the interesting case: capital efficiency differs enormously
    assert cf["STOCK"]["capital"] > cf["CALL_VERTICAL"]["capital"]
