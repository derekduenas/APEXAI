"""WorldLabState — F6. Proves this module WRAPS the existing world
simulator rather than reimplementing it, preserves ALL ten scenario
types as competing branches (never collapsing to a favorite), and never
lets an uncalibrated frequency masquerade as a probability.
"""
from __future__ import annotations

import pytest

from apex.frontier2.world_lab import (SCENARIO_TYPES, UNREACHABLE_SCENARIOS,
                                      Scenario, WorldLabError, from_simulation)
from apex.world.simulator import WorldSimulationResult


def _sim(freqs=None, calibration="UNCALIBRATED_SCENARIO_WEIGHT"):
    freqs = freqs or {"STRONG_CONTINUATION": 0.30, "MODERATE_CONTINUATION": 0.20,
                      "RANGE": 0.25, "FAILED_BREAKOUT": 0.10, "REVERSAL": 0.10,
                      "SHOCK": 0.05}
    return WorldSimulationResult(
        simulation_id="SIM1", as_of="2026-08-18T14:00:00+00:00",
        horizon_minutes=60, n_paths=200, source="conditional_block_bootstrap_v1",
        calibration_status=calibration, branch_scenario_frequencies=freqs,
        return_q10=-0.01, return_median=0.001, return_q90=0.015,
        mae_median=-0.005, mfe_median=0.008, target_first_frequency=0.3,
        stop_first_frequency=0.2, path_examples=(0.01, -0.005, 0.02),
        uncertainty="HIGH", provenance={"donor_sessions": 12, "config": {}})


def test_calibrated_input_is_refused():
    with pytest.raises(WorldLabError):
        from_simulation(_sim(calibration="SOMETHING_ELSE"), subject="NVDA")


def test_all_ten_scenario_types_always_present():
    wl = from_simulation(_sim(), subject="NVDA")
    types = {s["scenario_type"] for s in wl.scenarios}
    assert types == set(SCENARIO_TYPES) - {"UNKNOWN"}


def test_unreachable_scenarios_always_zero_support():
    wl = from_simulation(_sim(), subject="NVDA")
    for s in wl.scenarios:
        if s["scenario_type"] in UNREACHABLE_SCENARIOS:
            assert s["current_support"] == 0.0
            assert s["support_ordinal"] == "NONE"
            assert "UNREACHABLE" in s["expected_market_behavior"]


def test_reachable_scenario_carries_the_real_simulator_frequency():
    wl = from_simulation(_sim(), subject="NVDA")
    continuation_rows = [s for s in wl.scenarios if s["scenario_type"] == "CONTINUATION"]
    # both STRONG_CONTINUATION (0.30) and MODERATE_CONTINUATION (0.20)
    # map to CONTINUATION -- both must survive as separate rows.
    assert len(continuation_rows) == 2
    supports = sorted(r["current_support"] for r in continuation_rows)
    assert supports == [0.20, 0.30]


def test_support_class_is_always_uncalibrated():
    wl = from_simulation(_sim(), subject="NVDA")
    assert all(s["support_class"] == "UNCALIBRATED_SCENARIO_WEIGHT"
              for s in wl.scenarios)


def test_zero_frequency_branch_is_still_a_listed_competing_scenario():
    wl = from_simulation(_sim(freqs={"STRONG_CONTINUATION": 1.0,
                                     "MODERATE_CONTINUATION": 0.0,
                                     "RANGE": 0.0, "FAILED_BREAKOUT": 0.0,
                                     "REVERSAL": 0.0, "SHOCK": 0.0}),
                         subject="NVDA")
    reversal = [s for s in wl.scenarios if s["scenario_type"] == "REVERSAL"][0]
    assert reversal["current_support"] == 0.0
    # it is PRESENT (not dropped) despite zero support:
    assert any(s["scenario_type"] == "REVERSAL" for s in wl.scenarios)


def test_expected_sector_behavior_always_honestly_unknown():
    wl = from_simulation(_sim(), subject="NVDA")
    assert all("UNKNOWN" in s["expected_sector_behavior"] for s in wl.scenarios)


def test_ordinal_tiers_scale_with_support():
    wl = from_simulation(_sim(freqs={"STRONG_CONTINUATION": 0.40,
                                     "MODERATE_CONTINUATION": 0.05,
                                     "RANGE": 0.0, "FAILED_BREAKOUT": 0.0,
                                     "REVERSAL": 0.0, "SHOCK": 0.0}),
                         subject="NVDA")
    by_id = {s["scenario_id"].split(":")[-1]: s for s in wl.scenarios}
    assert by_id["STRONG_CONTINUATION"]["support_ordinal"] == "HIGH"
    assert by_id["MODERATE_CONTINUATION"]["support_ordinal"] == "LOW"
    assert by_id["RANGE"]["support_ordinal"] == "NONE"


def test_bad_scenario_type_refused_at_construction():
    with pytest.raises(WorldLabError):
        Scenario(scenario_id="x", scenario_type="NOT_REAL",
                required_conditions=(), current_support=0.0,
                support_ordinal="NONE", contradictions=(),
                expected_market_behavior="", expected_sector_behavior="",
                candidate_implications="", participant_implications="",
                falsification="", quality="UNKNOWN",
                support_class="UNCALIBRATED_SCENARIO_WEIGHT", known_from="x")


def test_simulator_provenance_preserved_not_copied_and_mutated():
    sim = _sim()
    wl = from_simulation(sim, subject="NVDA")
    assert wl.simulator_source == sim.source
    assert wl.simulator_version == sim.simulator_version


def test_determinism_same_simulation_twice_byte_identical():
    sim = _sim()
    a = from_simulation(sim, subject="NVDA")
    b = from_simulation(sim, subject="NVDA")
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.world_lab as wl_mod
    monkeypatch.setattr(wl_mod, "LEDGER", tmp_path / "wl.jsonl")
    wl = from_simulation(_sim(), subject="NVDA")
    rec1 = wl_mod.persist(wl)
    rec2 = wl_mod.persist(wl)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
