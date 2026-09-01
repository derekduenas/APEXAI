"""Tests for the edge-extraction state engines."""
from __future__ import annotations

from apex.organism import microstructure as ms
from apex.organism import options_surface as osf


def _q(t, bp, ap, bs=10, as_=10):
    return {"t": t, "bp": bp, "ap": ap, "bs": bs, "as": as_}


def _t(t, p, s=100):
    return {"t": t, "p": p, "s": s}


def test_quote_rule_signing():
    quotes = [_q("2026-01-05T14:30:00.000001Z", 99.99, 100.01)]
    trades = [_t("2026-01-05T14:30:00.500000Z", 100.01),   # at ask
              _t("2026-01-05T14:30:01.000000Z", 99.99),    # at bid
              _t("2026-01-05T14:30:02.000000Z", 100.005)]  # above mid
    signed = ms._sign_trades(trades, quotes)
    assert [x["sign"] for x in signed] == [1, -1, 1]


def test_micro_state_not_estimable_when_thin():
    st = ms.micro_state([_t("2026-01-05T14:30:00Z", 1)],
                        [_q("2026-01-05T14:30:00Z", 1, 1.01)])
    assert st["status"] == "NOT_ESTIMABLE"


def test_micro_state_computes_on_synthetic_window():
    quotes, trades = [], []
    for i in range(60):
        ts = f"2026-01-05T14:30:{i:02d}.000000Z"
        quotes.append(_q(ts, 100.00 + i * 0.001,
                         100.02 + i * 0.001, bs=20, as_=10))
        trades.append(_t(ts, 100.02 + i * 0.001, s=50))
    st = ms.micro_state(trades, quotes)
    assert st["n_trades"] == 60
    assert st["signed_buy_volume"] > 0
    assert st["nbbo_imbalance_mean"] > 0        # bid-heavy book
    assert "QUOTE_RULE" in st["signing_method"]


def test_surface_state_honest_on_thin_chain():
    ss = osf.surface_state("XX", 100.0, ["2026-09-18"],
                           chains={"2026-09-18": []})
    assert ss["per_expiry"]["2026-09-18"]["status"] == \
        "NOT_ESTIMABLE"


def test_surface_state_expected_move():
    chain = []
    for k in (95, 100, 105):
        chain.append({"strike": float(k), "right": "CALL",
                      "bid": 2.0, "ask": 2.2, "bid_size": 5,
                      "ask_size": 5, "timestamp": "T"})
        chain.append({"strike": float(k), "right": "PUT",
                      "bid": 1.8, "ask": 2.0, "bid_size": 5,
                      "ask_size": 5, "timestamp": "T"})
    ss = osf.surface_state("XX", 100.0, ["2026-09-18"],
                           chains={"2026-09-18": chain})
    pe = ss["per_expiry"]["2026-09-18"]
    # ATM straddle mid = (2.0+2.2+1.8+2.0)/4 = 2.0 -> 200 bps
    assert pe["atm_straddle_mid_bps_of_spot"] == 200.0
    assert pe["atm_put"]["strike"] == 100.0
