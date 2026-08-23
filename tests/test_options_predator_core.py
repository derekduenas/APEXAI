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


def test_long_leg_pays_ask_short_leg_receives_bid(monkeypatch):
    """QUOTED-SIDE LAW: each leg fills at ITS OWN contract's quoted
    side -- long=ASK, short=BID. This asserts the execution SEMANTIC,
    not a cross-contract price ordering: a surface anomaly or unusual
    structure must not be able to falsify a real invariant."""
    frozen = _frozen()
    cands = build_candidates(frozen, "LONG")
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    assert lc.legs[0][0] == "BUY" and "ASK" in " ".join(lc.notes)

    # rebuild the quote map the way the engine does, then prove each
    # leg's price IS that contract's own quoted side
    from apex.predators.options.expression import _latest_by_contract
    q = _latest_by_contract(list(frozen.option_quotes))

    def sides(strike, right="C", exp="2024-06-21"):
        r = q[(exp, strike, right)]
        return float(r["bid"]), float(r["ask"])

    assert lc.legs[0][3] == sides(lc.legs[0][2])[1]        # long = ASK
    vert = [c for c in cands if c.expression == "CALL_VERTICAL"]
    if vert:
        v = vert[0]
        assert v.legs[0][0] == "BUY" and v.legs[1][0] == "SELL"
        assert v.legs[0][3] == sides(v.legs[0][2])[1]      # long = ASK
        assert v.legs[1][3] == sides(v.legs[1][2])[0]      # short = BID
        # net debit is DERIVED from those two actual quotes
        assert abs(v.debit - (v.legs[0][3] - v.legs[1][3]) * 100) < 1e-6
        assert "never mid" in " ".join(v.notes)


def test_no_midpoint_or_theoretical_fill_anywhere():
    """No leg may ever price at a midpoint or a model value."""
    frozen = _frozen()
    from apex.predators.options.expression import _latest_by_contract
    q = _latest_by_contract(list(frozen.option_quotes))
    for direction in ("LONG", "SHORT"):
        for c in build_candidates(frozen, direction):
            for action, right, strike, price in c.legs:
                if right == "STOCK":
                    continue
                key = ("2024-06-21", strike,
                       "C" if right == "C" else "P")
                b, a = float(q[key]["bid"]), float(q[key]["ask"])
                mid = (a + b) / 2.0
                assert price in (a, b), "leg priced off-quote"
                assert price != mid or a == b, "midpoint fill detected"


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


# ------------------------------------------ NORMALIZATION HARDENING
# 1 contract != 100 shares of exposure; R != instrument default.

def test_one_contract_is_not_universally_100_shares():
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    if isinstance(lc.stock_equivalent_shares, float):
        assert lc.stock_equivalent_shares != 100.0, \
            "delta-equivalence collapsed back to the 100-share fiction"
        assert 0 < lc.stock_equivalent_shares < 100
        assert 0 < abs(lc.net_delta) < 1.0


def test_delta_unavailable_yields_not_estimable_not_a_guess():
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=None)   # no IV
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    assert lc.net_delta == NOT_ESTIMABLE
    assert lc.stock_equivalent_shares == NOT_ESTIMABLE


def test_vertical_net_delta_is_long_minus_short():
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    v = [c for c in cands if c.expression == "CALL_VERTICAL"]
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    if v and isinstance(v[0].net_delta, float) and \
            isinstance(lc.net_delta, float):
        assert abs(v[0].net_delta) < abs(lc.net_delta), \
            "a vertical must carry LESS net delta than its long leg"


def test_r_comes_from_the_declared_plan_not_the_instrument():
    from apex.predators.options.expression import (
        build_candidates, declared_risk)
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    lc = next(c for c in cands if c.expression == "LONG_CALL")
    # holding to zero: premium really is 1R
    full = declared_risk(lc, risk_basis="FULL_PREMIUM")
    assert full["declared_1R_dollars"] == lc.max_theoretical_loss
    # exiting on underlying invalidation: 1R is SMALLER than premium
    planned = declared_risk(lc, risk_basis="PLANNED_INVALIDATION",
                            planned_invalidation_loss=90.0)
    assert planned["declared_1R_dollars"] == 90.0
    assert planned["declared_1R_dollars"] < full["declared_1R_dollars"]
    assert "not an instrument default" in planned["law"]


def test_planned_invalidation_without_a_number_refuses():
    from apex.predators.options.expression import (
        build_candidates, declared_risk)
    lc = next(c for c in build_candidates(_frozen(), "LONG", iv=0.25)
              if c.expression == "LONG_CALL")
    r = declared_risk(lc, risk_basis="PLANNED_INVALIDATION")
    assert r["declared_1R_dollars"] == NOT_ESTIMABLE
    assert "may not be inferred" in r["reason"]


