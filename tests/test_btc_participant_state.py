"""BTC-L3 participant state.

The tests that matter most here are the ones that stop L3 becoming a
folk-wisdom engine: no reading may be stated as fact, the identification
problem must survive every code path, and inputs that cannot carry an
inference must produce NOT_ESTIMABLE rather than a quieter version of
the same claim.
"""
from __future__ import annotations

from apex.btc_sleeve.participant_state import (
    INTERPRETATIONS, NOT_ESTIMABLE, SUPPORT_LEVELS, Inputs, interpret)
from apex.btc_sleeve.semantics import (
    OI_DAILY_PUBLISHED, OI_DELAYED, OI_NOT_AVAILABLE, OI_REALTIME)


def _rt(**kw):
    base = dict(oi_cadence=OI_REALTIME, oi_age_s=1.0,
                horizon_minutes=15.0, book_quality="VALID")
    base.update(kw)
    return Inputs(**base)


def _state(**kw):
    return interpret(symbol="PBTCUCZ50", T="2026-08-23T18:00:00Z",
                     inputs=_rt(**kw))


# ------------------------------------------- the identification law

def test_the_folk_law_is_never_stated_as_fact():
    """price up + OI up may NEVER be reported as 'new longs'."""
    s = _state(price_change_pct=1.5, oi_change_pct=3.0,
               funding_rate_annualized=0.4)
    lb = s.by_name("POSSIBLE_LONG_BUILD")
    assert lb.support in ("CONSISTENT", "WEAKLY_CONSISTENT")
    assert lb.competing_explanations, \
        "a reading with no competitor is a law, and L3 may not make laws"
    assert any("short on the other side" in c
               for c in lb.competing_explanations)
    assert lb.interpretation != "NEW_LONGS"


def test_every_supported_reading_carries_a_competing_explanation():
    s = _state(price_change_pct=1.2, oi_change_pct=2.5,
               funding_rate_annualized=0.35,
               spot_change_pct=1.0, perp_change_pct=1.4,
               book_depth_change_pct=-30.0)
    for r in s.readings:
        if r.support in ("CONSISTENT", "WEAKLY_CONSISTENT"):
            assert r.competing_explanations, (
                f"{r.interpretation} asserted with no alternative")


def test_long_and_short_build_are_never_both_asserted():
    s = _state(price_change_pct=1.5, oi_change_pct=3.0,
               funding_rate_annualized=0.4)
    lb = s.by_name("POSSIBLE_LONG_BUILD").support
    sb = s.by_name("POSSIBLE_SHORT_BUILD").support
    assert not (lb == "CONSISTENT" and sb == "CONSISTENT")


def test_no_calibrated_probability_is_ever_emitted():
    s = _state(price_change_pct=1.0, oi_change_pct=2.0)
    assert s.calibration == "NONE_FITTED"
    for r in s.readings:
        assert r.calibration == "NONE_FITTED"
        assert r.support in SUPPORT_LEVELS
        assert not isinstance(r.support, float)


def test_l3_holds_no_decision_power():
    s = _state(price_change_pct=1.0, oi_change_pct=2.0)
    assert s.decision_power == "NONE"
    assert all(r.decision_power == "NONE" for r in s.readings)


# ------------------------------------------------- quality awareness

def test_daily_open_interest_cannot_support_an_intraday_claim():
    s = interpret(symbol="X", T="t", inputs=Inputs(
        price_change_pct=2.0, oi_change_pct=5.0,
        oi_cadence=OI_DAILY_PUBLISHED, horizon_minutes=15.0))
    for name in ("POSSIBLE_LONG_BUILD", "LEVERAGE_EXPANSION",
                 "COVERING", "DELEVERAGING_EXHAUSTION"):
        r = s.by_name(name)
        assert r.support == NOT_ESTIMABLE
        assert "yesterday's book" in r.limiting_factor


def test_delayed_oi_is_usable_only_within_its_own_horizon():
    fresh = interpret(symbol="X", T="t", inputs=Inputs(
        price_change_pct=2.0, oi_change_pct=5.0, oi_cadence=OI_DELAYED,
        oi_age_s=300.0, horizon_minutes=15.0))
    assert fresh.by_name("LEVERAGE_EXPANSION").support == "CONSISTENT"
    stale = interpret(symbol="X", T="t", inputs=Inputs(
        price_change_pct=2.0, oi_change_pct=5.0, oi_cadence=OI_DELAYED,
        oi_age_s=5400.0, horizon_minutes=15.0))
    assert stale.by_name("LEVERAGE_EXPANSION").support == NOT_ESTIMABLE


def test_absent_open_interest_refuses_rather_than_guesses():
    s = interpret(symbol="X", T="t", inputs=Inputs(
        price_change_pct=2.0, oi_cadence=OI_NOT_AVAILABLE))
    assert s.by_name("POSSIBLE_LONG_BUILD").support == NOT_ESTIMABLE
    assert s.data_quality in ("PARTIAL", "INSUFFICIENT")


def test_an_invalid_book_cannot_measure_its_own_thinning():
    s = _state(book_depth_change_pct=-40.0, book_quality="INVALID")
    r = s.by_name("BOOK_WITHDRAWAL")
    assert r.support == NOT_ESTIMABLE
    assert "invalid book" in r.limiting_factor


# ------------------------------------------------------- the readings

def test_noise_is_not_a_signal():
    s = _state(price_change_pct=0.01, oi_change_pct=0.05)
    assert s.by_name("LEVERAGE_EXPANSION").support == "INCONSISTENT"
    assert s.by_name("POSSIBLE_LONG_BUILD").support == "INCONSISTENT"


