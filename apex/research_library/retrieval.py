"""Deterministic retrieval over the library's structured metadata --
NOT an LLM/vector black box. Every function here reads the append-only
JSONL ledgers and filters in Python; that is the whole retrieval layer
tonight. Semantic retrieval may sit on top of this later, but the
canonical answer to "what do we know" always comes from these
structured fields, never from a vector similarity score alone.

THE CAPTAIN ACCESS LAW: `research_prior_for()` is the ONLY function
intended for CaptainFrontierShadow (or any live decision-adjacent
consumer) to call. It returns a small, explicitly-labeled RESEARCH_PRIOR
bundle -- never the whole library, never unbounded. The label exists so
a caller can never mistake research narrative for
CURRENT_MARKET_EVIDENCE; current live evidence always outranks it.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import documents as documents_mod
from . import hypotheses as hypotheses_mod
from . import mechanisms as mechanisms_mod

RESEARCH_PRIOR_LABEL = "RESEARCH_PRIOR"
DEFAULT_MAX_ITEMS = 3


def _read_all(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _latest_documents() -> list:
    """One row per (collection, title): the highest version only,
    unless a caller explicitly wants full lineage via
    document_lineage()."""
    by_key = {}
    for d in _read_all(documents_mod.LEDGER):
        key = (d.get("collection"), d.get("title"))
        if key not in by_key or d.get("version", 0) > by_key[key].get("version", 0):
            by_key[key] = d
    return list(by_key.values())


def document_lineage(collection: str, title: str) -> tuple:
    """ALL versions, oldest first -- the full, never-rewritten history."""
    matches = [d for d in _read_all(documents_mod.LEDGER)
              if d.get("collection") == collection and d.get("title") == title]
    return tuple(sorted(matches, key=lambda d: d.get("version", 0)))


def search_documents(*, collection: str | None = None, source_type: str | None = None,
                     document_type: str | None = None, research_status: str | None = None,
                     evidence_class: str | None = None, date_from: str | None = None,
                     date_to: str | None = None, text: str | None = None) -> tuple:
    docs = _latest_documents()
    out = []
    for d in docs:
        if collection and d.get("collection") != collection:
            continue
        if source_type and d.get("source_type") != source_type:
            continue
        if document_type and d.get("document_type") != document_type:
            continue
        if research_status and d.get("research_status") != research_status:
            continue
        if evidence_class and d.get("evidence_class") != evidence_class:
            continue
        pub = d.get("publication_date")
        if date_from and (pub is None or pub < date_from):
            continue
        if date_to and (pub is None or pub > date_to):
            continue
        if text and text.lower() not in (d.get("title", "") + " "
                                         + d.get("source_name", "")).lower():
            continue
        out.append(d)
    return tuple(out)


def get_document(document_id: str) -> dict | None:
    for d in _read_all(documents_mod.LEDGER):
        if d.get("document_id") == document_id:
            return d
    return None


def _latest_mechanisms() -> list:
    by_id = {}
    for m in _read_all(mechanisms_mod.LEDGER):
        mid = m.get("mechanism_id")
        # last write wins for a given id -- ledger order is chronological
        by_id[mid] = m
    return list(by_id.values())


def search_mechanisms(*, market: str | None = None, evidence_status: str | None = None,
                      apex_status: str | None = None, collection: str | None = None
                      ) -> tuple:
    mechs = _latest_mechanisms()
    out = []
    for m in mechs:
        if market and m.get("market") != market:
            continue
        if evidence_status and m.get("evidence_status") != evidence_status:
            continue
        if apex_status and m.get("apex_status") != apex_status:
            continue
        out.append(m)
    return tuple(out)


def get_mechanism(mechanism_id: str) -> dict | None:
    for m in reversed(_read_all(mechanisms_mod.LEDGER)):
        if m.get("mechanism_id") == mechanism_id:
            return m
    return None


def related_mechanisms(mechanism_id: str) -> tuple:
    """Same market, or sharing at least one supporting/contradicting
    document -- a deterministic, transparent relation, not a learned
    embedding similarity."""
    target = get_mechanism(mechanism_id)
    if target is None:
        return ()
    target_docs = set(target.get("supporting_documents", ())) | set(
        target.get("contradicting_documents", ()))
    out = []
    for m in _latest_mechanisms():
        if m.get("mechanism_id") == mechanism_id:
            continue
        docs = set(m.get("supporting_documents", ())) | set(
            m.get("contradicting_documents", ()))
        if m.get("market") == target.get("market") or (docs & target_docs):
            out.append(m)
    return tuple(out)


def get_supporting_evidence(mechanism_id: str) -> tuple:
    m = get_mechanism(mechanism_id)
    if m is None:
        return ()
    return tuple(get_document(d) for d in m.get("supporting_documents", ())
                if get_document(d) is not None)


def get_contradicting_evidence(mechanism_id: str) -> tuple:
    m = get_mechanism(mechanism_id)
    if m is None:
        return ()
    return tuple(get_document(d) for d in m.get("contradicting_documents", ())
                if get_document(d) is not None)


def get_hypothesis_candidates(*, mechanism_id: str | None = None,
                              status: str | None = None) -> tuple:
    out = []
    for h in _read_all(hypotheses_mod.LEDGER):
        if mechanism_id and h.get("mechanism_id") != mechanism_id:
            continue
        if status and h.get("status") != status:
            continue
        out.append(h)
    return tuple(out)


def research_prior_for(mechanism_id: str, *, max_items: int = DEFAULT_MAX_ITEMS) -> dict:
    """THE bounded Captain-facing entry point. Never returns the whole
    library; never returns raw document full text; always labeled
    RESEARCH_PRIOR so a consumer cannot mistake it for live evidence."""
    m = get_mechanism(mechanism_id)
    if m is None:
        return {"label": RESEARCH_PRIOR_LABEL, "mechanism_id": mechanism_id,
               "status": "NOT_FOUND", "note": "current live evidence outranks "
               "research narrative; this mechanism has no library entry"}
    supporting = get_supporting_evidence(mechanism_id)[:max_items]
    contradicting = get_contradicting_evidence(mechanism_id)[:max_items]
    return {
        "label": RESEARCH_PRIOR_LABEL,
        "mechanism_id": mechanism_id, "name": m.get("name"),
        "evidence_status": m.get("evidence_status"), "apex_status": m.get("apex_status"),
        "known_failure_modes": m.get("known_failure_modes", ()),
        "supporting_evidence": [
            {"document_id": d["document_id"], "title": d["title"],
            "source_name": d["source_name"]} for d in supporting],
        "contradicting_evidence": [
            {"document_id": d["document_id"], "title": d["title"],
            "source_name": d["source_name"]} for d in contradicting],
        "note": ("RESEARCH_PRIOR, not CURRENT_MARKET_EVIDENCE -- current live "
                "evidence always outranks research narrative"),
    }
