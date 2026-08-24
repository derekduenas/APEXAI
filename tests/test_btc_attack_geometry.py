"""BTC-L3 attack geometry.

The tests that carry weight: it must refuse mid-cascade, it must refuse
a good location with no thesis, and it must judge our size against the
ACTUAL book rather than against an imagined one.
"""
from __future__ import annotations

from apex.btc_sleeve.attack_geometry import (
    EXECUTION_STATES, NOT_ESTIMABLE, RULE_CLASSIFICATION, assess)
from apex.btc_sleeve.forced_action import assess as forced_assess
from apex.btc_sleeve.participant_state import Inputs, interpret
from apex.btc_sleeve.semantics import OI_REALTIME


def _thesis(prior=None, **kw):
    base = dict(oi_cadence=OI_REALTIME, oi_age_s=1.0,
                horizon_minutes=15.0, book_quality="VALID")
    base.update(kw)
    inp = Inputs(**base)
    ps = interpret(symbol="PBTCUCZ50", T="T", inputs=inp)
    return forced_assess(participant_state=ps, inputs=inp,
                         prior_oi_change_pct=prior)


def _exhausting():
    return _thesis(prior=-12.0, price_change_pct=-2.0,
                   oi_change_pct=-4.0, funding_rate_annualized=0.5,
                   book_depth_change_pct=-35.0)


def _mid_cascade():
    return _thesis(prior=-3.0, price_change_pct=-2.0,
                   oi_change_pct=-4.0, funding_rate_annualized=0.5,
                   book_depth_change_pct=-35.0)


def _book(bid=15450.0, ask=15455.0, bid_qty=50, ask_qty=60,
          quality="VALID"):
    return {"book_quality": quality, "best_bid_raw": bid,
            "best_ask_raw": ask, "best_bid_qty": bid_qty,
            "best_ask_qty": ask_qty}


_DEFAULT = object()


def _assess(thesis=None, book=_DEFAULT, **kw):
    # sentinel, not None: passing book=None must actually reach the
    # code as None, or the "no book" test silently tests nothing
    base = dict(subject="PBTCUCZ50", T="T",
                thesis=thesis or _exhausting(),
                book_top=_book() if book is _DEFAULT else book,
                atr=30.0, reference_price=15452.5,
                recent_extreme=15440.0, intended_size=1,
                tick_size=1.0)
    base.update(kw)
    return assess(**base)


# ------------------------------------------------ the thesis half

def test_mid_cascade_is_structurally_refused():
    """Racing liquidation engines is a latency contest we lose."""
    g = _assess(thesis=_mid_cascade())
    assert g.attackable is False
    assert "MID_CASCADE_NO_ATTACK" in g.structural_wounds
    assert "latency race" in " ".join(g.reasoning)


def test_exhaustion_is_the_moment_that_can_be_attacked():
    g = _assess()
    assert g.thesis_credible is True
    assert g.attackable is True
    assert "needs patience rather than speed" in " ".join(g.reasoning)


def test_the_attack_is_the_other_side_of_the_forced_flow():
    """Forced LONGS were selling; the attack is to buy from them."""
    g = _assess()
    assert g.pressured_side == "LONGS"
    assert g.direction == "LONG"
    assert "not a continuation" in " ".join(g.reasoning)


def test_forced_shorts_invert_the_direction():
    t = _thesis(prior=-12.0, price_change_pct=+2.0, oi_change_pct=-4.0,
                funding_rate_annualized=-0.4,
                book_depth_change_pct=-35.0)
    g = _assess(thesis=t, recent_extreme=15470.0)
    assert g.pressured_side == "SHORTS"
    assert g.direction == "SHORT"


def test_a_great_location_with_no_thesis_is_not_an_attack():
    quiet = _thesis(price_change_pct=0.1, oi_change_pct=0.1,
                    funding_rate_annualized=0.01,
                    book_depth_change_pct=1.0)
    g = _assess(thesis=quiet)
    assert g.attackable is False
    assert "location quality alone is not a reason to act" in \
        " ".join(g.reasoning)


def test_an_unaskable_thesis_refuses_structurally():
    from apex.btc_sleeve.semantics import OI_DAILY_PUBLISHED
    t = _thesis(price_change_pct=-2.0, oi_change_pct=-4.0,
                oi_cadence=OI_DAILY_PUBLISHED,
                funding_rate_annualized=0.5)
    g = _assess(thesis=t)
    assert "THESIS_NOT_ESTIMABLE" in g.structural_wounds
    assert "not a reason to attack" in " ".join(g.reasoning)


# ------------------------------------------------ the location half

