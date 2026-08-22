"""ACCEPTANCE MOVIE — deterministic synthetic proof that the Phase 1.0
re-underwriting fix makes Captain actually change its mind as reality
changes, and that a terminally-invalidated thesis stays dead.

T0 candidate appears, Curve POSITIVE          -> Captain forms a view
T1 Curve strengthens                          -> Captain re-reviews
T2 Propagation confirms                       -> Captain re-reviews
T3 Entry quality deteriorates                 -> Captain re-reviews
T4 Assassin objection appears                 -> Captain re-reviews
T5 thesis breaks                              -> Captain can INVALIDATE
T6 new positive evidence appears              -> OLD thesis STAYS INVALIDATED

This movie asserts the ORCHESTRATION contract (was Captain asked? was
Assassin refreshed first? did the terminal law hold?). It deliberately
does NOT assert which specific state Captain chooses at each step --
that is captain_shadow's own judgment semantics, which Phase 1.0 did
not touch and this movie must not silently pin down.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2 import reunderwrite_ledger as rl
from apex.frontier2 import reunderwrite_trigger as rt

T_BASE = pd.Timestamp("2026-08-19T13:35:00Z")

FORBIDDEN_AUTHORITY_WORDS = ("place_order", "submit_order", "size_position",
                             "capital_authority_granted", "execute")


def _inputs(**over):
    base = {
        "curve_state": "POSITIVE_TRANSITION", "curve_direction": "UP",
        "curve_expression": "CONFIRMED_EXPRESSION", "curve_likelihood": "LOW",
        "expectation_violation_state": "NONE",
        "participant_trap": "NONE", "participant_direction": "UNKNOWN",
        "propagation_state": "UNKNOWN", "leading_edge_entry_quality": "UNKNOWN",
        "observation_quality": "FULL", "system_cognition_state": "FULL",
        "model_market_tally_agrees": None,
        "assassin2_familiarity": "FAMILIAR", "assassin2_caution_label": "NONE",
    }
    base.update(over)
    return base


SCENES = [
    ("T0 candidate appears, Curve POSITIVE", _inputs(), 0),
    ("T1 Curve strengthens", _inputs(curve_likelihood="HIGH"), 60),
    ("T2 Propagation confirms",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED"), 120),
    ("T3 Entry quality deteriorates",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="POOR"), 180),
    ("T4 Assassin objection appears",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="POOR",
             assassin2_familiarity="DATA_CONFLICT",
             assassin2_caution_label="SEVERE"), 240),
    ("T5 thesis breaks",
     _inputs(curve_state="NEGATIVE_TRANSITION", curve_direction="DOWN",
             curve_likelihood="LOW", propagation_state="BROKEN",
             leading_edge_entry_quality="POOR",
             assassin2_familiarity="DATA_CONFLICT",
             assassin2_caution_label="SEVERE",
             observation_quality="INVALID"), 300),
]


def _run_movie():
    """Returns the ordered list of ReunderwriteDecisions for T0..T5,
    threading each scene's inputs as the next scene's prior."""
    frames = []
    prior_inputs = None
    prior_state = None
    last_review_at = None
    for label, inputs, offset in SCENES:
        now = T_BASE + pd.Timedelta(seconds=offset)
        secs = ((now - last_review_at).total_seconds()
                if last_review_at is not None else None)
        d = rt.evaluate(subject="MOVIE", candidate_id="MOVIE-LIVE",
                        prior_inputs=prior_inputs, current_inputs=inputs,
                        prior_state=prior_state,
                        seconds_since_last_review=secs, known_from=now, now=now)
        frames.append((label, d, inputs, now))
        if d.should_review:
            prior_inputs = inputs
            last_review_at = now
            # simulate Captain having reached a live (non-terminal) state
            prior_state = "DEVELOP"
    return frames


def test_movie_captain_reviewed_at_every_material_state_change():
    frames = _run_movie()
    assert len(frames) == 6
    for label, d, _inp, _now in frames:
        assert d.should_review is True, (
            f"{label}: Captain must be re-asked on a material change -- "
            f"this is the 2026-08-18 freeze the fix exists to prevent")


def test_movie_each_scene_names_its_real_trigger():
    frames = _run_movie()
    expected_present = [
        "NEVER_REVIEWED",              # T0
        "TRANSITION_QUALITY_CHANGE",   # T1 likelihood LOW->HIGH
        "PROPAGATION_CHANGE",          # T2
        "ENTRY_QUALITY_CHANGE",        # T3
        "ASSASSIN_WOUND_CHANGE",       # T4
        "CURVE_STATE_CHANGE",          # T5
    ]
    for (label, d, _i, _n), want in zip(frames, expected_present):
        assert want in d.triggers, f"{label}: expected {want} in {d.triggers}"


def test_movie_assassin_rerun_before_captain_where_required():
    frames = _run_movie()
    # T1 (transition quality), T2 (propagation) and T5 (curve break) all
    # change evidence Assassin reasons over.
    for idx in (0, 1, 2, 5):
        label, d = frames[idx][0], frames[idx][1]
        assert rt.requires_fresh_assassin(d) is True, (
            f"{label}: Assassin must be refreshed before Captain")
    # T3 is entry-quality only -- Assassin's evidence did not change.
    assert rt.requires_fresh_assassin(frames[3][1]) is False


def test_movie_t6_old_thesis_stays_invalidated():
    """T6: genuinely positive new evidence arrives AFTER a terminal
    INVALIDATE. The old thesis must not resurrect."""
    t6 = T_BASE + pd.Timedelta(seconds=360)
    revived = _inputs(curve_state="POSITIVE_TRANSITION", curve_direction="UP",
                      curve_likelihood="HIGH", propagation_state="CONFIRMED",
                      observation_quality="FULL")
    d = rt.evaluate(subject="MOVIE", candidate_id="MOVIE-LIVE",
                    prior_inputs=_inputs(curve_state="NEGATIVE_TRANSITION"),
                    current_inputs=revived, prior_state="INVALIDATE",
                    seconds_since_last_review=60.0, known_from=t6, now=t6)
    assert d.is_terminal is True
    assert d.should_review is False, (
        "an INVALIDATE-d thesis may never be re-underwritten back to life")


def test_movie_t6_new_evidence_requires_new_thesis_lineage():
    new_id = rt.new_thesis_lineage_id("MOVIE", generation=2)
    assert new_id != "MOVIE-LIVE"
    assert "GEN2" in new_id
    # and the fresh lineage, having no prior, reviews from scratch
    t6 = T_BASE + pd.Timedelta(seconds=360)
    d = rt.evaluate(subject="MOVIE", candidate_id=new_id, prior_inputs=None,
                    current_inputs=_inputs(), prior_state=None,
                    seconds_since_last_review=None, known_from=t6, now=t6)
    assert d.should_review is True
    assert d.triggers == ("NEVER_REVIEWED",)


def test_movie_ledger_distinguishes_review_from_state_change(tmp_path, monkeypatch):
    monkeypatch.setattr(rl, "LEDGER", tmp_path / "movie.jsonl")
    frames = _run_movie()
    states = ["WATCH", "DEVELOP", "SERIOUS", "WAIT_FOR_ENTRY", "DEGRADE",
              "INVALIDATE"]
    prev = None
    for i, ((label, d, _i, now), st) in enumerate(zip(frames, states), start=1):
        rl.persist(rl.record(
            candidate_id="MOVIE-LIVE", subject="MOVIE", review_number=i,
            review_time=now, trigger=d.triggers, previous_captain_state=prev,
            current_captain_state=st, changed_inputs=d.changed_inputs,
            unchanged_inputs=d.unchanged_inputs,
            assassin_refreshed=rt.requires_fresh_assassin(d), known_from=now))
        prev = st
    counts = rl.review_counts_by_subject(tmp_path / "movie.jsonl")
    assert counts["MOVIE"]["reviews"] == 6
    assert counts["MOVIE"]["state_changes"] == 6   # every scene moved the state


def test_movie_grants_no_capital_broker_or_execution_authority():
    frames = _run_movie()
    for label, d, _i, _n in frames:
        assert d.decision_power == "NONE_FRONTIER_SHADOW"
        blob = str(d.as_record()).lower()
        for w in FORBIDDEN_AUTHORITY_WORDS:
            assert w not in blob, f"{label}: {w!r} must never appear"


def test_movie_never_mutates_official_hunter_or_calls_execution():
    """Structural: the modules this movie exercises must not even be
    able to reach Hunter or execution."""
    from pathlib import Path
    for mod in ("apex/frontier2/reunderwrite_trigger.py",
                "apex/frontier2/reunderwrite_ledger.py"):
        src = Path(mod).read_text()
        for forbidden in ("apex.hunter", "apex.captain", "apex.execution",
                          "apex.frontier."):
            assert f"import {forbidden}" not in src
            assert f"from {forbidden}" not in src
