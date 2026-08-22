"""Certification ledger (validation_registry.py) + the
REFUSE_ANALYTICS_NOT_VALIDATED gate wired into expression_engine.py.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.option_analytics import validation_registry as vr
from apex.options_research import expression_engine as engine_mod
from apex.options_research import forward_distribution as fd_mod
from apex.options_research.expression_candidate import OptionExpressionCandidate
from apex.options_research.surface_state import build_surface

T0 = pd.Timestamp("2026-08-18T15:00:00Z")


def test_certified_true_requires_clean_run(tmp_path):
    with pytest.raises(vr.ValidationRegistryError):
        from apex.option_analytics.validation_registry import CertificationRecord
        CertificationRecord(certified=True, test_files=("x.py",), test_count=10,
                            passed_count=8, failed_count=2, source_hash="abc",
                            certified_at=str(T0))


def test_no_certification_record_is_uncertified(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "LEDGER", tmp_path / "cert.jsonl")
    assert vr.is_adversarial_suite_certified() is False


def test_clean_certification_reads_as_certified(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "LEDGER", tmp_path / "cert.jsonl")
    real_hash = vr.source_hash()
    monkeypatch.setattr(vr, "source_hash", lambda: real_hash)
    vr.record_certification(test_files=("x.py",), test_count=5, passed_count=5,
                            failed_count=0, now=T0)
    assert vr.is_adversarial_suite_certified() is True


def test_stale_certification_after_source_change_is_uncertified(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "LEDGER", tmp_path / "cert.jsonl")
    monkeypatch.setattr(vr, "source_hash", lambda: "hash_at_certification_time")
    vr.record_certification(test_files=("x.py",), test_count=5, passed_count=5,
                            failed_count=0, now=T0)
    # source changed after certification was minted
    monkeypatch.setattr(vr, "source_hash", lambda: "hash_after_code_changed")
    assert vr.is_adversarial_suite_certified() is False


def test_failed_run_never_certified(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "LEDGER", tmp_path / "cert.jsonl")
    rec = vr.record_certification(test_files=("x.py",), test_count=10, passed_count=8,
                                  failed_count=2, now=T0)
    assert rec.certified is False


# ---- gate wiring in expression_engine.py -----------------------------------

def _write_captain(path, subject):
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"subject": subject, "direction_quality": "STRONG",
          "transition_quality": "MODERATE", "data_quality": "FULL",
          "model_familiarity": "FAMILIAR", "falsification": "invalidated below VWAP"}
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


@pytest.fixture
def wired_thesis(tmp_path, monkeypatch):
    curve = tmp_path / "curve_ledger.jsonl"
    captain = tmp_path / "captain_shadow_ledger.jsonl"
    assassin = tmp_path / "assassin2_ledger.jsonl"
    monkeypatch.setattr(fd_mod, "CURVE_LEDGER", curve)
    monkeypatch.setattr(fd_mod, "CAPTAIN_LEDGER", captain)
    monkeypatch.setattr(fd_mod, "ASSASSIN_LEDGER", assassin)
    _write_captain(captain, "AAPL")


def _good_surface():
    return build_surface("AAPL260919C00230000", "2026-09-19", known_from=T0, now=T0,
                         values={"depth": 500.0, "volume": 300.0, "open_interest": 1200.0,
                                "spread_pct": 0.05, "atm_iv": 0.32})


def _opt002_candidate():
    return OptionExpressionCandidate(
        expression_type="CALL_DEBIT_SPREAD", underlying_thesis_id="AAPL", known_from=str(T0),
        entry_structure="vertical", expiry="2026-09-19", strikes=(230.0, 240.0), legs=(),
        net_debit_or_credit=3.0, max_loss=3.0, max_gain_if_defined=7.0, initial_delta=0.3,
        gamma=0.05, theta=-0.05, vega=0.1, spread_cost=0.15, estimated_slippage=0.0,
        fees=1.3, capital_required=300.0, risk_capital_required=300.0, thesis_horizon="60m",
        break_even=(233.0,), surface_context="normal", liquidity_context="liquid",
        data_quality="FULL", research_mechanism_ids=("OPT-002-RICH-WING-VERTICALIZATION",),
        as_of=str(T0))


def test_opt002_refused_when_not_certified(wired_thesis, monkeypatch):
    monkeypatch.setattr(engine_mod, "is_adversarial_suite_certified", lambda: False)
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(_opt002_candidate(),),
                              surface_state=_good_surface())
    gates = {r["gate"] for r in decision.refusals}
    assert "REFUSE_ANALYTICS_NOT_VALIDATED" in gates
    assert not any(c["expression_type"] == "CALL_DEBIT_SPREAD" for c in decision.candidates)


def test_opt002_admitted_when_certified(wired_thesis, monkeypatch):
    monkeypatch.setattr(engine_mod, "is_adversarial_suite_certified", lambda: True)
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(_opt002_candidate(),),
                              surface_state=_good_surface())
    types = {c["expression_type"] for c in decision.candidates}
    assert "CALL_DEBIT_SPREAD" in types


def test_opt001_never_gated_by_analytics_certification(wired_thesis, monkeypatch):
    """OPT-001 needs no Greeks/IV -- it must be admissible even when
    the analytics package is explicitly uncertified."""
    from tests.test_options_research_expression_engine import _option_candidate
    monkeypatch.setattr(engine_mod, "is_adversarial_suite_certified", lambda: False)
    decision = engine_mod.run(subject="AAPL", now=T0, known_from=T0,
                              hunter_present=True, frontier_present=True,
                              hunter_state_sufficient=True, candidate_dte=10,
                              expected_realization_minutes=60.0,
                              timing_uncertainty_minutes=30.0,
                              option_candidates=(_option_candidate(),),
                              surface_state=_good_surface())
    types = {c["expression_type"] for c in decision.candidates}
    assert "LONG_CALL" in types
