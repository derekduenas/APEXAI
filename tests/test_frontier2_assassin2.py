"""ModelBreakerState — F8 (Assassin 2.0). Proves the ten mechanisms
fire only on real signal, three declared-unreachable mechanisms can
never be asserted, and THE MONOTONE CAUTION LAW holds: caution can only
go up across a sequence of calls, never down.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.assassin2 import (UNREACHABLE_MECHANISMS, Assassin2Error,
                                      ModelBreakerState, assess,
                                      caution_action)
from apex.frontier2.observation_integrity import compute as oi_compute
from apex.frontier2.propagation import PropagationEdge
from apex.frontier2.world_lab import from_simulation
from apex.world.simulator import WorldSimulationResult

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _edge(status="SUPPORTED_LEAD_LAG"):
    return PropagationEdge(
        source="XLK", target="NVDA", relationship_type="LAGGED_RETURN_CORRELATION",
        lead_lag_direction="SOURCE_LEADS", estimated_delay_minutes=2,
        correlation_at_lag=0.9, support=80, sample_count=80, stability="STABLE",
        regime="X", quality="FULL", status=status, birth=None,
        known_from=str(T0), as_of=str(T0))


def _world_lab(support=0.5):
    sim = WorldSimulationResult(
        simulation_id="S1", as_of=str(T0), horizon_minutes=60, n_paths=200,
        source="conditional_block_bootstrap_v1",
        calibration_status="UNCALIBRATED_SCENARIO_WEIGHT",
        branch_scenario_frequencies={"STRONG_CONTINUATION": support,
                                     "MODERATE_CONTINUATION": 0.0, "RANGE": 0.0,
                                     "FAILED_BREAKOUT": 0.0, "REVERSAL": 0.0,
                                     "SHOCK": 0.0},
        return_q10=0.0, return_median=0.0, return_q90=0.0, mae_median=0.0,
        mfe_median=0.0, target_first_frequency=None, stop_first_frequency=None,
        path_examples=(), uncertainty="HIGH", provenance={"donor_sessions": 10})
    return from_simulation(sim, subject="NVDA")


def test_no_inputs_checked_is_unknown():
    st = assess(subject="NVDA", known_from=T0, now=T0)
    assert st.familiarity == "UNKNOWN"
    assert st.mechanisms_checked == ()


def test_all_checked_but_nothing_fired_is_familiar():
    oi = oi_compute(as_of=T0, known_from=T0)  # UNKNOWN quality but no disagreement
    from apex.intraday.universe_coverage import UniverseCoverageState
    uc = UniverseCoverageState(intended_universe=("A",), authorized_universe=("A",),
        streamed_universe=("A",), continuous_universe=("A",), rotated_universe=(),
        never_observed=(), coverage_count=1, coverage_fraction=1.0,
        continuous_coverage_fraction=1.0, broad_discovery_valid=True, status="HEALTHY")
    oi = oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)
    st = assess(subject="NVDA", observation_integrity=oi,
               propagation_edge=_edge("SUPPORTED_LEAD_LAG"),
               world_lab=_world_lab(support=0.5),
               system_health={"status": "HEALTHY"}, known_from=T0, now=T0)
    assert st.familiarity == "FAMILIAR"
    assert st.mechanisms_fired == ()


def test_material_disagreement_fires_data_conflict():
    from apex.intraday.disagreement import compare, SourceQuote
    q1 = SourceQuote(source="A", price=100.0, bid=99.9, ask=100.1,
                     event_time=str(T0), known_from=str(T0))
    q2 = SourceQuote(source="B", price=101.0, bid=100.9, ask=101.1,
                     event_time=str(T0), known_from=str(T0))
    dis = compare("AAPL", T0, (q1, q2))
    from apex.intraday.universe_coverage import UniverseCoverageState
    uc = UniverseCoverageState(intended_universe=("A",), authorized_universe=("A",),
        streamed_universe=("A",), continuous_universe=("A",), rotated_universe=(),
        never_observed=(), coverage_count=1, coverage_fraction=1.0,
        continuous_coverage_fraction=1.0, broad_discovery_valid=True, status="HEALTHY")
    oi = oi_compute(universe_coverage=uc, disagreements=(dis,), as_of=T0, known_from=T0)
    st = assess(subject="AAPL", observation_integrity=oi, known_from=T0, now=T0)
    assert "DATA_CONFLICT" in st.mechanisms_fired
    assert st.familiarity == "DATA_CONFLICT"


def test_invalid_quality_is_a_lethal_defect():
    from apex.hunter.session_coverage import SessionCoverage
    sc = SessionCoverage(session_date="2026-08-18", session_anchor_valid=False,
                         quality="INVALID")
    oi = oi_compute(session_coverage=sc, as_of=T0, known_from=T0)
    st = assess(subject="AAPL", observation_integrity=oi, known_from=T0, now=T0)
    assert st.lethal_defect is True
    assert st.familiarity == "DATA_CONFLICT"
    assert st.caution_label == "SEVERE"


def test_degraded_system_health_fires_structural_risk():
    st = assess(subject="NVDA", system_health={"status": "STALLED"},
               known_from=T0, now=T0)
    assert "SYSTEM_DEGRADATION" in st.mechanisms_fired
    assert st.familiarity == "STRUCTURAL_RISK"


def test_unstable_edge_fires_correlation_break():
    st = assess(subject="NVDA", propagation_edge=_edge("UNSTABLE"),
               known_from=T0, now=T0)
    assert "CORRELATION_BREAK" in st.mechanisms_fired
    assert st.familiarity == "STRUCTURAL_RISK"


def test_weak_world_lab_support_fires_weak_analog_support():
    st = assess(subject="NVDA", world_lab=_world_lab(support=0.05),
               known_from=T0, now=T0)
    assert "WEAK_ANALOG_SUPPORT" in st.mechanisms_fired
    assert st.familiarity == "LOW_FAMILIARITY"


def test_strong_world_lab_support_does_not_fire():
    st = assess(subject="NVDA", world_lab=_world_lab(support=0.5),
               known_from=T0, now=T0)
    assert "WEAK_ANALOG_SUPPORT" not in st.mechanisms_fired


def test_material_model_conflict_fires():
    snap = {"tally": {"SUPPORT": 3, "OPPOSE": 2, "ABSTAIN": 0, "UNKNOWN": 0}}
    st = assess(subject="NVDA", model_market_snapshot=snap, known_from=T0, now=T0)
    assert "MODEL_CONFLICT" in st.mechanisms_fired
    assert st.familiarity == "MODEL_CONFLICT"


def test_single_dissenter_is_not_material_conflict():
    snap = {"tally": {"SUPPORT": 5, "OPPOSE": 1, "ABSTAIN": 0, "UNKNOWN": 0}}
    st = assess(subject="NVDA", model_market_snapshot=snap, known_from=T0, now=T0)
    assert "MODEL_CONFLICT" not in st.mechanisms_fired


@pytest.mark.parametrize("mech", UNREACHABLE_MECHANISMS)
def test_unreachable_mechanism_refuses_construction(mech):
    with pytest.raises(Assassin2Error):
        ModelBreakerState(
            subject="X", as_of=str(T0), known_from=str(T0), familiarity="UNKNOWN",
            mechanisms_checked=(), mechanisms_fired=(mech,),
            mechanisms_unreachable=tuple(UNREACHABLE_MECHANISMS),
            lethal_defect=False, caution_level=0, caution_label="NONE",
            reasoning=("x",), quality="UNKNOWN")


# ---- THE MONOTONE CAUTION LAW ---------------------------------------------

def test_caution_never_decreases_across_a_sequence():
    level, label = caution_action("OUT_OF_DISTRIBUTION", 0)
    assert level == 3
    level2, label2 = caution_action("FAMILIAR", level)   # a later BENIGN reading
    assert level2 == 3                                    # must NOT drop
    assert label2 == "SEVERE"


def test_caution_can_increase_from_a_low_prior():
    level, _ = caution_action("FAMILIAR", 0)
    assert level == 0
    level2, _ = caution_action("DATA_CONFLICT", level)
    assert level2 == 2


def test_caution_is_monotone_over_a_realistic_sequence():
    seq = ["FAMILIAR", "LOW_FAMILIARITY", "FAMILIAR", "DATA_CONFLICT", "FAMILIAR"]
    level = 0
    levels = []
    for fam in seq:
        level, _ = caution_action(fam, level)
        levels.append(level)
    assert levels == sorted(levels[:3]) + levels[3:4] + [levels[3]]  # non-decreasing through the peak
    assert all(b >= a for a, b in zip(levels, levels[1:]))


def test_priority_lethal_beats_every_other_mechanism():
    from apex.hunter.session_coverage import SessionCoverage
    sc = SessionCoverage(session_date="2026-08-18", session_anchor_valid=False,
                         quality="INVALID")
    oi = oi_compute(session_coverage=sc, as_of=T0, known_from=T0)
    st = assess(subject="NVDA", observation_integrity=oi,
               world_lab=_world_lab(support=0.5),   # would otherwise be FAMILIAR
               known_from=T0, now=T0)
    assert st.familiarity == "DATA_CONFLICT"


def test_determinism_same_inputs_twice_byte_identical():
    a = assess(subject="NVDA", propagation_edge=_edge("UNSTABLE"),
              known_from=T0, now=T0)
    b = assess(subject="NVDA", propagation_edge=_edge("UNSTABLE"),
              known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.assassin2 as a2
    monkeypatch.setattr(a2, "LEDGER", tmp_path / "a2.jsonl")
    st = assess(subject="NVDA", known_from=T0, now=T0)
    rec1 = a2.persist(st)
    rec2 = a2.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
