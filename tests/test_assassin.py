"""The Assassin as a formal stage: every attack recorded, wounds feed the
monotone caution law, behavior identical to the pre-stage semantics."""

from __future__ import annotations

from apex.hunter.assassin import DORMANT_MECHANISMS, review
from apex.hunter.forecast import SwarmAssessment, assemble_bundle

CAND = {"decision_id": "d1", "symbol": "AMD", "direction": "LONG",
        "playbook_id": "HUNTER-001_v1", "chart_state": {"data_quality": []}}


def _swarm_ok(verdict):
    return SwarmAssessment(
        candidate_id="d1", as_of="t", status="OK",
        agents_run=("ADVERSARIAL_TRADER",),
        adversarial_flags=(("ADVERSARIAL_TRADER: MATERIAL_OBJECTION",)
                           if verdict == "MATERIAL_OBJECTION" else ()),
        provenance={"adversary_verdict": verdict})


def test_swarm_objection_wounds_and_is_attributed():
    b = assemble_bundle(CAND, swarm=_swarm_ok("MATERIAL_OBJECTION"))
    r = review(CAND, b)
    assert r.verdict == "SURVIVED_WOUNDED"
    assert "SWARM_ADVERSARIAL_TRADER" in r.landed
    assert "FORECAST_SOURCE_DISAGREEMENT" in r.landed  # flags -> HIGH
    assert r.disagreement_level == "HIGH"             # capital caution input


def test_clean_candidate_survives_clean_with_attempts_recorded():
    b = assemble_bundle(CAND, swarm=_swarm_ok("NO_MATERIAL_OBJECTION"))
    r = review(CAND, b)
    assert r.verdict == "SURVIVED_CLEAN" and r.landed == ()
    assert {a["mechanism"] for a in r.attempts} >= {
        "SWARM_ADVERSARIAL_TRADER", "FORECAST_SOURCE_DISAGREEMENT",
        "ANALOG_SUPPORT", "DATA_QUALITY"}
    assert set(DORMANT_MECHANISMS) == set(r.dormant_mechanisms)


def test_wounds_never_authorize_only_caution():
    rec = review(CAND, assemble_bundle(
        CAND, swarm=_swarm_ok("MATERIAL_OBJECTION"))).as_record()
    flat = str(rec)
    assert "PAPER_ELIGIBLE" not in flat and "TRADE\"" not in flat
    assert rec["kind"] == "assassin_review"
