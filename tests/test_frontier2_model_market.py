"""InternalModelMarket — F7. Proves stances are tallied, never
weighted into a consensus; scorecard arithmetic is correct on synthetic
resolution sequences; and nothing here can be misread as authority.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.model_market import (SEATS, ModelMarketError, Scorecard,
                                         Submission, new_scorecard, snapshot,
                                         submit, update_scorecard)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def test_unknown_seat_refused():
    with pytest.raises(ModelMarketError):
        submit("NOT_A_SEAT", "P1", "SUPPORT", reason="x", known_from=T0, now=T0)


def test_unknown_stance_refused():
    with pytest.raises(ModelMarketError):
        submit("CURVE", "P1", "NOT_A_STANCE", reason="x", known_from=T0, now=T0)


def test_all_thirteen_seats_are_valid():
    assert len(SEATS) == 13
    for seat in SEATS:
        s = submit(seat, "P1", "ABSTAIN", reason="x", known_from=T0, now=T0)
        assert s.engine == seat


# ---- snapshot: a tally, never a weighted vote -----------------------------

def test_snapshot_is_a_plain_tally():
    subs = (
        submit("CURVE", "P1", "SUPPORT", reason="a", known_from=T0, now=T0),
        submit("MOMENTUM", "P1", "SUPPORT", reason="b", known_from=T0, now=T0),
        submit("REVERSION", "P1", "OPPOSE", reason="c", known_from=T0, now=T0),
        submit("ANALOG", "P1", "ABSTAIN", reason="d", known_from=T0, now=T0),
    )
    snap = snapshot("P1", subs)
    assert snap["tally"] == {"SUPPORT": 2, "OPPOSE": 1, "ABSTAIN": 1, "UNKNOWN": 0}
    assert snap["n_submissions"] == 4
    assert "consensus" not in snap                    # structurally no such field


def test_snapshot_tracks_silent_seats():
    subs = (submit("CURVE", "P1", "SUPPORT", reason="a", known_from=T0, now=T0),)
    snap = snapshot("P1", subs)
    assert "CURVE" in snap["seats_heard_from"]
    assert "ASSASSIN" in snap["seats_silent"]
    assert len(snap["seats_heard_from"]) + len(snap["seats_silent"]) == len(SEATS)


def test_snapshot_refuses_mixed_propositions():
    subs = (
        submit("CURVE", "P1", "SUPPORT", reason="a", known_from=T0, now=T0),
        submit("MOMENTUM", "P2", "OPPOSE", reason="b", known_from=T0, now=T0),
    )
    with pytest.raises(ModelMarketError):
        snapshot("P1", subs)


def test_snapshot_output_has_no_numeric_score_field():
    """Structural proof there is no fitted/weighted score anywhere in
    the output -- only the closed STANCES vocabulary and integer counts."""
    subs = (submit("CURVE", "P1", "SUPPORT", reason="a", known_from=T0, now=T0),)
    snap = snapshot("P1", subs)
    assert set(snap.keys()) == {"kind", "proposition", "n_submissions", "tally",
                                "by_engine", "seats_heard_from", "seats_silent",
                                "decision_power"}


# ---- Scorecard arithmetic (synthetic resolution sequences) ---------------

def test_new_scorecard_starts_at_all_zero():
    sc = new_scorecard("CURVE", "curvature_direction")
    assert (sc.attempts, sc.resolved, sc.correct, sc.incorrect,
           sc.abstentions, sc.sample_size) == (0, 0, 0, 0, 0, 0)
    assert sc.drift is None


def test_correct_support_increments_correct_not_incorrect():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=True, now=T0)
    assert sc2.resolved == 1 and sc2.correct == 1 and sc2.incorrect == 0
    assert sc2.attempts == 1


def test_wrong_support_is_a_false_positive():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=False, now=T0)
    assert sc2.incorrect == 1 and sc2.false_positive == 1 and sc2.false_negative == 0


def test_wrong_oppose_is_a_false_negative():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "OPPOSE", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=True, now=T0)
    assert sc2.incorrect == 1 and sc2.false_negative == 1 and sc2.false_positive == 0


def test_abstain_never_touches_correct_or_incorrect():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "ABSTAIN", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=True, now=T0)
    assert sc2.abstentions == 1
    assert sc2.correct == 0 and sc2.incorrect == 0 and sc2.resolved == 0
    assert sc2.attempts == 1


def test_unknown_stance_also_counts_as_abstention_not_a_position():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "UNKNOWN", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=True, now=T0)
    assert sc2.abstentions == 1
    assert sc2.resolved == 0


def test_open_proposition_outcome_none_only_moves_attempts():
    sc = new_scorecard("CURVE", "P")
    sub = submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    sc2 = update_scorecard(sc, sub, outcome=None, now=T0)
    assert sc2.attempts == 1
    assert sc2.resolved == 0 and sc2.correct == 0 and sc2.incorrect == 0


def test_scorecard_accumulates_across_many_synthetic_resolutions():
    sc = new_scorecard("CURVE", "P")
    sequence = [("SUPPORT", True), ("SUPPORT", False), ("OPPOSE", False),
               ("OPPOSE", True), ("ABSTAIN", True), ("SUPPORT", True)]
    for stance, outcome in sequence:
        sub = submit("CURVE", "P", stance, reason="x", known_from=T0, now=T0)
        sc = update_scorecard(sc, sub, outcome=outcome, now=T0)
    assert sc.attempts == 6
    assert sc.resolved == 5           # everything except the one ABSTAIN
    assert sc.correct == 3            # SUPPORT/True, OPPOSE/False, SUPPORT/True
    assert sc.incorrect == 2          # SUPPORT/False, OPPOSE/True
    assert sc.abstentions == 1
    assert sc.false_positive == 1
    assert sc.false_negative == 1


def test_wrong_engine_on_scorecard_update_refused():
    sc = new_scorecard("CURVE", "P")
    sub = submit("MOMENTUM", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    with pytest.raises(ModelMarketError):
        update_scorecard(sc, sub, outcome=True, now=T0)


def test_drift_stays_none_below_the_minimum_resolved_sample():
    sc = new_scorecard("CURVE", "P")
    for _ in range(5):
        sub = submit("CURVE", "P", "SUPPORT", reason="x", known_from=T0, now=T0)
        sc = update_scorecard(sc, sub, outcome=True, now=T0)
    assert sc.drift is None


def test_past_accuracy_never_feeds_back_into_a_submission():
    """Structural proof of 'do not optimize weights': Submission's
    fields contain nothing derived from a Scorecard."""
    assert not (set(Submission.__dataclass_fields__)
               & {"correct", "incorrect", "accuracy", "weight"})


def test_decision_power_always_stamped():
    sub = submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    assert sub.decision_power == "NONE_FRONTIER_SHADOW"
    sc = new_scorecard("CURVE", "P")
    assert sc.decision_power == "NONE_FRONTIER_SHADOW"


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.model_market as mm
    monkeypatch.setattr(mm, "LEDGER", tmp_path / "mm.jsonl")
    sub = submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0)
    rec1 = mm.persist_submission(sub)
    rec2 = mm.persist_submission(sub)
    assert rec2["prev_hash"] == rec1["entry_hash"]
