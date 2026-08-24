"""BTC paper execution: the options sleeve's proven laws, on the book."""
from __future__ import annotations

import pytest

from apex.btc_sleeve.attack_geometry import assess
from apex.btc_sleeve.paper_execution import (
    ExecutionRefused, resolve, simulate_entry)
from tests.test_btc_attack_geometry import _book, _exhausting

CARD = "c" * 64


def _geometry(**kw):
    base = dict(subject="PBTCUCZ50", T="T", thesis=_exhausting(),
                book_top=_book(), atr=30.0, reference_price=15452.5,
                recent_extreme=15440.0, intended_size=1, tick_size=1.0)
    base.update(kw)
    return assess(**base)


def _fill(**kw):
    return simulate_entry(geometry=_geometry(), T="T",
                          sealed_card_hash=CARD, **kw)


def _top(bid, ask, quality="VALID"):
    return {"best_bid_raw": bid, "best_ask_raw": ask,
            "book_quality": quality}


# ------------------------------------------------ sequence law

def test_entry_refuses_without_a_sealed_card():
    with pytest.raises(ExecutionRefused):
        simulate_entry(geometry=_geometry(), T="T",
                       sealed_card_hash=None)


def test_resolution_refuses_a_mismatched_card():
    f = _fill()
    with pytest.raises(ExecutionRefused):
        resolve(fill=f, sealed_card_hash="d" * 64,
                path=[_top(15450, 15455)])


def test_an_unattackable_geometry_cannot_be_filled():
    g = _geometry(book_top=_book(quality="INVALID"))
    with pytest.raises(ExecutionRefused) as e:
        simulate_entry(geometry=g, T="T", sealed_card_hash=CARD)
    assert "refusals are refusals" in str(e.value)


# ------------------------------------------------ fill law

def test_a_long_pays_the_ask_and_records_the_half_spread():
    f = _fill()
    assert f.direction == "LONG"
    assert f.entry_price == 15455.0          # the ask, not the mid
    assert f.side_crossed == "ASK"
    assert f.entry_friction_ticks == 2.5     # (15455-15450)/2


def test_fill_size_is_capped_by_resting_liquidity():
    f = simulate_entry(geometry=_geometry(book_top=_book(ask_qty=3)),
                       T="T", sealed_card_hash=CARD, contracts=10)
    assert f.contracts == 3
    assert f.fill_capped_by_book is True


# ------------------------------------------------ risk law

def test_1R_is_the_declared_invalidation_loss_not_the_realized_one():
    f = _fill()
    assert f.risk_basis == "PLANNED_INVALIDATION"
    # entry 15455, invalidation 15440 -> 15 ticks * $5
    assert f.declared_1R_usd == 75.0


def test_r_multiple_divides_by_declared_1R():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15470, 15475)])
    # exit long on the BID at 15470: (15470-15455)*5 = +75
    assert out.pnl_usd == 75.0
    assert out.r_multiple == 1.0


# ------------------------------------------------ resolution

def test_invalidation_exits_at_the_first_touch():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15448, 15453), _top(15439, 15444),
                        _top(15480, 15485)])
    assert out.exit_reason == "INVALIDATED"
    assert out.exit_price == 15439.0
    assert out.pnl_usd == -80.0              # worse than 1R: gap-through
    assert out.r_multiple == pytest.approx(-80 / 75, abs=1e-3)


def test_a_gap_through_invalidation_is_not_flattered_to_1R():
    """The exit is the BID we could actually hit, not the level we
    wished for."""
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15400, 15405)])
    assert out.exit_reason == "INVALIDATED"
    assert out.pnl_usd == -275.0             # 55 ticks against us
    assert out.r_multiple < -3.0


def test_ambiguous_observations_resolve_against_us():
    """One top showing both levels touched takes the invalidation."""
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD, target=15470.0,
                  path=[_top(15439, 15490)])
    assert out.exit_reason == "INVALIDATED"


def test_target_exits_when_reached_cleanly():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD, target=15470.0,
                  path=[_top(15460, 15465), _top(15471, 15476)])
    assert out.exit_reason == "TARGET"
    assert out.pnl_usd == 80.0


def test_horizon_exit_marks_out_at_the_last_valid_book():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15451, 15456), _top(15456, 15461)])
    assert out.exit_reason == "HORIZON"
    assert out.exit_price == 15456.0


def test_invalid_books_are_skipped_never_traded():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15400, 15405, quality="INVALID"),
                        _top(15460, 15465)])
    assert out.exit_reason == "HORIZON"
    assert out.exit_price == 15460.0, \
        "the invalid book's panic prices must not resolve anything"


def test_no_valid_path_withholds_rather_than_guessing():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15400, 15405, quality="INVALID")])
    assert out.exit_reason == "NO_VALID_PATH"
    assert out.pnl_usd == "NOT_ESTIMABLE"


# ------------------------------------------------ friction identity

def test_the_friction_identity_holds_exactly():
    f = _fill()
    for path in ([_top(15470, 15475)], [_top(15439, 15444)],
                 [_top(15451, 15458)]):
        out = resolve(fill=f, sealed_card_hash=CARD, path=path)
        assert out.friction_identity_holds is True
        assert abs(out.mid_change_usd - out.entry_friction_usd
                   - out.exit_friction_usd - out.pnl_usd) < 0.02


def test_a_flat_mid_still_loses_the_spread():
    """The market went nowhere; we still paid to be there."""
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15450, 15455)])
    assert out.mid_change_usd == 0.0
    assert out.pnl_usd == -25.0              # both half-spreads
    assert out.friction_identity_holds is True


def test_outcome_is_stamped_prospective_and_powerless():
    f = _fill()
    out = resolve(fill=f, sealed_card_hash=CARD,
                  path=[_top(15460, 15465)])
    rec = out.as_record()
    assert rec["evidence_class"] == "PROSPECTIVE_PAPER"
    assert rec["decision_power"] == "NONE_PAPER"
    assert "exits on the BID" in rec["law"]
