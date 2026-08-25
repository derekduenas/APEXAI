"""CHRONOS contracts — the causal walk-forward laboratory.

These tests are the constitution: the clock only moves forward, poison
kills runs, zones purge and embargo, hypotheses freeze or descend,
the lockbox refuses, nonsense is measured, the two scores never blend,
lifelines cannot cite the future, and the tournament refuses
flattering subsets of history.
"""
from __future__ import annotations

import pytest

from apex.chronos import CHRONOS_VERSION, EVIDENCE_LABEL
from apex.chronos.clock import (CausalClock, ChronosViolation,
                                KnowledgeHorizon, PoisonConsumed,
                                assert_causal)
from apex.chronos.controls import (SHADOW_FEATURES, effective_sample,
                                   false_discovery_calibration,
                                   inject_shadows, shadow_feature_values,
                                   shuffle_labels)
from apex.chronos.evolution import EdgeLifeline, grade_retirement_timing
from apex.chronos.scoring import (SCIENTIFIC_DIMENSIONS, blend,
                                  economic_score, scientific_score)
from apex.chronos.tournament import run_tournament
from apex.chronos.zones import (Fold, assign_zone, build_folds, descend,
                                freeze_hypothesis, lockbox_guard,
                                seal_lockbox, verify_frozen)

T0 = "2019-01-03T09:55:00+00:00"


# ==================================================== THE CLOCK

def test_the_clock_only_moves_forward():
    c = CausalClock(start=T0)
    c.advance("2019-01-03T10:00:00+00:00", why="next bar")
    with pytest.raises(ChronosViolation, match="only move forward"):
        c.advance("2019-01-03T09:59:00+00:00", why="oops")


def test_a_future_field_is_refused_not_served():
    c = CausalClock(start=T0)
    h = KnowledgeHorizon(clock=c)
    h.register("close_price", 250.0,
               known_from="2019-01-03T16:00:00+00:00", source="test")
    assert h.get("close_price", consumer="genome") == "NOT_ESTIMABLE"
    assert h.refusals[0]["verdict"] == "NOT_YET_KNOWABLE"
    c.advance("2019-01-03T16:00:01+00:00", why="after close")
    assert h.get("close_price", consumer="genome") == 250.0


def test_consuming_poison_is_a_hard_fail_that_names_the_consumer():
    """The operator's poison pill: future_return planted, prohibited,
    and its only job is to be reached for."""
    c = CausalClock(start=T0)
    h = KnowledgeHorizon(clock=c)
    h.register_poison("future_return_30m", 0.0123,
                      why="contains the future by construction")
    with pytest.raises(PoisonConsumed) as exc:
        h.get("future_return_30m", consumer="frontier_discovery")
    msg = str(exc.value)
    assert "HARD FAIL" in msg
    assert "frontier_discovery" in msg
    assert "no partial result survives" in msg


def test_a_field_cannot_be_both_servable_and_poison():
    c = CausalClock(start=T0)
    h = KnowledgeHorizon(clock=c)
    h.register_poison("x", 1.0, why="trap")
    with pytest.raises(ChronosViolation, match="both servable"):
        h.register("x", 1.0, known_from=T0, source="test")


def test_a_replay_without_poison_has_an_untested_firewall():
    c = CausalClock(start=T0)
    naked = KnowledgeHorizon(clock=c)
    assert naked.audit()["firewall_tested"] is False
    armed = KnowledgeHorizon(clock=c)
    armed.register_poison("future_return_30m", 1.0, why="trap")
    assert armed.audit()["firewall_tested"] is True


def test_unregistered_and_unstamped_data_are_refused():
    c = CausalClock(start=T0)
    h = KnowledgeHorizon(clock=c)
    with pytest.raises(ChronosViolation, match="not registered"):
        h.get("invented_field", consumer="x")
    with pytest.raises(ChronosViolation, match="unstamped"):
        assert_causal([{"v": 1}], decision_time=T0)


def test_assert_causal_filters_strictly_by_known_from():
    rows = [{"v": 1, "known_from": "2019-01-03T09:00:00+00:00"},
            {"v": 2, "known_from": "2019-01-03T10:00:00+00:00"}]
    kept = assert_causal(rows, decision_time=T0)
    assert [r["v"] for r in kept] == [1]


# ==================================================== ZONES

def _fold():
    return Fold(fold_id="F", train_start="2019-01-01T00:00:00+00:00",
                train_end="2019-03-01T00:00:00+00:00",
                validate_start="2019-03-01T00:00:00+00:00",
                validate_end="2019-04-01T00:00:00+00:00",
                test_start="2019-04-01T00:00:00+00:00",
                test_end="2019-05-01T00:00:00+00:00",
                purge_horizon="20min", embargo="2d")


