"""CaptainFrontierShadow — F9. Proves the eight-state lattice is
deterministic, anti-anchoring is structural (prior REASONING can never
leak into a new review, only the prior STATE LABEL and INPUT SNAPSHOT
can), a terminal INVALIDATE never resurrects, and TRADE/BUY/SELL/SIZE
are not even words this module can produce.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.captain_shadow import (STATES, CaptainFrontierShadowState,
                                           CaptainShadowError, review,
                                           what_changed)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _inputs(**kw):
    base = {"curve_state": "UNKNOWN", "curve_direction": "UNKNOWN",
           "curve_expression": "UNKNOWN", "curve_likelihood": "UNKNOWN",
           "participant_trap": "NONE", "participant_direction": "UNKNOWN",
           "propagation_state": "UNKNOWN", "leading_edge_rank": None,
           "leading_edge_entry_quality": "UNKNOWN",
           "assassin2_familiarity": "FAMILIAR", "assassin2_caution_label": "NONE",
           "observation_quality": "FULL", "model_market_tally_agrees": None}
    base.update(kw)
    return base


def test_no_signal_at_all_is_ignore():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(), now=T0, known_from=T0)
    assert st.state == "IGNORE"
    assert st.prior_state is None


def test_strong_direction_and_entry_and_transition_is_serious():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(curve_direction="UP",
                                      curve_likelihood="HIGH",
                                      leading_edge_entry_quality="GOOD"),
               now=T0, known_from=T0)
    assert st.state == "SERIOUS"
    assert st.direction_quality == "STRONG"
    assert st.transition_quality == "STRONG"


def test_strong_direction_but_poor_entry_waits_for_entry():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(curve_direction="UP",
                                      curve_likelihood="HIGH",
                                      leading_edge_entry_quality="POOR"),
               now=T0, known_from=T0)
    assert st.state == "WAIT_FOR_ENTRY"


def test_strong_transition_unclear_direction_waits_for_confirmation():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(curve_direction="MIXED",
                                      curve_likelihood="HIGH"),
               now=T0, known_from=T0)
    assert st.state == "WAIT_FOR_CONFIRMATION"


def test_moderate_transition_alone_is_develop():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(curve_direction="MODERATE_PLACEHOLDER",
                                      curve_likelihood="MODERATE"),
               now=T0, known_from=T0)
    assert st.state == "DEVELOP"


def test_weak_transition_with_no_prior_engagement_is_watch():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(curve_likelihood="LOW"),
               now=T0, known_from=T0)
    assert st.state == "WATCH"


def test_weak_transition_after_prior_engagement_is_degrade_not_watch():
    prior = review(None, candidate_id="C1", subject="AAPL",
                   current_inputs=_inputs(curve_likelihood="MODERATE",
                                          curve_direction="MODERATE_PLACEHOLDER"),
                   now=T0, known_from=T0)
    assert prior.state == "DEVELOP"
    later = review(prior, candidate_id="C1", subject="AAPL",
                   current_inputs=_inputs(curve_likelihood="LOW",
                                          curve_direction="MODERATE_PLACEHOLDER"),
                   now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    assert later.state == "DEGRADE"


def test_data_conflict_invalidates_an_engaged_thesis():
    prior = review(None, candidate_id="C1", subject="AAPL",
                   current_inputs=_inputs(curve_direction="UP",
                                          curve_likelihood="HIGH",
                                          leading_edge_entry_quality="GOOD"),
                   now=T0, known_from=T0)
    assert prior.state == "SERIOUS"
    later = review(prior, candidate_id="C1", subject="AAPL",
                   current_inputs=_inputs(curve_direction="UP",
                                          curve_likelihood="HIGH",
                                          leading_edge_entry_quality="GOOD",
                                          assassin2_familiarity="DATA_CONFLICT"),
                   now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    assert later.state == "INVALIDATE"


def test_data_conflict_on_a_never_engaged_thesis_only_degrades():
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(assassin2_familiarity="DATA_CONFLICT"),
               now=T0, known_from=T0)
    assert st.state == "DEGRADE"


def test_invalidated_thesis_refuses_to_resurrect():
    prior = review(None, candidate_id="C1", subject="AAPL",
                   current_inputs=_inputs(curve_direction="UP",
                                          curve_likelihood="HIGH",
                                          leading_edge_entry_quality="GOOD"),
                   now=T0, known_from=T0)
    invalidated = review(prior, candidate_id="C1", subject="AAPL",
                         current_inputs=_inputs(curve_direction="UP",
                                                curve_likelihood="HIGH",
                                                leading_edge_entry_quality="GOOD",
                                                assassin2_familiarity="DATA_CONFLICT"),
                         now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    assert invalidated.state == "INVALIDATE"
    with pytest.raises(CaptainShadowError):
        review(invalidated, candidate_id="C1", subject="AAPL",
              current_inputs=_inputs(curve_direction="UP", curve_likelihood="HIGH",
                                     leading_edge_entry_quality="GOOD"),
              now=T0 + pd.Timedelta(minutes=10), known_from=T0 + pd.Timedelta(minutes=10))


# ---- anti-anchoring: prior REASONING can never leak in ------------------

def test_prior_reasoning_content_never_affects_the_new_review():
    """Two priors with the SAME state and inputs_snapshot but wildly
    different reasoning/competing_explanation text must produce an
    IDENTICAL new review -- because review() cannot read those fields."""
    inputs = _inputs(curve_likelihood="MODERATE")
    p1 = review(None, candidate_id="C1", subject="AAPL", current_inputs=inputs,
               now=T0, known_from=T0, competing_explanation="theory A")
    p2 = CaptainFrontierShadowState(
        candidate_id="C1", subject="AAPL", state=p1.state, prior_state=None,
        transition_quality=p1.transition_quality,
        direction_quality=p1.direction_quality, entry_quality=p1.entry_quality,
        data_quality=p1.data_quality, model_familiarity=p1.model_familiarity,
        what_changed=(), competing_explanation="a COMPLETELY different theory Z",
        falsification="something totally different", reasoning=("fabricated",),
        inputs_snapshot=p1.inputs_snapshot, known_from=str(T0), as_of=str(T0))

    new_inputs = _inputs(curve_likelihood="MODERATE", curve_direction="UP")
    r1 = review(p1, candidate_id="C1", subject="AAPL", current_inputs=new_inputs,
               now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    r2 = review(p2, candidate_id="C1", subject="AAPL", current_inputs=new_inputs,
               now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    assert r1.state == r2.state
    assert r1.transition_quality == r2.transition_quality
    assert r1.direction_quality == r2.direction_quality


def test_review_function_signature_has_no_prior_reasoning_parameter():
    import inspect
    params = inspect.signature(review).parameters
    assert "prior_reasoning" not in params
    assert "prior_competing_explanation" not in params


# ---- what_changed diff -----------------------------------------------

def test_what_changed_is_empty_when_nothing_differs():
    a = _inputs(curve_direction="UP")
    assert what_changed(a, a) == ()


def test_what_changed_reports_only_the_differing_fields():
    a = _inputs(curve_direction="UP", curve_likelihood="HIGH")
    b = _inputs(curve_direction="DOWN", curve_likelihood="HIGH")
    changes = what_changed(a, b)
    assert len(changes) == 1
    assert changes[0]["field"] == "curve_direction"
    assert changes[0]["was"] == "UP" and changes[0]["now"] == "DOWN"


# ---- vocabulary law --------------------------------------------------

def test_no_trade_words_anywhere_in_the_state_vocabulary():
    forbidden = {"TRADE", "BUY", "SELL", "SIZE", "OVERRIDE"}
    assert not (set(STATES) & forbidden)


def test_no_scalar_confidence_field_exists():
    fields = set(CaptainFrontierShadowState.__dataclass_fields__)
    assert not (fields & {"confidence", "conviction_score", "probability"})


def test_bad_state_refused_at_construction():
    with pytest.raises(CaptainShadowError):
        CaptainFrontierShadowState(
            candidate_id="C1", subject="AAPL", state="BUY", prior_state=None,
            transition_quality="UNKNOWN", direction_quality="UNKNOWN",
            entry_quality="UNKNOWN", data_quality="UNKNOWN",
            model_familiarity="UNKNOWN", what_changed=(),
            competing_explanation=None, falsification="x", reasoning=())


def test_determinism_same_inputs_twice_byte_identical():
    a = review(None, candidate_id="C1", subject="AAPL",
              current_inputs=_inputs(curve_likelihood="MODERATE"),
              now=T0, known_from=T0)
    b = review(None, candidate_id="C1", subject="AAPL",
              current_inputs=_inputs(curve_likelihood="MODERATE"),
              now=T0, known_from=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.captain_shadow as cs
    monkeypatch.setattr(cs, "LEDGER", tmp_path / "cs.jsonl")
    st = review(None, candidate_id="C1", subject="AAPL",
               current_inputs=_inputs(), now=T0, known_from=T0)
    rec1 = cs.persist(st)
    rec2 = cs.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
