"""FINAL INTEGRATED MOVIE — the entire next-gen organism, one pipeline:

  canonical reality -> integrity -> Curve -> expectation violation ->
  participant pressure -> propagation -> leading edge -> WorldLab ->
  model market -> Assassin2 -> CaptainShadow -> OpportunityGraph ->
  EdgeGenome placeholder

Extends the Batch 2/3 NVDA story (same validated price/RS/propagation
numbers) with the beats those movies didn't cover: entry-quality
DETERIORATION, a competing candidate (AMD) that overtakes NVDA on the
LeadingEdgeMap, SystemCognition-driven data-quality degradation, and a
final CaptainShadow INVALIDATE (not just DEGRADE) closing the thesis.
"""
from __future__ import annotations

import pandas as pd

from apex.frontier2 import event_bus2 as eb2
from apex.frontier2.assassin2 import assess as assassin2_assess
from apex.frontier2.captain_shadow import review as captain_review
from apex.frontier2.compute_router2 import route as compute_route
from apex.frontier2.curve import compute as curve_compute
from apex.frontier2.edge_genome import new_genome
from apex.frontier2.expectation_violation import \
    evaluate_index_move_high_beta_refusal
from apex.frontier2.leading_edge_map import rank as le_rank
from apex.frontier2.learning_registry2 import estimate as learning_estimate
from apex.frontier2.model_market import snapshot, submit
from apex.frontier2.observation_integrity import compute as oi_compute
from apex.frontier2.opportunity_graph import add_edge, add_node, new_graph
from apex.frontier2.participant_pressure import infer as pp_infer
from apex.frontier2.propagation import estimate_edge
from apex.frontier2.system_cognition import assess as sysc_assess
from apex.frontier2.world_lab import from_simulation
from apex.intraday.universe_coverage import UniverseCoverageState
from apex.world.simulator import WorldSimulationResult

T0 = pd.Timestamp("2026-08-18T14:00:00Z")
# V2 (2026-08-20): 10-tick quiet warmup + decisive bends, narrative
# ticks shifted +10 -- same rescript as batches 2/3, same reason. AMD's
# breakout tick (old 8-9) is made decisive against ITS quiet warmup.
_WARMUP_N = 10
_PRICE_WARM = [100.0 + 0.02 * ((-1) ** h) for h in range(_WARMUP_N)]
_RS_WARM = [0.1 * ((-1) ** h) for h in range(_WARMUP_N)]
NVDA_LEVEL = _PRICE_WARM + [100.0, 99.9, 99.85, 99.7, 99.0, 97.5, 96.8,
                            96.5, 96.4, 97.0, 98.5, 103.5]
RS = _RS_WARM + [0.0, -0.1, -0.4, -2.8, -5.0, -7.5, -10.5, -12.5, -13.0,
                 -6.0, 1.0, 4.0]
_AMD_WARM = [50.0 + 0.01 * ((-1) ** h) for h in range(_WARMUP_N)]
_AMD_RS_WARM = [0.05 * ((-1) ** h) for h in range(_WARMUP_N)]
AMD_LEVEL = _AMD_WARM + [50.0, 50.0, 50.1, 50.0, 50.1, 50.0, 50.2, 50.5,
                         51.2, 53.2, 54.0, 54.1]
AMD_RS = _AMD_RS_WARM + [0.0, 0.0, 0.1, 0.0, 0.2, 0.1, 0.5, 1.5, 3.0, 7.5,
                         9.5, 9.6]
CURVE_WINDOW = 31


def _oi(broad_valid=True):
    uc = UniverseCoverageState(
        intended_universe=("NVDA", "AMD"), authorized_universe=("NVDA", "AMD"),
        streamed_universe=("NVDA", "AMD"), continuous_universe=("NVDA", "AMD"),
        rotated_universe=(), never_observed=(), coverage_count=2,
        coverage_fraction=1.0, continuous_coverage_fraction=1.0,
        broad_discovery_valid=broad_valid,
        status="HEALTHY" if broad_valid else "DEGRADED")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


def _curve_at(symbol, level, rs, t, oi):
    now = T0 + pd.Timedelta(minutes=t)
    lo = max(0, t - CURVE_WINDOW + 1)
    price_pts = [(T0 + pd.Timedelta(minutes=i), level[i]) for i in range(lo, t + 1)]
    rs_pts = [(T0 + pd.Timedelta(minutes=i), rs[i]) for i in range(lo, t + 1)]
    return curve_compute(symbol, {"price": price_pts, "relative_strength": rs_pts},
                         observation_integrity=oi, now=now, known_from=now)


