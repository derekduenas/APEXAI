"""GOVERNOR CONTRACTS — an executive with a structural ceiling.

The point of these tests is not that the Governor is well-behaved. It
is that misbehaviour is unreachable.
"""
from __future__ import annotations

import pytest

from apex.governor import AUTONOMOUS_TIERS, CHARTER, TIERS
from apex.governor.authority import (CATALOG, PROTECTED_EVIDENCE,
                                     AuthorityViolation,
                                     authorize, catalog_report,
                                     tier_of)
from apex.governor.doctrine import (DAILY_KPI, DoctrineViolation,
                                    build_request, daily_scorecard)
from apex.governor.executive import (Diagnosis, ExecutiveViolation,
                                     Hypothesis, act, propose)


# ==================================================== THE CEILING

def test_every_trading_change_is_locked():
    for name in ("change_gate_threshold", "change_position_sizing",
                 "change_exit_rule", "add_trading_signal",
                 "promote_edge_dna", "grant_capital_authority"):
        assert tier_of(name) == "TIER3_PRODUCTION_TRADING"
        with pytest.raises(AuthorityViolation, match="LOCKED"):
            authorize(name)


def test_self_supplied_approval_does_not_unlock_tier_three():
    """Approval is the operator's act, not a parameter the executive
    hands to itself."""
    with pytest.raises(AuthorityViolation,
                       match="not a parameter the executive supplies"):
        authorize("promote_edge_dna",
                  operator_approval="I_APPROVE_THIS")


def test_the_lock_is_structural_not_advisory():
    """No function anywhere in the governor package mutates a trading
    rule. An executive that decided to would find nothing to call."""
    import apex.governor.executive as ex
    import apex.governor.authority as au
    import apex.governor.doctrine as do
    for mod in (ex, au, do):
        for banned in ("apply", "deploy", "activate_change",
                       "set_threshold", "promote"):
            assert not hasattr(mod, banned), \
                f"{mod.__name__}.{banned} exists -- the ceiling leaks"


def test_the_catalog_is_a_whitelist_not_a_blocklist():
    with pytest.raises(AuthorityViolation, match="whitelist"):
        authorize("something_nobody_thought_of")


def test_operational_and_research_are_autonomous():
    for name in ("restart_service", "resume_durable_consumer",
                 "rotate_disposable_logs"):
        assert authorize(name)["tier"] == "TIER1_OPERATIONAL"
    for name in ("register_hypothesis", "run_chronos_campaign",
                 "run_falsification"):
        assert authorize(name)["tier"] == "TIER2_RESEARCH"
    assert set(AUTONOMOUS_TIERS) == {"TIER1_OPERATIONAL",
                                     "TIER2_RESEARCH"}


def test_a_disk_repair_may_never_delete_sealed_evidence():
    """The failure this forbids: disk pressure at 81% used, and a
    tidy-up that removes the research it exists to protect."""
    for p in PROTECTED_EVIDENCE:
        with pytest.raises(AuthorityViolation, match="never disposable"):
            authorize("rotate_disposable_logs", target=f"{p}/old.jsonl")
    assert authorize("rotate_disposable_logs",
                     target="results/ops/logs/orchestrator.out")


def test_research_may_request_recording_but_not_decisions():
    a = CATALOG["request_boundary_instrumentation"]
    assert a.tier == "TIER2_RESEARCH"
    assert "may not change any decision" in a.bounded_by


def test_the_catalog_report_names_what_is_locked():
    r = catalog_report()
    assert r["locked"] == "TIER3_PRODUCTION_TRADING"
    assert set(r["tiers"]) == set(TIERS)
    assert "structural" in r["law"]
    assert "propose" in CHARTER or "propose" in CHARTER.lower()


# ==================================================== DIAGNOSIS

def test_a_hypothesis_without_a_falsifier_is_refused():
    with pytest.raises(ExecutiveViolation, match="narrating"):
        Hypothesis(statement="something is wrong",
                   supporting_evidence=("a log line",), falsifier="")


def test_a_hypothesis_without_evidence_is_refused():
    with pytest.raises(ExecutiveViolation, match="cites no evidence"):
        Hypothesis(statement="x", supporting_evidence=(),
                   falsifier="y")


def test_a_diagnosis_cannot_smuggle_a_trading_change_as_a_repair():
    with pytest.raises(ExecutiveViolation, match="smuggle"):
        Hypothesis(statement="the gate is too tight",
                   supporting_evidence=("two losing days",),
                   falsifier="a wider gate loses more",
                   implied_repair="change_gate_threshold")


def test_diagnoses_rank_by_confidence():
    d = Diagnosis(subject="options-paper", symptom="alive, 0 scans")
    d.hypotheses = [
        Hypothesis("universe init throws", ("exit after init",),
                   "it exits at a different stage", confidence="LOW"),
        Hypothesis("secrets unreadable", ("PermissionError in log",),
                   "the secret reads fine as this user",
                   implied_repair="restart_service",
                   confidence="HIGH")]
    r = d.as_record()
    assert r["hypotheses"][0]["confidence"] == "HIGH"
    assert "would kill it" in r["law"]


# ==================================================== ACTIONS

def test_a_refused_action_is_still_recorded(tmp_path, monkeypatch):
    import apex.governor.executive as ex
    monkeypatch.setattr(ex, "INCIDENTS", tmp_path / "inc.jsonl")
    with pytest.raises(AuthorityViolation):
        act(action="promote_edge_dna", target="CEDGE_002",
            reason="it looked good")
    body = (tmp_path / "inc.jsonl").read_text()
    assert "governor_action_refused" in body, \
        "a Governor that quietly declines is indistinguishable from " \
        "one that never noticed"