def test_all_four_comparison_bases_are_preserved():
    from apex.predators.options.expression import (
        COMPARISON_BASES, build_candidates, normalize)
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    n = normalize(cands, risk_budget_dollars=500.0,
                  risk_basis="MAX_LOSS")
    for basis in COMPARISON_BASES:
        assert basis in n
    assert "no single normalization may crown a winner" in n["_law"]
    assert "DIAGNOSTIC ONLY" in \
        n["EQUAL_CAPITAL_DEPLOYED"]["STOCK"]["caveat"]


def test_equal_risk_budget_scales_by_declared_1R():
    from apex.predators.options.expression import (
        build_candidates, normalize)
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    n = normalize(cands, risk_budget_dollars=600.0,
                  risk_basis="MAX_LOSS")
    lc = n["EQUAL_RISK_BUDGET"]["LONG_CALL"]
    if "units_for_budget" in lc:
        assert lc["units_for_budget"] == round(600.0 / lc["one_R"], 3)


def test_stock_execution_pedigree_is_honest():
    """Modelled underlying fills must not masquerade as observed NBBO."""
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    st = next(c for c in cands if c.expression == "STOCK")
    # tightened 2026-08-23 by operator ruling: not merely "modelled"
    # but LIMITED -- it crosses no spread at all, so it cannot settle
    # an option-vs-stock question.
    assert st.execution_pedigree == "LIMITED_MODELLED_EXECUTION"
    opt = next(c for c in cands if c.expression == "LONG_CALL")
    assert opt.execution_pedigree == "OBSERVED_QUOTE"
    assert any("crosses NO spread" in nt for nt in st.notes)


def test_option_vs_stock_superiority_is_not_proven():
    """Stock gets friction-free fills; options pay real spreads. No
    superiority verdict may be drawn from that comparison."""
    from apex.predators.options.expression import (
        build_candidates, compare, normalize)
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    out = compare(cands, expected_move_pct=2.0)
    assert out["option_vs_stock"] == "NOT_PROVEN"
    assert out["stock_comparator_pedigree"] == "LIMITED_MODELLED_EXECUTION"
    assert "DIAGNOSTIC expression only" in out["stock_comparator_law"]
    n = normalize(cands, risk_budget_dollars=500.0,
                  risk_basis="MAX_LOSS")
    assert n["_stock_comparator"]["option_vs_stock"] == "NOT_PROVEN"


def test_options_compete_against_each_other_on_equal_terms():
    """The limitation applies ONLY to the stock comparator -- every
    option expression pays real quoted-side friction."""
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    opts = [c for c in cands if c.expression != "STOCK"]
    assert len(opts) >= 2
    assert all(c.execution_pedigree == "OBSERVED_QUOTE" for c in opts)
    assert all(c.round_trip_friction > 0 for c in opts)


def test_compare_forbids_a_single_metric_winner():
    from apex.predators.options.expression import (
        build_candidates, compare)
    out = compare(build_candidates(_frozen(), "LONG", iv=0.25),
                  expected_move_pct=2.0)
    assert out["comparison_basis_required"] is True
    assert "No OPTION_BETTER / STOCK_BETTER verdict" in out["law"]


def test_defined_risk_is_defined_only_at_expiry():
    """A vertical closed at quoted sides crosses two more spreads. The
    debit bounds the loss AT EXPIRY, not on a round-trip exit -- the
    first real replay produced a put vertical up +$103 on mid that
    realized -$215 against a $160 debit."""
    from apex.predators.options.expression import build_candidates
    cands = build_candidates(_frozen(), "LONG", iv=0.25)
    for c in cands:
        if c.expression == "STOCK":
            continue
        assert c.max_loss_basis == "AT_EXPIRY"
        assert c.round_trip_friction is not None
        assert c.round_trip_friction > 0, "crossing spreads is not free"
        assert c.immediate_liquidation_value is not None
        # liquidating immediately must cost the friction, exactly
        assert abs((c.debit - c.immediate_liquidation_value)
                   - c.round_trip_friction) < 0.01


def test_friction_is_knowable_before_the_trade():
    """It is computed from the SAME quotes that priced the entry, so it
    is pre-trade information rather than hindsight."""
    from apex.predators.options.expression import build_candidates
    frozen = _frozen()
    a = build_candidates(frozen, "LONG", iv=0.25)
    b = build_candidates(frozen, "LONG", iv=0.25)
    assert [c.round_trip_friction for c in a] == \
           [c.round_trip_friction for c in b]