def test_folds_roll_and_a_partial_tail_is_dropped_not_stretched():
    folds = build_folds(start="2019-01-01T00:00:00+00:00",
                        end="2019-12-31T00:00:00+00:00",
                        train_days=120, validate_days=30, test_days=30,
                        purge_horizon="20min", embargo="2d")
    assert len(folds) >= 5
    spans = [(f.train_start, f.test_end) for f in folds]
    assert len(set(spans)) == len(spans)
    with pytest.raises(ChronosViolation, match="zero complete folds"):
        build_folds(start="2019-01-01T00:00:00+00:00",
                    end="2019-02-01T00:00:00+00:00",
                    train_days=120, validate_days=30, test_days=30,
                    purge_horizon="20min", embargo="2d")


def test_a_train_sample_that_peeks_into_validation_is_purged():
    f = _fold()
    z = assign_zone(f, decision_time="2019-02-28T23:50:00+00:00",
                    outcome_horizon_end="2019-03-01T00:10:00+00:00")
    assert z == "PURGED"
    z2 = assign_zone(f, decision_time="2019-02-15T10:00:00+00:00",
                     outcome_horizon_end="2019-02-15T10:20:00+00:00")
    assert z2 == "ZONE_A_DISCOVERY"


def test_the_embargo_creates_dead_time_after_each_boundary():
    f = _fold()
    z = assign_zone(f, decision_time="2019-04-01T12:00:00+00:00",
                    outcome_horizon_end="2019-04-01T12:20:00+00:00")
    assert z == "EMBARGOED"
    z2 = assign_zone(f, decision_time="2019-04-04T12:00:00+00:00",
                     outcome_horizon_end="2019-04-04T12:20:00+00:00")
    assert z2 == "ZONE_C_SEALED_TEST"


def _spec(**over):
    s = {"variables": ["gap_pct", "open_drift_pct"],
         "direction": "SHORT", "threshold_family": "quantile",
         "mechanism": "failed opening extension",
         "horizon": "SESSION_CLOSE",
         "payoff_definition": "signed forward underlying return"}
    s.update(over)
    return s


def test_a_hypothesis_with_an_unfrozen_degree_of_freedom_refuses():
    spec = _spec()
    del spec["payoff_definition"]
    with pytest.raises(ChronosViolation, match="unfrozen degrees"):
        freeze_hypothesis(hypothesis_id="H", birth_time=T0, spec=spec)


def test_turning_a_knob_between_freeze_and_test_is_caught():
    frozen = freeze_hypothesis(hypothesis_id="EDGE_00931",
                               birth_time=T0, spec=_spec())
    assert verify_frozen(frozen, _spec())["verdict"] == "FROZEN_INTACT"
    v = verify_frozen(frozen, _spec(direction="LONG"))
    assert v["verdict"] == "FROZEN_VIOLATED"
    assert v["changed_fields"] == ["direction"]
    assert "DESCENDANT" in v["remedy"]


def test_a_descendant_is_a_new_birth_with_zero_inherited_evidence():
    frozen = freeze_hypothesis(hypothesis_id="EDGE_00931",
                               birth_time="2018-06-30T00:00:00+00:00",
                               spec=_spec())
    child = descend(frozen, child_spec=_spec(direction="LONG"),
                    child_suffix="B",
                    birth_time="2019-02-15T00:00:00+00:00",
                    mutation_reason="direction inverted after regime "
                                    "study")
    assert child["hypothesis_id"] == "EDGE_00931B"
    assert child["parent"] == "EDGE_00931"
    assert child["inherited_evidence"] == 0
    assert "does not transfer" in child["law"]


def test_the_lockbox_refuses_everything_but_an_explicit_operator_act():
    box = seal_lockbox(start="2025-01-01T00:00:00+00:00",
                       end="2026-06-01T00:00:00+00:00",
                       sealed_by="operator",
                       sealed_utc="2026-08-25T05:00:00+00:00")
    assert box["status"] == "SEALED" and box["seal_hash"]
    with pytest.raises(ChronosViolation, match="LOCKBOX"):
        lockbox_guard(box, decision_time="2025-06-15T10:00:00+00:00")
    lockbox_guard(box, decision_time="2024-06-15T10:00:00+00:00")
    lockbox_guard(box, decision_time="2025-06-15T10:00:00+00:00",
                  operator_token="OPERATOR_AUTHORIZED_LOCKBOX_OPEN")


# ==================================================== CONTROLS

