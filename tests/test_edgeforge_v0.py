"""EdgeForge V0 contracts.

The tests that carry the weight: the firewall (EdgeForge is physically
incapable of touching V1), the causal ordering of the analog engine,
the common-world law, and every refusal that keeps the research
substrate from inventing numbers it has not earned.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apex.edgeforge.attack_lab import (
    AttackLabViolation, CandidateAttack, evaluate_common,
    summarize_attack)
from apex.edgeforge.edge_dna import (
    EdgeDNA, EdgeDNAViolation, SmallWinsAssessment,
    capital_accelerant_assessment, mutate)
from apex.edgeforge.edge_surface import (
    AxisSpec, EdgeSurfaceViolation, sweep)
from apex.edgeforge.genome import (
    GenomeField, GenomeViolation, MarketStateGenome)
from apex.edgeforge.hypotheses import (
    DisagreementState, HypothesisTournament, HypothesisViolation,
    MarketHypothesis)
from apex.edgeforge.multiverse import (
    MultiverseViolation, WorldBranch, adversarial_branch,
    branches_from_analogs, select_analogs)
from apex.edgeforge.registry import (
    RegistryViolation, family_ledger, record_result, register_discovery)

REPO = Path(__file__).resolve().parents[1]


# ================================================= 0. THE FIREWALL

INCUMBENT_DECISION_PATHS = [
    "scripts/options_paper_session.py",
    "scripts/btc_paper_session.py",
    "apex/predators/options/attack_geometry.py",
    "apex/predators/options/expression.py",
    "apex/predators/options/paper_execution.py",
    "apex/predators/equities/attack_geometry.py",
    "apex/btc_sleeve/participant_state.py",
    "apex/btc_sleeve/forced_action.py",
    "apex/btc_sleeve/attack_geometry.py",
    "apex/btc_sleeve/paper_execution.py",
    "apex/execution_paper/harness.py",
]


def test_no_incumbent_can_import_edgeforge():
    """V0 is physically incapable of changing a live/paper decision."""
    for rel in INCUMBENT_DECISION_PATHS:
        p = REPO / rel
        if not p.exists():
            continue
        assert "apex.edgeforge" not in p.read_text(), (
            f"{rel} imports EdgeForge -- the arrow points V1 -> "
            f"EdgeForge, never back")


def test_every_edgeforge_output_is_powerless():
    from apex.edgeforge import EDGEFORGE_POWER
    assert EDGEFORGE_POWER == "NONE_RESEARCH"


# ================================================= 1. GENOME

def _genome():
    g = MarketStateGenome(subject="SPY", T="2026-08-24 09:55:04",
                          session="2026-08-24",
                          source_lineage="DAY1_CORRECTED")
    g.add("UNDERLYING", "gap_pct", 0.42, known_from="09:30",
          source="alpaca_daily", pedigree="OBSERVED", authority="SENSOR")
    g.add("UNDERLYING", "trend_state", "DOWN", known_from="09:55",
          source="equity_faculty", pedigree="COMMISSIONED",
          authority="EQUITY_FACULTY")
    g.add("OPTIONS", "atm_iv", 0.146, known_from="09:55",
          source="options_state", pedigree="COMMISSIONED",
          authority="OPTIONS_FACULTY")
    g.add("BTC", "funding", "UNKNOWN", known_from="09:55",
          source="derivatives_poller", pedigree="OBSERVED",
          quality="UNKNOWN")
    return g


def test_a_genome_from_corrupted_lineage_refuses_to_exist():
    with pytest.raises(GenomeViolation) as e:
        MarketStateGenome(subject="SPY", T="t", session="s",
                          source_lineage="DAY1_SUPERSEDED_ORIGINAL")
    assert "known-corrupted labels are forbidden" in str(e.value)


def test_unknown_stays_unknown_and_is_never_imputed():
    v = _genome().vector([("UNDERLYING", "gap_pct"), ("BTC", "funding"),
                          ("OPTIONS", "missing_field")])
    assert v["values"] == {"UNDERLYING.gap_pct": 0.42}
    assert any(x["field"] == "BTC.funding"
               for x in v["excluded_non_numeric"])
    assert "OPTIONS.missing_field" in v["missing"]
    assert "nothing was imputed" in v["law"]


def test_forward_filling_is_refused_by_construction():
    with pytest.raises(GenomeViolation) as e:
        GenomeField(name="x", value=1.0, event_time=None,
                    known_from="t", source="s", pedigree="p",
                    forward_filled=True)
    assert "explicit authorization" in str(e.value)


def test_every_field_carries_full_provenance():
    rec = _genome().as_record()
    f = rec["fields"]["OPTIONS"]["atm_iv"]
    for k in ("value", "event_time", "known_from", "source", "pedigree",
              "quality", "authority"):
        assert k in f
    assert rec["state_hash"] and len(rec["state_hash"]) == 64


def test_state_hash_is_content_sensitive():
    a, b = _genome(), _genome()
    b.add("TIME", "time_from_open_min", 25.0, known_from="09:55",
          source="clock", pedigree="OBSERVED")
    assert a.state_hash() != b.state_hash()


# ================================================= 2. HYPOTHESES

def _hyp(hid="H1", **kw):
    base = dict(hypothesis_id=hid, birth_time="t",
                mechanism="opening downside impulse continues",
                falsifiers=("reclaim of open VWAP",))
    base.update(kw)
    return MarketHypothesis(**base)


def test_a_hypothesis_without_falsifiers_is_refused():
    with pytest.raises(HypothesisViolation) as e:
        _hyp(falsifiers=())
    assert "cannot be wrong" in str(e.value)


def test_no_invented_probability_may_ride_in_as_evidence():
    with pytest.raises(HypothesisViolation):
        _hyp(supporting_evidence=("probability 0.7 of continuation",))


def test_the_tournament_preserves_disagreement_and_refuses_to_average():
    t = HypothesisTournament(state_hash="x")
    t.enter(_hyp("H1"))
    t.enter(_hyp("H2", mechanism="ordinary opening volatility"))
    s = t.standings()
    assert s["live_disagreement"] is True
    assert s["note"] == "OK"
    with pytest.raises(HypothesisViolation):
        t.average()


def test_a_single_hypothesis_is_flagged_as_a_story():
    t = HypothesisTournament(state_hash="x")
    t.enter(_hyp("H1"))
    assert "SINGLE_NARRATIVE_WARNING" in t.standings()["note"]


def test_disagreement_records_redundancy_and_carries_no_conclusion():
    d = DisagreementState(state_hash="x", faculty_a="equity",
                          reading_a="trend UP", faculty_b="options",
                          reading_b="upside expensive",
                          inputs_redundancy="PARTIALLY_REDUNDANT")
    assert d.conclusion == "NONE_RECORDED"
    with pytest.raises(HypothesisViolation):
        DisagreementState(state_hash="x", faculty_a="a", reading_a="r",
                          faculty_b="b", reading_b="r2",
                          conclusion="A_IS_RIGHT")


# ================================================= 3. MULTIVERSE

def _worlds(n=5, start=100.0, drifts=None):
    drifts = drifts or [0.5, -0.5, 1.0, -1.0, 0.0][:n]
    out = []
    for i, d in enumerate(drifts):
        path = tuple((m, start + d * m / 60.0) for m in range(0, 361, 60))
        out.append(WorldBranch(
            branch_id=f"w{i}", parent_state_hash="p",
            hypothesis_condition="UNCONDITIONED_EMPIRICAL",
            generation_method="EMPIRICAL_HISTORICAL_ANALOG",
            generation_pedigree="test", path=path,
            source_session=f"2020-01-0{i + 1}"))
    return out


def test_analog_selection_cannot_see_the_future_by_construction():
    import inspect
    from apex.edgeforge import multiverse as m
    sig = inspect.signature(m.select_analogs)
    assert "future" not in " ".join(sig.parameters).lower(), \
        "selection accepting futures would let membership peek ahead"


def test_analogs_are_chosen_by_pre_state_distance():
    cur = {"gap": 0.5, "drift": -0.3}
    cands = {"2020-01-02": {"gap": 0.52, "drift": -0.28},
             "2021-06-15": {"gap": -2.0, "drift": 2.0},
             "2022-03-08": {"gap": 0.48, "drift": -0.33}}
    sel = select_analogs(current_features=cur, candidates=cands, k=2)
    got = [a.session for a in sel["analogs"]]
    assert "2021-06-15" not in got
    assert sel["n_effective_lower_bound"] == 2
    assert "futures revealed only after" in sel["law"]


def test_low_coverage_candidates_are_excluded_not_imputed():
    cur = {"a": 1.0, "b": 1.0, "c": 1.0}
    cands = {"s1": {"a": 1.0, "b": 1.0, "c": 1.0},
             "s2": {"a": 1.0},                       # 33% coverage
             "s3": {"a": 1.1, "b": 0.9, "c": 1.05}}
    sel = select_analogs(current_features=cur, candidates=cands, k=5,
                         min_coverage=0.8)
    assert "s2" not in [a.session for a in sel["analogs"]]


def test_missing_futures_are_dropped_and_reported_never_fabricated():
    cur = {"a": 1.0}
    cands = {"s1": {"a": 1.0}, "s2": {"a": 1.1}}
    sel = select_analogs(current_features=cur, candidates=cands, k=2,
                         min_coverage=0.5)
    out = branches_from_analogs(selection=sel,
                                futures={"s1": ((0, 100.0), (60, 101.0))},
                                parent_state_hash="p")
    assert len(out["branches"]) == 1
    assert out["missing_futures"] == ["s2"]


def test_fake_branch_probabilities_are_refused():
    with pytest.raises(MultiverseViolation) as e:
        WorldBranch(branch_id="w", parent_state_hash="p",
                    hypothesis_condition="c",
                    generation_method="EMPIRICAL_HISTORICAL_ANALOG",
                    generation_pedigree="t", path=((0, 1.0),),
                    branch_weight_status="P=0.35")
    assert "fake" in str(e.value)


def test_adversarial_worlds_are_labelled_stress_not_probability():
    base = _worlds(1)[0]
    b = adversarial_branch(base=base, kind="ENTRY_SLIPPAGE",
                           transform=lambda p: [(t, px - 0.05)
                                                for t, px in p],
                           note="entry 5c worse")
    assert b.generation_method == "ADVERSARIAL_STRESS"
    assert "not a\nmarket probability" in b.generation_pedigree or \
        "not a market probability" in b.generation_pedigree.replace(
            "\n", " ")


# ================================================= 4. ATTACK LAB

def _stock_attack(direction="LONG", entry=100.0, aid="a1",
                  kind="SYNTHETIC"):
    return CandidateAttack(
        attack_id=aid, kind=kind, expression="STOCK",
        params={"direction": direction, "entry": entry, "shares": 100},
        evaluator_name="stock",
        execution_pedigree="MODELLED_EXECUTION", declared_1R=100.0)


def test_every_attack_fights_the_identical_world_set():
    worlds = _worlds(5)
    run = evaluate_common(
        attacks=[_stock_attack(aid="long"),
                 _stock_attack("SHORT", aid="short"),
                 CandidateAttack(attack_id="flat", kind="SYNTHETIC",
                                 expression="NO_TRADE", params={},
                                 evaluator_name="no_trade",
                                 execution_pedigree="NONE")],
        worlds=worlds)
    ids = set(run["world_ids"])
    for a, outs in run["outcomes"].items():
        assert set(outs) == ids, f"{a} fought a different universe"


def test_summaries_speak_world_fractions_not_probabilities():
    worlds = _worlds(5)
    a = _stock_attack()
    run = evaluate_common(attacks=[a], worlds=worlds)
    s = summarize_attack(run, a)
    assert "favorable_world_fraction" in s
    assert "probability" not in " ".join(s).lower()
    assert "never probabilities" in s["law"]


def test_no_trade_is_a_first_class_baseline():
    worlds = _worlds(3)
    flat = CandidateAttack(attack_id="flat", kind="SYNTHETIC",
                           expression="NO_TRADE", params={},
                           evaluator_name="no_trade",
                           execution_pedigree="NONE")
    run = evaluate_common(attacks=[flat], worlds=worlds)
    assert all(o["pnl"] == 0.0 for o in run["outcomes"]["flat"].values())


def test_bsm_reprice_carries_its_modelled_pedigree():
    from apex.edgeforge.attack_lab import long_option_bsm_evaluator
    a = CandidateAttack(
        attack_id="put", kind="INCUMBENT", expression="LONG_PUT",
        params={"entry_premium": 2.79, "strike": 763.0,
                "option_type": "put", "iv": 0.146, "dte_days": 2,
                "contracts": 1},
        evaluator_name="long_option_bsm",
        execution_pedigree="MODELLED_BSM_REPRICE", declared_1R=279.0)
    w = WorldBranch(branch_id="w", parent_state_hash="p",
                    hypothesis_condition="c",
                    generation_method="EMPIRICAL_HISTORICAL_ANALOG",
                    generation_pedigree="t",
                    path=tuple((m, 763.4 - m * 0.01)
                               for m in range(0, 361, 30)))
    out = long_option_bsm_evaluator(a, w)
    assert isinstance(out["pnl"], float)
    assert out["pnl"] > 0, "a falling path should pay a put"
    assert a.execution_pedigree == "MODELLED_BSM_REPRICE"


# ================================================= 5. EDGE SURFACE

def test_an_axis_without_a_mechanism_reason_is_refused():
    with pytest.raises(EdgeSurfaceViolation) as e:
        AxisSpec(name="x", values=(1, 2), mechanism_reason="")
    assert "fishing rod" in str(e.value)


def test_the_surface_finds_decision_boundaries():
    worlds = _worlds(5, drifts=[2.0, 1.5, 1.0, -0.2, -0.4])
    surf = sweep(
        base_params={"direction": "LONG", "shares": 100},
        axes=[AxisSpec(name="entry", values=(100.0, 106.0, 112.0),
                       mechanism_reason="how far can entry worsen "
                                        "before the edge disappears")],
        worlds=worlds,
        make_attack=lambda p: _stock_attack(
            "LONG", p["entry"], aid=f"e{p['entry']}"),
        evaluate_common=evaluate_common,
        summarize_attack=summarize_attack)
    assert surf["n_cells"] == 3
    assert surf["region_rule"]["classification"] == "REPORTING_PRIOR"
    regions = {c["cell"]["entry"]: c["region"] for c in surf["cells"]}
    assert regions[100.0] == "ROBUST_REGION"
    assert regions[112.0] == "FAILURE_REGION"
    assert surf["decision_boundaries"], "the flip point must be found"


def test_brute_force_surfaces_are_refused():
    axes = [AxisSpec(name=f"a{i}", values=(1, 2), mechanism_reason="m")
            for i in range(4)]
    with pytest.raises(EdgeSurfaceViolation):
        sweep(base_params={}, axes=axes, worlds=_worlds(2),
              make_attack=None, evaluate_common=None,
              summarize_attack=None)


# ================================================= 6. EDGE DNA

def _dna(**kw):
    base = dict(
        edge_id="EDGE_00001", birth_timestamp="t",
        discovery_origin="monday_case_study",
        mechanism="opening impulse continuation",
        required_state={"trend": "DOWN"},
        competing_explanations=("ordinary opening volatility",),
        why_small_wins=SmallWinsAssessment.build(
            reason="UNKNOWN",
            giant_competition_risk="HIGH").as_record())
    base.update(kw)
    return EdgeDNA(**base)


def test_an_edge_without_competing_explanations_is_a_story():
    with pytest.raises(EdgeDNAViolation):
        _dna(competing_explanations=())


def test_why_small_wins_is_mandatory_even_when_unknown():
    with pytest.raises(EdgeDNAViolation):
        _dna(why_small_wins={})


def test_claimed_small_advantage_requires_evidence():
    with pytest.raises(EdgeDNAViolation) as e:
        SmallWinsAssessment(reason="FOOTPRINT_ADVANTAGE")
    assert "UNKNOWN" in str(e.value)


def test_giant_terrain_with_no_small_advantage_is_flagged():
    a = SmallWinsAssessment.build(reason="UNKNOWN",
                                  giant_competition_risk="HIGH")
    assert "someone else's edge" in a.flag


def test_edges_cannot_self_promote():
    with pytest.raises(EdgeDNAViolation) as e:
        _dna(authority="PAPER_EXPLORATORY")
    assert "self-promotion" in str(e.value)


def test_mutation_births_a_child_and_never_edits_the_parent():
    parent = _dna()
    child = mutate(parent, child_suffix="B",
                   mutation_reason="condition on IV regime",
                   mechanism="opening impulse continuation in low IV")
    assert child.edge_id == "EDGE_00001B"
    assert child.parent_edge_id == "EDGE_00001"
    assert child.prospective_support["n"] == 0
    assert parent.mechanism == "opening impulse continuation"
    with pytest.raises(EdgeDNAViolation):
        mutate(parent, child_suffix="C", mutation_reason="",
               mechanism="x")


def test_capital_accelerant_grants_nothing():
    a = capital_accelerant_assessment(
        explicit_downside=True, favorable_tail_evidence="NOT_ESTIMABLE",
        holding_period="intraday", capital_efficiency="NOT_ESTIMABLE",
        footprint="negligible", mechanism_credibility="PLAUSIBLE",
        execution_survivability="NOT_ESTIMABLE")
    assert a["grants_capital_authority"] is False


# ================================================= 7. REGISTRY

def test_experiments_register_before_results_exist(tmp_path):
    led = tmp_path / "disc.jsonl"
    with pytest.raises(RegistryViolation) as e:
        record_result(led, discovery_id="ghost", status="NULL_RESULT",
                      result={}, why="x")
    assert "story told backwards" in str(e.value)


def test_corrupted_dataset_boundaries_are_dead_on_arrival(tmp_path):
    with pytest.raises(RegistryViolation):
        register_discovery(
            tmp_path / "d.jsonl", discovery_id="D1",
            research_question="q", feature_set=["a"],
            interaction_form="single", search_method="manual",
            dataset_boundary="day1_SUPERSEDED_originals",
            multiple_testing_family="fam1")


def test_an_experiment_needs_a_multiple_testing_family(tmp_path):
    with pytest.raises(RegistryViolation) as e:
        register_discovery(
            tmp_path / "d.jsonl", discovery_id="D1",
            research_question="q", feature_set=["a"],
            interaction_form="single", search_method="manual",
            dataset_boundary="DAY1_CORRECTED",
            multiple_testing_family="")
    assert "p-hacking" in str(e.value)


def test_null_results_stay_visible_in_the_family_denominator(tmp_path):
    led = tmp_path / "d.jsonl"
    for i in range(3):
        register_discovery(
            led, discovery_id=f"D{i}", research_question="q",
            feature_set=["a"], interaction_form="single",
            search_method="manual", dataset_boundary="DAY1_CORRECTED",
            multiple_testing_family="fam1")
    record_result(led, discovery_id="D0", status="NULL_RESULT",
                  result={}, why="nothing there")
    record_result(led, discovery_id="D1", status="ABANDONED",
                  result={}, why="data insufficient")
    fam = family_ledger(led, "fam1")
    assert fam["n_experiments"] == 3
    assert fam["n_null_or_dead"] == 2
    assert "denominator" in fam["law"]


# ================================================= 8. BOUNDARY MAP

from apex.edgeforge.boundary_map import (  # noqa: E402
    DecisionBoundaryMap, compare_cohorts, map_equity_decision)


def test_thresholds_are_imported_from_the_incumbent_never_restated():
    """A copied constant would drift and the archaeology would then
    measure a boundary the Predator does not use."""
    import inspect
    from apex.edgeforge import boundary_map as bm
    src = inspect.getsource(bm)
    assert "from apex.predators.equities.attack_geometry import" in src
    from apex.predators.equities.attack_geometry import CHASE_LOW_ATR
    assert bm.CHASE_LOW_ATR is CHASE_LOW_ATR


def test_a_knife_edge_verdict_implicates_the_threshold():
    m = map_equity_decision(
        subject="SPY", T="t", verdict="GOOD", cohort="PAPER_ATTACKED",
        extension_atr=1.48,      # CHASE_MODERATE_ATR is 1.5
        invalidation_atr=0.9)
    assert m.overall_proximity == "KNIFE_EDGE"
    assert "decided BY THE THRESHOLD" in m.interpretation


def test_an_interior_verdict_implicates_a_missing_variable():
    m = map_equity_decision(
        subject="SPY", T="t", verdict="GOOD", cohort="PAPER_ATTACKED",
        extension_atr=1.0,       # mid-band of (0.5, 1.5)
        invalidation_atr=0.75)   # mid-band of (-inf, 1.5) -> measurable
    assert m.overall_proximity == "INTERIOR"
    assert "MISSING A STATE VARIABLE" in m.interpretation


def test_distances_are_per_dimension_never_a_scalar():
    m = map_equity_decision(subject="SPY", T="t", verdict="GOOD",
                            cohort="PAPER_ATTACKED", extension_atr=1.0,
                            invalidation_atr=0.9)
    rec = m.as_record()
    assert isinstance(rec["dimensions"], list) and len(rec["dimensions"]) >= 2
    assert "distance" not in rec, "a collapsed scalar distance exists"
    for d in rec["dimensions"]:
        assert "distance_to_worse" in d and "distance_to_better" in d


def test_an_unestimable_dimension_invents_no_distance():
    m = map_equity_decision(subject="SPY", T="t", verdict="UNKNOWN",
                            cohort="REFUSED",
                            extension_atr="NOT_ESTIMABLE",
                            invalidation_atr="NOT_ESTIMABLE")
    assert m.overall_proximity == "NOT_ESTIMABLE"
    for d in m.dimensions:
        assert d.distance_to_worse == "NOT_ESTIMABLE"


def test_cohort_comparison_asks_whether_states_actually_differed():
    attacked = [map_equity_decision(
        subject="SPY", T="t1", verdict="GOOD", cohort="PAPER_ATTACKED",
        extension_atr=1.2, invalidation_atr=0.8)]
    waited = [map_equity_decision(
        subject="QQQ", T=f"t{i}", verdict="POOR",
        cohort="WAIT_FOR_ENTRY", extension_atr=1.1 + i * 0.05,
        invalidation_atr=0.85) for i in range(4)]
    c = compare_cohorts(attacked + waited)
    assert c["cohorts"]["PAPER_ATTACKED"] == 1
    assert c["cohorts"]["WAIT_FOR_ENTRY"] == 4
    assert c["separation"]["extension_atr (chase)"] == "OVERLAPPING"
    assert "merely land on the other side of a line" in c["question"]


def test_separated_cohorts_are_reported_as_separated():
    a = [map_equity_decision(subject="A", T="t", verdict="GOOD",
                             cohort="PAPER_ATTACKED", extension_atr=0.6,
                             invalidation_atr=0.8)]
    b = [map_equity_decision(subject="B", T="t", verdict="POOR",
                             cohort="WAIT_FOR_ENTRY", extension_atr=2.8,
                             invalidation_atr=0.8)]
    assert compare_cohorts(a + b)["separation"][
        "extension_atr (chase)"] == "SEPARATED"


def test_the_boundary_map_holds_no_authority():
    m = map_equity_decision(subject="SPY", T="t", verdict="GOOD",
                            cohort="PAPER_ATTACKED", extension_atr=1.0,
                            invalidation_atr=0.9)
    assert m.decision_power == "NONE_RESEARCH"
    assert m.proximity_rule == "REPORTING_PRIOR"


def test_boundary_distances_are_recorded_but_never_read_by_a_gate():
    """V0.5 shadow recording: the funnel must PRESERVE the distances
    that produced each verdict, without any decision consulting them.
    Day-1 recorded verdicts only, which left the archaeology with
    nothing to measure."""
    import inspect
    from scripts import options_paper_session as sess
    src = inspect.getsource(sess._scan_symbol)
    for f in ("extension_atr", "invalidation_distance_atr",
              "range_position", "vwap_distance_atr"):
        assert f'"{f}"' in src, f"{f} is not recorded"
    # they may be WRITTEN into rec, never CONSULTED in a condition
    for line in src.splitlines():
        st = line.strip()
        if st.startswith(("if ", "elif ", "while ")):
            for f in ("extension_atr", "invalidation_distance_atr",
                      "range_position", "vwap_distance_atr"):
                assert f"ug.{f}" not in st, (
                    f"a gate consults {f}: recording became a decision")
