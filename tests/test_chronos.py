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


# ============ CALIBRATION (operator, 2026-08-25: the bar is set by
# garbage, inside Discovery, then frozen)

from apex.chronos.calibration import (freeze_bar, null_distribution,
                                      research_hallucination_rate,
                                      search_complexity, verify_bar)
from apex.chronos.epoch import (beliefs_at, intelligence_trajectory,
                                write_epoch)
from apex.chronos.poison_suite import (POISON_CATALOG,
                                       plant_full_catalog, self_attack)
from apex.chronos.scoring import classify_experiment


def _cx(**over):
    base = dict(candidate_features_considered=4,
                transformations_considered=1, interaction_orders=1,
                thresholds_searched=1, horizons_searched=1,
                directions_searched=2, regimes_searched=1,
                expressions_searched=1)
    base.update(over)
    return search_complexity(**base)


def _nulls(n=30, score=0.2, cx=None):
    cx = cx or _cx()
    return [{"replicate_id": f"r{i}", "control_kind": "RANDOM_FEATURES",
             "complexity": cx, "best_abs_score": score + i * 0.001}
            for i in range(n)]


def test_every_degree_of_freedom_must_be_counted():
    c = _cx()
    assert c["total_search_space"] == 8
    with pytest.raises(ChronosViolation, match="uncounted degree"):
        search_complexity(candidate_features_considered=4)
    with pytest.raises(ChronosViolation, match="undeclared complexity"):
        _cx(secret_knob=5)


def test_a_toy_control_family_cannot_calibrate_a_big_search():
    big = _cx(candidate_features_considered=800)
    with pytest.raises(ChronosViolation, match="complexity class"):
        null_distribution(family="f", real_complexity=big,
                          null_replicates=_nulls())


def test_a_barely_sampled_null_distribution_is_refused():
    with pytest.raises(ChronosViolation, match="barely sampled"):
        null_distribution(family="f", real_complexity=_cx(),
                          null_replicates=_nulls(n=5))


def test_the_bar_freezes_in_discovery_and_nowhere_else():
    nd = null_distribution(family="f", real_complexity=_cx(),
                           null_replicates=_nulls())
    bar = freeze_bar(null_dist=nd)
    assert bar["bar"] == nd["p99_null"]
    assert "learn to lie" in bar["law"]
    with pytest.raises(ChronosViolation, match="already been adjusted"):
        freeze_bar(null_dist=nd, frozen_in_zone="ZONE_B_VALIDATION")


def test_a_moved_bar_kills_the_run():
    nd = null_distribution(family="f", real_complexity=_cx(),
                           null_replicates=_nulls())
    bar = freeze_bar(null_dist=nd)
    ok = verify_bar(bar, family="f", bar=bar["bar"],
                    quantile="p99_null")
    assert ok["verdict"] == "BAR_INTACT"
    moved = verify_bar(bar, family="f", bar=bar["bar"] - 0.1,
                       quantile="p99_null")
    assert moved["verdict"] == "BAR_MOVED_AFTER_FREEZE"
    assert "run is dead" in moved["remedy"]


def test_hallucination_rate_is_per_family_never_pooled():
    nd = null_distribution(family="single_feature",
                           real_complexity=_cx(),
                           null_replicates=_nulls())
    bar = freeze_bar(null_dist=nd)
    with pytest.raises(ChronosViolation, match="never across"):
        research_hallucination_rate(
            family="five_way_interactions", null_dist=nd,
            real_results=[], frozen_bar=bar)


def test_the_signature_metric_reports_real_vs_garbage_excess():
    nd = null_distribution(family="f", real_complexity=_cx(),
                           null_replicates=_nulls(score=0.2))
    bar = freeze_bar(null_dist=nd)
    rh = research_hallucination_rate(
        family="f", null_dist=nd,
        real_results=[{"score": 0.5}, {"score": 0.1}], frozen_bar=bar)
    assert rh["best_real_score"] == 0.5
    assert rh["real_vs_null_excess"] > 0
    assert rh["interpretation"] == "REAL_EXCEEDS_GARBAGE"
    assert rh["false_discovery_restraint"] == "DEMONSTRATED"
    weak = research_hallucination_rate(
        family="f", null_dist=nd,
        real_results=[{"score": 0.15}], frozen_bar=bar)
    assert weak["interpretation"] == \
        "REAL_INDISTINGUISHABLE_FROM_GARBAGE"


# ============ EXPERIMENT CLASSIFICATION (the three-line law)

