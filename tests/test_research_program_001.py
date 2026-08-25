"""RESEARCH PROGRAM #001 -- gate_separation_v1 preregistration.

These are governance contracts, not behaviour tests. They exist so the
program cannot quietly drift into the shape of whatever Tuesday
produces.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "prereg", ROOT / "scripts" / "preregister_gate_separation_v1.py")
prereg = importlib.util.module_from_spec(spec)
sys.modules["prereg"] = prereg
spec.loader.exec_module(prereg)
P = prereg.PROGRAM


def test_the_program_was_sealed_before_the_data_it_will_judge():
    assert P["status"] == "PREREGISTERED"
    assert "2026-08-25 forward" in P["dataset_boundary"]
    assert "Day-1 excluded" in P["dataset_boundary"]
    assert P["multiple_testing_family"] == "gate_separation_v1"


def test_twenty_sessions_is_a_reporting_checkpoint_not_a_verdict_date():
    fr = P["first_read"]
    assert fr["nature"] == "REPORTING_CHECKPOINT"
    assert fr["explicitly_not"] == "an evidence-sufficiency threshold"
    for field in ("n_raw", "n_effective_lower_bound",
                  "independent_session_count", "regime_coverage",
                  "cohort_occupancy", "outcome_concentration",
                  "top_session_influence", "boundary_state_distribution"):
        assert field in fr["checkpoint_must_report"]
    assert "calendar" in fr["law"]


def test_ordinary_variance_stays_a_live_explanation():
    joined = " ".join(P["explicitly_not_assumed"])
    assert "ordinary outcome variance" in joined
    assert "threshold problem" in P["explicitly_not_assumed"]
    assert "missing-variable problem" in P["explicitly_not_assumed"]


def test_interior_may_never_be_read_as_a_missing_variable():
    b = P["boundary_archaeology"]
    assert "MISSING VARIABLE may NEVER" in b["forbidden_inference"]
    assert "ordinary variance" in b["INTERIOR"]


def test_thesis_quality_is_never_conflated_with_expression_quality():
    assert "signed_forward_underlying_return" in P["primary_outcomes"]
    assert "instrument_executable_pnl" in P["secondary_outcomes"]
    assert "never conflated" in P["separation_law"]


def test_the_program_cannot_move_the_live_system():
    assert P["changes_v1"] is False
    assert P["authority"] == "NONE_RESEARCH"
    assert P["decision_power"] == "NONE_RESEARCH"
    assert "no discovered variable changes V1" in \
        P["residual_discovery"]["authority"]


def test_the_suspended_generator_has_no_reinstatement_deadline():
    g = P["learned_generator_status"]
    assert g["state"] == "SUSPENDED"
    assert "vol_clustering_acf1" in g["reason"]
    assert "0.352" in g["reason"] and "[-1,1]" in g["reason"]
    assert g["deadline"].startswith("NONE")


def test_the_bias_monitor_does_not_demand_that_worlds_match_reality():
    m = P["world_generator_bias_monitor"]
    assert "equality is NOT required" in m["law"]
    assert "preserved and reported" in m["law"]