def test_an_authorized_action_records_its_grant(tmp_path, monkeypatch):
    import apex.governor.executive as ex
    monkeypatch.setattr(ex, "INCIDENTS", tmp_path / "inc.jsonl")
    r = act(action="restart_service", target="options-paper",
            reason="alive but zero scans for 15 minutes")
    assert r["grant"]["tier"] == "TIER1_OPERATIONAL"
    assert r["grant"]["reversible"] is True


# ==================================================== PROPOSALS

def test_a_proposal_is_a_document_not_a_deployment(tmp_path,
                                                   monkeypatch):
    import apex.governor.executive as ex
    monkeypatch.setattr(ex, "PROPOSALS", tmp_path / "p.jsonl")
    p = propose(change="change_gate_threshold",
                rationale="WAIT cohort outperformed ATTACK over 40 "
                          "independent sessions",
                evidence={"gate_value": "results/.../gate_value.json"},
                expected_effect="fewer attacks, higher median",
                risk_if_wrong="we stop taking the only trades that win",
                falsifier="ATTACK median exceeds WAIT over the next 40")
    assert p["status"] == "AWAITING_OPERATOR"
    assert p["applied"] is False
    assert p["decision_power"] == "NONE_PROPOSAL_ONLY"


def test_a_proposal_without_a_falsifier_is_advocacy(tmp_path,
                                                    monkeypatch):
    import apex.governor.executive as ex
    monkeypatch.setattr(ex, "PROPOSALS", tmp_path / "p.jsonl")
    with pytest.raises(ExecutiveViolation, match="advocacy"):
        propose(change="change_exit_rule", rationale="r",
                evidence={}, expected_effect="e", risk_if_wrong="k",
                falsifier="")


# ==================================================== DOCTRINE

def _ev():
    return {k: f"artifact for {k}" for k in DAILY_KPI}


def test_the_six_questions_must_all_be_answered():
    ans = {k: "YES" for k in DAILY_KPI}
    del ans["DID_WE_LEARN_FROM_THE_RESULTS"]
    with pytest.raises(DoctrineViolation, match="unasked question"):
        daily_scorecard(session="2026-08-26", answers=ans,
                        evidence=_ev())


def test_an_answer_without_an_artifact_is_an_impression():
    ans = {k: "YES" for k in DAILY_KPI}
    ev = _ev()
    ev["DID_WE_OBSERVE"] = ""
    with pytest.raises(DoctrineViolation, match="impression"):
        daily_scorecard(session="2026-08-26", answers=ans, evidence=ev)


def test_tuesday_scores_as_a_day_with_gaps():
    """The report card the Governor would have filed for 2026-08-25."""
    ans = {"DID_WE_SHOW_UP": "NO", "DID_WE_OBSERVE": "NO",
           "DID_WE_HAVE_VALID_OPPORTUNITIES": "NOT_ESTIMABLE",
           "DID_WE_ATTACK_WHEN_WARRANTED": "NOT_ESTIMABLE",
           "DID_WE_REFUSE_WHEN_WARRANTED": "NOT_ESTIMABLE",
           "DID_WE_LEARN_FROM_THE_RESULTS": "NO"}
    s = daily_scorecard(session="2026-08-25", answers=ans,
                        evidence=_ev())
    assert s["verdict"] == "DAY_WITH_GAPS"
    assert "DID_WE_SHOW_UP" in s["failed"]


def test_the_default_answer_to_building_is_defer():
    r = build_request(capability="another regime classifier",
                      motivation="it would be interesting",
                      proven_gap=None,
                      cheaper_alternative_considered="none")
    assert r["verdict"] == "DEFER"
    assert r["freeze_in_force"] is True
    assert "TIER2" in r["route"]


def test_a_market_loss_is_not_a_proven_gap():
    r = build_request(capability="looser gate",
                      motivation="we lost twice",
                      proven_gap={"kind": "MARKET_LOSS",
                                  "evidence": "two losing trades"},
                      cheaper_alternative_considered="none")
    assert r["verdict"] == "DEFER"
    assert "not a proven gap kind" in r["why"]


def test_a_suspicion_without_an_artifact_is_deferred():
    r = build_request(capability="x", motivation="m",
                      proven_gap={"kind": "OPS_DEFECT"},
                      cheaper_alternative_considered="none")
    assert r["verdict"] == "DEFER"
    assert "suspicion" in r["why"]


def test_a_real_defect_proceeds_with_scope_limited_to_it():
    r = build_request(
        capability="schedule the options session",
        motivation="Tuesday produced no options session at all",
        proven_gap={"kind": "OPS_DEFECT",
                    "evidence": "heartbeat last write Mon 20:27 UTC; "
                                "no launchd/systemd entry exists"},
        cheaper_alternative_considered="a manual runbook reminder, "
                                       "rejected: it failed once "
                                       "already")
    assert r["verdict"] == "PROCEED"
    assert r["scope"] == "repair the named gap and nothing adjacent"


def test_you_must_say_out_loud_what_cheaper_thing_you_considered():
    with pytest.raises(DoctrineViolation, match="out loud"):
        build_request(capability="x", motivation="m",
                      proven_gap=None,
                      cheaper_alternative_considered="")
