"""EdgeForge frontier stack contracts (Phases 1-27).

Weight-bearing tests: the firewall still holds across every new module;
the multiverse cannot be silently dominated by a model; the adversary
can actually kill things; nothing anywhere can reach a trading rung.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from apex.edgeforge.adversary import (
    AdversaryViolation, attack_candidate, entry_slippage, exit_friction,
    iv_shock)
from apex.edgeforge.attack_lab import (
    CandidateAttack, evaluate_common, summarize_attack)
from apex.edgeforge.baselines import (
    BaselineViolation, arena, build_baselines)
from apex.edgeforge.challenger import (
    ChallengerViolation, PROMOTION_LADDER, advance, mutate_challenger,
    reproducibility_manifest, seal_challenger, value_of_information)
from apex.edgeforge.credibility import (
    CredibilityViolation, register_claim, resolve_claim, standing)
from apex.edgeforge.discovery import (
    DiscoveryViolation, frontier_scan, propose_missing_variable,
    residual_search)
from apex.edgeforge.factory import (
    FactoryViolation, ResearchRun, frontier_report, world_budget)
from apex.edgeforge.observatory import (
    Observation, ObservatoryViolation, analog_quality, cohort_partition)
from apex.edgeforge.outcome_intel import (
    classify_decision, gate_value, opportunity_archaeology)
from apex.edgeforge.scaling import (
    ScalingViolation, capital_accelerant_research, kelly_reference,
    scale_response, simulate_capital_paths)
from apex.edgeforge.self_critic import critique
from apex.edgeforge.world_foundry import (
    ConditionalStateSpaceGenerator, FoundryViolation,
    causal_resampled_worlds, generative_health, memorization_test,
    results_by_class, triangulate, validate_generated_worlds,
    world_class_of, world_set_hash)

REPO = Path(__file__).resolve().parents[1]


# ============================================ 0. FIREWALL (extended)

EDGEFORGE_MODULES = sorted(
    p.name for p in (REPO / "apex" / "edgeforge").glob("*.py"))


def test_the_firewall_covers_every_edgeforge_module():
    """No incumbent may import ANY part of the research stack."""
    incumbents = [
        "scripts/options_paper_session.py", "scripts/btc_paper_session.py",
        "apex/predators/options/attack_geometry.py",
        "apex/predators/options/expression.py",
        "apex/predators/options/paper_execution.py",
        "apex/predators/equities/attack_geometry.py",
        "apex/btc_sleeve/participant_state.py",
        "apex/btc_sleeve/forced_action.py",
        "apex/btc_sleeve/attack_geometry.py",
        "apex/btc_sleeve/paper_execution.py",
    ]
    assert len(EDGEFORGE_MODULES) >= 12, "stack smaller than expected"
    for rel in incumbents:
        p = REPO / rel
        if p.exists():
            src = p.read_text()
            assert "edgeforge" not in src, f"{rel} reaches into EdgeForge"


def test_nothing_in_the_stack_grants_trading_authority():
    import re
    banned = re.compile(r"PAPER_AUTHORIZED|TINY_LIVE|LIVE_SCALE")
    for name in EDGEFORGE_MODULES:
        src = (REPO / "apex" / "edgeforge" / name).read_text()
        for m in banned.finditer(src):
            line = src[:m.start()].count("\n")
            ctx = src.splitlines()[line]
            assert ("FORBIDDEN" in ctx or "not on this ladder" in src
                    or "not reachable" in src), \
                f"{name}:{line} references {m.group()} outside a refusal"


# ============================================ 1. OBSERVATORY

def _obs(cohort="WAIT_FOR_ENTRY", session="2026-08-25", sym="SPY"):
    return Observation(observation_id=f"{sym}-{cohort}-{session}",
                       session=session, subject=sym, T="t",
                       cohort=cohort, genome_hash="h", genome={})


def test_an_unclassifiable_state_cannot_join_the_partition():
    with pytest.raises(ObservatoryViolation):
        _obs(cohort="SORT_OF_INTERESTING")


def test_outcomes_do_not_get_second_chances():
    o = _obs()
    o.resolve({"pnl": 1.0})
    with pytest.raises(ObservatoryViolation):
        o.resolve({"pnl": 2.0})


def test_cohorts_partition_and_report_resolution_separately():
    obs = [_obs("PAPER_ATTACKED"), _obs("WAIT_FOR_ENTRY"),
           _obs("NEAR_MISS")]
    obs[0].resolve({"pnl": -1.0})
    p = cohort_partition(obs)
    assert sum(p["counts"].values()) == 3
    assert p["resolved"] == {"PAPER_ATTACKED": 1}


class _A:
    def __init__(self, s, d, c=1.0):
        self.session, self.distance, self.feature_coverage = s, d, c


def test_analog_quality_flags_regime_concentration():
    sel = {"analogs": [_A(f"2020-01-{i:02d}", 0.1 + i * 0.01)
                       for i in range(1, 11)]}
    q = analog_quality(sel, regime_of={f"2020-01-{i:02d}": "HIGH_VOL"
                                       for i in range(1, 11)})
    assert q["regime_concentration"] == 1.0
    assert any("REGIME_CONCENTRATION" in c for c in q["concerns"])
    assert q["verdict"] == "QUALIFIED_WITH_CONCERNS"


def test_analog_quality_flags_top5_dominance_and_narrow_era():
    sel = {"analogs": [_A("2020-01-01", 0.001)] +
           [_A(f"2020-02-{i:02d}", 5.0) for i in range(1, 9)]}
    q = analog_quality(sel)
    assert any("TOP5_DOMINANCE" in c for c in q["concerns"])
    assert any("NARROW_ERA" in c for c in q["concerns"])


# ============================================ 4. WORLD FOUNDRY

def test_single_return_resampling_is_refused():
    with pytest.raises(FoundryViolation) as e:
        causal_resampled_worlds(returns_pool=[0.001] * 100, n_worlds=2,
                                horizon=10, start_price=100.0,
                                parent_state_hash="p", block=1)
    assert "autocorrelation" in str(e.value)


def test_resampled_worlds_are_deterministic_and_classed():
    kw = dict(returns_pool=[0.001, -0.002, 0.0015] * 50, n_worlds=3,
              horizon=20, start_price=100.0, parent_state_hash="p",
              seed=7)
    a = causal_resampled_worlds(**kw)
    b = causal_resampled_worlds(**kw)
    assert [w.path for w in a] == [w.path for w in b]
    assert world_class_of(a[0]) == "CAUSAL_RESAMPLED"


def _series(n_sessions=40, n=200, drift=0.0, vol=0.001, seed=3):
    from apex.edgeforge.world_foundry import _Rng
    rng = _Rng(seed)
    return [[drift + vol * rng.normal() for _ in range(n)]
            for _ in range(n_sessions)]


def test_the_generator_refuses_regimes_with_too_little_data():
    g = ConditionalStateSpaceGenerator()
    fit = g.fit(series_by_regime={"QUIET": _series(2, 20),
                                  "NORMAL": _series(40, 200)},
                min_obs=500)
    assert "QUIET" in fit["refused"]
    assert "NORMAL" in fit["regimes"]
    with pytest.raises(FoundryViolation) as e:
        g.sample(regime="QUIET", n_worlds=1, horizon=10,
                 start_price=100.0, parent_state_hash="p")
    assert "extrapolation dressed as simulation" in str(e.value)


def test_an_untrained_generator_may_not_produce_worlds():
    g = ConditionalStateSpaceGenerator()
    with pytest.raises(FoundryViolation):
        g.sample(regime="NORMAL", n_worlds=1, horizon=5,
                 start_price=100.0, parent_state_hash="p")


def test_generated_worlds_are_validated_against_real_ones():
    g = ConditionalStateSpaceGenerator()
    g.fit(series_by_regime={"NORMAL": _series(60, 200)})
    gen = g.sample(regime="NORMAL", n_worlds=30, horizon=200,
                   start_price=100.0, parent_state_hash="p")
    real = causal_resampled_worlds(
        returns_pool=[r for s in _series(60, 200) for r in s],
        n_worlds=30, horizon=200, start_price=100.0,
        parent_state_hash="p", seed=11)
    v = validate_generated_worlds(generated=gen, real=real)
    assert v["verdict"] in ("CONDITIONAL_FIDELITY_OK",
                            "CONDITIONAL_FIDELITY_FAILED")
    assert v["eligibility_recommendation"] in ("UNCALIBRATED",
                                               "SUSPENDED")


def test_memorization_is_detected_when_paths_are_copies():
    from apex.edgeforge.multiverse import WorldBranch
    train = [tuple((i, 100.0 + i * 0.1) for i in range(50))]
    copy = WorldBranch(branch_id="g", parent_state_hash="p",
                       hypothesis_condition="c",
                       generation_method="ADVERSARIAL_STRESS",
                       generation_pedigree="[LEARNED_GENERATIVE] copy",
                       path=train[0])
    m = memorization_test(generated=[copy], training_paths=train)
    assert m["verdict"] == "MEMORIZATION_SUSPECTED"
    assert "not a multiverse" in m["law"]


def test_a_model_cannot_silently_outvote_reality():
    from apex.edgeforge.multiverse import WorldBranch
    def mk(cls, i):
        return WorldBranch(
            branch_id=f"{cls}{i}", parent_state_hash="p",
            hypothesis_condition="c",
            generation_method="ADVERSARIAL_STRESS",
            generation_pedigree=f"[{cls}] t", path=((0, 1.0), (1, 1.1)))
    t = triangulate({"LEARNED_GENERATIVE": [mk("LEARNED_GENERATIVE", i)
                                            for i in range(9)],
                     "EMPIRICAL_ANALOG": [mk("EMPIRICAL_ANALOG", 0)]})
    assert any("outvoting reality" in w for w in t["warnings"])
    t2 = triangulate({"LEARNED_GENERATIVE": [mk("LEARNED_GENERATIVE", 0)]})
    assert any("lost its reality anchor" in w for w in t2["warnings"])


def test_an_empty_multiverse_is_refused():
    with pytest.raises(FoundryViolation):
        triangulate({})


def test_world_set_hash_is_stable_and_content_sensitive():
    w = causal_resampled_worlds(returns_pool=[0.001] * 100, n_worlds=3,
                                horizon=10, start_price=100.0,
                                parent_state_hash="p", block=5, seed=1)
    assert world_set_hash(w) == world_set_hash(list(reversed(w)))
    w2 = causal_resampled_worlds(returns_pool=[0.002] * 100, n_worlds=3,
                                 horizon=10, start_price=100.0,
                                 parent_state_hash="p", block=5, seed=1)
    assert world_set_hash(w) != world_set_hash(w2)


def test_generative_health_suspends_on_failure():
    h = generative_health(
        validation={"verdict": "CONDITIONAL_FIDELITY_FAILED",
                    "failures": ["ret_sd"]},
        memorization={"verdict": "NO_MEMORIZATION_DETECTED"})
    assert h["generative_world_eligibility"] == "SUSPENDED"
    assert "EMPIRICAL_ANALOG worlds remain available" in h["fallback"]


# ============================================ 5. ADVERSARY

def _stock(entry=100.0, aid="cand", direction="LONG"):
    return CandidateAttack(
        attack_id=aid, kind="INCUMBENT", expression="STOCK",
        params={"direction": direction, "entry": entry, "shares": 100,
                "round_trip_friction": 0.0},
        evaluator_name="stock",
        execution_pedigree="MODELLED_EXECUTION", declared_1R=100.0)


def _mixed_worlds(n=10):
    from apex.edgeforge.multiverse import WorldBranch
    out = []
    for i in range(n):
        d = 0.4 if i % 2 == 0 else -0.1
        out.append(WorldBranch(
            branch_id=f"w{i}", parent_state_hash="p",
            hypothesis_condition="c",
            generation_method="EMPIRICAL_HISTORICAL_ANALOG",
            generation_pedigree="[EMPIRICAL_ANALOG] t",
            path=tuple((t, 100.0 + d * t) for t in range(10)),
            source_session=f"2020-0{i % 9 + 1}-01"))
    return out


def test_the_adversary_can_actually_kill_an_edge():
    worlds = _mixed_worlds()
    rep = attack_candidate(
        attack=_stock(), worlds=worlds, evaluate_common=evaluate_common,
        stress_grid={"ENTRY_SLIPPAGE": [(0.05, entry_slippage(0.05)),
                                        (5.0, entry_slippage(5.0))]})
    assert rep["breakpoints_by_family"]["EXECUTION"]["ENTRY_SLIPPAGE"] \
        == 5.0, "a 5-point slippage should break a 0.4/bar drift edge"
    assert rep["verdict"] in ("CONDITIONALLY_ROBUST", "FRAGILE")


def test_an_undeclared_stress_is_refused():
    with pytest.raises(AdversaryViolation):
        attack_candidate(attack=_stock(), worlds=_mixed_worlds(),
                         evaluate_common=evaluate_common,
                         stress_grid={"VIBES": [(1.0, lambda a, w: (a, w))]})


def test_breakpoints_are_reported_per_family_not_averaged():
    rep = attack_candidate(
        attack=_stock(), worlds=_mixed_worlds(),
        evaluate_common=evaluate_common,
        stress_grid={"ENTRY_SLIPPAGE": [(9.0, entry_slippage(9.0))]})
    assert "breakpoints_by_family" in rep
    assert "robustness_score" not in rep, "a magic score reappeared"


# ============================================ 20. BASELINES

def test_a_candidate_that_cannot_beat_flat_is_named():
    worlds = _mixed_worlds()
    loser = _stock(entry=200.0, aid="loser")     # entry far above path
    res = arena(candidate=loser,
                baselines=build_baselines(entry=100.0),
                worlds=worlds, evaluate_common=evaluate_common,
                summarize_attack=summarize_attack)
    assert res["beats_no_trade"] is False
    assert res["verdict"] == "INFERIOR_TO_A_SIMPLE_BASELINE"


def test_undeclared_baselines_are_refused():
    with pytest.raises(BaselineViolation):
        build_baselines(entry=100.0, include=("MAGIC_ORACLE",))


# ============================================ 8. CREDIBILITY

def test_unsupported_certainty_is_refused(tmp_path):
    led = tmp_path / "c.jsonl"
    with pytest.raises(CredibilityViolation):
        register_claim(led, claim_id="c1", faculty="curve",
                       claim_type="PROBABILISTIC", prediction="up",
                       probability=1.0, resolution_rule="close>open",
                       context={}, session="s1")


def test_a_claim_without_a_resolution_rule_is_free_credibility(tmp_path):
    with pytest.raises(CredibilityViolation) as e:
        register_claim(tmp_path / "c.jsonl", claim_id="c1",
                       faculty="f", claim_type="ORDINAL",
                       prediction="up", resolution_rule="",
                       context={}, session="s")
    assert "free credibility" in str(e.value)


def test_standing_refuses_a_busy_afternoon(tmp_path):
    led = tmp_path / "c.jsonl"
    for i in range(30):
        register_claim(led, claim_id=f"c{i}", faculty="curve",
                       claim_type="ORDINAL", prediction="up",
                       resolution_rule="r", context={"regime": "TREND"},
                       session="2026-08-25")          # ALL one session
        resolve_claim(led, claim_id=f"c{i}", outcome="up")
    s = standing(led, faculty="curve", context_key="regime")
    e = s["by_context"]["TREND"]
    assert e["n_raw"] == 30 and e["n_effective_lower_bound"] == 1
    assert e["verdict"] == "INSUFFICIENT_EVIDENCE"


def test_standing_measures_across_independent_sessions(tmp_path):
    led = tmp_path / "c.jsonl"
    for i in range(25):
        register_claim(led, claim_id=f"c{i}", faculty="curve",
                       claim_type="ORDINAL", prediction="up",
                       resolution_rule="r", context={"regime": "TREND"},
                       session=f"2026-08-{i + 1:02d}")
        resolve_claim(led, claim_id=f"c{i}",
                      outcome="up" if i < 15 else "down")
    e = standing(led, faculty="curve",
                 context_key="regime")["by_context"]["TREND"]
    assert e["verdict"] == "MEASURED"
    assert e["hit_rate"] == 0.6


# ============================================ 2. DISCOVERY

def _pop(n=60):
    out = []
    for i in range(n):
        hidden = 1.0 if i % 2 == 0 else -1.0
        out.append({"entry_quality": "GOOD", "chase": "LOW",
                    "liquidity_replenishment": hidden + 0.01 * i,
                    "noise": (i * 37) % 11,
                    "outcome_R": hidden * 0.5,
                    "session": f"2026-07-{i % 28 + 1:02d}"})
    return out


def test_residual_search_finds_structure_the_incumbent_cannot_see():
    r = residual_search(
        observations=_pop(), incumbent_equivalence=("entry_quality",
                                                    "chase"),
        candidate_variables=("liquidity_replenishment", "noise"),
        outcome_key="outcome_R", family="LIQUIDITY_TRANSITIONS")
    assert r["verdict"] == "CANDIDATES_GENERATED"
    top = r["findings"][0]
    assert top["candidate_variable"] == "liquidity_replenishment"
    assert abs(top["separation_over_sd"]) > 0.5
    assert r["search_accounting"]["family_wise_search_count"] >= 2


def test_a_missing_variable_hypothesis_needs_falsifiers():
    r = residual_search(
        observations=_pop(), incumbent_equivalence=("entry_quality",),
        candidate_variables=("liquidity_replenishment",),
        outcome_key="outcome_R", family="LIQUIDITY_TRANSITIONS")
    with pytest.raises(DiscoveryViolation):
        propose_missing_variable(
            search=r, finding=r["findings"][0], hypothesis_id="MV1",
            mechanism="m", competing=("alt",), falsifiers=(),
            n_effective=20)


def test_the_scan_reports_the_whole_denominator():
    s = frontier_scan(
        observations=_pop(),
        families=("LIQUIDITY_TRANSITIONS", "TAIL_PRECURSORS"),
        incumbent_equivalence=("entry_quality",),
        candidate_variables=("liquidity_replenishment", "noise"),
        outcome_key="outcome_R")
    assert s["total_comparisons_across_families"] >= 4
    assert "must be read against" in s["runs"][
        "LIQUIDITY_TRANSITIONS"]["law"]


# ============================================ 12-14. OUTCOME INTEL

def test_a_profitable_trade_can_be_a_bad_decision():
    c = classify_decision(pnl=500.0, mid_change=520.0,
                          thesis_path_state="THESIS_NEVER_INVALIDATED",
                          adversary_verdict="FRAGILE",
                          boundary_proximity="KNIFE_EDGE",
                          friction_share=0.04)
    assert c["primary_class"] == "BAD_DECISION_GOOD_OUTCOME"
    assert "Nobody investigates a winner" in " ".join(c["reasoning"])


def test_a_losing_trade_can_be_a_good_decision():
    c = classify_decision(pnl=-100.0, mid_change=-95.0,
                          thesis_path_state="THESIS_NEVER_INVALIDATED",
                          adversary_verdict="CONDITIONALLY_ROBUST",
                          boundary_proximity="INTERIOR",
                          friction_share=0.05)
    assert c["primary_class"] == "GOOD_DECISION_BAD_OUTCOME"


def test_archaeology_requires_the_control_group():
    """Tails must be genuinely separable, and their near-twins are the
    control group without which this is jackpot storytelling."""
    pop = [{"f1": (2.0 if i > 47 else 0.0) + i * 0.001,
            "f2": (i * 7) % 5,
            "outcome_R": (3.0 if i > 47 else 0.01 * (i % 7))}
           for i in range(60)]
    a = opportunity_archaeology(target=pop[50], population=pop,
                                prestate_fields=("f1", "f2"),
                                outcome_key="outcome_R")
    assert a["verdict"] != "DEGENERATE_TAIL_CUT"
    assert a["n_near_twins"] > 0
    assert "control group" in a["law"]
    assert a["discriminators"]
    assert a["discriminators"][0]["field"] == "f1"


def test_a_degenerate_tail_cut_says_no_comparison_was_possible():
    """Outcomes concentrated at a mass point leave no control group;
    that is different from finding no discriminators."""
    pop = [{"f1": i * 0.1, "outcome_R": 0.05} for i in range(60)]
    a = opportunity_archaeology(target=pop[10], population=pop,
                                prestate_fields=("f1",),
                                outcome_key="outcome_R")
    assert a["verdict"] == "DEGENERATE_TAIL_CUT"
    assert "no control group" in a["why"]


def test_gate_value_names_backward_filtering_without_acting():
    g = gate_value(cohorts={"PAPER_ATTACKED": [-0.2, -0.3],
                            "WAIT_FOR_ENTRY": [0.1, 0.2, 0.05]},
                   horizon_note="session close")
    assert "REFUSED_STATES_OUTPERFORMED_ATTACKS" in g["signal"]
    assert "never optimized automatically" in g["law"]


# ============================================ 15-17. SCALING

def test_an_edge_that_survives_institutional_size_is_not_ours():
    r = scale_response(base_edge_per_unit=1.0, touch_liquidity=1e9,
                       spread=0.01, unit_notional=100.0)
    assert r["verdict"] == "INSTITUTIONAL_ADVANTAGE"
    assert "not ours" in r["why"]


def test_capacity_limited_edge_indicates_small_advantage():
    r = scale_response(base_edge_per_unit=0.02, touch_liquidity=50.0,
                       spread=0.05, unit_notional=76_300.0)
    assert r["verdict"] in ("SMALL_ADVANTAGE_INDICATED", "NEUTRAL_SCALE")


def test_iid_capital_simulation_is_refused():
    with pytest.raises(ScalingViolation) as e:
        simulate_capital_paths(r_multiples=[1.0, -1.0], risk_fraction=0.01,
                               trades_per_path=10, n_paths=5,
                               starting_equity=10_000, cluster_len=1)
    assert "loss clustering" in str(e.value)


def test_clustered_simulation_reports_ruin_and_drawdown():
    rs = [1.5, -1.0, -1.0, -1.0, 2.0, -1.0, 0.5, -1.0]
    out = simulate_capital_paths(r_multiples=rs, risk_fraction=0.05,
                                 trades_per_path=100, n_paths=200,
                                 starting_equity=10_000, seed=5)
    assert 0.0 <= out["risk_of_ruin"] <= 1.0
    assert out["max_drawdown_p95"] >= out["max_drawdown_median"]
    assert "not a prediction" in out["not_a_forecast"]


def test_kelly_is_a_reference_not_an_instruction():
    k = kelly_reference(win_rate=0.55, win_loss_ratio=1.5,
                        estimation_error="NOT_ESTIMABLE")
    assert k["is_a_sizing_instruction"] is False
    assert "ruin machine" in k["warning"]


def test_accelerant_research_returns_insufficient_when_unknown():
    a = capital_accelerant_research(
        tail_asymmetry="NOT_ESTIMABLE", loss_bound=True,
        capital_efficiency="high", holding_period="intraday",
        execution="ok", mechanism="plausible", capacity="small",
        uncertainty="high", correlation="low")
    assert a["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert a["grants_capital_authority"] is False


# ============================================ 19. SELF-CRITIC

def test_the_critic_downgrades_an_unexamined_finding():
    c = critique(discovery={"dataset_boundary": "", "falsifiers": ()},
                 prospective_n=0)
    assert c["research_confidence"] in ("RESEARCH_DOUBTFUL",
                                        "RESEARCH_REJECTED")
    assert c["may_promote"] is False
    assert "leakage" in c["concerns"]


def test_the_critic_can_never_promote():
    c = critique(
        discovery={"dataset_boundary": "DAY1_CORRECTED",
                   "falsifiers": ("x",),
                   "competing_explanations": ("y",)},
        analog_quality={"regime_concentration": 0.2,
                        "n_effective_lower_bound": 40},
        adversary={"verdict": "CONDITIONALLY_ROBUST",
                   "execution_breakpoint": {}},
        arena={"verdict": "BEATS_ALL_TESTED_BASELINES", "lost_to": []},
        world_class_split={"flag": None},
        family={"n_experiments": 12, "n_null_or_dead": 9},
        prospective_n=30)
    assert c["research_confidence"] == "RESEARCH_PROMISING"
    assert c["may_promote"] is False


# ============================================ 21/23/26. CHALLENGER

def _chal(**kw):
    base = dict(challenger_id="CH1", sealed_rules={"entry": "x"},
                feature_requirements=("f1",),
                execution_assumptions={"fill": "quoted"},
                invalidation={"level": 1.0}, exit_rule="close",
                risk_basis="FULL_PREMIUM", eligible_universe=("SPY",),
                expected_failure_conditions=("chop",))
    base.update(kw)
    return seal_challenger(**base)


def test_a_challenger_must_say_how_it_expects_to_fail():
    with pytest.raises(ChallengerViolation):
        _chal(expected_failure_conditions=())


def test_a_challenger_cannot_be_born_on_a_trading_rung():
    with pytest.raises(ChallengerViolation) as e:
        _chal(rung="PAPER_AUTHORIZED")
    assert "not reachable from EdgeForge" in str(e.value)


def test_mutation_births_a_child_with_a_fresh_record():
    p = _chal()
    c = mutate_challenger(p, suffix="B", mutation_reason="new condition",
                          sealed_rules={"entry": "y"})
    assert c.challenger_id == "CH1B" and c.parent_challenger_id == "CH1"
    assert c.definition_hash() != p.definition_hash()
    assert p.sealed_rules == {"entry": "x"}


def test_the_ladder_stops_at_paper_review():
    assert PROMOTION_LADDER[-1] == "PAPER_REVIEW"
    out = advance("PAPER_REVIEW", evidence={"anything": True})
    assert out["advanced"] is False
    assert "operator decision" in out["why"]


def test_rungs_require_their_own_evidence():
    blocked = advance("RESEARCH_CANDIDATE", evidence={})
    assert blocked["advanced"] is False
    assert set(blocked["missing_evidence"]) >= {
        "world_evidence", "beats_baselines", "adversary_survived"}
    ok = advance("RESEARCH_CANDIDATE",
                 evidence={"world_evidence": 1, "beats_baselines": 1,
                           "adversary_survived": 1})
    assert ok["to"] == "HISTORICALLY_VALIDATED"


def test_a_feed_that_changes_nothing_is_overhead():
    v = value_of_information(
        feed_name="expensive_feed", decisions_changed=0,
        decisions_observed=500, losses_avoided=0,
        opportunities_found=0, discrimination_delta=0.0,
        execution_delta=0.0, cost_monthly=2000, latency_ms=40,
        complexity="high", new_failure_modes=("vendor outage",))
    assert v["verdict"] == "CHANGES_NOTHING_OBSERVED"
    assert "overhead" in v["law"]


def test_an_unreconstructable_result_is_not_a_result():
    m = reproducibility_manifest(code_sha="abc", dataset_boundary="d")
    assert m["verdict"] == "RESULT_UNVERIFIABLE"
    assert "absence of one" in m["law"]


# ============================================ 18/27. FACTORY

def test_the_factory_cannot_spend_a_confirmatory_credit():
    r = ResearchRun(session="2026-08-25")
    with pytest.raises(FactoryViolation) as e:
        r.stage("RUN_FRONTIER_DISCOVERY", {}, consumes_confirmatory=True)
    assert "explicit authority" in str(e.value)


def test_the_report_leads_with_failures():
    r = ResearchRun(session="2026-08-25")
    r.stage("BUILD_GENOMES", {"n": 5})
    rep = frontier_report(r, discoveries=["d1"], nulls=["n1", "n2"],
                          killed_by_adversary=["k1"],
                          inferior_to_baseline=["b1"])
    keys = list(rep)
    assert keys.index("null_results") < keys.index("new_hypotheses")
    assert rep["n_negative_findings"] == 4
    assert rep["promotes_nothing"] is True


def test_world_budget_is_staged_behind_validation():
    b = world_budget("DEEP_RESEARCH")
    assert b["granted"] == "SMOKE" and b["blockers"]
    ok = world_budget("RESEARCH", pipeline_valid=True,
                      generator_valid=True)
    assert ok["granted"] == "RESEARCH"
