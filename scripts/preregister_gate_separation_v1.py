"""PREREGISTER RESEARCH PROGRAM #001 — gate_separation_v1.

Sealed BEFORE Tuesday's observations exist. That ordering is the whole
point: cohorts, outcomes, horizon, residual variables and the first-read
checkpoint are all fixed while the answer is still unknown, so the
denominator cannot grow to fit a finding later.

THE 20-SESSION CHECKPOINT IS A REPORTING TRIGGER, NOT A TRUTH
THRESHOLD. If the market spends seventeen of those sessions in one
regime we will have twenty observations and almost no evidence, and the
checkpoint report is designed to say so rather than to deliver a
verdict on schedule.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.edgeforge.registry import register_discovery       # noqa: E402
from apex.governance.chain_ledger import chain_append        # noqa: E402

PROGRAM = {
    "kind": "edgeforge_research_program",
    "program_id": "gate_separation_v1",
    "number": "001",
    "status": "PREREGISTERED",
    "sealed_before": "2026-08-25 market open (Tuesday Session 2)",

    "primary_question": (
        "Does incumbent APEX GOOD / ATTACK_READY meaningfully separate "
        "favorable future path distributions from states it WAITs on or "
        "rejects at Geometry?"),
    "secondary_question": (
        "If separation is weak or absent, what causally available "
        "residual information may explain the difference?"),
    "explicitly_not_assumed": [
        "threshold problem", "missing-variable problem",
        "ordinary outcome variance is an equally legitimate explanation "
        "and must remain a live hypothesis throughout"],

    "primary_cohorts": ["ATTACK_READY", "WAIT_FOR_ENTRY",
                        "GEOMETRY_NEAR_MISS", "GEOMETRY_REFUSED"],
    "secondary_control_cohort": "NO_DIRECTIONAL_THESIS",

    "per_observation_record": [
        "session_id", "genome_hash", "decision_boundary_map",
        "incumbent_verdict", "decision_timestamp", "source_pedigree",
        "quality", "corrected_outcome_lineage"],

    "primary_outcomes": [
        "signed_forward_underlying_return", "mfe", "mae",
        "time_to_mfe", "time_to_mae", "time_to_thesis_invalidation",
        "invalidation_before_favorable_move",
        "favorable_move_before_invalidation", "path_persistence",
        "tail_outcome"],
    "secondary_outcomes": ["instrument_executable_pnl", "friction"],
    "separation_law": (
        "underlying THESIS quality and instrument EXPRESSION quality are "
        "recorded separately and never conflated -- that conflation "
        "produced Monday's false 'right thesis, wrong instrument' "
        "reading"),

    "resolution_horizon": ("official regular-session close, per the "
                           "corrected resolution-time law"),

    "boundary_archaeology": {
        "record": "per-dimension boundary distance for every "
                  "prospectively estimable state",
        "classes": ["KNIFE_EDGE", "INTERIOR", "UNKNOWN"],
        "KNIFE_EDGE": "decision materially sensitive to the incumbent "
                      "boundary; threshold placement and measurement "
                      "noise are priority hypotheses",
        "INTERIOR": "decision not marginal under the incumbent rule; "
                    "simple threshold placement alone is unlikely to "
                    "explain it. Candidate explanations: representation, "
                    "interaction misspecification, regime dependence, "
                    "temporal dynamics, measurement quality, mechanism "
                    "error, ordinary variance",
        "UNKNOWN": "required governed observation unavailable",
        "forbidden_inference": "INTERIOR = MISSING VARIABLE may NEVER be "
                               "encoded as causal truth"},

    "residual_discovery": {
        "conditioning": "must condition ON incumbent information",
        "question": "among incumbent-similar states, what additional "
                    "causally available information separates favorable "
                    "from unfavorable path distributions?",
        "candidate_domains": [
            "breadth", "sector_index_behavior", "liquidity",
            "volatility_transition", "options_state", "participant_state",
            "cross_predator_disagreement", "sequence_structure",
            "time_session_structure", "execution_environment"],
        "authority": "DISCOVERY_ONLY; no discovered variable changes V1",
        "pedigree": "every candidate receives a birth timestamp and "
                    "multiple-testing pedigree"},

    "first_read": {
        "trigger": "approximately 20 INDEPENDENT market sessions",
        "nature": "REPORTING_CHECKPOINT",
        "explicitly_not": "an evidence-sufficiency threshold",
        "checkpoint_must_report": [
            "n_raw", "n_effective_lower_bound",
            "independent_session_count", "regime_coverage",
            "cohort_occupancy", "outcome_concentration",
            "top_session_influence", "boundary_state_distribution"],
        "law": "evidence maturity is determined by the data, not by the "
               "calendar; twenty sessions inside one regime is twenty "
               "observations and almost no evidence"},

    "world_generator_bias_monitor": {
        "diagnostic": "GENERATOR_OPTIMISM_DIAGNOSTIC",
        "compare_across": ["EMPIRICAL_ANALOG", "CAUSAL_RESAMPLED",
                           "LEARNED_GENERATIVE", "ADVERSARIAL_STRESS"],
        "on": ["favorable_fraction", "median", "mfe", "mae",
               "invalidation_rate", "left_tail", "right_tail",
               "execution_burden"],
        "purpose": "identify whether a synthetic source systematically "
                   "flatters or punishes candidates relative to reality",
        "law": "equality is NOT required -- supplying unseen paths is "
               "the point -- but the difference is preserved and "
               "reported"},

    "learned_generator_status": {
        "state": "SUSPENDED",
        "reason": "conditional fidelity failed: vol_clustering_acf1 "
                  "-0.006 vs real +0.346 (absolute gap 0.352 on a "
                  "[-1,1] scale) and mae_median 3.73x deeper than "
                  "reality",
        "open_question": "can a volatility-persistent conditional model "
                         "materially improve out-of-sample conditional "
                         "world fidelity?",
        "deadline": "NONE -- if the answer is no, it stays suspended "
                    "forever, and that is an acceptable outcome"},

    "multiple_testing_family": "gate_separation_v1",
    "dataset_boundary": ("prospective sessions from 2026-08-25 forward; "
                         "CORRECTED lineage only; Day-1 excluded "
                         "(independent_session_count = 1 and boundary "
                         "inputs unrecorded)"),
    "authority": "NONE_RESEARCH",
    "changes_v1": False,
    "decision_power": "NONE_RESEARCH",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/edgeforge")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = out / "discovery_registry.jsonl"

    rec = dict(PROGRAM)
    rec["preregistered_utc"] = datetime.now(timezone.utc).isoformat()
    chain_append(reg, rec)

    register_discovery(
        reg, discovery_id="gate_separation_v1",
        research_question=PROGRAM["primary_question"],
        feature_set=PROGRAM["residual_discovery"]["candidate_domains"],
        interaction_form="cohort_separation_then_conditional_residual",
        dataset_boundary=PROGRAM["dataset_boundary"],
        search_method="prospective_cohort_accumulation",
        multiple_testing_family="gate_separation_v1")

    (out / "program_001_gate_separation_v1.json").write_text(
        json.dumps(rec, indent=2))
    print(json.dumps({
        "program": PROGRAM["program_id"],
        "status": PROGRAM["status"],
        "cohorts": PROGRAM["primary_cohorts"],
        "first_read": PROGRAM["first_read"]["nature"],
        "trigger": PROGRAM["first_read"]["trigger"],
        "boundary": PROGRAM["dataset_boundary"],
        "changes_v1": PROGRAM["changes_v1"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
