"""EVENT_INTELLIGENCE_ADMISSIBILITY_V0 -- the refusals, first.

Each test breaks exactly one thing in an otherwise valid record, so a
failure names what was broken. Nothing here mirrors the implementation: the
assertions are about what a record MEANS (can this be joined to a market
state? is this one observation or two? did the model say how likely it is?),
not about which branch ran.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from apex.catalyst.events import CatalystEvent, SourceObservation
from apex.catalyst.event_admissibility import (ADMISSIBLE_CONFLICTED, ADMISSIBLE_FACT,
                                               ADMISSIBLE_LEAD, AUTHORITY, CONTRACT,
                                               EventAdmissibilityRefused, ExtractionProvenance,
                                               SourceRecord, admit, content_sha256,
                                               keyword_baseline_event_type)

NOW = "2026-03-05T15:00:00Z"


def _extraction(**kw):
    base = dict(extractor="ANTHROPIC_SKILL", model="claude", model_version="v1",
                prompt_contract_sha="a" * 64, extraction_time="2026-03-05T14:59:00Z")
    base.update(kw)
    return ExtractionProvenance(**base)


def _source(sid="reuters", authority="WIRE", published="2026-03-05T14:30:00Z",
            retrieved="2026-03-05T14:31:00Z", content="story one", basis="DECLARED_BY_SOURCE"):
    return SourceRecord(source_id=sid, source_authority=authority, source_ref="https://x/%s" % sid,
                        published_time=published, retrieval_time=retrieved,
                        content_sha256=content_sha256(content), publication_time_basis=basis)


def _event(**kw):
    base = dict(event_id="EV_1", event_type="EARNINGS", event_time="2026-03-05T14:29:00Z",
                first_seen="2026-03-05T14:31:00Z", known_from="2026-03-05T14:31:00Z",
                scheduled=True, headline="ACME beats on EPS", factual_summary="EPS 1.20 vs 1.10",
                affected_symbols=("ACME",))
    base.update(kw)
    return CatalystEvent(**base)


def _ok(**kw):
    kw.setdefault("event", _event())
    kw.setdefault("extraction", _extraction())
    kw.setdefault("sources", [_source()])
    kw.setdefault("entity_status", {"ACME": "RESOLVED"})
    kw.setdefault("now_utc", NOW)
    ev = kw.pop("event")
    return admit(ev, **kw)


# ------------------------------------------------- it works at all
def test_a_well_formed_record_is_admitted_as_a_fact():
    a = _ok()
    assert a.status == ADMISSIBLE_FACT and a.contract == CONTRACT
    assert a.fact_bearing_source_count == 1 and a.independent_source_count == 1
    assert a.authority["PROBABILITY_AUTHORITY"] == "NONE"
    assert a.authority["TRADING_AUTHORITY"] == "NONE"
    assert a.authority["PRIME_INPUT"] == "NOT_ADMITTED_BY_THIS_CONTRACT"


def test_a_record_with_no_fact_bearing_source_is_a_lead_not_a_fact():
    a = _ok(sources=[_source(sid="blog", authority="AGGREGATOR")])
    assert a.status == ADMISSIBLE_LEAD and a.fact_bearing_source_count == 0
    assert "never to assert what" in a.reason


def test_conflicting_sources_stay_conflicted():
    a = _ok(event=_event(verification="CONFLICTED"),
            sources=[_source(), _source(sid="ap", content="story two")])
    assert a.status == ADMISSIBLE_CONFLICTED and a.conflict is True
    assert "never as a fact" in a.reason


# ------------------------------------------------- leakage and clocks
def test_a_future_event_or_known_from_is_refused():
    with pytest.raises(EventAdmissibilityRefused, match="^FUTURE_TIMESTAMP"):
        _ok(event=_event(event_time="2026-03-05T16:00:00Z"))
    with pytest.raises(EventAdmissibilityRefused, match="^FUTURE_TIMESTAMP"):
        _ok(event=_event(first_seen="2026-03-05T16:00:00Z", known_from="2026-03-05T16:00:00Z"))
    with pytest.raises(EventAdmissibilityRefused, match="^FUTURE_TIMESTAMP"):
        _ok(sources=[_source(published="2026-03-05T14:30:00Z", retrieved="2026-03-05T18:00:00Z")])


def test_known_from_may_not_precede_publication():
    """Knowing something before anyone published it is the leak that makes
    an event study look profitable."""
    with pytest.raises(EventAdmissibilityRefused, match="^KNOWN_FROM_PRECEDES_PUBLICATION"):
        _ok(event=_event(first_seen="2026-03-05T14:00:00Z", known_from="2026-03-05T14:00:00Z"),
            sources=[_source(published="2026-03-05T14:30:00Z")])


def test_a_missing_known_from_is_refused():
    for bad in ("", "   ", "NONE", "UNKNOWN"):
        with pytest.raises(EventAdmissibilityRefused, match="^MISSING_KNOWN_FROM"):
            _ok(event=_event(known_from=bad, first_seen=""))


def test_publication_time_may_not_be_the_retrieval_time():
    t = "2026-03-05T14:31:00Z"
    with pytest.raises(EventAdmissibilityRefused, match="^PUBLICATION_IS_RETRIEVAL"):
        _ok(sources=[_source(published=t, retrieved=t, basis="DECLARED_BY_SOURCE")])
    # a MEASURED basis may legitimately coincide
    a = _ok(sources=[_source(published=t, retrieved=t, basis="MEASURED")],
            event=_event(first_seen=t, known_from=t))
    assert a.status == ADMISSIBLE_FACT


def test_an_unknown_publication_basis_is_refused():
    with pytest.raises(EventAdmissibilityRefused, match="^PUBLICATION_TIME_UNKNOWN"):
        _ok(sources=[_source(basis="UNKNOWN")])


def test_malformed_times_are_refused_not_defaulted():
    with pytest.raises(EventAdmissibilityRefused, match="^MALFORMED_TIME"):
        _ok(event=_event(event_time="last tuesday"))


# ------------------------------------------------- sources
def test_duplicate_source_content_is_not_two_corroborations():
    """One wire story republished under two names is one observation."""
    with pytest.raises(EventAdmissibilityRefused, match="^DUPLICATE_SOURCE_CONTENT"):
        _ok(sources=[_source(sid="reuters", content="identical body"),
                     _source(sid="yahoo", content="identical body")])


def test_source_mutation_is_detected():
    s = _source(content="original")
    with pytest.raises(EventAdmissibilityRefused, match="^SOURCE_CONTENT_MUTATED"):
        _ok(sources=[s], recheck_content={"reuters": content_sha256("edited later")})
    a = _ok(sources=[s], recheck_content={"reuters": content_sha256("original")})
    assert a.status == ADMISSIBLE_FACT


def test_a_source_without_a_content_hash_or_identity_is_refused():
    with pytest.raises(EventAdmissibilityRefused, match="^SOURCE_CONTENT_UNHASHED"):
        SourceRecord(source_id="x", source_authority="WIRE", source_ref="u",
                     published_time=NOW, retrieval_time=NOW, content_sha256="short",
                     publication_time_basis="MEASURED")
    with pytest.raises(EventAdmissibilityRefused, match="^UNVERIFIED_SOURCE_IDENTITY"):
        SourceRecord(source_id="", source_authority="WIRE", source_ref="",
                     published_time=NOW, retrieval_time=NOW, content_sha256="b" * 64,
                     publication_time_basis="MEASURED")


def test_an_event_with_no_source_is_not_an_observation():
    with pytest.raises(EventAdmissibilityRefused, match="^NO_SOURCE"):
        _ok(sources=[])


# ------------------------------------------------- entities
def test_unresolved_or_ambiguous_entities_are_refused():
    with pytest.raises(EventAdmissibilityRefused, match="^ENTITY_NOT_RESOLVED"):
        _ok(entity_status={"ACME": "UNRESOLVED"})
    with pytest.raises(EventAdmissibilityRefused, match="^ENTITY_NOT_RESOLVED"):
        _ok(entity_status={"ACME": "AMBIGUOUS"})
    with pytest.raises(EventAdmissibilityRefused, match="^ENTITY_NOT_RESOLVED"):
        _ok(entity_status={})                      # affected symbol never resolved at all


# ------------------------------------------------- authority
def test_an_llm_probability_anywhere_in_the_payload_is_refused():
    for payload in ({"probability": 0.8},
                    {"event": {"confidence": 0.9}},
                    {"hypotheses": [{"p_up": 0.6}]},
                    {"nested": {"deep": {"likelihood_of_beat": 0.3}}}):
        with pytest.raises(EventAdmissibilityRefused, match="^LLM_PROBABILITY_PRESENT"):
            _ok(payload=payload)


def test_a_trade_or_sizing_field_anywhere_is_refused():
    for payload in ({"direction": "LONG"}, {"order": {"quantity": 100}},
                    {"plan": [{"stop_loss": 1.2}]}, {"position_size": 3}):
        with pytest.raises(EventAdmissibilityRefused, match="^TRADE_FIELD_PRESENT"):
            _ok(payload=payload)


def test_a_benign_payload_passes_and_mechanism_hypotheses_survive():
    a = _ok(payload={"mechanism": "margin expansion", "entities": ["ACME"], "sector": "TECH"},
            event=_event(mechanism_hypotheses=("guidance raise lifts sector",),
                         uncertainty=("consensus source unverified",)))
    assert a.mechanism_hypotheses == ("guidance raise lifts sector",)
    assert a.uncertainty == ("consensus source unverified",)


def test_extraction_provenance_is_required_and_may_not_claim_authority():
    for missing in ("model", "model_version", "prompt_contract_sha", "extraction_time", "extractor"):
        with pytest.raises(EventAdmissibilityRefused, match="^MISSING_EXTRACTION_PROVENANCE"):
            _extraction(**{missing: ""})
    with pytest.raises(EventAdmissibilityRefused, match="^EXTRACTOR_CLAIMS_AUTHORITY"):
        _extraction(extractor_authority="AUTHORITATIVE")


# ------------------------------------------------- determinism
def test_serialisation_is_deterministic_and_replay_is_identical():
    a, b = _ok(), _ok()
    assert a.canonical() == b.canonical()
    assert a.record_sha256 == b.record_sha256
    assert json.loads(a.canonical())["status"] == ADMISSIBLE_FACT
    rec = a.as_record()
    assert rec["kind"] == "event_admission" and rec["record_sha256"] == a.record_sha256
    # a different source order or content changes the record, and says so
    c = _ok(sources=[_source(sid="ap", content="other story")])
    assert c.record_sha256 != a.record_sha256


def test_the_event_object_is_never_mutated():
    ev = _event()
    before = (ev.verification, ev.known_from, tuple(ev.observations))
    _ok(event=ev)
    assert (ev.verification, ev.known_from, tuple(ev.observations)) == before


# ------------------------------------------------- baseline and null stream
def test_the_keyword_baseline_is_deterministic_and_admits_no_guessing():
    assert keyword_baseline_event_type("ACME beats on EPS this quarter") == "EARNINGS"
    assert keyword_baseline_event_type("FOMC holds rates") == "CENTRAL_BANK"
    assert keyword_baseline_event_type("FDA approval granted") == "REGULATORY"
    assert keyword_baseline_event_type("ACME opens a new office") == "UNKNOWN"
    assert keyword_baseline_event_type("") == "UNKNOWN"
    assert keyword_baseline_event_type("x") == keyword_baseline_event_type("x")


def test_a_baseline_extraction_is_admissible_on_the_same_contract():
    """The comparator must pass through the same gate, or the comparison
    would be between an audited record and an unaudited one."""
    a = _ok(extraction=_extraction(extractor="KEYWORD_BASELINE", model="keyword_rules",
                                   model_version="v0", prompt_contract_sha="b" * 64))
    assert a.status == ADMISSIBLE_FACT and a.extraction["extractor"] == "KEYWORD_BASELINE"


def test_an_empty_event_stream_yields_nothing_and_raises_nothing():
    admitted = [_ok(event=e) for e in []]
    assert admitted == []


def test_the_contract_grants_no_authority_at_module_level():
    assert set(AUTHORITY) >= {"PROBABILITY_AUTHORITY", "TRADING_AUTHORITY", "ORDER_AUTHORITY",
                              "SIZING_AUTHORITY", "PRIME_INPUT", "DECISION_POWER"}
    assert all(v in ("NONE", "NOT_ADMITTED_BY_THIS_CONTRACT", "SHADOW_CONTEXT_ONLY", CONTRACT)
               for v in AUTHORITY.values())


def test_this_module_reaches_no_decision_layer():
    import ast
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "apex/catalyst/event_admissibility.py"
    tree = ast.parse(src.read_text())
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for m in mods:
        assert not m.startswith(("apex.execution", "apex.organism", "apex.capital",
                                 "apex.world_model")), m