def test_economic_success_cannot_rescue_scientific_invalidity():
    c = classify_experiment(economic_positive=True,
                            false_discovery_restraint="FAILED",
                            survived_unseen_time=True)
    assert c["ECONOMIC_TEST_RESULT"] == "POSITIVE"
    assert c["SCIENTIFIC_VALIDITY"] == "FAILED_FALSE_DISCOVERY_CONTROL"
    assert c["EDGE_AUTHORITY"] == "NONE"
    assert "zero edge authority" in c["note"]


def test_one_bad_draw_does_not_kill_a_valid_process():
    c = classify_experiment(economic_positive=False,
                            false_discovery_restraint="DEMONSTRATED",
                            survived_unseen_time=False)
    assert c["EDGE_AUTHORITY"] == "NONE"
    assert "bad draw" in c["note"]
    assert "not as proof the process is broken" in c["note"]


def test_uncalibrated_is_not_the_same_as_passing():
    c = classify_experiment(
        economic_positive=True,
        false_discovery_restraint="INSUFFICIENT_EVIDENCE",
        survived_unseen_time=True)
    assert c["SCIENTIFIC_VALIDITY"] == "UNCALIBRATED"
    assert c["EDGE_AUTHORITY"] == "NONE"


def test_the_best_case_is_still_only_a_research_candidate():
    c = classify_experiment(economic_positive=True,
                            false_discovery_restraint="DEMONSTRATED",
                            survived_unseen_time=True)
    assert c["EDGE_AUTHORITY"] == "RESEARCH_CANDIDATE"
    assert "prospective sessions remain the judge" in c["note"]


# ============ POISON SUITE (the adversarial causal catalog)

def test_the_catalog_covers_the_operators_named_leaks():
    for name in ("future_return", "future_high", "future_low",
                 "future_event_resolution", "revised_economic_data",
                 "future_earnings_result", "future_oi_value",
                 "forward_filled_state", "delisting_knowledge"):
        assert name in POISON_CATALOG


def test_self_attack_every_trap_must_fire():
    c = CausalClock(start=T0)
    hz = KnowledgeHorizon(clock=c)
    plant_full_catalog(hz)
    rep = self_attack(hz, attacker="test")
    assert rep["verdict"] == "FIREWALL_HELD"
    assert all(v == "TRAP_FIRED" for v in rep["results"].values())


def test_an_unplanted_poison_fails_the_self_attack():
    """A missing trap is a hole too: the attack demands the full
    catalog, so a replay cannot quietly skip planting one."""
    c = CausalClock(start=T0)
    hz = KnowledgeHorizon(clock=c)
    hz.register_poison("future_return", 1.0, why="only one planted")
    with pytest.raises(ChronosViolation, match="FIREWALL BREACHED"):
        self_attack(hz, attacker="test")


# ============ EPOCHS (what did the organism believe THEN?)

def _epoch(i, cutoff, rate):
    return {"epoch_id": f"E{i:03d}", "knowledge_cutoff": cutoff,
            "code_sha": "abc", "dataset_boundary": "SPY daily",
            "active_edge_library": ["CEDGE_001"] if i else [],
            "retired_edges": [], "candidate_registry": [],
            "credibility_state": "EMPTY",
            "world_source_authority": "EMPIRICAL_ONLY",
            "research_hallucination_rate": {
                "null_over_bar_rate": rate,
                "false_discovery_restraint": "DEMONSTRATED"},
            "capital_policy_state": "NONE_RESEARCH"}


def test_an_epoch_with_a_hole_refuses_to_seal(tmp_path):
    led = tmp_path / "ep.jsonl"
    bad = _epoch(0, "2019-01-01T00:00:00+00:00", 0.1)
    del bad["credibility_state"]
    with pytest.raises(ChronosViolation, match="hole"):
        write_epoch(led, epoch=bad)


def test_the_organism_does_not_unknow_things(tmp_path):
    led = tmp_path / "ep.jsonl"
    write_epoch(led, epoch=_epoch(0, "2019-01-01T00:00:00+00:00", 0.1))
    with pytest.raises(ChronosViolation, match="not advance"):
        write_epoch(led, epoch=_epoch(1, "2018-12-01T00:00:00+00:00",
                                      0.1))


def test_beliefs_are_reconstructed_never_synthesized(tmp_path):
    led = tmp_path / "ep.jsonl"
    write_epoch(led, epoch=_epoch(0, "2019-01-01T00:00:00+00:00", 0.3))
    write_epoch(led, epoch=_epoch(1, "2019-02-01T00:00:00+00:00", 0.1))
    b = beliefs_at(led, timestamp="2019-01-15T00:00:00+00:00")
    assert b["epoch_id"] == "E000"
    assert b["beliefs"]["active_edge_library"] == []
    early = beliefs_at(led, timestamp="2018-06-01T00:00:00+00:00")
    assert early["verdict"] == "ORGANISM_DID_NOT_EXIST_YET"


