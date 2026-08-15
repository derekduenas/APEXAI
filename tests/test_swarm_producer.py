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


def test_ordering_law_candidates_persist_before_enrichment(tmp_path):
    """The archive outranks Claude: decision_pass(enrich=False) yields
    scan+decisions with NO enrichment records (persistable first); a
    separate enrichment_pass then produces bundle+capital from the
    PERSISTED records alone — so a crash mid-LLM loses enrichment only."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from nightly_pull import _chain_append

    from apex.hunter.forward_pass import decision_pass, enrichment_pass
    from tests.test_hunter_p1b import bars, ctx, failed_spike_frame
    f, t = failed_spike_frame(date="2026-08-17")
    uni = {"symbols": {"X": {"sector": "Technology", "sector_etf": None,
                             "median_dollar_volume": 500e6}},
           "universe_limitation": "test"}
    scan_rec, decisions = decision_pass(
        t, uni, {"X": f, "SPY.US": bars("SPY", n=120, noise=5e-5)},
        {"X": ctx("X"), "SPY.US": ctx("SPY")}, enrich=False)
    kinds = {d.get("kind") for d in decisions}
    assert kinds == {"decision"}                 # nothing waits on an LLM
    led = tmp_path / "led.jsonl"
    _chain_append(led, scan_rec)
    for d in decisions:
        _chain_append(led, d)                    # CRASH could happen here...
    enriched = enrichment_pass(t, "2026-08-17", decisions, uni)
    assert {r["kind"] for r in enriched} == {"forecast_bundle",
                                             "capital_decision"}
    cap = [r for r in enriched if r["kind"] == "capital_decision"][0]
    assert cap["final_state"] in ("OBSERVE", "WATCH", "NO_TRADE", "REFUSED")
    # enrichment reads ONLY persisted record fields (replayable)
    assert cap["decision_id"] in {d["decision_id"] for d in decisions}
