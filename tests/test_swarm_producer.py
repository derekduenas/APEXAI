"""Swarm producer v1: transport contract, defensive parsing, firewalls.
Unit tests use an injected runner — no live LLM calls in the suite."""

from __future__ import annotations

import json

import pytest

import apex.hunter.swarm as swarm

CAND = {"decision_id": "d1", "symbol": "AMD", "playbook_id": "HUNTER-001_v1",
        "direction": "LONG", "matched": {"rvol_tod": 3.2},
        "market_state": {"day_return": 0.002},
        "relative_strength": {"excess_market_60m": 0.01}}

GOOD = json.dumps({"claims": [{"claim": "RVOL is elevated",
                               "basis": "matched.rvol_tod"}],
                   "adversarial_flags": ["crowded opening spike"],
                   "unresolved_questions": []})


def test_blocked_without_marker(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: False)
    a = swarm.run_specialists(CAND, as_of="t")
    assert a.status == "BLOCKED_EXTERNAL_AUTH" and a.claims == ()


def test_ok_path_with_role_separated_calls(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    prompts = []

    def runner(p):
        prompts.append(p)
        return GOOD
    a = swarm.run_specialists(CAND, as_of="t", runner=runner)
    assert a.status == "OK"
    assert a.agents_run == swarm.V1_ACTIVE_AGENTS
    assert len(prompts) == 2                     # one call PER agent
    assert prompts[0] != prompts[1]              # role separation
    assert all(c[2] for c in a.claims)           # every claim has a basis
    assert any("ADVERSARIAL_TRADER" in f for f in a.adversarial_flags)


def test_garbage_output_is_failed_never_partial(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    a = swarm.run_specialists(CAND, as_of="t",
                              runner=lambda p: "I think you should BUY!!!")
    assert a.status == "FAILED" and a.claims == ()
    with pytest.raises(ValueError):              # contract: non-OK, no claims
        from apex.hunter.forecast import SwarmAssessment
        SwarmAssessment(candidate_id="x", as_of="t", status="FAILED",
                        claims=(("A", "b", "c"),))


def test_deadline_yields_not_available(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    a = swarm.run_specialists(CAND, as_of="t", deadline_seconds=-1,
                              runner=lambda p: GOOD)
    assert a.status == "NOT_AVAILABLE_IN_TIME" and a.claims == ()


def test_facts_only_from_candidate_no_instructions_leak():
    facts = swarm._candidate_facts(CAND)
    parsed = json.loads(facts)
    assert set(parsed) <= {"symbol", "playbook_id", "direction", "matched",
                           "risk_frac", "market", "relative_strength"}