def test_the_trajectory_asks_if_it_is_harder_to_fool(tmp_path):
    led = tmp_path / "ep.jsonl"
    for i, (cut, rate) in enumerate((
            ("2019-01-01T00:00:00+00:00", 0.5),
            ("2019-02-01T00:00:00+00:00", 0.4),
            ("2019-03-01T00:00:00+00:00", 0.1),
            ("2019-04-01T00:00:00+00:00", 0.05))):
        write_epoch(led, epoch=_epoch(i, cut, rate))
    t = intelligence_trajectory(led)
    assert t["becoming_harder_to_fool"] is True
    assert "never recomputed with hindsight" in t["law"]


# ============ LIFETIME HYPOTHESIS IDENTITY (Campaign #002 directive:
# "a new id does not create a new idea")

from apex.chronos.identity import (LifetimeLedger, family_id,
                                   mechanism_id, spec_id)
from apex.chronos.scoring import (VALIDITY_COMPONENTS,
                                  scientific_validity_decomposition)
from apex.chronos.sequential import (alpha_for_attempt,
                                     null_budget_for_attempt,
                                     sequential_test)


def _spec2(**over):
    s = {"variables": ["rs"], "direction": "LONG",
         "threshold_family": "quantile", "mechanism": "m",
         "horizon": "SESSION_CLOSE",
         "payoff_definition": "signed pct", "threshold": 0.62,
         "lookback": 19}
    s.update(over)
    return s


MECH = ("sustained relative demand creates continuation because "
        "incremental buyers remain present")


def test_parameter_drift_does_not_escape_the_family():
    """RS>0.62 vs RS>0.63, lookback 19 vs 20: different specs, SAME
    idea. This is the p-hack-by-mutation door, closed."""
    a, b = _spec2(), _spec2(threshold=0.63, lookback=20)
    assert spec_id(a) != spec_id(b)
    assert family_id(a) == family_id(b)
    c = _spec2(direction="SHORT")
    assert family_id(a) != family_id(c)


def test_a_mechanism_must_be_a_causal_claim_not_a_label():
    assert mechanism_id(MECH) == mechanism_id(MECH.upper() + "  ")
    with pytest.raises(ChronosViolation, match="label"):
        mechanism_id("momentum")


def test_an_active_family_cannot_be_reborn_under_a_new_name():
    led = LifetimeLedger()
    led.record_attempt(spec=_spec2(), mechanism=MECH,
                       at="2020-01-01T00:00:00+00:00",
                       outcome="BIRTHED", edge_id="E1")
    birth = led.classify_birth(spec=_spec2(threshold=0.63),
                               mechanism=MECH,
                               at="2020-02-01T00:00:00+00:00")
    assert birth["classification"] == "CLONE_BLOCKED"
    assert "may not run concurrently under two names" in birth["why"]


def test_a_retired_family_returns_only_as_a_descendant_with_debt():
    led = LifetimeLedger()
    led.record_attempt(spec=_spec2(), mechanism=MECH,
                       at="2020-01-01T00:00:00+00:00",
                       outcome="BIRTHED", edge_id="E1")
    led.record_attempt(spec=_spec2(), mechanism=MECH,
                       at="2020-06-01T00:00:00+00:00",
                       outcome="RETIRED", edge_id="E1")
    led.record_attempt(spec=_spec2(), mechanism=MECH,
                       at="2020-06-01T00:00:00+00:00",
                       outcome="SEALED_TEST_FAILURE", edge_id="E1")
    birth = led.classify_birth(spec=_spec2(lookback=20),
                               mechanism=MECH,
                               at="2020-07-01T00:00:00+00:00")
    assert birth["classification"] == "DESCENDANT"
    assert birth["family_attempt_number"] == 2
    assert birth["debt"]["family_sealed_test_failures"] == 1
    assert "in full view" in birth["why"]


def test_debt_is_never_collapsed_to_one_magic_number():
    led = LifetimeLedger()
    for _ in range(3):
        led.record_attempt(spec=_spec2(), mechanism=MECH,
                           at="2020-01-01T00:00:00+00:00",
                           outcome="DISCOVERY_FAILURE")
    d = led.debt(family=family_id(_spec2()),
                 mechanism=mechanism_id(MECH))
    assert d["family_discovery_failures"] == 3
    assert "score" not in d and "total" not in d
    assert "calendar does not erase" in d["law"]


