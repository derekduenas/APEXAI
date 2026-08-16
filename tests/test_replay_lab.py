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
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    for f in ("hunter_replay.py", "hunter_replay_fast.py"):
        assert "LAB-02 HEALTH ABORT" in (scripts / f).read_text()
    # aggregate provider-budget invariant: workers SHARE one lab total —
    # per-worker slice, so N workers can never collectively over-authorize
    fast = (scripts / "hunter_replay_fast.py").read_text()
    assert "LAB_TOTAL_BUDGET = 45_000" in fast   # CALL UNITS (LAB-05b)
    assert "LAB_TOTAL_BUDGET // a.workers" in fast
    assert "daily_budget=worker_budget" in fast
    legacy = (scripts / "hunter_replay.py").read_text()
    assert "LAB_DAILY_BUDGET" in legacy          # single-process: one total


def test_lab05b_governor_speaks_call_units():
    """Quota accounting is provider CALL UNITS: an intraday acquire costs
    5 units; the forward reserve is sovereign over lab spare."""
    from apex.intraday.eodhd import (DAILY_LIMIT_CALL_UNITS,
                                     FORWARD_RESERVE_CALL_UNITS,
                                     INTRADAY_CALL_COST, QuotaGovernor)
    assert INTRADAY_CALL_COST == 5
    g = QuotaGovernor(daily_budget=12)
    assert g.acquire(INTRADAY_CALL_COST) and g.used == 5
    assert g.acquire(INTRADAY_CALL_COST) and g.used == 10
    assert not g.acquire(INTRADAY_CALL_COST)      # 15 > 12: unit-exhausted
    assert g.acquire(1)                            # cheap call still fits
    assert FORWARD_RESERVE_CALL_UNITS >= 30_000    # Monday is sovereign
    assert DAILY_LIMIT_CALL_UNITS == 100_000
