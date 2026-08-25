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


EXP = "2024-06-21"


def _call(strike=100.0, ask=3.0, bid=2.8, expiration=EXP):
    return ExpressionCandidate(
        expression="LONG_CALL", direction="LONG", expiration=expiration,
        legs=(("BUY", "C", strike, ask),), debit=ask * 100,
        max_loss=ask * 100, max_gain="UNBOUNDED",
        breakeven=strike + ask, breakeven_move_pct=3.0,
        quoted_spread_cost=(ask - bid) * 100, liquidity="QUOTED",
        capital_required=ask * 100)


def _vertical():
    return ExpressionCandidate(
        expression="CALL_VERTICAL", direction="LONG", expiration=EXP,
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
    # T is ET-naive 14:00, so the entry is 18:00Z and the path must
    # start AFTER it. The old fixture put bars at 14:01Z -- four hours
    # BEFORE its own entry -- which only passed because the pre-repair
    # resolver compared naive ET against naive UTC. Day-1 Defect B in
    # miniature, and the repaired causal filter now rejects it.
    t0 = pd.Timestamp("2024-05-22T18:01:00Z")
    return [{"t": str(t0 + pd.Timedelta(minutes=i)), "c": c}
            for i, c in enumerate(path)]


def _quotes(mapping, expiration=EXP):
    """Identity-keyed lookup. Accepts the legacy (strike, right) mapping
    and binds it to ONE expiration, so a test can never accidentally
    close a position with another expiry's quote."""
    def lookup(exp, strike, right):
        if exp != expiration:
            return None
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


def test_r_multiple_is_withheld_when_risk_was_never_declared():
    """Superseded 2026-08-23: R used to default to capital committed.
    That silently equated 'the debit' with 'the planned loss'. It now
    REFUSES rather than assume."""
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=_quotes({(100.0, "C"): (6.0, 6.2)}),
                  entry_underlying=100.0)
    assert out.pnl == 300.0
    assert out.r_multiple == "NOT_ESTIMABLE"
    assert "R withheld rather than assumed" in out.risk_basis


def test_full_premium_declaration_makes_R_the_premium():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD,
                       risk_basis="FULL_PREMIUM")
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=_quotes({(100.0, "C"): (6.0, 6.2)}),
                  entry_underlying=100.0)
    assert out.declared_1R_dollars == 300.0
    assert out.r_multiple == 1.0
    assert out.risk_basis == "FULL_PREMIUM"


def test_planned_invalidation_gives_a_larger_R_multiple():
    """The SAME trade, same P&L: a plan that exits on underlying
    invalidation risks less, so the win is worth more R. Two honest
    numbers -- which is precisely why the basis must be recorded."""
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD,
                       risk_basis="PLANNED_INVALIDATION",
                       planned_invalidation_loss=100.0)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=_quotes({(100.0, "C"): (6.0, 6.2)}),
                  entry_underlying=100.0)
    assert out.pnl == 300.0
    assert out.declared_1R_dollars == 100.0
    assert out.r_multiple == 3.0
    assert out.capital_deployed == 300.0
    assert out.capital_deployed != out.declared_1R_dollars


def test_the_three_risk_numbers_are_persisted_separately():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD,
                       risk_basis="PLANNED_INVALIDATION",
                       planned_invalidation_loss=120.0)
    rec = f.as_record()
    for k in ("capital_deployed", "maximum_theoretical_loss",
              "planned_invalidation_loss", "declared_1R_dollars",
              "risk_basis"):
        assert k in rec
    assert rec["capital_deployed"] == 300.0
    assert rec["planned_invalidation_loss"] == 120.0
    assert "three different numbers" in rec["risk_law"]


def test_unknown_risk_basis_is_refused():
    import pytest
    with pytest.raises(ExecutionRefused):
        simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD,
                       risk_basis="WHATEVER_LOOKS_GOOD")


def test_fill_records_its_execution_pedigree():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    assert f.execution_pedigree == "OBSERVED_QUOTE"

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


def test_counterfactuals_refuse_to_crown_a_winner():
    """Every expression resolved, no single-metric verdict emitted."""
    from apex.predators.options.paper_execution import (
        counterfactual_expressions)
    from apex.predators.options.expression import build_candidates
    from tests.test_options_predator_core import _frozen

    frozen = _frozen()
    cands = build_candidates(frozen, "LONG", iv=0.25)
    strikes = {float(q["strike"]) for q in frozen.option_quotes}
    quotes = {(k, "C"): (6.0, 6.2) for k in strikes}
    quotes.update({(k, "P"): (6.0, 6.2) for k in strikes})
    cf = counterfactual_expressions(
        candidates=cands, T=T, sealed_card_hash=CARD,
        future_underlying=_future([106]),
        future_quote_lookup=_quotes(quotes),
        entry_underlying=frozen.spot_ref,
        risk_basis="FULL_PREMIUM")
    assert cf["_winner"].startswith("WITHHELD")
    assert "report the basis or report nothing" in cf["_comparison_law"]
    assert "STOCK" in cf
    # stock is sized to matching underlying exposure, not 1 share
    assert cf["STOCK"]["quantity"] == 100
    # and each resolved leg carries the basis that produced its R
    for name, row in cf.items():
        if name.startswith("_") or "error" in row:
            continue
        assert "risk_basis" in row and "execution_pedigree" in row


