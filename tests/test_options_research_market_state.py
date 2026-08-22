"""OptionMarketState — OCC symbol parsing, UNKNOWN preservation (never
a fabricated 0 for missing Greeks/IV/OI), real Alpaca snapshot shape.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.options_research.market_state import (OptionMarketStateError,
                                                 from_alpaca_snapshot,
                                                 parse_occ_symbol)

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def test_parse_occ_symbol():
    p = parse_occ_symbol("AAPL260819C00210000")
    assert p == {"root": "AAPL", "expiration": "2026-08-19",
                "call_put": "CALL", "strike": 210.0}


def test_parse_put():
    p = parse_occ_symbol("AAPL260819P00205000")
    assert p["call_put"] == "PUT" and p["strike"] == 205.0


def test_parse_bad_symbol_refused():
    with pytest.raises(OptionMarketStateError):
        parse_occ_symbol("NOT-A-REAL-SYMBOL")


def test_from_real_alpaca_snapshot_shape():
    """The exact shape confirmed live tonight against AAPL."""
    snap = {"dailyBar": {"c": 101.1, "h": 101.1, "l": 96.68, "n": 24, "o": 96.79,
                        "t": "2026-08-18T04:00:00Z", "v": 31},
           "latestQuote": {"ap": 102.8, "as": 52, "ax": "S", "bp": 99.5, "bs": 50,
                          "bx": "B", "c": " ", "t": "2026-08-18T14:42:57Z"},
           "latestTrade": {"c": "g", "p": 101.1, "s": 1, "t": "2026-08-18T14:41:20Z",
                          "x": "I"}}
    m = from_alpaca_snapshot("AAPL260819C00210000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.strike == 210.0 and m.call_put == "CALL"
    assert m.bid == 99.5 and m.ask == 102.8
    assert m.mid == pytest.approx(101.15)
    assert m.last_trade == 101.1


def test_greeks_and_iv_are_none_when_absent_from_payload():
    """OI/volume are never in this payload -- always honest None.
    Greeks/IV ARE sometimes present (see
    test_greeks_and_iv_parsed_when_present) but this specific snapshot
    (an illiquid/thin contract shape, confirmed live) omits both --
    the adapter must never fabricate a value either way."""
    snap = {"latestQuote": {"ap": 1.0, "bp": 0.9}, "latestTrade": {}}
    m = from_alpaca_snapshot("AAPL260819C00210000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.implied_volatility is None
    assert m.delta is None and m.gamma is None and m.theta is None and m.vega is None
    assert m.rho is None
    assert m.open_interest is None
    assert m.volume is None


def test_greeks_and_iv_parsed_when_present():
    """Confirmed live 2026-08-18 against a 100-contract AAPL chain:
    41/100 actively-quoted contracts DO carry `greeks` and
    `impliedVolatility` -- this is the real shape for those."""
    snap = {"latestQuote": {"ap": 27.15, "bp": 24.6},
           "greeks": {"delta": 0.9576, "gamma": 0.0057, "rho": 0.0074,
                     "theta": -0.7374, "vega": 0.0147},
           "impliedVolatility": 0.9676}
    m = from_alpaca_snapshot("AAPL260819C00285000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.implied_volatility == pytest.approx(0.9676)
    assert m.delta == pytest.approx(0.9576)
    assert m.gamma == pytest.approx(0.0057)
    assert m.theta == pytest.approx(-0.7374)
    assert m.vega == pytest.approx(0.0147)
    assert m.rho == pytest.approx(0.0074)


def test_missing_quote_leaves_bid_ask_none_data_quality_partial():
    snap = {}
    m = from_alpaca_snapshot("AAPL260819C00210000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.bid is None and m.ask is None and m.mid is None
    assert m.data_quality == "PARTIAL"


def test_dte_computed_from_true_calendar_not_guessed():
    snap = {"latestQuote": {"ap": 1.0, "bp": 0.9}}
    m = from_alpaca_snapshot("AAPL260825C00210000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.dte == 7          # 2026-08-25 minus 2026-08-18


def test_bad_call_put_refused_at_construction():
    from apex.options_research.market_state import OptionMarketState
    with pytest.raises(OptionMarketStateError):
        OptionMarketState(
            symbol="AAPL", underlying_price=230.0, contract_id="x",
            option_symbol="x", call_put="NOT_CALL_OR_PUT", strike=210.0,
            expiration="2026-08-19", dte=1, bid=None, ask=None, bid_size=None,
            ask_size=None, mid=None, last_trade=None, last_trade_size=None,
            volume=None, open_interest=None, implied_volatility=None, delta=None,
            gamma=None, theta=None, vega=None, rho=None, quote_time=None, trade_time=None,
            event_time=str(T0), known_from=str(T0), as_of=str(T0),
            source="x", provider="x", data_quality="PARTIAL", staleness_s=None)


def test_decision_power_stamped():
    snap = {"latestQuote": {"ap": 1.0, "bp": 0.9}}
    m = from_alpaca_snapshot("AAPL260819C00210000", snap, underlying_price=230.0,
                             now=T0, known_from=T0)
    assert m.decision_power == "NONE_OPTIONS_RESEARCH"
