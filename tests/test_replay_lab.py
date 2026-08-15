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