def test_an_invalid_book_is_structurally_impossible():
    g = _assess(book=_book(quality="INVALID"))
    assert g.execution_state == "EXECUTION_IMPOSSIBLE"
    assert "BOOK_NOT_VALID" in g.structural_wounds
    assert g.attackable is False


def test_a_crossed_book_is_refused():
    g = _assess(book=_book(bid=15460.0, ask=15455.0))
    assert "CROSSED_OR_LOCKED" in g.structural_wounds
    assert g.attackable is False


def test_no_book_at_all_refuses_rather_than_assuming():
    g = _assess(book=None)
    assert "BOOK_NOT_VALID" in g.structural_wounds


def test_size_is_judged_against_the_actual_book():
    ok = _assess(intended_size=10, book=_book(ask_qty=60))
    assert ok.execution_state == "EXECUTION_ACCEPTABLE"
    too_big = _assess(intended_size=500, book=_book(ask_qty=60))
    assert too_big.execution_state == "EXECUTION_DEGRADED"
    assert "SIZE_EXCEEDS_BOOK" in too_big.wounds
    assert "SIZE_EXCEEDS_BOOK" not in too_big.structural_wounds, \
        "being too big is a quality prior, not an impossibility"


def test_a_negligible_footprint_is_named_as_the_small_account_edge():
    g = _assess(intended_size=1, book=_book(ask_qty=60))
    assert g.small_account_note is not None
    assert "a fund does not" in g.small_account_note


def test_a_wide_spread_downgrades_without_refusing():
    g = _assess(book=_book(bid=15400.0, ask=15450.0))
    assert "WIDE_SPREAD" in g.wounds
    assert "WIDE_SPREAD" not in g.structural_wounds
    assert "paid twice before the thesis pays once" in \
        " ".join(g.reasoning)


# ------------------------------------------------ risk and payoff

def test_an_attack_without_an_invalidation_is_refused():
    g = _assess(recent_extreme=None)
    assert "NO_INVALIDATION_LEVEL" in g.structural_wounds
    assert "an attack without an invalidation is a hope" in \
        " ".join(g.reasoning)


def test_a_distant_invalidation_is_flagged():
    g = _assess(recent_extreme=15300.0, atr=30.0)
    assert "WIDE_INVALIDATION" in g.wounds
    assert isinstance(g.invalidation_distance_atr, float)


def test_an_unfavourable_tail_is_flagged():
    """Reward must exceed risk or being right does not pay."""
    g = _assess(recent_extreme=15400.0, atr=30.0)   # risk 52.5, reward 30
    assert "UNFAVOURABLE_TAIL" in g.wounds
    assert isinstance(g.tail_ratio, float)
    assert g.tail_ratio < 1.5


def test_extended_chase_is_flagged_not_ignored():
    g = _assess(recent_extreme=15340.0, atr=30.0)
    assert g.chase_state in ("HIGH", "EXTREME")
    assert "EXTENDED_CHASE" in g.wounds
    assert "already happened" in " ".join(g.reasoning)


# ------------------------------------------------ governance

def test_every_rule_is_classified():
    g = _assess()
    for w in g.wounds:
        assert w in RULE_CLASSIFICATION
    assert set(RULE_CLASSIFICATION.values()) <= {
        "STRUCTURAL_INVALIDITY", "EXPLORATORY_QUALITY_PRIOR"}, \
        "no LEARNED_ECONOMIC_THRESHOLD is authorized at this authority"


def test_only_structural_wounds_can_refuse():
    """Quality priors downgrade; they must not veto on their own."""
    g = _assess(book=_book(bid=15400.0, ask=15450.0))   # wide spread
    assert "WIDE_SPREAD" in g.wounds
    assert not g.structural_wounds
    assert g.attackable is True


def test_geometry_holds_no_decision_power_and_no_calibration():
    g = _assess()
    assert g.decision_power == "NONE"
    assert g.calibration == "NONE_FITTED"
    rec = g.as_record()
    assert rec["kind"] == "btc_attack_geometry"
    assert rec["evidence_class"] == "PROSPECTIVE_LIVE_CAPTURE"


def test_execution_state_is_always_declared():
    for book in (None, _book(), _book(quality="INVALID"),
                 _book(ask_qty=0)):
        assert _assess(book=book).execution_state in EXECUTION_STATES


def test_continuous_measurements_are_preserved_for_later_study():
    g = _assess()
    for f in ("invalidation_distance", "invalidation_distance_atr",
              "tail_ratio", "extension_atr", "spread_ticks",
              "executable_size", "size_vs_book"):
        assert getattr(g, f) is not None
