"""MarketPropagationGraph — F4. Proves lead-lag edges are measured, not
hard-coded; correlation is never mislabeled causation; instability is
actually detected via the split-sample check; and LeadingEdgeState never
claims propagation that has not yet been observed.
"""
from __future__ import annotations

import random

import pandas as pd
import pytest

from apex.frontier2.propagation import (PropagationEdge, PropagationError,
                                        estimate_edge, infer_leading_edge)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _identity_shift_series(n=90, lag=2):
    """target[i] == source[i - lag] EXACTLY -- guarantees correlation 1.0
    at the true lag, robustly above every threshold, in both halves."""
    full = [((i * 37) % 11) - 5 + 0.05 * i for i in range(n)]
    return full[lag:], full[:-lag]


def test_insufficient_samples_is_insufficient_data_not_a_guess():
    e = estimate_edge("SPY", "AAPL", [0.01, 0.02], [0.01, 0.02],
                      known_from=T0, now=T0)
    assert e.status == "INSUFFICIENT_DATA"
    assert e.lead_lag_direction == "UNKNOWN"
    assert e.estimated_delay_minutes is None


def test_weak_correlation_is_observational_not_supported():
    random.seed(1)
    n = 80
    source = [random.uniform(-1, 1) for _ in range(n)]
    target = [random.uniform(-1, 1) for _ in range(n)]     # unrelated
    e = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    assert e.status in ("OBSERVATIONAL_RELATIONSHIP", "UNSTABLE")
    assert abs(e.correlation_at_lag) < 0.55 or e.status != "SUPPORTED_LEAD_LAG"


def test_strong_stable_relationship_is_supported_lead_lag():
    source, target = _identity_shift_series()
    e = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    assert e.status == "SUPPORTED_LEAD_LAG"
    assert e.lead_lag_direction == "SOURCE_LEADS"
    assert e.estimated_delay_minutes == 2
    assert e.correlation_at_lag == pytest.approx(1.0, abs=1e-9)
    assert e.stability == "STABLE"


def test_relationship_is_never_labeled_causal():
    source, target = _identity_shift_series()
    e = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    assert "CAUSAL" not in e.status
    assert "CAUSAL" not in e.relationship_type


def test_reversed_series_reports_target_leads_honestly():
    """No hard-coded direction: swap which series is 'source' and the
    measured direction must flip, never stay fixed."""
    source, target = _identity_shift_series()
    e = estimate_edge("AAPL", "SPY", target, source, known_from=T0, now=T0)
    assert e.lead_lag_direction == "TARGET_LEADS"
    assert e.estimated_delay_minutes == -2


def test_sign_flipping_relationship_across_halves_is_detected_unstable():
    """Same nominal lag, opposite sign in each half -- the split-sample
    check must catch this, not just trust the aggregate correlation."""
    random.seed(7)
    full1 = [((i * 37) % 11) - 5 + 0.05 * i for i in range(60)]
    src1, tgt1 = full1[2:], full1[:-2]                     # strong + at lag+2
    src2 = [random.uniform(-1, 1) for _ in range(58)]
    tgt2 = [-v + random.uniform(-0.05, 0.05) for v in src2]  # ~-1 at lag 0

    source = src1 + src2
    target = tgt1 + tgt2
    e = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    assert e.status == "UNSTABLE"
    assert e.stability == "UNSTABLE"


def test_bad_status_refused_at_construction():
    with pytest.raises(PropagationError):
        PropagationEdge(source="A", target="B",
                        relationship_type="LAGGED_RETURN_CORRELATION",
                        lead_lag_direction="UNKNOWN",
                        estimated_delay_minutes=None, correlation_at_lag=None,
                        support=0, sample_count=0, stability="UNKNOWN",
                        regime="X", quality="UNKNOWN", status="NOT_A_STATUS",
                        birth=None, known_from=str(T0), as_of=str(T0))


def test_determinism_same_series_twice_byte_identical():
    source, target = _identity_shift_series()
    a = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    b = estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)
    assert a.as_record() == b.as_record()


# ---- LeadingEdgeState -----------------------------------------------------

def _supported_edge():
    source, target = _identity_shift_series()
    return estimate_edge("SPY", "AAPL", source, target, known_from=T0, now=T0)


def test_unsupported_edge_yields_unknown_leading_edge():
    bad_edge = estimate_edge("SPY", "AAPL", [0.01, 0.02], [0.01, 0.02],
                             known_from=T0, now=T0)
    le = infer_leading_edge(bad_edge, {"subject": "SPY", "event_time": str(T0)},
                            now=T0)
    assert le.propagation_state == "UNKNOWN"


def test_no_observed_target_change_yet_reads_propagating_within_window():
    edge = _supported_edge()
    src_change = {"subject": "SPY", "event_time": str(T0)}
    le = infer_leading_edge(edge, src_change,
                            now=T0 + pd.Timedelta(minutes=1),
                            target_change_event_time=None)
    assert le.propagation_state == "PROPAGATING"
    assert le.expected_delay_if_supported == 2


def test_no_change_far_past_expected_delay_reads_stalled():
    edge = _supported_edge()
    src_change = {"subject": "SPY", "event_time": str(T0)}
    le = infer_leading_edge(edge, src_change,
                            now=T0 + pd.Timedelta(minutes=30),
                            target_change_event_time=None)
    assert le.propagation_state == "STALLED"


def test_observed_target_change_after_source_reads_propagated():
    edge = _supported_edge()
    src_change = {"subject": "SPY", "event_time": str(T0)}
    le = infer_leading_edge(
        edge, src_change, now=T0 + pd.Timedelta(minutes=3),
        target_change_event_time=str(T0 + pd.Timedelta(minutes=2)))
    assert le.propagation_state == "PROPAGATED"
    assert le.observed_delay_minutes == pytest.approx(2.0)


def test_target_change_before_source_is_a_contradiction_not_lookahead_use():
    """A target that changed BEFORE the source event must be flagged as
    a contradiction, never silently accepted as confirming propagation
    (that would be treating a coincidence as a lookahead-shaped proof)."""
    edge = _supported_edge()
    src_change = {"subject": "SPY", "event_time": str(T0)}
    le = infer_leading_edge(
        edge, src_change, now=T0 + pd.Timedelta(minutes=1),
        target_change_event_time=str(T0 - pd.Timedelta(minutes=1)))
    assert "target_changed_before_source" in le.contradictions
    assert le.propagation_state == "UNKNOWN"


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.propagation as prop
    monkeypatch.setattr(prop, "LEDGER", tmp_path / "prop.jsonl")
    edge = _supported_edge()
    rec1 = prop.persist_edge(edge)
    rec2 = prop.persist_edge(edge)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
