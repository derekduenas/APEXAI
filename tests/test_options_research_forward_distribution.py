"""UnderlyingForwardDistribution — assembled from real Frontier-2
ledger rows only, never independently recomputed, honestly UNKNOWN
when no ledger entry exists or Curve has no numeric magnitude estimate.
"""
from __future__ import annotations

import json

import pandas as pd

from apex.options_research.forward_distribution import build

T0 = pd.Timestamp("2026-08-18T14:40:00Z")


def _write(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def test_no_ledger_data_is_fully_unknown(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    monkeypatch.setattr(fd, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", tmp_path / "captain.jsonl")
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", tmp_path / "a2.jsonl")
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.direction_quality == "UNKNOWN"
    assert dist.has_legitimate_thesis() is False


def test_reads_real_captain_shadow_fields(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    curve_p, captain_p, a2_p = (tmp_path / "curve.jsonl", tmp_path / "captain.jsonl",
                               tmp_path / "a2.jsonl")
    monkeypatch.setattr(fd, "CURVE_LEDGER", curve_p)
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", captain_p)
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", a2_p)
    _write(captain_p, {"subject": "AAPL", "direction_quality": "STRONG",
                       "transition_quality": "STRONG", "data_quality": "FULL",
                       "model_familiarity": "FAMILIAR", "falsification": "reverses"})
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.direction_quality == "STRONG"
    assert dist.has_legitimate_thesis() is True
    assert dist.invalidation == "reverses"


def test_uses_latest_record_not_first(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    captain_p = tmp_path / "captain.jsonl"
    monkeypatch.setattr(fd, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", captain_p)
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", tmp_path / "a2.jsonl")
    _write(captain_p, {"subject": "AAPL", "direction_quality": "WEAK"})
    _write(captain_p, {"subject": "AAPL", "direction_quality": "STRONG"})
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.direction_quality == "STRONG"


def test_different_subject_is_isolated(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    captain_p = tmp_path / "captain.jsonl"
    monkeypatch.setattr(fd, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", captain_p)
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", tmp_path / "a2.jsonl")
    _write(captain_p, {"subject": "QQQ", "direction_quality": "STRONG"})
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.direction_quality == "UNKNOWN"


def test_magnitude_and_timing_stay_unknown_no_fabrication(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    captain_p = tmp_path / "captain.jsonl"
    monkeypatch.setattr(fd, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", captain_p)
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", tmp_path / "a2.jsonl")
    _write(captain_p, {"subject": "AAPL", "direction_quality": "STRONG"})
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.magnitude_range == "UNKNOWN"
    assert dist.timing_range == "UNKNOWN"
    assert dist.support_class == "UNCALIBRATED"


def test_decision_power_stamped(tmp_path, monkeypatch):
    import apex.options_research.forward_distribution as fd
    monkeypatch.setattr(fd, "CURVE_LEDGER", tmp_path / "curve.jsonl")
    monkeypatch.setattr(fd, "CAPTAIN_LEDGER", tmp_path / "captain.jsonl")
    monkeypatch.setattr(fd, "ASSASSIN_LEDGER", tmp_path / "a2.jsonl")
    dist = build("AAPL", now=T0, known_from=T0)
    assert dist.decision_power == "NONE_OPTIONS_RESEARCH"
