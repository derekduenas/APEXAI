"""ObservationIntegrityState — F13 (partial). Pure composition tests:
no disk I/O, every input hand-constructed, so the verdict ladder itself
is proven independent of what happens to be on disk tonight.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.frontier2 import FRONTIER2_POWER
from apex.frontier2.observation_integrity import (
    FULL, INVALID, LIMITED, PARTIAL, UNKNOWN,
    ObservationIntegrityState, ObservationIntegrityViolation, compute)
from apex.hunter.session_coverage import SessionCoverage
from apex.intraday.disagreement import DataDisagreementState, SourceQuote
from apex.intraday.universe_coverage import UniverseCoverageState

NOW = pd.Timestamp("2026-08-18T14:00:00Z")


def _sc(**kw):
    base = dict(session_date="2026-08-18", session_anchor_valid=True,
               quality=FULL)
    base.update(kw)
    return SessionCoverage(**base)


def _uc(**kw):
    base = dict(intended_universe=("AAPL", "MSFT"),
               authorized_universe=("AAPL", "MSFT"),
               streamed_universe=("AAPL", "MSFT"),
               continuous_universe=("AAPL", "MSFT"),
               rotated_universe=(), never_observed=(),
               coverage_count=2, coverage_fraction=1.0,
               continuous_coverage_fraction=1.0,
               broad_discovery_valid=True, status="HEALTHY")
    base.update(kw)
    return UniverseCoverageState(**base)


# ---- the verdict ladder -----------------------------------------------

def test_no_inputs_is_unknown_not_a_silent_pass():
    st = compute(as_of=NOW, known_from=NOW)
    assert st.quality == UNKNOWN
    assert "NO_INTEGRITY_INPUTS_PROVIDED" in st.quality_reasons


def test_invalid_session_anchor_caps_at_invalid():
    st = compute(session_coverage=_sc(session_anchor_valid=False,
                                      quality="INVALID"),
                 as_of=NOW, known_from=NOW)
    assert st.quality == INVALID
    assert "SESSION_ANCHOR_INVALID" in st.quality_reasons


def test_valid_session_but_unvalidated_broad_discovery_is_limited():
    st = compute(session_coverage=_sc(),
                 universe_coverage=_uc(broad_discovery_valid=False),
                 as_of=NOW, known_from=NOW)
    assert st.quality == LIMITED
    assert "BROAD_DISCOVERY_NOT_VALID" in st.quality_reasons
    assert st.breadth_usable() is False


def test_clean_session_and_valid_broad_discovery_is_full():
    st = compute(session_coverage=_sc(), universe_coverage=_uc(),
                 as_of=NOW, known_from=NOW)
    assert st.quality == FULL
    assert st.breadth_usable() is True


def test_material_disagreement_downgrades_even_a_clean_session():
    q1 = SourceQuote(source="A", price=100.0, bid=99.9, ask=100.1,
                     event_time=str(NOW), known_from=str(NOW))
    q2 = SourceQuote(source="B", price=101.0, bid=100.9, ask=101.1,
                     event_time=str(NOW), known_from=str(NOW))
    from apex.intraday.disagreement import compare
    dis = compare("AAPL", NOW, (q1, q2))
    assert dis.material is True
    st = compute(session_coverage=_sc(), universe_coverage=_uc(),
                 disagreements=(dis,), as_of=NOW, known_from=NOW)
    assert st.quality == PARTIAL
    assert st.disagreement_material == 1
    assert st.disagreement_symbols_material == ("AAPL",)


def test_zero_disagreements_checked_is_not_zero_disagreement():
    """An empty disagreements tuple means no overlap symbols were
    checked this tick -- it must not be conflated with 'sources agree'."""
    st = compute(session_coverage=_sc(), universe_coverage=_uc(),
                 disagreements=(), as_of=NOW, known_from=NOW)
    assert st.disagreement_checked == 0
    assert st.disagreement_material == 0
    # quality is FULL here only because nothing contradicted it --
    # a caller that cares about the distinction reads disagreement_checked.
    assert st.quality == FULL


def test_degraded_session_coverage_reads_limited():
    st = compute(session_coverage=_sc(quality="DEGRADED"),
                 universe_coverage=_uc(),
                 as_of=NOW, known_from=NOW)
    assert st.quality == LIMITED


def test_partial_session_coverage_reads_partial():
    st = compute(session_coverage=_sc(quality="PARTIAL"),
                 universe_coverage=_uc(),
                 as_of=NOW, known_from=NOW)
    assert st.quality == PARTIAL


# ---- contract discipline -----------------------------------------------

def test_bad_quality_value_is_refused_at_construction():
    with pytest.raises(ObservationIntegrityViolation):
        ObservationIntegrityState(
            as_of=str(NOW), known_from=str(NOW), session_date=None,
            session_anchor_valid=None, session_coverage_quality=UNKNOWN,
            broad_discovery_valid=None, broad_coverage_fraction=None,
            broad_continuous_coverage_fraction=None,
            discovery_latency_scope=None, disagreement_checked=0,
            disagreement_material=0, quality="NOT_A_REAL_QUALITY")


def test_decision_power_is_always_stamped():
    st = compute(as_of=NOW, known_from=NOW)
    assert st.decision_power == FRONTIER2_POWER == "NONE_FRONTIER_SHADOW"


def test_determinism_same_inputs_twice_byte_identical():
    a = compute(session_coverage=_sc(), universe_coverage=_uc(),
               as_of=NOW, known_from=NOW)
    b = compute(session_coverage=_sc(), universe_coverage=_uc(),
               as_of=NOW, known_from=NOW)
    assert a.as_record() == b.as_record()


def test_as_record_carries_kind():
    st = compute(as_of=NOW, known_from=NOW)
    assert st.as_record()["kind"] == "observation_integrity_state"


# ---- honest I/O edge ----------------------------------------------------

def test_load_latest_with_no_artifact_on_disk_is_unknown(tmp_path, monkeypatch):
    import apex.frontier2.observation_integrity as oi
    monkeypatch.chdir(tmp_path)
    st = oi.load_latest(as_of=NOW)
    assert st.quality == UNKNOWN
