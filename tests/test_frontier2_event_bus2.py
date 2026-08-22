"""event_bus2 — F14. Same laws as apex.frontier.senses.emit(), tested
independently since this module deliberately does not import that one.
"""
from __future__ import annotations

import pandas as pd
import pytest

import apex.frontier2.event_bus2 as eb2
from apex.frontier2 import FRONTIER2_POWER
from apex.frontier2.event_bus2 import (EventBus2Violation, emit, latest_for,
                                       read_all)

NOW = pd.Timestamp("2026-08-18T14:00:00Z")
LATER = NOW + pd.Timedelta(minutes=1)


def test_unknown_event_type_refused():
    with pytest.raises(EventBus2Violation):
        emit("NOT_A_REAL_TYPE", "AAPL", event_time=NOW, known_from=NOW,
            source="curve", prior_state="X", new_state="Y", quality="FULL")


def test_unknown_transport_refused():
    with pytest.raises(EventBus2Violation):
        emit("CURVATURE_CHANGE", "AAPL", event_time=NOW, known_from=NOW,
            source="curve", prior_state="X", new_state="Y", quality="FULL",
            transport="MADE_UP_TRANSPORT")


def test_known_from_before_event_time_refused():
    with pytest.raises(EventBus2Violation):
        emit("CURVATURE_CHANGE", "AAPL", event_time=LATER, known_from=NOW,
            source="curve", prior_state="X", new_state="Y", quality="FULL")


def test_emit_writes_and_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    rec = emit("CURVATURE_CHANGE", "AAPL", event_time=NOW, known_from=NOW,
              source="curve", prior_state="NO_INFLECTION",
              new_state="EARLY_NEGATIVE_CURVATURE", quality="FULL")
    assert rec["decision_power"] == FRONTIER2_POWER
    assert rec["material_change"] is True
    all_events = read_all()
    assert len(all_events) == 1
    assert all_events[0]["event_id"] == rec["event_id"]


def test_same_prior_and_new_state_is_not_material(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    rec = emit("CURVATURE_CHANGE", "AAPL", event_time=NOW, known_from=NOW,
              source="curve", prior_state="NO_INFLECTION",
              new_state="NO_INFLECTION", quality="FULL")
    assert rec["material_change"] is False


def test_latest_for_returns_none_when_never_fired(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    assert latest_for("AAPL") is None


def test_latest_for_filters_by_subject_and_type(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    emit("CURVATURE_CHANGE", "AAPL", event_time=NOW, known_from=NOW,
        source="curve", prior_state=None, new_state="A", quality="FULL")
    emit("CURVATURE_CHANGE", "MSFT", event_time=NOW, known_from=NOW,
        source="curve", prior_state=None, new_state="B", quality="FULL")
    emit("CURVATURE_CHANGE", "AAPL", event_time=LATER, known_from=LATER,
        source="curve", prior_state="A", new_state="C", quality="FULL")
    latest = latest_for("AAPL", "CURVATURE_CHANGE")
    assert latest["new_state"] == "C"
    assert latest_for("MSFT")["new_state"] == "B"


def test_read_all_on_missing_ledger_is_empty_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    assert read_all() == []


def test_events_are_hash_chained(tmp_path, monkeypatch):
    monkeypatch.setattr(eb2, "LEDGER", tmp_path / "event_bus2.jsonl")
    emit("SYSTEM_DEGRADATION", "MARKET", event_time=NOW, known_from=NOW,
        source="system_cognition", prior_state="HEALTHY", new_state="DEGRADED",
        quality="PARTIAL")
    emit("SYSTEM_DEGRADATION", "MARKET", event_time=LATER, known_from=LATER,
        source="system_cognition", prior_state="DEGRADED", new_state="HEALTHY",
        quality="FULL")
    events = read_all()
    assert events[1]["prev_hash"] == events[0]["entry_hash"]
