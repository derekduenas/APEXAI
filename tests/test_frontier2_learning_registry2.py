"""learning_registry2 — F16. Proves all ten hypotheses start
NOT_YET_ESTIMABLE, post-hoc hypotheses are refused, amending a
registered preregistration is a lineage break, and the sample-rule-met
path deliberately raises rather than quietly computing something.
"""
from __future__ import annotations

import json

import pytest

from apex.frontier2.learning_registry2 import (PREREGISTRATION,
                                               LearningRegistry2Violation,
                                               estimate, preregister)

ALL_HYPOTHESES = ("H_CURVE_TRANSITION", "H_CURVE_DIRECTION",
                  "H_CURVE_EXPRESSION", "H_EXPECTATION_VIOLATION",
                  "H_PARTICIPANT_PRESSURE", "H_PROPAGATION",
                  "H_LEADING_EDGE", "H_MODEL_MARKET", "H_ASSASSIN2",
                  "H_CAPTAIN_FRONTIER")


def test_all_ten_hypotheses_preregistered():
    assert set(PREREGISTRATION["hypotheses"].keys()) == set(ALL_HYPOTHESES)


@pytest.mark.parametrize("h", ALL_HYPOTHESES)
def test_every_hypothesis_starts_not_yet_estimable_with_zero_observations(h):
    r = estimate(h, observations=())
    assert r["status"] == "NOT_YET_ESTIMABLE"
    assert r["resolved_observations"] == 0
    assert r["distinct_dates"] == 0


def test_post_hoc_hypothesis_refused():
    with pytest.raises(LearningRegistry2Violation):
        estimate("H_MADE_UP_AFTER_THE_FACT")


def test_below_min_n_is_not_yet_estimable():
    obs = [{"session_date": "2026-08-18"}] * 10
    r = estimate("H_CURVE_TRANSITION", observations=tuple(obs))
    assert r["status"] == "NOT_YET_ESTIMABLE"


def test_enough_n_but_too_few_dates_is_still_not_yet_estimable():
    obs = [{"session_date": "2026-08-18"}] * 25   # all same date
    r = estimate("H_CURVE_TRANSITION", observations=tuple(obs))
    assert r["status"] == "NOT_YET_ESTIMABLE"
    assert r["distinct_dates"] == 1


def test_sample_rule_met_raises_rather_than_computing():
    obs = tuple({"session_date": f"2026-08-{d:02d}"} for d in range(1, 11)
               for _ in range(2))
    dates = {o["session_date"] for o in obs}
    assert len(obs) >= 20 and len(dates) >= 10
    with pytest.raises(LearningRegistry2Violation):
        estimate("H_CURVE_TRANSITION", observations=obs)


def test_preregister_writes_the_file(tmp_path, monkeypatch):
    import apex.frontier2.learning_registry2 as lr2
    monkeypatch.setattr(lr2, "REGISTRY", tmp_path / "reg.json")
    p = preregister()
    payload = json.loads(p.read_text())
    # compare through the same JSON round-trip preregister() itself uses
    # (PREREGISTRATION holds tuples; JSON has no tuple type).
    assert payload["preregistration"] == json.loads(json.dumps(PREREGISTRATION))
    assert payload["observations"] == []


def test_preregister_is_idempotent(tmp_path, monkeypatch):
    import apex.frontier2.learning_registry2 as lr2
    monkeypatch.setattr(lr2, "REGISTRY", tmp_path / "reg.json")
    preregister()
    p2 = preregister()          # second call must not raise or change anything
    assert (json.loads(p2.read_text())["preregistration"]
           == json.loads(json.dumps(PREREGISTRATION)))


def test_amending_a_registered_preregistration_is_a_lineage_break(tmp_path, monkeypatch):
    import apex.frontier2.learning_registry2 as lr2
    reg_path = tmp_path / "reg.json"
    monkeypatch.setattr(lr2, "REGISTRY", reg_path)
    preregister()
    tampered = json.loads(reg_path.read_text())
    tampered["preregistration"]["min_n_per_group"] = 1
    reg_path.write_text(json.dumps(tampered))
    with pytest.raises(LearningRegistry2Violation):
        preregister()


def test_decision_power_is_stamped_in_the_preregistration():
    assert PREREGISTRATION["decision_power"] == "NONE_FRONTIER_SHADOW"


def test_no_confirmatory_status_value_exists_anywhere():
    """Structural proof: CONFIRMED/REJECTED are not even valid outputs
    of estimate() in this lineage."""
    r = estimate("H_CURVE_TRANSITION", observations=())
    assert r["status"] not in ("CONFIRMED", "REJECTED", "SIGNIFICANT")
