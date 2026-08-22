"""ResearchScientist — F12. Proves proposals can only ever carry
RESEARCH_PROPOSAL_ONLY status, the auto-generators fire only on
genuine material triggers, and this module cannot reach the two
governance modules that would let it actually spend anything real.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from apex.audit.execution_path import module_closure
from apex.frontier2.model_market import new_scorecard, snapshot, submit
from apex.frontier2.research_scientist import (STATUS, ResearchProposal,
                                               ResearchScientistError,
                                               from_false_positive,
                                               from_model_market_conflict,
                                               propose)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")
REPO = Path(__file__).resolve().parents[1]


def _propose(**overrides):
    base = dict(proposal_id="P1", subject_component="CURVE",
               observation="x", hypothesis="y", mechanism="z",
               falsification="f", required_data=("d",), primary_metric="m",
               sample_requirement="n>=20", regime_requirement="any",
               prospective_test="t", expected_failure_mode="e",
               known_from=T0, now=T0)
    base.update(overrides)
    return propose(**base)


def test_status_is_always_research_proposal_only():
    p = _propose()
    assert p.status == STATUS == "RESEARCH_PROPOSAL_ONLY"


def test_status_has_no_settable_parameter():
    import inspect
    assert "status" not in inspect.signature(propose).parameters


def test_constructing_with_a_different_status_directly_is_refused():
    with pytest.raises(ResearchScientistError):
        ResearchProposal(
            proposal_id="P1", subject_component="X", observation="o",
            hypothesis="h", mechanism="m", falsification="f",
            required_data=(), primary_metric="pm", secondary_metric=None,
            sample_requirement="s", regime_requirement="r",
            prospective_test="pt", expected_failure_mode="ef", provenance=(),
            known_from=str(T0), as_of=str(T0), status="PROMOTED")


# ---- auto-generator: model market conflict --------------------------------

def test_material_conflict_generates_a_proposal():
    subs = (
        submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0),
        submit("MOMENTUM", "P", "SUPPORT", reason="b", known_from=T0, now=T0),
        submit("REVERSION", "P", "OPPOSE", reason="c", known_from=T0, now=T0),
        submit("ANALOG", "P", "OPPOSE", reason="d", known_from=T0, now=T0),
    )
    snap = snapshot("P", subs)
    prop = from_model_market_conflict(snap, now=T0)
    assert prop is not None
    assert prop.subject_component == "InternalModelMarket"
    assert prop.status == "RESEARCH_PROPOSAL_ONLY"


def test_no_material_conflict_generates_nothing():
    subs = (submit("CURVE", "P", "SUPPORT", reason="a", known_from=T0, now=T0),)
    snap = snapshot("P", subs)
    assert from_model_market_conflict(snap, now=T0) is None


# ---- auto-generator: false positives --------------------------------------

def test_false_positive_generates_a_proposal():
    sc = new_scorecard("CURVE", "P")
    sc = sc.__class__(**{**sc.__dict__, "false_positive": 1, "resolved": 5})
    prop = from_false_positive(sc, now=T0)
    assert prop is not None
    assert prop.subject_component == "CURVE"


def test_zero_false_positives_generates_nothing():
    sc = new_scorecard("CURVE", "P")
    assert from_false_positive(sc, now=T0) is None


# ---- the cannot list, mechanically -----------------------------------

def test_cannot_reach_governance_ledger_or_holdout():
    reached = module_closure(REPO, "apex.frontier2.research_scientist")
    forbidden = {r for r in reached
                if r in ("apex.governance.ledger", "apex.governance.holdout_capacity")
                or r.startswith("apex.governance.ledger.")
                or r.startswith("apex.governance.holdout_capacity.")}
    assert not forbidden


def test_cannot_reach_production_stack():
    reached = module_closure(REPO, "apex.frontier2.research_scientist")
    forbidden = {r for r in reached
                if r.startswith("apex.hunter") or r.startswith("apex.captain")
                or r.startswith("apex.execution")}
    assert not forbidden


def test_determinism_same_inputs_twice_byte_identical():
    a = _propose()
    b = _propose()
    assert a.as_record() == b.as_record()


def test_persist_writes_and_chains(tmp_path, monkeypatch):
    import apex.frontier2.research_scientist as rs
    monkeypatch.setattr(rs, "LEDGER", tmp_path / "rs.jsonl")
    p = _propose()
    rec1 = rs.persist(p)
    rec2 = rs.persist(p)
    assert rec2["prev_hash"] == rec1["entry_hash"]
    assert rec1["decision_power"] == "NONE_FRONTIER_SHADOW"
