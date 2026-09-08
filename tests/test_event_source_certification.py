"""EVENT_SOURCE_CERTIFICATION_V0 -- can this source say when APEX could have known?

Disposable JSONL fixtures only. No real event store is read, no market row is
touched, nothing is admitted. The assertions are about MEANING: is this
knowledge or hindsight, is this one event or two, was this the original
information set or a later correction.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("event_source_certify",
                                               REPO / "scripts/event_source_certify.py")
C = importlib.util.module_from_spec(_spec)
sys.modules["event_source_certify"] = C
_spec.loader.exec_module(C)
Refused = C.EventSourceRefused


def write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return p


def obs(**kw):
    base = dict(source="reuters", source_authority="WIRE", locator="https://x/1",
                published_time="2026-08-27T10:00:00+00:00",
                retrieved_time="2026-08-27T10:02:00+00:00",
                first_seen_time="2026-08-27T10:02:00+00:00",
                known_from="2026-08-27T10:02:00+00:00",
                raw_text_hash="a" * 64, title="a headline")
    base.update(kw)
    return base


def certify(tmp_path, rows, *, role=None, name="s.jsonl"):
    p = write(tmp_path, name, rows)
    cand = {"source_id": "fixture", "family": "news", "provider": "test",
            "location": str(p), "role": role or C.ROLE_OBSERVATION_STREAM}
    return C.classify(cand, C.scan_jsonl(p), True)


# ---------------------------------------------- timestamps and knowledge
def test_publication_time_missing_is_visible_in_the_field_inventory(tmp_path):
    cert = certify(tmp_path, [{k: v for k, v in obs().items() if k != "published_time"}])
    assert "published_time" not in cert["fields"]
    assert cert["fields"]["known_from"] == C.ADMISSIBLE


def test_publication_time_equal_to_retrieval_is_flagged_not_accepted(tmp_path):
    t = "2026-08-27T10:02:00+00:00"
    cert = certify(tmp_path, [obs(published_time=t, retrieved_time=t)])
    assert cert["fields"]["published_time"] == C.ADMISSIBLE_WITH_LIMITATIONS


def test_known_from_before_publication_makes_the_source_inadmissible(tmp_path):
    """Knowing it before it was published is hindsight wearing a timestamp."""
    cert = certify(tmp_path, [obs(published_time="2026-08-27T10:00:00+00:00",
                                  known_from="2026-08-27T09:00:00+00:00")])
    assert cert["status"] == C.NOT_ADMISSIBLE
    assert "before their publication time" in cert["reason"]


def test_an_event_date_without_a_publication_date_does_not_confer_history(tmp_path):
    """The governing rule: an old event_time with a recent known_from is a
    recent piece of knowledge about an old happening."""
    rows = [obs(published_time="2015-01-21T16:15:00-05:00",
                known_from="2026-08-27T10:02:00+00:00",
                first_seen_time="2026-08-27T10:02:00+00:00")]
    cert = certify(tmp_path, rows)
    assert cert["status"] == C.PROSPECTIVE_ONLY
    assert cert["coverage_start"] == "2026-08-27"
    gap = cert["event_date_versus_known_from"]
    assert gap["earliest_event_or_publication"] == "2015-01-21"
    assert gap["earliest_known_from"] == "2026-08-27"


def test_future_leakage_is_visible_as_coverage_beyond_now(tmp_path):
    cert = certify(tmp_path, [obs(published_time="2099-01-01T00:00:00+00:00")])
    assert cert["coverage_start"] == "2026-08-27"
    # the future publication is recorded, not silently accepted as knowledge
    assert cert["fields"]["published_time"] in (C.ADMISSIBLE, C.ADMISSIBLE_WITH_LIMITATIONS)
    e = C.assert_usable_for({"source_id": "f", "admission_status": C.PROSPECTIVE_ONLY,
                             "coverage_start": "2026-08-27", "coverage_end": "2026-09-04"},
                            purpose="PROSPECTIVE", window_start="2026-08-27", window_end="2026-09-04")
    assert e["usable"]


# ---------------------------------------------- timezone and DST
def test_timezone_and_dst_are_normalised_not_assumed():
    """Two spellings of the same instant must compare equal; a naive time is
    not silently treated as UTC-shifted local."""
    a, fa = C.parse_time("2026-03-08T14:30:00+00:00")
    b, fb = C.parse_time("2026-03-08T09:30:00-05:00")      # EST, same instant
    assert a == b and fa == fb == "ISO8601"
    # the same wall clock a day later is EDT, and is NOT the same instant
    c, _ = C.parse_time("2026-03-09T09:30:00-04:00")
    assert c != C.parse_time("2026-03-09T09:30:00-05:00")[0]
    d, fd = C.parse_time("Tue, 25 Aug 2026 18:00:00 GMT")
    assert fd == "RFC2822" and d.tzinfo is not None
    assert C.parse_time("last tuesday")[1] == "UNPARSEABLE"
    assert C.parse_time(None)[1] == "ABSENT"
    assert C.parse_time("NOT_ESTIMABLE")[1] == "SENTINEL"


def test_rfc2822_event_times_are_flagged_because_an_iso_consumer_refuses_them(tmp_path):
    """apex.catalyst.event_admissibility parses ISO only; a store of RFC-2822
    times is not malformed, but every record would be refused downstream."""
    rows = [{"event_time": "Tue, 25 Aug 2026 18:00:00 GMT", "known_from": "2026-08-27T10:00:00+00:00",
             "first_seen": "2026-08-27T10:00:00+00:00"}]
    cert = certify(tmp_path, rows, role=C.ROLE_EVENT_STREAM)
    assert cert["fields"]["event_time"] == C.ADMISSIBLE_WITH_LIMITATIONS
    from apex.catalyst.event_admissibility import _t, EventAdmissibilityRefused
    with pytest.raises(EventAdmissibilityRefused, match="^MALFORMED_TIME"):
        _t("Tue, 25 Aug 2026 18:00:00 GMT", "event_time")


# ---------------------------------------------- duplicates and conflicts
def test_the_same_story_from_two_providers_is_one_observation(tmp_path):
    rows = [obs(source="reuters", raw_text_hash="d" * 64),
            obs(source="yahoo", locator="https://y/1", raw_text_hash="d" * 64)]
    scan = C.scan_jsonl(write(tmp_path, "d.jsonl", rows))
    assert scan["duplicate_content_hashes"]["distinct_repeated"] == 1
    assert scan["sources"] == {"reuters": 1, "yahoo": 1}


def test_conflicting_values_from_two_sources_are_counted_not_collapsed(tmp_path):
    rows = [obs(source="a", raw_text_hash="1" * 64, title="EPS 1.20"),
            obs(source="b", locator="https://b/1", raw_text_hash="2" * 64, title="EPS 1.10")]
    scan = C.scan_jsonl(write(tmp_path, "c.jsonl", rows))
    assert scan["duplicate_content_hashes"]["distinct_repeated"] == 0
    assert scan["records"] == 2 and len(scan["sources"]) == 2


def test_source_content_mutation_shows_as_a_changed_file_hash(tmp_path):
    p = write(tmp_path, "m.jsonl", [obs()])
    before = C.sha256_of(p)
    p.write_text(p.read_text().replace("a headline", "an edited headline"))
    assert C.sha256_of(p) != before


def test_a_revised_record_is_not_the_original_information_set(tmp_path):
    """A correction published later carries a later known_from. Treating the
    revision as if it had been available at the original time is the classic
    restatement leak."""
    original = obs(raw_text_hash="1" * 64, title="CPI 3.1%",
                   published_time="2026-08-27T12:30:00+00:00",
                   known_from="2026-08-27T12:31:00+00:00",
                   first_seen_time="2026-08-27T12:31:00+00:00")
    revision = obs(raw_text_hash="2" * 64, title="CPI 3.2% (revised)",
                   published_time="2026-08-29T12:30:00+00:00",
                   known_from="2026-08-29T12:31:00+00:00",
                   first_seen_time="2026-08-29T12:31:00+00:00")
    scan = C.scan_jsonl(write(tmp_path, "r.jsonl", [original, revision]))
    assert scan["known_from_before_publication"] == 0
    kf = scan["coverage_by_time_field"]["known_from"]
    assert kf["min"][:10] == "2026-08-27" and kf["max"][:10] == "2026-08-29"
    # a revision that claims the ORIGINAL known_from is refused
    bad = dict(revision, known_from="2026-08-27T12:31:00+00:00")
    cert = certify(tmp_path, [original, bad], name="r2.jsonl")
    assert cert["status"] == C.NOT_ADMISSIBLE


# ---------------------------------------------- entities and adjustments
def test_entity_ambiguity_is_refused_by_the_existing_admissibility_gate():
    """Certification does not resolve entities; the gate refuses unresolved
    ones. This checks the two contracts meet."""
    from apex.catalyst.event_admissibility import EventAdmissibilityRefused
    from apex.catalyst.events import CatalystEvent
    ev = CatalystEvent(event_id="EV_x", event_type="EARNINGS",
                       event_time="2026-08-27T10:00:00+00:00",
                       first_seen="2026-08-27T10:02:00+00:00",
                       known_from="2026-08-27T10:02:00+00:00", scheduled=True,
                       headline="h", factual_summary="s", affected_symbols=("ACME",))
    from apex.catalyst.event_admissibility import ExtractionProvenance, SourceRecord, admit, content_sha256
    src = SourceRecord(source_id="reuters", source_authority="WIRE", source_ref="https://x/1",
                       published_time="2026-08-27T10:00:00+00:00",
                       retrieval_time="2026-08-27T10:02:00+00:00",
                       content_sha256=content_sha256("body"), publication_time_basis="DECLARED_BY_SOURCE")
    prov = ExtractionProvenance(extractor="KEYWORD_BASELINE", model="m", model_version="v",
                                prompt_contract_sha="a" * 64, extraction_time="2026-08-27T10:03:00+00:00")
    with pytest.raises(EventAdmissibilityRefused, match="^ENTITY_NOT_RESOLVED"):
        admit(ev, extraction=prov, sources=[src], entity_status={"ACME": "AMBIGUOUS"},
              now_utc="2026-08-27T11:00:00+00:00")


def test_a_back_adjusted_reference_row_is_pit_only_at_its_decision_date(tmp_path):
    """Universe membership decided as of a date is admissible AT that date.
    A later re-decision is a different row, not a correction of the first."""
    rows = [{"kind": "pit_membership", "member_month": "2016-05", "decided_asof": "2016-04-29",
             "rule": "top100", "symbols": ["A", "B"]},
            {"kind": "pit_membership", "member_month": "2016-06", "decided_asof": "2016-05-31",
             "rule": "top100", "symbols": ["A", "C"]}]
    cert = certify(tmp_path, rows, role=C.ROLE_PIT_REFERENCE, name="pit.jsonl")
    assert cert["status"] == C.ADMISSIBLE_WITH_LIMITATIONS
    assert cert["coverage_start"] == "2016-04-29" and cert["coverage_end"] == "2016-05-31"
    assert "NOT as an event stream" in cert["reason"]


# ---------------------------------------------- roles and refusal
def test_an_operational_log_is_not_a_failed_event_source(tmp_path):
    rows = [{"cycle_id": "c1", "sources_checked": 5, "failures": 0}]
    cert = certify(tmp_path, rows, role=C.ROLE_OPERATIONAL_LOG, name="cy.jsonl")
    assert cert["status"] == C.NOT_AN_EVENT_SOURCE
    assert "never meant to" in cert["reason"]


def test_an_absent_source_is_untraced_not_admissible():
    cert = C.classify({"source_id": "gone", "family": "sec_filings", "provider": "p",
                       "location": "/nope", "role": C.ROLE_EVENT_STREAM}, None, False)
    assert cert["status"] == C.UNTRACED and cert["fields"] == {}


@pytest.mark.parametrize("purpose", ["TRAINING", "VALIDATION", "EVALUATION"])
def test_a_prospective_only_source_is_refused_for_every_historical_purpose(purpose):
    entry = {"source_id": "apex_catalyst_events", "admission_status": C.PROSPECTIVE_ONLY,
             "coverage_start": "2026-08-27", "coverage_end": "2026-09-04",
             "reason": "capture began 2026-08-27"}
    with pytest.raises(Refused, match="^PROSPECTIVE_ONLY_SOURCE"):
        C.assert_usable_for(entry, purpose=purpose, window_start="2016-01-04",
                            window_end="2021-12-31")
    ok = C.assert_usable_for(entry, purpose="PROSPECTIVE", window_start="2026-08-27",
                             window_end="2026-09-04")
    assert ok["usable"] and ok["status"] == C.PROSPECTIVE_ONLY


def test_window_outside_coverage_and_unusable_statuses_are_refused():
    entry = {"source_id": "pit", "admission_status": C.ADMISSIBLE_WITH_LIMITATIONS,
             "coverage_start": "2016-04-29", "coverage_end": "2026-07-31", "reason": "r"}
    ok = C.assert_usable_for(entry, purpose="TRAINING", window_start="2016-05-01",
                             window_end="2021-12-31")
    assert ok["usable"]
    with pytest.raises(Refused, match="^WINDOW_OUTSIDE_COVERAGE"):
        C.assert_usable_for(entry, purpose="TRAINING", window_start="2015-01-01",
                            window_end="2021-12-31")
    for bad in (C.NOT_ADMISSIBLE, C.UNTRACED, C.NOT_AN_EVENT_SOURCE):
        with pytest.raises(Refused, match="^SOURCE_NOT_ADMISSIBLE"):
            C.assert_usable_for({"source_id": "x", "admission_status": bad,
                                 "coverage_start": "2016-01-01", "coverage_end": "2026-01-01"},
                                purpose="TRAINING", window_start="2016-01-02",
                                window_end="2025-01-01")
    with pytest.raises(Refused, match="^UNKNOWN_PURPOSE"):
        C.assert_usable_for(entry, purpose="TRADING", window_start="2016-05-01",
                            window_end="2021-12-31")


def test_certification_admits_nothing_and_touches_no_market_row():
    src = (REPO / "scripts/event_source_certify.py").read_text()
    for forbidden in ("observable_rows", "load_session", "economic", "place_order",
                      "boundary.admit", "verify_decision"):
        assert forbidden not in src
    assert "admits nothing" in src
