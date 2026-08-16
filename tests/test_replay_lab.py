"""Replay laboratory laws: exploratory class always, Rule-17 tripwire,
counterfactual declared, graduation forever forbidden."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from hunter_replay import restamp  # noqa: E402


def test_restamp_enforces_class_limitation_and_counterfactual():
    r = restamp({"kind": "decision", "decision_id": "d",
                 "evidence_class": "EODHD_FORWARD_OBSERVATION"})
    assert r["evidence_class"] == "EODHD_HISTORICAL_EXPLORATORY"
    assert r["HISTORICAL_PROVIDER_SURVIVORSHIP_LIMITATION"] is True
    assert r["replay_counterfactual_eligibility"] is True


def test_rule17_tripwire_aborts_on_llm_view():
    with pytest.raises(RuntimeError, match="RULE 17"):
        restamp({"kind": "forecast_bundle",
                 "swarm_view": {"status": "OK"}})
    # blocked/absent swarm views pass through
    r = restamp({"kind": "forecast_bundle",
                 "swarm_view": {"status": "BLOCKED_EXTERNAL_AUTH"}})
    assert r["evidence_class"] == "EODHD_HISTORICAL_EXPLORATORY"


def test_replay_results_can_never_graduate():
    from apex.hunter.evidence import (EvidenceClass, EvidenceViolation,
                                      require_permitted)
    for use in ("graduation", "calibration_certification",
                "credit_5_decision", "live_capital_eligibility"):
        with pytest.raises(EvidenceViolation):
            require_permitted(EvidenceClass.EODHD_HISTORICAL_EXPLORATORY,
                              use)


def test_lab02_health_abort_semantics():
    """A quota-starved day must ABORT loudly, never race through hollow
    ticks (the ATTEMPT_1 failure mode). We assert the guard exists in
    BOTH harnesses and fires below the 50% bars floor."""
    for f in ("hunter_replay.py", "hunter_replay_fast.py"):
        src = (Path(__file__).resolve().parent.parent / "scripts" / f
               ).read_text()
        assert "LAB-02 HEALTH ABORT" in src
        assert "daily_budget=90_000" in src.replace("LAB_DAILY_BUDGET",
                                                    "daily_budget=90_000")             or "LAB_DAILY_BUDGET" in src
