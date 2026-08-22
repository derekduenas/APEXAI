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
    assert a.status == "OK"                      # GOOD has no verdict: no kill
    assert a.agents_run == swarm.V2_ACTIVE_AGENTS
    assert len(prompts) == 4                     # one call PER seat
    assert len(set(prompts)) == 4                # role separation
    assert "other desk seats" in prompts[-1]     # only Synthesis sees views
    assert all("other desk seats" not in x for x in prompts[:-1])
    assert all(c[2] for c in a.claims)           # every claim has a basis


def test_garbage_output_is_failed_never_partial(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    a = swarm.run_specialists(CAND, as_of="t",
                              runner=lambda p: "I think you should BUY!!!")
    assert a.status == "FAILED" and a.claims == ()
    with pytest.raises(ValueError):              # contract: non-OK, no claims
        from apex.hunter.forecast import SwarmAssessment
        SwarmAssessment(candidate_id="x", as_of="t", status="FAILED",
                        claims=(("A", "b", "c"),))


def test_blown_deadline_keeps_tier1_partial_honesty(monkeypatch):
    """A blown total budget skips the committee but keeps the assassin's
    completed work — partial honesty over wholesale loss."""
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    a = swarm.run_specialists(CAND, as_of="t", deadline_seconds=-1,
                              runner=lambda p: GOOD)
    assert a.status == "OK"
    assert a.agents_run == swarm.TIER1_AGENTS
    assert a.provenance["tier_completed"] == "TIER1"
    assert set(a.provenance["agents_skipped"]) == set(swarm.TIER2_AGENTS)


def test_facts_only_from_candidate_no_instructions_leak():
    facts = swarm._candidate_facts(CAND)
    parsed = json.loads(facts)
    assert set(parsed) <= {"symbol", "playbook_id", "direction", "matched",
                           "risk_frac", "market", "relative_strength",
                           "chart"}


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
        t, uni, {"X": f, "SPY.US": bars("SPY", date="2026-08-17",
                                        n=120, noise=5e-5)},
        {"X": ctx("X", as_of_date="2026-08-17"),
         "SPY.US": ctx("SPY", as_of_date="2026-08-17")}, enrich=False)
    kinds = {d.get("kind") for d in decisions}
    assert kinds == {"decision"}                 # nothing waits on an LLM
    led = tmp_path / "led.jsonl"
    _chain_append(led, scan_rec)
    for d in decisions:
        _chain_append(led, d)                    # CRASH could happen here...
    enriched = enrichment_pass(t, "2026-08-17", decisions, uni)
    assert {r["kind"] for r in enriched} == {"forecast_bundle",
                                             "assassin_review",
                                             "capital_decision",
                                             "captain_state",
                                             "opportunity_board"}
    cap_state = [r for r in enriched if r["kind"] == "captain_state"][0]
    assert cap_state["decision_power"] == "NONE_OBSERVATIONAL_EPOCH1"
    assert cap_state["capital_is_sovereign"] is True
    rev = [r for r in enriched if r["kind"] == "assassin_review"][0]
    assert rev["verdict"] in ("SURVIVED_CLEAN", "SURVIVED_WOUNDED")
    assert len(rev["attempts"]) >= 4              # every mechanism recorded
    cap = [r for r in enriched if r["kind"] == "capital_decision"][0]
    assert cap["final_state"] in ("OBSERVE", "WATCH", "NO_TRADE", "REFUSED")
    # enrichment reads ONLY persisted record fields (replayable)
    assert cap["decision_id"] in {d["decision_id"] for d in decisions}


ADVERSARY = json.dumps({
    "flags": {"CHASE_RISK": "HIGH", "SECTOR_CONFIRMATION": "LOW",
              "MARKET_SUPPORT": "MODERATE", "EXTENSION_RISK": "LOW"},
    "primary_objection": "already 1.6x the normal opening-range extension",
    "verdict": "MATERIAL_OBJECTION", "claims": []})
SYNTH = json.dumps({"contradictions": ["quant strong vs adversary chase"],
                    "synthesis": "good thesis, bad price", "claims": []})


def _desk_runner(p):
    if "OTHER SIDE" in p:
        return ADVERSARY
    if "other desk seats" in p:
        return SYNTH
    return GOOD


def test_tier1_fast_kill_skips_the_committee(monkeypatch):
    """The assassin ends the desk: MATERIAL_OBJECTION -> Tier 2 never
    convenes; the objection already carries maximum caution downstream."""
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    a = swarm.run_specialists(CAND, as_of="t", runner=_desk_runner)
    assert a.status == "OK"
    assert a.provenance["adversary_verdict"] == "MATERIAL_OBJECTION"
    assert a.provenance["fast_kill"] is True
    assert a.provenance["tier_completed"] == "TIER1"
    assert a.agents_run == swarm.TIER1_AGENTS
    assert "THESIS_ANALYST" in a.provenance["agents_skipped"]
    # HIGH risk axis and LOW confirmation axis flag; LOW risk axis does not
    assert any("CHASE_RISK=HIGH" in f for f in a.adversarial_flags)
    assert any("SECTOR_CONFIRMATION=LOW" in f for f in a.adversarial_flags)
    assert not any("EXTENSION_RISK=LOW" in f for f in a.adversarial_flags)
    assert any("PRIMARY_OBJECTION" in c[1] for c in a.claims)


SURVIVOR = json.dumps({
    "flags": {"CHASE_RISK": "LOW", "SECTOR_CONFIRMATION": "HIGH",
              "MARKET_SUPPORT": "HIGH", "EXTENSION_RISK": "MODERATE"},
    "primary_objection": "", "verdict": "NO_MATERIAL_OBJECTION",
    "claims": []})


def test_survivor_gets_the_full_desk(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)

    def runner(p):
        if "OTHER SIDE" in p:
            return SURVIVOR
        if "other desk seats" in p:
            return SYNTH
        return GOOD
    a = swarm.run_specialists(CAND, as_of="t", runner=runner)
    assert a.provenance["fast_kill"] is False
    assert a.provenance["tier_completed"] == "FULL_DESK"
    assert a.agents_run == swarm.V2_ACTIVE_AGENTS
    assert not any("CHASE_RISK=LOW" in f for f in a.adversarial_flags)
    assert any("SYNTHESIS" in d for d in a.disagreements)
    assert any(c[0] == "SYNTHESIS_ANALYST" and "bad price" in c[1]
               for c in a.claims)


def test_material_objection_raises_disagreement_to_high(monkeypatch):
    monkeypatch.setattr(swarm, "auth_available", lambda: True)
    from apex.hunter.forecast import assemble_bundle
    a = swarm.run_specialists(CAND, as_of="t", runner=_desk_runner)
    b = assemble_bundle({"decision_id": "d1", "direction": "LONG",
                         "playbook_id": "HUNTER-001_v1"}, swarm=a)
    assert b.disagreement["level"] == "HIGH"     # conservative-only path
