"""SystemCognitionState — F13 (full assembly). Proves the overall
quality rollup is the WORST of every tracked component, an absent
component reads UNKNOWN (never healthy-by-default), and
`can_claim_high_quality()` is the one place "no HIGH_QUALITY while
integrity is degraded" gets enforced.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2.observation_integrity import compute as oi_compute
from apex.frontier2.system_cognition import (COMPONENTS, SystemCognitionError,
                                             SystemCognitionState, assess)
from apex.intraday.universe_coverage import UniverseCoverageState

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _healthy_oi():
    uc = UniverseCoverageState(
        intended_universe=("A",), authorized_universe=("A",),
        streamed_universe=("A",), continuous_universe=("A",), rotated_universe=(),
        never_observed=(), coverage_count=1, coverage_fraction=1.0,
        continuous_coverage_fraction=1.0, broad_discovery_valid=True,
        status="HEALTHY")
    return oi_compute(universe_coverage=uc, as_of=T0, known_from=T0)


def test_all_healthy_components_is_overall_healthy():
    st = assess(observation_integrity=_healthy_oi(), provider_health="HEALTHY",
               trade_coverage="FULL", quote_coverage="FULL",
               service_progress="HEALTHY", bar_completeness="FULL",
               latency="HEALTHY", runtime_drift="HEALTHY", disk="HEALTHY",
               quota="HEALTHY", model_freshness="HEALTHY",
               event_backlog="HEALTHY", known_from=T0, now=T0)
    assert st.overall_quality == "HEALTHY"
    assert st.can_claim_high_quality() is True


def test_one_degraded_component_caps_the_whole_system():
    st = assess(observation_integrity=_healthy_oi(), provider_health="HEALTHY",
               quota="STALLED", known_from=T0, now=T0)
    assert st.overall_quality == "CRITICAL"
    assert st.worst_component == "quota"
    assert st.can_claim_high_quality() is False


def test_degraded_observation_integrity_alone_prevents_high_quality():
    """THE LAW, directly: even if every OTHER component is perfect,
    degraded observation integrity caps the system."""
    from apex.hunter.session_coverage import SessionCoverage
    sc = SessionCoverage(session_date="2026-08-18", session_anchor_valid=True,
                         quality="DEGRADED")
    oi = oi_compute(session_coverage=sc, as_of=T0, known_from=T0)
    st = assess(observation_integrity=oi, provider_health="HEALTHY",
               known_from=T0, now=T0)
    assert st.can_claim_high_quality() is False
    assert st.overall_quality != "HEALTHY"


def test_unsupplied_components_read_unknown_not_healthy():
    st = assess(observation_integrity=_healthy_oi(), known_from=T0, now=T0)
    # every unsupplied component is UNKNOWN (severity 2) -> LIMITED overall,
    # never HEALTHY just because nothing was reported.
    assert st.overall_quality != "HEALTHY"
    assert "not supplied" in " ".join(st.quality_reasons)


def test_all_twelve_components_tracked():
    st = assess(observation_integrity=_healthy_oi(), known_from=T0, now=T0)
    assert set(st.component_statuses.keys()) == set(COMPONENTS)


def test_unknown_overall_quality_refused_at_construction():
    with pytest.raises(SystemCognitionError):
        SystemCognitionState(subject="X", as_of=str(T0), known_from=str(T0),
                             component_statuses={}, overall_quality="GREAT",
                             quality_reasons=(), worst_component=None)


def test_failed_beats_degraded_as_worst():
    st = assess(observation_integrity=_healthy_oi(), latency="DEGRADED",
               disk="FAILED", known_from=T0, now=T0)
    assert st.worst_component == "disk"
    assert st.overall_quality == "CRITICAL"


def test_determinism_same_inputs_twice_byte_identical():
    a = assess(observation_integrity=_healthy_oi(), provider_health="HEALTHY",
              known_from=T0, now=T0)
    b = assess(observation_integrity=_healthy_oi(), provider_health="HEALTHY",
              known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.system_cognition as sysc
    monkeypatch.setattr(sysc, "LEDGER", tmp_path / "sc.jsonl")
    st = assess(observation_integrity=_healthy_oi(), known_from=T0, now=T0)
    rec1 = sysc.persist(st)
    rec2 = sysc.persist(st)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