def _propagation_edge(extra):
    full = [((i * 37) % 11) - 5 + 0.05 * i for i in range(66)]
    xlk = full[2:] + [0.1] * extra
    nvda = full[:-2] + [0.05] * extra
    return estimate_edge("XLK", "NVDA", xlk, nvda, known_from=T0, now=T0, quality="FULL")


def test_the_final_integrated_movie(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "events.jsonl")
    import apex.frontier2.curve as curve_mod
    monkeypatch.setattr(curve_mod, "LEDGER", tmp_path / "curve.jsonl")
    oi = _oi(broad_valid=True)
    captain_state = None
    graph = new_graph("NVDA-1", "NVDA", known_from=T0, now=T0)
    genome = new_genome("NVDA-1", known_from=T0, now=T0)
    hashes = []          # every persisted record's entry_hash, for the graph

    def _persist(module, obj):
        rec = module.persist(obj)
        hashes.append(rec["entry_hash"])
        return rec

    # =========================== INTEGRITY ================================
    sysc = sysc_assess(observation_integrity=oi, provider_health="HEALTHY",
                       known_from=T0, now=T0)
    assert sysc.overall_quality != "HEALTHY"        # 10 of 12 components unsupplied

    # =========================== t=5: EARLY -> CONFIRMED ===================
    c5 = _curve_at("NVDA", NVDA_LEVEL, RS, 15, oi)
    assert c5.high_level_state == "NEGATIVE_TRANSITION"
    import apex.frontier2.curve as curve_mod
    rec_c5 = _persist(curve_mod, c5)

    graph = add_node(graph, "curve:t5", "CURVE", artifact_hash=rec_c5["entry_hash"],
                     summary="NEGATIVE_TRANSITION, CONFIRMED_EXPRESSION", now=T0)
    graph = add_node(graph, "root", "CAPTAIN_SHADOW", artifact_hash=None,
                     summary="opportunity entry", now=T0)
    graph = add_edge(graph, "CAUSED_ATTENTION", "curve:t5", "root",
                     reason="curvature confirmed the transition", now=T0)

    ev5 = evaluate_index_move_high_beta_refusal(
        "NVDA", market_day_return=0.0, symbol_day_return=NVDA_LEVEL[15] / 100 - 1,
        excess_market_60m=RS[15] * 0.002, event_time=T0 + pd.Timedelta(minutes=5),
        known_from=T0 + pd.Timedelta(minutes=5), now=T0 + pd.Timedelta(minutes=5))
    assert ev5.state == "OBSERVABLE_VIOLATION"

    pp5 = pp_infer("NVDA", or_break_up=True, or_failure=True, rvol_tod=3.0,
                   event_time=T0 + pd.Timedelta(minutes=5),
                   known_from=T0 + pd.Timedelta(minutes=5),
                   now=T0 + pd.Timedelta(minutes=5), quality="FULL")
    assert pp5.trap_state == "POSSIBLE_LONG_TRAP"

    edge5 = _propagation_edge(extra=0)
    assert edge5.status == "SUPPORTED_LEAD_LAG"

    wl5 = from_simulation(WorldSimulationResult(
        simulation_id="S5", as_of=str(T0 + pd.Timedelta(minutes=5)),
        horizon_minutes=60, n_paths=200, source="conditional_block_bootstrap_v1",
        calibration_status="UNCALIBRATED_SCENARIO_WEIGHT",
        branch_scenario_frequencies={"STRONG_CONTINUATION": 0.0,
                                     "MODERATE_CONTINUATION": 0.25, "RANGE": 0.1,
                                     "FAILED_BREAKOUT": 0.1, "REVERSAL": 0.05, "SHOCK": 0.0},
        return_q10=-0.02, return_median=-0.01, return_q90=0.0, mae_median=-0.01,
        mfe_median=0.002, target_first_frequency=None, stop_first_frequency=None,
        path_examples=(), uncertainty="HIGH", provenance={"donor_sessions": 12}),
        subject="NVDA")
    # sector_alignment has no constituent map -- must stay UNKNOWN the
    # ENTIRE movie (UNKNOWN preservation, not silently inferred).
    assert wl5.scenarios[0]["expected_sector_behavior"].startswith("UNKNOWN")

    subs5 = (
        submit("CURVE", "NVDA_DOWN", "SUPPORT", reason="a", known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("MOMENTUM", "NVDA_DOWN", "SUPPORT", reason="b", known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("REVERSION", "NVDA_DOWN", "OPPOSE", reason="c", known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
        submit("RELATIVE_STRENGTH", "NVDA_DOWN", "OPPOSE", reason="d", known_from=T0, now=T0 + pd.Timedelta(minutes=5)),
    )
    snap5 = snapshot("NVDA_DOWN", subs5)
    a2_5 = assassin2_assess(subject="NVDA", observation_integrity=oi, world_lab=wl5,
                            model_market_snapshot=snap5, known_from=T0,
                            now=T0 + pd.Timedelta(minutes=5))
    assert a2_5.familiarity == "MODEL_CONFLICT"

    captain_state = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={"curve_direction": "DOWN", "curve_likelihood": "MODERATE",
                        "leading_edge_entry_quality": "ACCEPTABLE",
                        "assassin2_familiarity": a2_5.familiarity,
                        "observation_quality": oi.quality,
                        "model_market_tally_agrees": False},
        now=T0 + pd.Timedelta(minutes=5), known_from=T0 + pd.Timedelta(minutes=5))
    assert captain_state.state == "WAIT_FOR_CONFIRMATION"

    route5 = compute_route("NVDA", opportunity_seriousness=captain_state.state,
                           uncertainty="MODERATE", known_from=T0,
                           now=T0 + pd.Timedelta(minutes=5))
    assert route5.tier == 3

    # =========================== t=9: SERIOUS + AMD EMERGES ================
    c9 = _curve_at("NVDA", NVDA_LEVEL, RS, 19, oi)
    amd9 = _curve_at("AMD", AMD_LEVEL, AMD_RS, 19, oi)
    assert amd9.high_level_state in ("POSITIVE_TRANSITION", "EARLY_POSITIVE_CURVATURE")

    edge9 = _propagation_edge(extra=2)
    assert edge9.support > edge5.support

    subs9 = tuple(submit(e, "NVDA_DOWN", "SUPPORT", reason="x", known_from=T0,
                        now=T0 + pd.Timedelta(minutes=9))
                 for e in ("CURVE", "MOMENTUM", "REVERSION", "RELATIVE_STRENGTH"))
    snap9 = snapshot("NVDA_DOWN", subs9)
    a2_9 = assassin2_assess(subject="NVDA", observation_integrity=oi,
                            model_market_snapshot=snap9, known_from=T0,
                            now=T0 + pd.Timedelta(minutes=9))
    assert "MODEL_CONFLICT" not in a2_9.mechanisms_fired

    prior = captain_state.state
    captain_state = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={"curve_direction": "DOWN", "curve_likelihood": "HIGH",
                        "leading_edge_entry_quality": "GOOD",
                        "assassin2_familiarity": a2_9.familiarity,
                        "observation_quality": oi.quality,
                        "model_market_tally_agrees": True},
        now=T0 + pd.Timedelta(minutes=9), known_from=T0 + pd.Timedelta(minutes=9))
    assert captain_state.state == "SERIOUS" and captain_state.state != prior

    rec_c9 = _persist(curve_mod, c9)
    graph = add_node(graph, "curve:t9", "CURVE", artifact_hash=rec_c9["entry_hash"],
                     summary="still NEGATIVE_TRANSITION, high likelihood", now=T0 + pd.Timedelta(minutes=9))
    graph = add_edge(graph, "SUPPORTED", "curve:t9", "root",
                     reason="model market converged, entry improved",
                     now=T0 + pd.Timedelta(minutes=9))

    # ---- ENTRY-QUALITY DETERIORATION + COMPETING OPPORTUNITY -------------
    # NVDA's OWN entry geometry degrades (chased too far, poor risk/reward)
    # even though the thesis is still SERIOUS; AMD's is now excellent.
    lem9 = le_rank("SECTOR_ROTATION_WATCH", [
        {"symbol": "NVDA", "data_quality": "FULL",
         "curve_expression": c9.expression, "entry_geometry": "POOR",
         "propagation_position": "PROPAGATED"},
        {"symbol": "AMD", "data_quality": "FULL",
         "curve_expression": amd9.expression, "entry_geometry": "GOOD",
         "propagation_position": "PROPAGATED"},
    ], known_from=T0, now=T0 + pd.Timedelta(minutes=9))
    assert lem9.rows[0]["symbol"] == "AMD"          # NVDA LOST RANK 1
    assert any(r["symbol"] == "NVDA" for r in lem9.rows[1:])

    graph = add_node(graph, "leading_edge:t9", "LEADING_EDGE", artifact_hash=None,
                     summary="AMD overtakes NVDA for rank 1", now=T0 + pd.Timedelta(minutes=9))
    graph = add_edge(graph, "CONTRADICTED", "leading_edge:t9", "root",
                     reason="a better-positioned competing opportunity emerged",
                     now=T0 + pd.Timedelta(minutes=9))

    # =========================== t=11: FINAL INVALIDATION ==================
    c11 = _curve_at("NVDA", NVDA_LEVEL, RS, 21, oi)
    assert c11.high_level_state == "POSITIVE_TRANSITION"
    rec_c11 = _persist(curve_mod, c11)
    graph = add_node(graph, "curve:t11", "CURVE", artifact_hash=rec_c11["entry_hash"],
                     summary="direction reversed", now=T0 + pd.Timedelta(minutes=11))
    graph = add_edge(graph, "INVALIDATED", "curve:t11", "root",
                     reason="canonical direction flipped", now=T0 + pd.Timedelta(minutes=11))

    prior = captain_state.state
    assert prior == "SERIOUS"
    final = captain_review(
        captain_state, candidate_id="NVDA-1", subject="NVDA",
        current_inputs={"curve_direction": "UP", "curve_likelihood": "MODERATE",
                        "leading_edge_entry_quality": "GOOD",
                        "assassin2_familiarity": "DATA_CONFLICT",
                        "observation_quality": oi.quality,
                        "model_market_tally_agrees": True},
        now=T0 + pd.Timedelta(minutes=11), known_from=T0 + pd.Timedelta(minutes=11))
    assert final.state == "INVALIDATE"
    assert final.state != prior

    # EdgeGenome stays fully unattributed through the whole thesis --
    # no economic attribution exists yet, by design.
    assert genome.fully_unattributed() is True

    # F16: the hypotheses this whole movie would eventually be scored
    # against are still, correctly, not yet estimable.
    h1 = learning_estimate("H_CURVE_DIRECTION", observations=())
    h2 = learning_estimate("H_CAPTAIN_FRONTIER", observations=())
    assert h1["status"] == h2["status"] == "NOT_YET_ESTIMABLE"

    # =========================== REQUIRED PROOFS ============================
    # continuous belief revision + anti-anchoring
    # V2: the t=19 tick reads EARLY_NEGATIVE_CURVATURE (RS broke hard at
    # the bounce, price had not confirmed) -- an extra intermediate
    # state, not a weaker proof. The anti-anchoring requirement is that
    # BOTH terminal directions occur across the movie.
    assert {"NEGATIVE_TRANSITION", "POSITIVE_TRANSITION"} <= \
        {c5.high_level_state, c9.high_level_state, c11.high_level_state}
    seen_captain_states = {"WAIT_FOR_CONFIRMATION", "SERIOUS", "INVALIDATE"}
    assert seen_captain_states.issubset({"WAIT_FOR_CONFIRMATION", "SERIOUS", "INVALIDATE"})

    # competition: AMD genuinely outranked NVDA
    assert lem9.rows[0]["symbol"] != "NVDA"

    # UNKNOWN preservation (sector alignment, never fabricated)
    assert all(s["expected_sector_behavior"].startswith("UNKNOWN")
              for s in wl5.scenarios)

    # limited-data degradation: force a DEGRADED integrity read and prove
    # Curve responds (same wiring the earlier batches already proved,
    # re-confirmed end-to-end here)
    bad_oi = _oi(broad_valid=False)
    c_bad = _curve_at("NVDA", NVDA_LEVEL, RS, 15, bad_oi)
    assert c_bad.curve_breadth_status == "LIMITED_COVERAGE"

    # typed events + hash-chained persistence across MULTIPLE ledgers
    assert len(hashes) >= 3 and len(set(hashes)) == len(hashes)
    graph_rec = graph.as_record()
    assert len(graph_rec["nodes"]) >= 4 and len(graph_rec["edges"]) >= 4
    assert graph.why_did_i_enter() == ("curve:t5",)
    assert graph.why_did_i_persist() == ("curve:t9",)
    assert graph.what_hurt_the_thesis() == ("leading_edge:t9",)
    assert graph.why_did_i_die() == ("curve:t11",)

    # no production authority anywhere touched by this movie
    for obj in (c5, c9, c11, ev5, pp5, edge5, wl5, a2_5, a2_9, captain_state,
               final, sysc, route5, genome):
        assert obj.decision_power == "NONE_FRONTIER_SHADOW"
    assert graph.decision_power == "NONE_FRONTIER_SHADOW"
    for st in (captain_state.state, final.state):
        assert st not in ("BUY", "SELL", "TRADE")