# ------------------------------------- CONTRACT IDENTITY (regression)
# Caught 2026-08-23 by the first real-data replay: a CALL_VERTICAL
# reported -$525 on a $155 debit. A long vertical cannot lose more than
# its debit. Cause: resolution keyed on (strike, right) only, so a
# DIFFERENT expiration's quote could close the position.

def test_a_long_vertical_can_never_lose_more_than_its_debit():
    v = _vertical()
    f = simulate_entry(v, T=T, sealed_card_hash=CARD,
                       risk_basis="FULL_PREMIUM")
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([95.0]),
                  future_quote_lookup=_quotes({(100.0, "C"): (0.05, 0.10),
                                               (105.0, "C"): (0.01, 0.05)}),
                  entry_underlying=100.0)
    assert isinstance(out.pnl, float)
    assert out.pnl >= -f.net_debit - 1e-6, (
        f"lost {out.pnl} on a {f.net_debit} debit -- impossible")


def test_a_foreign_expiry_may_not_close_the_position():
    """The exact defect: same strikes, wrong expiry. It must refuse to
    price rather than silently resolve against another contract."""
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD,
                       risk_basis="FULL_PREMIUM")
    foreign = _quotes({(100.0, "C"): (99.0, 99.5)},
                      expiration="2024-12-20")
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=foreign, entry_underlying=100.0)
    assert out.pnl == "NOT_ESTIMABLE", (
        "a December quote closed a June position")


def test_the_fill_records_which_contract_it_bought():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    assert f.expiration == EXP
    assert EXP in f.fill_pedigree[0]


def test_an_option_without_contract_identity_is_refused():
    import pytest
    from dataclasses import replace
    anon = replace(_call(), expiration=None)
    with pytest.raises(ExecutionRefused):
        simulate_entry(anon, T=T, sealed_card_hash=CARD)


# --------------------------------- THE FRICTION ACCOUNTING IDENTITY
# pnl = mid_change - entry_friction - exit_friction, exactly. This is
# what separates "the thesis was wrong" from "the thesis was right and
# the spread took it" -- and it is the only test that can prove a
# large loss came from the market rather than from a bug.

def test_the_friction_identity_holds_exactly():
    f = simulate_entry(_vertical(), T=T, sealed_card_hash=CARD,
                       risk_basis="FULL_PREMIUM")
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([104.0]),
                  future_quote_lookup=_quotes({(100.0, "C"): (5.0, 6.5),
                                               (105.0, "C"): (2.0, 3.4)}),
                  entry_underlying=100.0)
    assert out.friction_identity_holds is True
    e = out.exit
    assert abs(e["mid_change"] - e["entry_friction"]
               - e["exit_friction"] - out.pnl) < 0.02


def test_a_right_thesis_can_still_lose_to_the_spread():
    """The Volmageddon case, in miniature: the position gains on mid and
    still loses money, because both exit spreads must be crossed. SPY
    2018-02-05 did exactly this -- 251 dollars of mid value against a
    155 dollar debit, realized as a 212 dollar loss."""
    f = simulate_entry(_vertical(), T=T, sealed_card_hash=CARD,
                       risk_basis="FULL_PREMIUM")
    # wide exit market, but the spread's mid value has RISEN
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106.0]),
                  future_quote_lookup=_quotes({(100.0, "C"): (4.0, 8.0),
                                               (105.0, "C"): (1.5, 5.5)}),
                  entry_underlying=100.0)
    assert out.mid_change > 0, "mid value should have risen"
    assert out.pnl < 0, "and the spread should still have taken it"
    assert out.friction_identity_holds is True
    assert out.exit_friction > 0


def test_missing_exit_quotes_withhold_the_identity():
    f = simulate_entry(_call(ask=3.0), T=T, sealed_card_hash=CARD)
    out = resolve(fill=f, sealed_card_hash=CARD,
                  future_underlying=_future([106]),
                  future_quote_lookup=_quotes({}), entry_underlying=100.0)
    assert out.friction_identity_holds == "NOT_ESTIMABLE"
    assert out.exit_friction == "NOT_ESTIMABLE"
