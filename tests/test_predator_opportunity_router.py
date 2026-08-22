"""Canonical Predator Opportunity + PAPER_EXPLORATORY router tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.predators.core.opportunity import (  # noqa: E402
    ATTACK_CLASSES, STATES, OpportunityRefused, PredatorOpportunity)
from apex.predators.core.paper_router import (  # noqa: E402
    EXPLORATORY_REQUIREMENTS, ROUTES, RouterRefused, route)


def _opp(**over):
    base = {"opportunity_id": "OPP-1", "sleeve": "EQUITIES_INTRADAY",
            "subject": "NVDA", "mechanism": "PULLBACK_TO_VWAP",
            "first_known_from": "2026-08-21T14:00:00Z",
            "state": "SERIOUS", "direction": "LONG",
            "entry_quality": "GOOD", "invalidation": 98.5,
            "data_quality": "FULL"}
    base.update(over)
    return PredatorOpportunity(**base)


# ------------------------------------------------ schema laws

def test_unknown_is_a_value_not_zero():
    o = _opp()
    assert o.expected_return == "NOT_ESTIMABLE"
    assert o.expected_mae == "NOT_ESTIMABLE"
    assert o.n_raw is None and o.n_effective_lower_bound is None
    assert o.participant_state == "UNKNOWN"


def test_attack_ready_requires_bounded_loss():
    with pytest.raises(OpportunityRefused, match="invalidation"):
        _opp(state="ATTACK_READY", invalidation=None)
    ok = _opp(state="ATTACK_READY")
    assert ok.state == "ATTACK_READY"


def test_attack_class_requires_known_entry():
    with pytest.raises(OpportunityRefused, match="attack_class"):
        _opp(attack_class="STRONG_ATTACK", entry_quality="UNKNOWN")
    with pytest.raises(OpportunityRefused):
        _opp(attack_class="NORMAL_ATTACK", entry_quality="POOR")
    assert _opp(attack_class="RARE_ASYMMETRIC_ATTACK").attack_class \
        == "RARE_ASYMMETRIC_ATTACK"


def test_attack_class_carries_no_percentage():
    """Sizing belongs to Capital; the Predator never sizes itself."""
    o = _opp(attack_class="RARE_ASYMMETRIC_ATTACK")
    rec = o.as_record()
    # sizing field NAMES, not any field containing 'risk' -- chase_risk
    # is geometry, not sizing
    forbidden = ("risk_pct", "risk_frac", "risk_usd", "account_risk",
                 "position_size", "size", "contracts", "shares",
                 "notional", "leverage", "allocation")
    for k in rec:
        assert k.lower() not in forbidden, f"opportunity sizes itself: {k}"
        assert not k.lower().startswith("size"), k
    assert set(ATTACK_CLASSES) == {"NO_TRADE", "NORMAL_ATTACK",
                                   "STRONG_ATTACK",
                                   "RARE_ASYMMETRIC_ATTACK"}


def test_attack_ready_is_not_execution_authority():
    o = _opp(state="ATTACK_READY")
    assert o.decision_power == "NONE_PREDATOR"
    assert o.authority_eligibility == "OBSERVE_ONLY"


def test_state_vocabulary_is_closed():
    with pytest.raises(OpportunityRefused):
        _opp(state="FIRE_AT_WILL")
    assert "ATTACK_READY" in STATES and "NO_TRADE" not in STATES


# ------------------------------------------------ router laws

def _route(opp, authority="OBSERVE", commissioned=True, test=False):
    return route(opp, authority_level=authority,
                 sleeve_foundation_commissioned=commissioned,
                 commissioning_test=test)


def test_observe_never_approves_a_real_card():
    r = _route(_opp())
    assert r["route"] == "PAPER_EXPLORATORY_CANDIDATE"
    assert "approval withheld" in " ".join(r["reasons"])
    assert r["live_promotion_eligible"] is False


def test_commissioning_test_exercises_plumbing_only():
    r = _route(_opp(), test=True)
    assert r["route"] == "PAPER_EXPLORATORY_CANDIDATE"
    assert r["commissioning_test"] is True
    assert "plumbing" in " ".join(r["reasons"])


def test_bad_data_is_pipeline_stop_not_no_trade():
    r = _route(_opp(data_quality="INVALID"))
    assert r["route"] == "PIPELINE_STOP"


def test_no_trade_is_a_positive_decision():
    r = _route(_opp(entry_quality="POOR", attack_class="NO_TRADE"))
    assert r["route"] == "NO_TRADE"
    assert any("not attackable" in x for x in r["reasons"])


def test_uncommissioned_foundation_blocks():
    r = _route(_opp(), commissioned=False)
    assert r["route"] == "NO_TRADE"
    assert any("foundation" in x for x in r["reasons"])


def test_missing_invalidation_blocks_exploratory():
    r = _route(_opp(state="SERIOUS", invalidation=None))
    assert r["route"] == "NO_TRADE"
    assert any("bounded" in x for x in r["reasons"])


def test_lethal_contradiction_blocks():
    r = _route(_opp(contradictions=("LETHAL: data conflict",)))
    assert r["route"] == "NO_TRADE"
    assert any("assassin" in x for x in r["reasons"])


def test_cohorts_never_merge():
    exploratory = _route(_opp(), authority="PAPER_EXPLORATORY")
    authorized = _route(_opp(), authority="PAPER_AUTHORIZED")
    assert exploratory["route"] == "PAPER_EXPLORATORY_APPROVED"
    assert authorized["route"] == "PAPER_AUTHORIZED"
    assert exploratory["route"] != authorized["route"]
    assert exploratory["live_promotion_eligible"] is False
    assert "never edge-proof" in exploratory["cohort_law"]


def test_router_is_pure():
    o = _opp()
    assert _route(o) == _route(o)


def test_unknown_authority_refused():
    with pytest.raises(RouterRefused):
        _route(_opp(), authority="COWBOY")


def test_eligibility_law_is_recorded_not_activated():
    assert len(EXPLORATORY_REQUIREMENTS) == 8
    assert any("BEFORE card" in r for r in EXPLORATORY_REQUIREMENTS)
    assert set(ROUTES) >= {"PIPELINE_STOP", "NO_TRADE",
                           "PAPER_EXPLORATORY_CANDIDATE"}
