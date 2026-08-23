"""OPTIONS PREDATOR CORE -- state + expression competition properties.

Fixture-driven: no real corpus, no outcome inspection, no thresholds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.options.expression import (  # noqa: E402
    CANDIDATE_RULES, EXPRESSIONS, build_candidates, compare)
from apex.predators.options.replay import FrozenState  # noqa: E402
from apex.predators.options.state import (  # noqa: E402
    NOT_ESTIMABLE, build, realized_vol)

T = "2024-05-22T14:00:00"


def _frozen(spot=100.0, n_bars=400, chain=True, vol=0.0008):
    import math
    t0 = pd.Timestamp("2024-05-22T13:30:00Z")
    bars = [{"t": str(t0 + pd.Timedelta(minutes=i)),
             "c": spot * (1 + vol * math.sin(i / 3.0)),
             "session": "REGULAR"} for i in range(n_bars)]
    quotes = []
    if chain:
        for strike in [spot * m for m in
                       (0.90, 0.95, 0.98, 1.00, 1.02, 1.05, 1.10)]:
            for right, base in (("CALL", max(spot - strike, 0) + 3.0),
                                ("PUT", max(strike - spot, 0) + 3.0)):
                quotes.append({
                    "symbol": "TEST", "expiration": "2024-06-21",
                    "strike": f"{strike:.3f}", "right": right,
                    "timestamp": "2024-05-22T13:59:00.000",
                    "bid": f"{base * 0.98:.2f}", "bid_size": "20",
                    "ask": f"{base * 1.02:.2f}", "ask_size": "20",
                    "moneyness_status": "CAUSAL"})
    return FrozenState(
        symbol="TEST", session="2024-05-22", T=T,
        underlying_bars=tuple(bars), option_quotes=tuple(quotes),
        oi_rows=(), spot_ref=bars[-1]["c"],
        spot_ref_source_label="x", spot_ref_age_s=60.0)


# ---------------------------------------------- state

def test_state_is_observation_never_a_label():
    st = build(_frozen())
    rec = st.as_record()
    # scope the scan to DATA fields -- `law` legitimately names the
    # forbidden labels in order to forbid them
    data = {k: v for k, v in rec.items() if k != "law"}
    blob = str(data).upper()
    for banned in ("CHEAP", "RICH", "BUY_VOL", "SELL_VOL",
                   "OVERPRICED", "UNDERPRICED"):
        assert banned not in blob, f"state emitted a label: {banned}"
    assert "no CHEAP/RICH" in st.law


def test_iv_and_rv_are_computed_by_our_own_stack():
    st = build(_frozen())
    assert st.pricing_source == "APEX_COMMISSIONED_STACK"
    assert st.atm_iv is not None and 0 < st.atm_iv < 5
    assert st.realized_vol["rv_30m"] is not None


def test_insufficient_data_refuses_rather_than_guesses():
    thin = _frozen(chain=False)
    st = build(thin)
    assert st.data_quality in ("INSUFFICIENT_SURFACE", "INSUFFICIENT")
    assert st.atm_iv is None
    assert st.iv_minus_rv == NOT_ESTIMABLE
    # and with no spot at all
    empty = FrozenState("T", "s", T, (), (), (), None, None, None)
    assert build(empty).data_quality == "INSUFFICIENT"


def test_realized_vol_is_causal_and_windowed():
    bars = [{"c": 100.0 + i} for i in range(100)]
    assert realized_vol(bars, 30) is not None
    assert realized_vol(bars, 500) is None       # honest None, not 0


def test_term_structure_and_skew_present_or_not_estimable():
    st = build(_frozen())
    assert isinstance(st.term_structure, tuple)
    for v in (st.put_skew, st.call_skew):
        assert v == NOT_ESTIMABLE or isinstance(v, float)


# ---------------------------------------------- expression competition

def test_stock_is_always_a_competitor():
    cands = build_candidates(_frozen(), "LONG")
    assert any(c.expression == "STOCK" for c in cands), \
        "the underlying must always compete -- otherwise the sleeve " \
        "can never say EQUITY_BETTER"


def test_long_leg_pays_ask_short_leg_receives_bid():
    cands = build_candidates(_frozen(), "LONG")
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    action, right, strike, price = lc.legs[0]
    assert action == "BUY" and "ASK" in " ".join(lc.notes)
    vert = [c for c in cands if c.expression == "CALL_VERTICAL"]
    if vert:
        v = vert[0]
        assert v.legs[0][0] == "BUY" and v.legs[1][0] == "SELL"
        assert v.legs[1][3] < v.legs[0][3]        # sold at bid < ask
        assert "never mid" in " ".join(v.notes)
        # vertical must cost less than the outright it is built from
        assert v.debit < lc.debit


def test_vertical_caps_the_favorable_tail_explicitly():
    cands = build_candidates(_frozen(), "LONG")
    vert = [c for c in cands if c.expression == "CALL_VERTICAL"]
    if vert:
        assert isinstance(vert[0].max_gain, float)
        assert "CAPPED" in " ".join(vert[0].notes)
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    assert lc.max_gain == "UNBOUNDED"


def test_breakeven_is_computed_and_expressed_as_required_move():
    cands = build_candidates(_frozen(), "LONG")
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    assert lc.breakeven > lc.legs[0][2]          # strike + premium
    assert lc.breakeven_move_pct > 0


def test_no_forecast_means_no_option_beats_stock():
    """Refusal law: without an estimable expected move, ranking
    options above the underlying is unjustified."""
    cands = build_candidates(_frozen(), "LONG")
    out = compare(cands, expected_move_pct=NOT_ESTIMABLE)
    assert out["verdict"] == "NOT_ESTIMABLE"
    assert "no option may be declared superior" in out["reason"]


def test_breakeven_reach_ratio_exposes_the_real_hurdle():
    cands = build_candidates(_frozen(), "LONG")
    out = compare(cands, expected_move_pct=1.0)
    rows = {r["expression"]: r for r in out["candidates"]}
    lc = rows["LONG_CALL"]
    assert lc["breakeven_reach_ratio"] is not None
    # stock breaks even at zero move; the option never can
    assert rows["STOCK"]["breakeven_move_pct"] == 0.0
    assert lc["breakeven_move_pct"] > 0


def test_candidate_rules_are_predeclared_and_deterministic():
    assert "declared BEFORE any outcome inspection" in \
        CANDIDATE_RULES["note"]
    a = build_candidates(_frozen(), "LONG")
    b = build_candidates(_frozen(), "LONG")
    assert [c.as_record() for c in a] == [c.as_record() for c in b]


def test_no_expression_without_a_spot_reference():
    empty = FrozenState("T", "s", T, (), (), (), None, None, None)
    assert build_candidates(empty, "LONG") == []


def test_expression_vocabulary_closed():
    assert set(EXPRESSIONS) == {"STOCK", "LONG_CALL", "LONG_PUT",
                                "CALL_VERTICAL", "PUT_VERTICAL",
                                "NO_TRADE"}