def test_funding_corroborates_a_build_but_does_not_create_one():
    weak = _state(price_change_pct=1.0, oi_change_pct=2.0)
    assert weak.by_name("POSSIBLE_LONG_BUILD").support == \
        "WEAKLY_CONSISTENT"
    strong = _state(price_change_pct=1.0, oi_change_pct=2.0,
                    funding_rate_annualized=0.5)
    assert strong.by_name("POSSIBLE_LONG_BUILD").support == "CONSISTENT"
    # funding alone, with OI falling, must NOT manufacture a build
    none = _state(price_change_pct=1.0, oi_change_pct=-2.0,
                  funding_rate_annualized=0.5)
    assert none.by_name("POSSIBLE_LONG_BUILD").support == "INCONSISTENT"


def test_short_build_reads_from_aggressive_selling_into_new_contracts():
    s = _state(price_change_pct=-1.2, oi_change_pct=3.0,
               funding_rate_annualized=-0.2)
    assert s.by_name("POSSIBLE_SHORT_BUILD").support == "CONSISTENT"
    assert s.by_name("POSSIBLE_LONG_BUILD").support == "INCONSISTENT"


def test_a_trap_needs_both_a_build_and_a_move_against_it():
    trapped = _state(price_change_pct=-1.5, oi_change_pct=3.0,
                     funding_rate_annualized=0.4)
    assert trapped.by_name("LONG_TRAP").support == "WEAKLY_CONSISTENT"
    # same funding and OI, price NOT against them -> no trap
    fine = _state(price_change_pct=1.5, oi_change_pct=3.0,
                  funding_rate_annualized=0.4)
    assert fine.by_name("LONG_TRAP").support == "INCONSISTENT"


def test_a_trap_admits_that_underwater_is_not_forced():
    r = _state(price_change_pct=-1.5, oi_change_pct=3.0,
               funding_rate_annualized=0.4).by_name("LONG_TRAP")
    assert any("not the same as forced" in c
               for c in r.competing_explanations)


def test_covering_admits_profit_taking_looks_identical():
    r = _state(price_change_pct=1.5, oi_change_pct=-3.0
               ).by_name("COVERING")
    assert r.support == "WEAKLY_CONSISTENT"
    assert any("taking profit" in c for c in r.competing_explanations)


def test_leadership_refuses_to_claim_causation_from_a_gap():
    s = _state(spot_change_pct=0.5, perp_change_pct=1.4)
    r = s.by_name("PERP_LED")
    assert r.support == "WEAKLY_CONSISTENT"
    assert any("not lead-lag" in c for c in r.competing_explanations)
    assert s.by_name("SPOT_LED").support == "INCONSISTENT"


def test_cascade_requires_the_conjunction_not_either_half():
    crowded_only = _state(funding_rate_annualized=0.6,
                          book_depth_change_pct=+5.0)
    assert crowded_only.by_name(
        "CASCADE_SUSCEPTIBILITY").support == "INCONSISTENT"
    thin_only = _state(funding_rate_annualized=0.01,
                       book_depth_change_pct=-40.0)
    assert thin_only.by_name(
        "CASCADE_SUSCEPTIBILITY").support == "INCONSISTENT"
    both = _state(funding_rate_annualized=0.6,
                  book_depth_change_pct=-40.0)
    assert both.by_name("CASCADE_SUSCEPTIBILITY").support == "CONSISTENT"


def test_cascade_susceptibility_is_not_prediction():
    r = _state(funding_rate_annualized=0.6,
               book_depth_change_pct=-40.0).by_name(
        "CASCADE_SUSCEPTIBILITY")
    assert any("not prediction" in c for c in r.competing_explanations)
    assert any("stop placement" in c for c in r.competing_explanations)


def test_exhaustion_admits_it_is_only_visible_afterwards():
    r = _state(price_change_pct=0.05, oi_change_pct=-4.0
               ).by_name("DELEVERAGING_EXHAUSTION")
    assert r.support == "WEAKLY_CONSISTENT"
    assert any("only visible afterwards" in c
               for c in r.competing_explanations)


# ------------------------------------------------------- completeness

def test_every_authorized_interpretation_is_emitted_every_time():
    s = _state(price_change_pct=1.0, oi_change_pct=2.0)
    emitted = {r.interpretation for r in s.readings}
    assert emitted == set(INTERPRETATIONS), (
        f"missing {set(INTERPRETATIONS) - emitted}")


def test_no_unauthorized_interpretation_can_appear():
    s = _state(price_change_pct=1.0, oi_change_pct=2.0,
               funding_rate_annualized=0.3,
               spot_change_pct=0.8, perp_change_pct=1.1,
               book_depth_change_pct=-20.0)
    for r in s.readings:
        assert r.interpretation in INTERPRETATIONS


def test_the_record_carries_the_identification_law():
    rec = _state(price_change_pct=1.0, oi_change_pct=2.0).as_record()
    assert "never WHO wanted them" in rec["identification_law"]
    assert rec["evidence_class"] == "PROSPECTIVE_LIVE_CAPTURE"
    assert rec["kind"] == "btc_participant_state"


def test_a_totally_empty_input_yields_insufficient_not_a_view():
    s = interpret(symbol="X", T="t", inputs=Inputs())
    assert s.data_quality == "INSUFFICIENT"
    assert all(r.support == NOT_ESTIMABLE for r in s.readings)
