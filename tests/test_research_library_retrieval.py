"""Retrieval layer — contradiction retrieval, mechanism linking, bounded
Captain access, and the RESEARCH_PRIOR vs CURRENT_MARKET_EVIDENCE
distinction.
"""
from __future__ import annotations

import pandas as pd

from apex.research_library.documents import ingest
from apex.research_library.hypotheses import propose
from apex.research_library.mechanisms import register_mechanism
from apex.research_library.retrieval import (RESEARCH_PRIOR_LABEL,
                                              get_contradicting_evidence,
                                              get_hypothesis_candidates,
                                              get_mechanism,
                                              get_supporting_evidence,
                                              related_mechanisms,
                                              research_prior_for,
                                              search_documents,
                                              search_mechanisms)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _patch_all(tmp_path, monkeypatch):
    import apex.research_library.documents as d
    import apex.research_library.hypotheses as h
    import apex.research_library.mechanisms as m
    monkeypatch.setattr(d, "LEDGER", tmp_path / "documents.jsonl")
    monkeypatch.setattr(m, "LEDGER", tmp_path / "mechanisms.jsonl")
    monkeypatch.setattr(h, "LEDGER", tmp_path / "hypotheses.jsonl")


def test_search_documents_by_collection(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    ingest(title="A", collection="ELITE_TRADING", document_type="RESEARCH_REPORT",
          source_type="INTERNAL", source_name="x", source_reference="x.md",
          content="a", known_from=T0, now=T0)
    ingest(title="B", collection="OPTIONS", document_type="RESEARCH_REPORT",
          source_type="INTERNAL", source_name="x", source_reference="y.md",
          content="b", known_from=T0, now=T0)
    results = search_documents(collection="ELITE_TRADING")
    assert len(results) == 1 and results[0]["title"] == "A"


def test_search_documents_returns_only_latest_version(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    ingest(title="A", collection="X", document_type="RESEARCH_REPORT",
          source_type="INTERNAL", source_name="x", source_reference="x.md",
          content="v1", known_from=T0, now=T0)
    ingest(title="A", collection="X", document_type="RESEARCH_REPORT",
          source_type="INTERNAL", source_name="x", source_reference="x.md",
          content="v2", known_from=T0, now=T0)
    results = search_documents(collection="X")
    assert len(results) == 1
    assert results[0]["version"] == 2


def _mechanism_with_evidence(tmp_path, monkeypatch, mid="M1", market="EQUITIES"):
    sup, _ = ingest(title="Supporting Doc", collection="X",
                    document_type="RESEARCH_REPORT", source_type="INTERNAL",
                    source_name="x", source_reference="s.md", content="support",
                    known_from=T0, now=T0)
    con, _ = ingest(title="Contradicting Doc", collection="X",
                    document_type="RESEARCH_REPORT", source_type="INTERNAL",
                    source_name="x", source_reference="c.md", content="contra",
                    known_from=T0, now=T0)
    m = register_mechanism(
        mechanism_id=mid, name="Mech", description="d", market=market,
        time_horizon="INTRADAY", claimed_mechanism="c", why_it_might_exist="w",
        expected_behavior="e", falsification="f",
        supporting_documents=(sup.document_id,),
        contradicting_documents=(con.document_id,),
        known_failure_modes=("regime shift",), known_from=T0, now=T0)
    return m, sup, con


def test_contradiction_retrieval_returns_both_sides(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    m, sup, con = _mechanism_with_evidence(tmp_path, monkeypatch)
    supporting = get_supporting_evidence(m.mechanism_id)
    contradicting = get_contradicting_evidence(m.mechanism_id)
    assert supporting[0]["document_id"] == sup.document_id
    assert contradicting[0]["document_id"] == con.document_id


def test_related_mechanisms_by_shared_market(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    m1, _, _ = _mechanism_with_evidence(tmp_path, monkeypatch, mid="M1", market="EQUITIES")
    m2 = register_mechanism(
        mechanism_id="M2", name="Mech2", description="d", market="EQUITIES",
        time_horizon="INTRADAY", claimed_mechanism="c", why_it_might_exist="w",
        expected_behavior="e", falsification="f", known_from=T0, now=T0)
    m3 = register_mechanism(
        mechanism_id="M3", name="Mech3", description="d", market="CRYPTO",
        time_horizon="INTRADAY", claimed_mechanism="c", why_it_might_exist="w",
        expected_behavior="e", falsification="f", known_from=T0, now=T0)
    related = related_mechanisms("M1")
    ids = {r["mechanism_id"] for r in related}
    assert "M2" in ids
    assert "M3" not in ids


def test_captain_bounded_retrieval_is_labeled_research_prior(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    m, sup, con = _mechanism_with_evidence(tmp_path, monkeypatch)
    prior = research_prior_for(m.mechanism_id)
    assert prior["label"] == RESEARCH_PRIOR_LABEL
    assert "CURRENT_MARKET_EVIDENCE" not in prior["label"]
    assert "outranks" in prior["note"]


def test_captain_retrieval_is_bounded_not_the_whole_library(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    docs = []
    for i in range(10):
        doc, _ = ingest(title=f"Doc{i}", collection="X", document_type="RESEARCH_REPORT",
                       source_type="INTERNAL", source_name="x",
                       source_reference=f"{i}.md", content=f"c{i}",
                       known_from=T0, now=T0)
        docs.append(doc.document_id)
    m = register_mechanism(
        mechanism_id="M1", name="Mech", description="d", market="EQUITIES",
        time_horizon="INTRADAY", claimed_mechanism="c", why_it_might_exist="w",
        expected_behavior="e", falsification="f",
        supporting_documents=tuple(docs), known_from=T0, now=T0)
    prior = research_prior_for("M1", max_items=3)
    assert len(prior["supporting_evidence"]) == 3     # bounded, not all 10


def test_captain_retrieval_of_unknown_mechanism_is_honest(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    prior = research_prior_for("NOT_A_REAL_MECHANISM")
    assert prior["status"] == "NOT_FOUND"
    assert prior["label"] == RESEARCH_PRIOR_LABEL


def test_captain_retrieval_never_returns_raw_document_full_text(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    m, sup, con = _mechanism_with_evidence(tmp_path, monkeypatch)
    prior = research_prior_for(m.mechanism_id)
    for item in prior["supporting_evidence"] + prior["contradicting_evidence"]:
        assert set(item.keys()) == {"document_id", "title", "source_name"}


def test_search_mechanisms_by_apex_status(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    register_mechanism(mechanism_id="M1", name="A", description="d", market="EQ",
                       time_horizon="I", claimed_mechanism="c", why_it_might_exist="w",
                       expected_behavior="e", falsification="f",
                       apex_status="OBSERVATIONAL", known_from=T0, now=T0)
    register_mechanism(mechanism_id="M2", name="B", description="d", market="EQ",
                       time_horizon="I", claimed_mechanism="c", why_it_might_exist="w",
                       expected_behavior="e", falsification="f",
                       apex_status="REJECTED", known_from=T0, now=T0)
    results = search_mechanisms(apex_status="OBSERVATIONAL")
    assert len(results) == 1 and results[0]["mechanism_id"] == "M1"


def test_get_hypothesis_candidates_filters_by_mechanism(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    propose(hypothesis_id="H1", mechanism_id="M1", statement="s", market="EQ",
           primary_metric="m", minimum_sample="n", falsification="f",
           regime_requirements="r", cost_requirements="c",
           prospective_test_design="t", known_from=T0, now=T0)
    propose(hypothesis_id="H2", mechanism_id="M2", statement="s", market="EQ",
           primary_metric="m", minimum_sample="n", falsification="f",
           regime_requirements="r", cost_requirements="c",
           prospective_test_design="t", known_from=T0, now=T0)
    results = get_hypothesis_candidates(mechanism_id="M1")
    assert len(results) == 1 and results[0]["hypothesis_id"] == "H1"


def test_empty_library_retrieval_is_empty_not_a_crash(tmp_path, monkeypatch):
    _patch_all(tmp_path, monkeypatch)
    assert search_documents() == ()
    assert search_mechanisms() == ()
    assert get_hypothesis_candidates() == ()
    assert get_mechanism("nope") is None
