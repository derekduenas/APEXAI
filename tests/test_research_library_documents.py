"""ResearchDocument — immutable versioning, hash integrity, duplicate
detection, source provenance.
"""
from __future__ import annotations

import pandas as pd
import pytest

from apex.research_library.documents import (INGEST_VERDICTS,
                                              ResearchLibraryError, ingest)

T0 = pd.Timestamp("2026-08-18T14:00:00Z")


def _ingest(tmp_path, monkeypatch, **overrides):
    import apex.research_library.documents as docmod
    monkeypatch.setattr(docmod, "LEDGER", tmp_path / "documents.jsonl")
    base = dict(title="Test Report", collection="ELITE_TRADING",
               document_type="RESEARCH_REPORT", source_type="INTERNAL",
               source_name="test", source_reference="docs/test.md",
               content="the original content", known_from=T0, now=T0)
    base.update(overrides)
    return ingest(**base)


def test_first_ingest_verdict(tmp_path, monkeypatch):
    doc, verdict = _ingest(tmp_path, monkeypatch)
    assert verdict == "INGESTED"
    assert doc.version == 1
    assert doc.supersedes is None


def test_identical_content_twice_is_duplicate(tmp_path, monkeypatch):
    d1, v1 = _ingest(tmp_path, monkeypatch)
    d2, v2 = _ingest(tmp_path, monkeypatch)
    assert v1 == "INGESTED"
    assert v2 == "DUPLICATE"
    assert d1.document_id == d2.document_id
    assert d1.content_hash == d2.content_hash


def test_different_content_same_title_is_new_version(tmp_path, monkeypatch):
    d1, _ = _ingest(tmp_path, monkeypatch, content="version one")
    d2, verdict = _ingest(tmp_path, monkeypatch, content="version TWO, different")
    assert verdict == "NEW_VERSION"
    assert d2.version == 2
    assert d2.supersedes == d1.document_id
    assert d1.content_hash != d2.content_hash


def test_v1_is_never_rewritten(tmp_path, monkeypatch):
    """Immutability: ingesting v2 must not alter v1's own ledger row."""
    import apex.research_library.documents as docmod
    d1, _ = _ingest(tmp_path, monkeypatch, content="version one")
    _ingest(tmp_path, monkeypatch, content="version TWO")
    from apex.research_library.retrieval import document_lineage
    lineage = document_lineage("ELITE_TRADING", "Test Report")
    assert len(lineage) == 2
    assert lineage[0]["version"] == 1
    assert lineage[0]["content_hash"] == d1.content_hash
    assert lineage[1]["version"] == 2


def test_content_hash_is_deterministic_sha256(tmp_path, monkeypatch):
    import hashlib
    doc, _ = _ingest(tmp_path, monkeypatch, content="known text")
    assert doc.content_hash == hashlib.sha256(b"known text").hexdigest()


def test_source_reference_and_hash_preserved(tmp_path, monkeypatch):
    doc, _ = _ingest(tmp_path, monkeypatch, source_reference="docs/some/path.md")
    assert doc.source_reference == "docs/some/path.md"
    assert doc.source_hash  # non-empty, deterministic from the reference


def test_unknown_document_type_refused(tmp_path, monkeypatch):
    with pytest.raises(ResearchLibraryError):
        _ingest(tmp_path, monkeypatch, document_type="NOT_A_REAL_TYPE")


def test_unknown_research_status_refused(tmp_path, monkeypatch):
    with pytest.raises(ResearchLibraryError):
        _ingest(tmp_path, monkeypatch, research_status="PROVEN")


def test_new_collection_not_in_the_named_tuple_still_works(tmp_path, monkeypatch):
    """Allow future collections without a schema rewrite."""
    doc, verdict = _ingest(tmp_path, monkeypatch,
                           collection="A_BRAND_NEW_COLLECTION_NAME")
    assert verdict == "INGESTED"
    assert doc.collection == "A_BRAND_NEW_COLLECTION_NAME"


def test_provenance_fields_all_present(tmp_path, monkeypatch):
    doc, _ = _ingest(tmp_path, monkeypatch, authors=("A. Author",),
                     publication_date="2025-01-01")
    for field in ("document_id", "source_type", "source_name", "source_reference",
                 "content_hash", "source_hash", "known_from", "as_of"):
        assert getattr(doc, field)


def test_decision_power_stamped(tmp_path, monkeypatch):
    doc, _ = _ingest(tmp_path, monkeypatch)
    assert doc.decision_power == "NONE_RESEARCH_MEMORY"


def test_ledger_is_hash_chained(tmp_path, monkeypatch):
    _ingest(tmp_path, monkeypatch, content="a")
    _ingest(tmp_path, monkeypatch, content="b")
    import json
    lines = (tmp_path / "documents.jsonl").read_text().strip().splitlines()
    recs = [json.loads(l) for l in lines]
    assert recs[1]["prev_hash"] == recs[0]["entry_hash"]