def test_shadow_features_are_declared_deterministic_nonsense():
    ts = [f"2019-01-0{d}T10:00:00+00:00" for d in range(1, 8)]
    for name in SHADOW_FEATURES:
        a = shadow_feature_values(name, ts, seed=7)
        b = shadow_feature_values(name, ts, seed=7)
        assert a == b, "a shadow discovery must be reproducible"
    with pytest.raises(ChronosViolation, match="declared, never"):
        shadow_feature_values("plausible_sounding_factor", ts)


def test_injection_leaves_a_census_no_stage_can_deny():
    table = {f"t{i}": {"real_feat": i * 0.1} for i in range(5)}
    out = inject_shadows(table, seed=3)
    assert out["injected"] == list(SHADOW_FEATURES)
    for row in out["features"].values():
        assert set(SHADOW_FEATURES) <= set(row)


def test_shuffled_labels_preserve_the_multiset_and_destroy_order():
    labels = list(range(50))
    sh = shuffle_labels(labels, seed=11)
    assert sorted(sh) == labels and sh != labels
    assert shuffle_labels(labels, seed=11) == sh


def test_an_engine_that_finds_edge_in_nonsense_is_named_permissive():
    runs = ([{"control_kind": "SHUFFLED_LABELS", "target": f"s{i}",
              "discovered": i < 3, "strength": 0.4} for i in range(10)]
            + [{"control_kind": "SHADOW_FEATURE",
                "target": "moon_phase_mod_7", "discovered": False,
                "strength": None} for _ in range(10)])
    cal = false_discovery_calibration(control_runs=runs)
    assert cal["verdict"] == "PIPELINE_TOO_PERMISSIVE"
    assert cal["hallucination_temperature"] == 0.3
    assert cal["by_control"]["SHUFFLED_LABELS"]["hits"] == 3


def test_zero_controls_is_an_unmeasured_rate_not_a_low_one():
    cal = false_discovery_calibration(control_runs=[])
    assert cal["verdict"] == "NO_CONTROLS_RUN"
    assert "not the same as a low one" in cal["why"]


def test_effective_sample_counts_sessions_not_observations():
    obs = [{"session": f"s{i % 4}", "regime": "NORMAL"}
           for i in range(100)]
    es = effective_sample(observations=obs, session_key="session",
                          regime_key="regime")
    assert es["n_raw"] == 100
    assert es["n_effective_lower_bound"] == 4
    with pytest.raises(ChronosViolation, match="session key"):
        effective_sample(observations=[{"x": 1}], session_key="session")


# ==================================================== SCORING

def test_replay_economics_carry_the_label_that_never_upgrades():
    s = economic_score(oos_r_multiples=[0.5, -0.3, 1.1],
                       friction_total=42.0, n_sessions=3)
    assert s["evidence_label"] == EVIDENCE_LABEL == "HISTORICAL_REPLAY"
    assert "never upgrade to" in s["law"]


def test_the_scientific_score_refuses_unasked_questions():
    ev = {d: {"verdict": "INSUFFICIENT_EVIDENCE", "evidence": "none yet"}
          for d in SCIENTIFIC_DIMENSIONS}
    s = scientific_score(dimension_evidence=ev)
    assert s["no_composite_number"] is True
    assert "research theater" in s["standing_question"].lower() or \
        "Research theater" in s["standing_question"]
    incomplete = dict(ev)
    del incomplete["false_discovery_restraint"]
    with pytest.raises(ChronosViolation, match="unassessed"):
        scientific_score(dimension_evidence=incomplete)


def test_a_verdict_without_evidence_is_refused():
    ev = {d: {"verdict": "DEMONSTRATED", "evidence": "x"}
          for d in SCIENTIFIC_DIMENSIONS}
    ev["calibration"] = {"verdict": "DEMONSTRATED", "evidence": ""}
    with pytest.raises(ChronosViolation, match="opinion wearing"):
        scientific_score(dimension_evidence=ev)


def test_the_blend_is_a_named_grave():
    with pytest.raises(ChronosViolation, match="no combined"):
        blend(economic=1.0, scientific=0.5)


# ==================================================== EVOLUTION

def test_a_lifeline_cannot_cite_the_future():
    lf = EdgeLifeline(edge_id="EDGE_17", born=T0, frozen_hash="abc")
    with pytest.raises(ChronosViolation, match="is a story"):
        lf.record(event="WEAKENING", at="2019-06-01T00:00:00+00:00",
                  evidence="drawdown deepened",
                  evidence_known_from="2019-07-01T00:00:00+00:00")


