"""HUNTER P0 acceptance tests (gap analysis §8-9): every constitutional
guarantee proven, most by counterexample."""

from __future__ import annotations

import pytest

from apex.hunter.broker import BrokerAdapter, LiveExecutionDisabled
from apex.hunter.contracts import (
    FailClosed, PlaybookDefinition, TradeThesis, gate_decision,
)
from apex.hunter.lifecycle import (
    LifecycleError, ModelState, degrade, live_eligible, paper_eligible, promote,
)
from apex.hunter.statemachine import TradeLifecycle, TradeState, TransitionError


def _thesis(**kw):
    base = dict(symbol="XYZ", created_at="2026-08-15T14:30:00Z",
                playbook_id="pb-test", market_state={"regime": "CALM_UP"},
                regime_state={"trend": "UP"}, catalyst="test",
                chart_state={}, model_id="m1@v1",
                distribution={"status": "PAPER_GRADE"},
                calibration_status="PAPER_GRADE", expected_cost_bps=12.0,
                entry_zone=(100.0, 100.5), invalidation="close < ORL",
                stop=99.0, targets=(103.0,), time_stop_minutes=60,
                max_holding_minutes=90, risk_budget_frac=0.0025,
                expected_net_edge=0.004, confidence="PAPER-GRADE")
    base.update(kw)
    return TradeThesis(**base)


# --- thesis immutability -----------------------------------------------------

def test_a_thesis_is_immutable_and_hash_recoverable():
    t = _thesis()
    assert len(t.thesis_hash) == 64
    with pytest.raises(Exception):
        t.stop = 95.0                       # frozen
    t2 = _thesis()
    assert t2.thesis_hash == t.thesis_hash, "same content, same identity"
    assert _thesis(stop=98.0).thesis_hash != t.thesis_hash


def test_a_thesis_without_invalidation_or_sane_risk_is_refused():
    with pytest.raises(ValueError, match="hope"):
        _thesis(invalidation="")
    with pytest.raises(ValueError, match="research template"):
        _thesis(risk_budget_frac=0.02)      # 2% per trade: refused


def test_a_playbook_without_a_mechanism_is_a_pattern_not_a_candidate():
    with pytest.raises(ValueError, match="mechanism"):
        PlaybookDefinition(
            playbook_id="p", mechanism="", eligible_universe="u",
            required_state={}, prohibited_state={}, required_data=("bars",),
            setup="s", trigger="t", entry_semantics="e", invalidation="i",
            stop_methodology="m", target_methodology="g",
            time_stop_minutes=60, max_holding_minutes=90,
            execution_restrictions="", calibration_requirement="PAPER_GRADE",
            known_failure_modes=("x",))


# --- state machine + decision ledger -----------------------------------------

def test_every_transition_needs_a_rule_and_lands_in_the_chain(tmp_path):
    tl = TradeLifecycle(_thesis(), tmp_path / "decisions.jsonl")
    tl.transition(TradeState.ARMED, "setup+trigger satisfied", "T1")
    tl.transition(TradeState.TRIGGERED, "entry condition hit", "T2")
    tl.transition(TradeState.ENTERED, "fill confirmed", "T3")
    with pytest.raises(TransitionError, match="mood"):
        tl.transition(TradeState.CLOSED, "", "T4")
    with pytest.raises(TransitionError, match="not a legal transition"):
        tl.transition(TradeState.ARMED, "go back", "T4")
    assert tl.verify_ledger() == 3


def test_counterexample_the_stop_can_never_widen(tmp_path):
    tl = TradeLifecycle(_thesis(), tmp_path / "d.jsonl")
    tl.transition(TradeState.ARMED, "r", "T1")
    tl.transition(TradeState.TRIGGERED, "r", "T2")
    tl.transition(TradeState.ENTERED, "r", "T3")
    tl.tighten_stop(99.8, "trail rule v1", "T4")        # toward: allowed
    with pytest.raises(TransitionError, match="never widened"):
        tl.tighten_stop(99.0, "Claude still loves the company", "T5")
    assert tl.current_stop == 99.8
    rows = tl.verify_ledger()
    assert rows == 4, "the stop change must be in the chain with its rule"


# --- lifecycle gating: mechanical, no override -------------------------------

def test_promotion_past_paper_requires_calibration_evidence():
    with pytest.raises(LifecycleError, match="cannot be asserted"):
        promote(ModelState.PAPER, {"n_effective_dates": 3, "reliability": 0.002})
    s = promote(ModelState.PAPER, {"n_effective_dates": 25, "reliability": 0.004})
    assert s is ModelState.CALIBRATED


def test_degraded_loses_live_eligibility_structurally():
    assert live_eligible(ModelState.LIVE)
    assert not live_eligible(degrade(ModelState.LIVE))
    assert paper_eligible(ModelState.PAPER_GRADE)
    assert not live_eligible(ModelState.PAPER_GRADE)


def test_no_override_api_exists_for_eligibility():
    import inspect
    for fn in (live_eligible, paper_eligible):
        assert list(inspect.signature(fn).parameters) == ["state"], (
            "eligibility grew an argument that could override the gate")


# --- fail closed -------------------------------------------------------------

def test_any_tripped_condition_vetoes_with_named_reasons():
    d, reasons = gate_decision({FailClosed.STALE_MARKET_DATA,
                                FailClosed.DEGRADED_CALIBRATION})
    assert d == "NO-TRADE" and len(reasons) == 2
    assert gate_decision(set())[0] == "ELIGIBLE"


# --- broker: live is sealed --------------------------------------------------

def test_live_execution_is_disabled_and_cannot_be_reenabled_by_subclass():
    class Paper(BrokerAdapter):
        def market_data_status(self): return {}
        def portfolio(self): return {}
        def positions(self): return []
        def paper_execute(self, thesis_hash, side, qty, limit): return {}
        def shadow_record(self, thesis_hash, intended): return {}

    b = Paper()
    with pytest.raises(LiveExecutionDisabled, match="dated governance change"):
        b.place_order("XYZ", "buy", 100)
    with pytest.raises(TypeError, match="cannot be re-enabled"):
        class Sneaky(BrokerAdapter):
            def market_data_status(self): return {}
            def portfolio(self): return {}
            def positions(self): return []
            def paper_execute(self, *a): return {}
            def shadow_record(self, *a): return {}
            def place_order(self, *a, **k): return {"status": "filled"}


# --- firewall ---------------------------------------------------------------

def test_hunter_imports_neither_registration_nor_ledger():
    import inspect

    import apex.hunter.broker as B
    import apex.hunter.contracts as C
    import apex.hunter.lifecycle as L
    import apex.hunter.statemachine as S
    for mod in (C, L, S, B):
        src = inspect.getsource(mod)
        for banned in ("apex.registration", "apex.governance.ledger"):
            assert banned not in src, (
                f"{mod.__name__} references {banned}: the Hunter cannot "
                f"spend, register, or unlock anything")
