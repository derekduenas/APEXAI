"""BTC-L3 forced-action thesis.

The load-bearing tests are the ones that keep this honest: it must
never claim to see margin, never claim to predict a cascade, and never
offer a tradeable moment in the middle of one.
"""
from __future__ import annotations

from apex.btc_sleeve.forced_action import (
    FORCED_ACTION_STATES, NOT_ESTIMABLE, assess)
from apex.btc_sleeve.participant_state import Inputs, interpret
from apex.btc_sleeve.semantics import OI_DAILY_PUBLISHED, OI_REALTIME


def _inp(**kw):
    base = dict(oi_cadence=OI_REALTIME, oi_age_s=1.0,
                horizon_minutes=15.0, book_quality="VALID")
    base.update(kw)
    return Inputs(**base)


def _assess(prior=None, **kw):
    inp = _inp(**kw)
    ps = interpret(symbol="PBTCUCZ50", T="2026-08-23T18:00:00Z",
                   inputs=inp)
    return assess(participant_state=ps, inputs=inp,
                  prior_oi_change_pct=prior)


# ------------------------------------------------ what we cannot see

def test_margin_and_stops_are_declared_unobservable_always():
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert "margin balances" in t.unobservable
    assert "liquidation prices" in t.unobservable
    assert "stop-order placement" in t.unobservable


def test_forced_is_inferred_from_consequences_never_observed():
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert any("never observed directly" in c
               for c in t.competing_explanations)


def test_no_calibrated_probability_is_emitted():
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert t.calibration == "NONE_FITTED"
    assert t.decision_power == "NONE"


# ------------------------------------------------ the states

def test_deleveraging_in_progress_needs_all_three_conditions():
    """Rapid destruction, against the paying side, into a thin book."""
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert t.state == "DELEVERAGING_IN_PROGRESS"
    assert t.pressured_side == "LONGS"


def test_a_thick_book_is_not_deleveraging():
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=+5.0)
    assert t.state != "DELEVERAGING_IN_PROGRESS"


def test_destruction_that_favours_the_paying_side_is_not_forced():
    """OI falling while price moves IN FAVOUR of the payers is profit
    taking, not a squeeze."""
    t = _assess(price_change_pct=+2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert t.state != "DELEVERAGING_IN_PROGRESS"


def test_shorts_can_be_the_pressured_side_too():
    t = _assess(price_change_pct=+2.0, oi_change_pct=-4.0,
                funding_rate_annualized=-0.4,
                book_depth_change_pct=-35.0)
    assert t.state == "DELEVERAGING_IN_PROGRESS"
    assert t.pressured_side == "SHORTS"


def test_exhaustion_is_a_comparison_not_a_level():
    """Same window; only the PRIOR window differs."""
    still = _assess(prior=-3.0, price_change_pct=-2.0,
                    oi_change_pct=-4.0, funding_rate_annualized=0.5,
                    book_depth_change_pct=-35.0)
    assert still.state == "DELEVERAGING_IN_PROGRESS"
    decaying = _assess(prior=-12.0, price_change_pct=-2.0,
                       oi_change_pct=-4.0, funding_rate_annualized=0.5,
                       book_depth_change_pct=-35.0)
    assert decaying.state == "DELEVERAGING_EXHAUSTING"


def test_susceptible_is_not_an_event():
    t = _assess(price_change_pct=-0.05, oi_change_pct=0.0,
                funding_rate_annualized=0.6,
                book_depth_change_pct=-40.0)
    assert t.state == "SUSCEPTIBLE_NOT_TRIGGERED"
    assert t.tradeable_moment.startswith("NONE")
    assert any("never become cascades" in c
               for c in t.competing_explanations)


def test_ordinary_trade_reads_as_none_observed():
    t = _assess(price_change_pct=0.2, oi_change_pct=0.3,
                funding_rate_annualized=0.02,
                book_depth_change_pct=1.0)
    assert t.state == "NONE_OBSERVED"


def test_absence_of_signature_is_not_proof_nobody_is_forced():
    t = _assess(price_change_pct=0.2, oi_change_pct=0.3,
                funding_rate_annualized=0.02,
                book_depth_change_pct=1.0)
    assert any("not proof that nobody is being forced" in c
               for c in t.competing_explanations)


def test_unusable_inputs_refuse_the_question():
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                oi_cadence=OI_DAILY_PUBLISHED,
                funding_rate_annualized=0.5)
    assert t.state == NOT_ESTIMABLE
    assert "different from answering 'no'" in " ".join(t.because)


# --------------------------------- the edge, and its honest limits

def test_no_tradeable_moment_in_the_middle_of_a_cascade():
    """Front-running forced flow is a latency battle against giants."""
    t = _assess(price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert t.tradeable_moment.startswith("NONE")
    assert "latency battle" in t.tradeable_moment


def test_exhaustion_is_the_only_moment_offered_and_is_unproven():
    t = _assess(prior=-12.0, price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert "PATIENT_LIQUIDITY_INTO_EXHAUSTION" in t.tradeable_moment
    assert "unproven" in t.tradeable_moment
    assert "OBSERVE" in t.tradeable_moment


def test_every_thesis_states_what_would_falsify_it():
    for kw in ({"price_change_pct": -2.0, "oi_change_pct": -4.0,
                "funding_rate_annualized": 0.5,
                "book_depth_change_pct": -35.0},
               {"price_change_pct": -0.05, "oi_change_pct": 0.0,
                "funding_rate_annualized": 0.6,
                "book_depth_change_pct": -40.0},
               {"price_change_pct": 0.2, "oi_change_pct": 0.3,
                "funding_rate_annualized": 0.02,
                "book_depth_change_pct": 1.0}):
        t = _assess(**kw)
        assert t.falsified_by, f"{t.state} offered no falsifier"


def test_exhaustion_admits_a_pause_looks_the_same():
    t = _assess(prior=-12.0, price_change_pct=-2.0, oi_change_pct=-4.0,
                funding_rate_annualized=0.5,
                book_depth_change_pct=-35.0)
    assert any("pause is indistinguishable" in c
               for c in t.competing_explanations)


def test_every_state_emitted_is_declared():
    for kw in ({"price_change_pct": -2.0, "oi_change_pct": -4.0,
                "funding_rate_annualized": 0.5,
                "book_depth_change_pct": -35.0},
               {"price_change_pct": 0.2, "oi_change_pct": 0.3},
               {"price_change_pct": -0.05, "oi_change_pct": 0.0,
                "funding_rate_annualized": 0.6,
                "book_depth_change_pct": -40.0}):
        assert _assess(**kw).state in FORCED_ACTION_STATES