def test_the_ledger_counts_ideas_not_ids():
    led = LifetimeLedger()
    for th in (0.60, 0.62, 0.63, 0.65):
        led.record_attempt(spec=_spec2(threshold=th), mechanism=MECH,
                           at="2020-01-01T00:00:00+00:00",
                           outcome="DISCOVERY_FAILURE")
    rec = led.as_record()
    assert rec["unique_specs"] == 4
    assert rec["unique_families"] == 1
    assert rec["unique_mechanisms"] == 1


# ============ SEQUENTIAL CONTROL (predeclared before #002 outcomes)

def test_the_lifetime_alpha_budget_is_bounded():
    # the geometric series sums to ALPHA_TOTAL in the limit and every
    # finite prefix is strictly below it -- unlimited fresh chances
    # cannot exist at any attempt count
    partial = sum(alpha_for_attempt(k) for k in range(1, 20))
    assert partial < 0.05
    assert alpha_for_attempt(1) == 0.025
    assert alpha_for_attempt(2) == 0.0125


def test_the_null_budget_is_set_by_attempt_number_not_by_the_score():
    assert null_budget_for_attempt(1) == 100
    assert null_budget_for_attempt(2) == 100
    assert null_budget_for_attempt(3) == 320


def test_an_unresolvable_tail_refuses_no_matter_how_big_the_score():
    """And the refusal is about OUR instrument, never about the
    market: TEST_NOT_ESTIMABLE carries no evidence against the
    hypothesis."""
    r = sequential_test(family="F", attempt=5, real_score=99.0,
                        null_scores=[0.1] * 100)
    assert r["verdict"] == "TEST_NOT_ESTIMABLE"
    assert r["reason"] == "NULL_TAIL_RESOLUTION"
    assert r["evidence_about_hypothesis"].startswith("NONE")
    assert "Refusal, not fake precision" in r["why"]


def test_closure_is_law_not_data():
    """FAMILY_CLOSED comes from the preregistered schedule alone --
    alpha halves, the null budget is capped -- with no scores
    involved. Out of budget is not proven wrong."""
    from apex.chronos.sequential import family_closure
    open_ = family_closure(family="F", next_attempt=4)
    assert open_["status"] == "FAMILY_OPEN"
    closed = family_closure(family="F", next_attempt=5)
    assert closed["status"] == "FAMILY_CLOSED"
    assert closed["reason"] == "SEQUENTIAL_BUDGET_EXHAUSTED"
    assert "not proven wrong" in closed["law"]


def test_rank_arithmetic_is_checkable_by_hand():
    nulls = [i / 100 for i in range(100)]      # 0.00 .. 0.99
    r = sequential_test(family="F", attempt=1, real_score=0.995,
                        null_scores=nulls)
    assert r["null_exceedance_rank"] == 0
    assert r["p_hat"] == round(1 / 101, 6)
    assert r["verdict"] == "DISCOVERY"
    weak = sequential_test(family="F", attempt=1, real_score=0.5,
                           null_scores=nulls)
    assert weak["verdict"] == "NOT_DISCOVERED"
    assert weak["p_hat"] > 0.025


def test_later_attempts_need_stronger_evidence():
    nulls = [i / 320 for i in range(320)]
    a1 = sequential_test(family="F", attempt=1, real_score=0.9,
                         null_scores=nulls)
    a3 = sequential_test(family="F", attempt=3, real_score=0.9,
                         null_scores=nulls)
    assert a1["alpha_k"] > a3["alpha_k"]
    assert "does not exist" in a1["lifetime_budget_note"] or \
        "do not exist" in a1["lifetime_budget_note"]


# ============ DECOMPOSABLE SCIENTIFIC VALIDITY

def _components(**over):
    base = {c: {"verdict": "PASS", "evidence": "x"}
            for c in VALIDITY_COMPONENTS}
    for k, v in over.items():
        base[k] = v
    return base


def test_one_failed_defense_means_no_overall_authority():
    d = scientific_validity_decomposition(components=_components(
        CROSS_EPOCH_MULTIPLICITY_CONTROL={"verdict": "FAIL",
                                          "evidence": "51 rebirths"}))
    assert d["OVERALL_SCIENTIFIC_AUTHORITY"] == "NONE"
    assert d["failed"] == ["CROSS_EPOCH_MULTIPLICITY_CONTROL"]
    assert "passing one defense is not passing the process" in d["law"]


def test_an_unexercised_defense_also_blocks_authority():
    d = scientific_validity_decomposition(components=_components(
        SURVIVORSHIP_CONTROL={"verdict": "NOT_EXERCISED",
                              "evidence": "no survivors existed"}))
    assert d["OVERALL_SCIENTIFIC_AUTHORITY"] == "NONE"