def test_a_retired_edge_stops_and_only_a_descendant_continues():
    lf = EdgeLifeline(edge_id="EDGE_17", born=T0, frozen_hash="abc")
    lf.record(event="DECAY_FLAGGED", at="2019-03-01T00:00:00+00:00",
              evidence="rolling favorable fraction under floor",
              evidence_known_from="2019-03-01T00:00:00+00:00")
    lf.record(event="RETIRED", at="2019-06-01T00:00:00+00:00",
              evidence="decay persisted two review cycles",
              evidence_known_from="2019-06-01T00:00:00+00:00")
    with pytest.raises(ChronosViolation, match="create a descendant"):
        lf.record(event="EVIDENCE", at="2019-07-01T00:00:00+00:00",
                  evidence="x", evidence_known_from="2019-07-01T00:00:00+00:00")


def test_retirement_grading_uses_the_future_only_as_a_grade():
    lf = EdgeLifeline(edge_id="EDGE_17", born=T0, frozen_hash="abc")
    lf.record(event="DECAY_FLAGGED", at="2019-03-01T00:00:00+00:00",
              evidence="deterioration", evidence_known_from="2019-03-01T00:00:00+00:00")
    lf.record(event="RETIRED", at="2019-06-01T00:00:00+00:00",
              evidence="persistent decay", evidence_known_from="2019-06-01T00:00:00+00:00")
    g = grade_retirement_timing(
        lf, post_retirement_outcomes=[-0.5, -0.3, -0.8, -0.2, -0.6],
        pre_retirement_outcomes=[0.4, 0.2, -0.1, 0.3, 0.1])
    assert g["verdict"] == "TIMELY_RETIREMENT_AFTER_FLAG"
    g2 = grade_retirement_timing(
        lf, post_retirement_outcomes=[0.5, 0.3, 0.8, 0.2, 0.6],
        pre_retirement_outcomes=[0.4, 0.2, -0.1, 0.3, 0.1])
    assert g2["verdict"] == "RETIRED_A_LIVING_EDGE"
    assert "refusal has a price" in g2["law"]


# ==================================================== TOURNAMENT

def _moments(vals):
    return {f"2019-04-{d:02d}T10:00:00+00:00": v
            for d, v in enumerate(vals, start=1)}


def test_a_policy_skipping_moments_breaks_the_tournament():
    common = _moments([0.0] * 5)
    with pytest.raises(ChronosViolation, match="flattering subset"):
        run_tournament(period="2019-04", decisions_by_policy={
            "NO_TRADE": common,
            "APEX_CHALLENGER": _moments([0.5] * 4)})


def test_no_trade_is_mandatory_and_the_roster_is_closed():
    with pytest.raises(ChronosViolation, match="NO_TRADE must run"):
        run_tournament(period="p", decisions_by_policy={
            "APEX_CHALLENGER": _moments([1.0])})
    with pytest.raises(ChronosViolation, match="undeclared policies"):
        run_tournament(period="p", decisions_by_policy={
            "NO_TRADE": _moments([0.0]),
            "MY_COOL_NEW_BOT": _moments([9.9])})


def test_beating_momentum_but_not_random_eligible_is_not_skill():
    common_n = 6
    t = run_tournament(period="2019-04", decisions_by_policy={
        "NO_TRADE": _moments([0.0] * common_n),
        "SIMPLE_MOMENTUM": _moments([-0.2] * common_n),
        "RANDOM_ELIGIBLE": _moments([0.4] * common_n),
        "APEX_CHALLENGER": _moments([0.2] * common_n)})
    assert t["verdict"] == "CHALLENGER_NOT_SUPERIOR"
    assert any("RANDOM_ELIGIBLE" in f for f in t["challenger_findings"])
    assert "eligibility, not skill" in t["law"]


def test_declining_to_act_scores_zero_like_no_trade():
    t = run_tournament(period="p", decisions_by_policy={
        "NO_TRADE": _moments([None, None, None]),
        "APEX_CHALLENGER": _moments([None, 0.5, None])})
    ch = t["standings"]["APEX_CHALLENGER"]
    assert ch["n_acted"] == 1 and ch["total_R"] == 0.5
    assert t["standings"]["NO_TRADE"]["total_R"] == 0.0


def test_every_chronos_artifact_is_labelled_historical_replay():
    t = run_tournament(period="p", decisions_by_policy={
        "NO_TRADE": _moments([0.0])})
    assert t["evidence_label"] == "HISTORICAL_REPLAY"
    assert CHRONOS_VERSION


def test_shadows_are_deterministic_across_processes_not_just_calls():
    """builtin hash() is salted per process; a shadow computed with it
    would be 'deterministic' only inside one interpreter. Pin the
    actual values so a hash-salt regression cannot hide."""
    ts = ["2019-01-03T10:00:00+00:00", "2019-01-04T10:00:00+00:00"]
    vals = shadow_feature_values("moon_phase_mod_7", ts)
    import hashlib as _h
    expect = [int(_h.sha256(t.encode()).hexdigest(), 16) % 7 for t in ts]
    assert vals == expect