def test_all_passing_components_qualify():
    d = scientific_validity_decomposition(components=_components())
    assert d["OVERALL_SCIENTIFIC_AUTHORITY"] == "QUALIFIED"


def test_an_unnamed_defense_cannot_pass():
    c = _components()
    del c["LOCKBOX_INTEGRITY"]
    with pytest.raises(ChronosViolation, match="unnamed defense"):
        scientific_validity_decomposition(components=c)


# ============ ROSTER MULTIPLICITY (Campaign #003, predeclared)

from apex.chronos.roster import (ALPHA_GLOBAL, HypothesisRoster,
                                 hierarchical_alpha, roster_null_budget,
                                 three_level_hallucination)
from apex.chronos.scoring import campaign_status


def test_the_whole_tree_is_bounded_by_the_global_alpha():
    total = sum(hierarchical_alpha(mechanism_order=m, family_order=j,
                                   attempt=k)
                for m in range(1, 12) for j in range(1, 12)
                for k in range(1, 12))
    assert total < ALPHA_GLOBAL
    assert hierarchical_alpha(mechanism_order=1, family_order=1,
                              attempt=1) == 0.0125


def test_later_mechanisms_are_more_expensive_by_construction():
    a1 = hierarchical_alpha(mechanism_order=1, family_order=1,
                            attempt=1)
    a5 = hierarchical_alpha(mechanism_order=5, family_order=1,
                            attempt=1)
    assert a5 < a1
    assert roster_null_budget(a1) == 100
    assert roster_null_budget(a5) is None, \
        "mechanism 5's first attempt is already unresolvable at the " \
        "capped budget: research opportunity is consumed, not printed"


def test_tree_positions_are_permanent_first_test_order():
    r = HypothesisRoster(label="T")
    p1 = r.register_attempt_position(mechanism="M_A", family="F_A1")
    p2 = r.register_attempt_position(mechanism="M_B", family="F_B1")
    p3 = r.register_attempt_position(mechanism="M_A", family="F_A1")
    assert p1["mechanism_order"] == 1 and p2["mechanism_order"] == 2
    assert p3["mechanism_order"] == 1, "no re-sorting to a cheaper slot"
    assert p3["attempt"] == 2
    assert p3["alpha"] < p1["alpha"]


def test_an_unregistered_outcome_is_a_cooked_book():
    r = HypothesisRoster(label="T")
    with pytest.raises(ChronosViolation, match="cooked"):
        r.record_outcome(family="NEVER_SEEN", admitted=True)


def test_hallucination_is_three_numbers_never_one():
    r = HypothesisRoster(label="C")
    r.register_attempt_position(mechanism="M1", family="F1")
    r.register_attempt_position(mechanism="M2", family="F2")
    r.record_outcome(family="F1", admitted=True)
    r.record_outcome(family="F2", admitted=False)
    h = three_level_hallucination(
        control_roster=r,
        control_admissions=[
            {"spec_admitted": True, "family": "F1", "mechanism": "M1"},
            {"spec_admitted": False, "family": "F2",
             "mechanism": "M2"}])
    assert h["SPEC_HALLUCINATION_RATE"] == 0.5
    assert h["FAMILY_HALLUCINATION_RATE"] == 0.5
    assert h["MECHANISM_HALLUCINATION_RATE"] == 0.5
    assert h["verdict"] == "ROSTER_MULTIPLICITY_CONTROL_FAILED"
    assert "pooling is how a hierarchy hides" in h["law"]


def test_an_unmeasured_roster_is_not_a_clean_one():
    h = three_level_hallucination(
        control_roster=HypothesisRoster(label="E"),
        control_admissions=[])
    assert h["verdict"] == "NO_CONTROLS_RUN"


# ============ STATUS SEPARATION (operator: QUALIFIED must not imply
# proven edge)

def test_three_statuses_never_collapse_into_one_word():
    s = campaign_status(process_qualified=True,
                        economic_edge_proven=False)
    assert s["SCIENTIFIC_PROCESS_AUTHORITY"] == "QUALIFIED_REPLAY_ONLY"
    assert s["ECONOMIC_EDGE_STATUS"] == "UNPROVEN"
    assert s["TRADING_AUTHORITY"] == "NONE"


def test_no_replay_can_ever_claim_a_proven_edge():
    with pytest.raises(ChronosViolation, match="structurally incapable"):
        campaign_status(process_qualified=True,
                        economic_edge_proven=True)
