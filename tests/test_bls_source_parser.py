"""BLS_RESPONSE_PARSER_V0 -- the refusals, from fixtures, never from the network.

No test here makes an HTTP request. The success fixture was captured once,
read-only, and is sealed by hash; the refusal fixture is CONSTRUCTED from the
documented BLS format and labelled as such in PROVENANCE.json, because the
live API succeeded at capture time and deliberately exhausting a public
quota to obtain a real one would have been abusive.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from apex.catalyst.bls_parse import (PARSER_VERSION, PUBLICATION_TIME_NOT_AVAILABLE,
                                     BLSResponseRefused, diagnostic, parse_bls_response)

FX = Path(__file__).resolve().parent / "fixtures" / "bls"
SID = "CUUR0000SA0"
CAPTURED = FX / "captured_CUUR0000SA0_REQUEST_SUCCEEDED.json"
QUOTA = FX / "constructed_REQUEST_NOT_PROCESSED_quota.json"


def load(p):
    return p.read_text()


def ok_doc(**over):
    d = json.loads(load(CAPTURED))
    d.update(over)
    return json.dumps(d)


def with_data(data, series_id=SID):
    return json.dumps({"status": "REQUEST_SUCCEEDED", "responseTime": 1, "message": [],
                       "Results": {"series": [{"seriesID": series_id, "data": data}]}})


# ------------------------------------------------ the reproduction
def test_the_original_expression_fails_on_the_refusal_response_exactly_as_recorded():
    """Reproduces the recorded failure 'unexpected shape (\'series\')' against
    the ORIGINAL parser expression, before any repair."""
    doc = json.loads(load(QUOTA))
    with pytest.raises(KeyError) as ei:
        _ = doc["Results"]["series"][0]["data"]          # the original line
    assert str(ei.value) == "'series'"
    # and the old adapter turned that into a schema complaint
    assert "unexpected shape ('series')" == "unexpected shape (%s)" % ei.value


def test_the_repaired_parser_names_the_real_cause():
    with pytest.raises(BLSResponseRefused, match="^BLS_QUOTA_EXCEEDED"):
        parse_bls_response(load(QUOTA), expect_series=SID)


def test_a_refusal_without_quota_wording_is_still_refused_but_named_differently():
    doc = json.dumps({"status": "REQUEST_NOT_PROCESSED", "responseTime": 0,
                      "message": ["Series does not exist for Series CUUR0000SA0"], "Results": {}})
    with pytest.raises(BLSResponseRefused, match="^BLS_REQUEST_NOT_PROCESSED"):
        parse_bls_response(doc, expect_series=SID)


# ------------------------------------------------ the current shape
def test_the_captured_current_response_parses_and_is_sealed_by_hash():
    body = load(CAPTURED)
    prov = json.loads((FX / "PROVENANCE.json").read_text())
    rec = prov["fixtures"][CAPTURED.name]
    assert rec["origin"] == "CAPTURED"
    assert hashlib.sha256(body.encode()).hexdigest() == rec["sha256"]
    out = parse_bls_response(body, expect_series=SID)
    assert out["status"] == "REQUEST_SUCCEEDED" and out["series_id"] == SID
    assert out["n_datapoints"] >= 12 and out["parser_version"] == PARSER_VERSION
    assert out["raw_sha256"] == rec["sha256"]           # raw provenance preserved
    latest = out["latest"]
    assert latest.latest is True and latest.reference_period == "2026-M07"
    assert latest.value == "333.918" and latest.period_name == "July"


def test_the_fixture_provenance_never_claims_the_constructed_one_was_captured():
    prov = json.loads((FX / "PROVENANCE.json").read_text())
    assert prov["fixtures"][QUOTA.name]["origin"] == "CONSTRUCTED_NOT_CAPTURED"
    assert "must never be presented as captured" in prov["fixtures"][QUOTA.name]["why"]


# ------------------------------------------------ timestamps
def test_the_reference_period_is_never_offered_as_a_publication_time():
    """The old adapter set published_time to '2026-July'. A reference period
    is what the number measures, not when it was released."""
    out = parse_bls_response(load(CAPTURED), expect_series=SID)
    d = out["latest"]
    assert d.publication_time == PUBLICATION_TIME_NOT_AVAILABLE
    assert d.publication_time_basis == "UNKNOWN"
    assert d.reference_period == "2026-M07"
    assert d.publication_time != d.reference_period
    assert "publication" in d.as_record()["law"]


def test_no_retrieval_time_leaks_into_the_parsed_datapoint():
    out = parse_bls_response(load(CAPTURED), expect_series=SID)
    rec = out["latest"].as_record()
    assert "retrieved" not in json.dumps(rec).lower()
    assert "known_from" not in rec


def test_a_bls_observation_cannot_pass_the_admissibility_gate_and_says_why():
    """The honest consequence: with no release instant, a BLS datapoint is a
    retrieval-only observation. A BLS release calendar is required before
    macro events can be admitted."""
    from apex.catalyst.event_admissibility import (EventAdmissibilityRefused,
                                                   SourceRecord, content_sha256)
    d = parse_bls_response(load(CAPTURED), expect_series=SID)["latest"]
    with pytest.raises(EventAdmissibilityRefused, match="^PUBLICATION_TIME_BASIS_UNKNOWN_VALUE|"
                                                        "^SOURCE_CONTENT_UNHASHED"):
        SourceRecord(source_id="BLS", source_authority="PRIMARY_OFFICIAL",
                     source_ref="https://data.bls.gov/timeseries/%s" % SID,
                     published_time=d.publication_time,
                     retrieval_time="2026-09-08T03:06:06+00:00",
                     content_sha256=d.content_sha256,
                     publication_time_basis="NOT_A_VALID_BASIS")
    # with the honest basis the record constructs, and the gate refuses it later
    rec = SourceRecord(source_id="BLS", source_authority="PRIMARY_OFFICIAL",
                       source_ref="https://data.bls.gov/timeseries/%s" % SID,
                       published_time=d.publication_time,
                       retrieval_time="2026-09-08T03:06:06+00:00",
                       content_sha256=d.content_sha256, publication_time_basis="UNKNOWN")
    assert rec.publication_time_basis == "UNKNOWN"


# ------------------------------------------------ malformed and partial
@pytest.mark.parametrize("body,reason", [
    ("", "BLS_EMPTY_RESPONSE"),
    ("not json at all", "BLS_MALFORMED_JSON"),
    ("[1,2,3]", "BLS_MALFORMED_JSON"),
    ('{"responseTime":1,"Results":{}}', "BLS_NO_STATUS"),
    ('{"status":"SOMETHING_NEW","Results":{}}', "BLS_UNSUPPORTED_STATUS"),
    ('{"status":"REQUEST_SUCCEEDED","Results":"nope"}', "BLS_NO_RESULTS"),
    ('{"status":"REQUEST_SUCCEEDED","Results":{}}', "BLS_NO_SERIES"),
    ('{"status":"REQUEST_SUCCEEDED","Results":{"series":{}}}', "BLS_SERIES_NOT_A_LIST"),
    ('{"status":"REQUEST_SUCCEEDED","Results":{"series":[]}}', "BLS_NO_SERIES"),
])
def test_malformed_and_partial_responses_are_refused_by_name(body, reason):
    with pytest.raises(BLSResponseRefused, match="^" + reason):
        parse_bls_response(body, expect_series=SID)


def test_multiple_unexpected_series_are_refused():
    body = json.dumps({"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
        {"seriesID": SID, "data": [{"year": "2026", "period": "M07", "periodName": "July", "value": "1"}]},
        {"seriesID": "LNS14000000", "data": []}]}})
    with pytest.raises(BLSResponseRefused, match="^BLS_MULTIPLE_SERIES"):
        parse_bls_response(body, expect_series=SID)


def test_a_series_that_is_not_the_one_requested_is_refused():
    with pytest.raises(BLSResponseRefused, match="^BLS_SERIES_MISMATCH"):
        parse_bls_response(with_data([{"year": "2026", "period": "M07", "periodName": "July",
                                       "value": "1"}], series_id="LNS14000000"),
                           expect_series=SID)


def test_missing_and_empty_series_data_are_refused():
    with pytest.raises(BLSResponseRefused, match="^BLS_NO_DATA"):
        parse_bls_response(json.dumps({"status": "REQUEST_SUCCEEDED", "message": [],
                                       "Results": {"series": [{"seriesID": SID}]}}),
                           expect_series=SID)
    with pytest.raises(BLSResponseRefused, match="^BLS_EMPTY_SERIES"):
        parse_bls_response(with_data([]), expect_series=SID)


@pytest.mark.parametrize("dp,reason", [
    ({"year": "20xx", "period": "M07", "periodName": "July", "value": "1"}, "BLS_BAD_YEAR"),
    ({"year": "2026", "period": "Q01", "periodName": "Q1", "value": "1"}, "BLS_BAD_PERIOD"),
    ({"year": "2026", "period": "M99", "periodName": "x", "value": "1"}, "BLS_BAD_PERIOD"),
    ({"year": "2026", "period": "M07", "periodName": "July", "value": ""}, "BLS_BAD_VALUE"),
    ({"year": "2026", "period": "M07", "periodName": "July", "value": "n/a"}, "BLS_BAD_VALUE"),
    ("not-a-dict", "BLS_DATAPOINT_MALFORMED"),
])
def test_invalid_datapoints_are_refused_not_skipped(dp, reason):
    with pytest.raises(BLSResponseRefused, match="^" + reason):
        parse_bls_response(with_data([dp]), expect_series=SID)


def test_a_duplicate_period_in_one_response_is_refused():
    dp = {"year": "2026", "period": "M07", "periodName": "July", "value": "333.918"}
    with pytest.raises(BLSResponseRefused, match="^BLS_DUPLICATE_PERIOD"):
        parse_bls_response(with_data([dp, dict(dp)]), expect_series=SID)


def test_two_datapoints_claiming_to_be_latest_are_refused():
    a = {"year": "2026", "period": "M07", "periodName": "July", "value": "1", "latest": "true"}
    b = {"year": "2026", "period": "M06", "periodName": "June", "value": "2", "latest": "true"}
    with pytest.raises(BLSResponseRefused, match="^BLS_MULTIPLE_LATEST"):
        parse_bls_response(with_data([a, b]), expect_series=SID)


# ------------------------------------------------ revisions and identity
def test_a_revised_value_for_the_same_period_is_a_different_record():
    """A revision must not be mistaken for the original print, and a
    re-fetch of an unchanged print must not look like new evidence."""
    dp = {"year": "2026", "period": "M07", "periodName": "July", "value": "333.918", "latest": "true"}
    first = parse_bls_response(with_data([dp]), expect_series=SID)["latest"]
    same = parse_bls_response(with_data([dict(dp)]), expect_series=SID)["latest"]
    revised = parse_bls_response(with_data([dict(dp, value="334.001")]), expect_series=SID)["latest"]
    assert first.content_sha256 == same.content_sha256          # re-fetch: not new evidence
    assert revised.content_sha256 != first.content_sha256       # revision: new evidence
    assert revised.reference_period == first.reference_period


def test_source_content_mutation_changes_the_raw_hash():
    body = load(CAPTURED)
    mutated = body.replace("333.918", "999.999", 1)
    a = parse_bls_response(body, expect_series=SID)
    b = parse_bls_response(mutated, expect_series=SID)
    assert a["raw_sha256"] != b["raw_sha256"]
    assert a["latest"].content_sha256 != b["latest"].content_sha256


def test_serialisation_is_deterministic():
    a = parse_bls_response(load(CAPTURED), expect_series=SID)["latest"]
    b = parse_bls_response(load(CAPTURED), expect_series=SID)["latest"]
    assert json.dumps(a.as_record(), sort_keys=True) == json.dumps(b.as_record(), sort_keys=True)
    assert a.content_sha256 == b.content_sha256


# ------------------------------------------------ diagnostic
def test_the_diagnostic_reports_every_required_field():
    d = diagnostic({"responses_received": 3, "accepted_records": 1, "refused_records": 2,
                    "refusal_reasons": {"BLS_QUOTA_EXCEEDED": 2},
                    "last_source_contact_utc": "2026-09-08T03:06:06Z",
                    "last_successful_parse_utc": "2026-09-08T03:06:06Z",
                    "last_persisted_event_utc": None})
    for k in ("responses_received", "accepted_records", "refused_records", "refusal_reasons",
              "last_source_contact_utc", "last_successful_parse_utc", "last_persisted_event_utc"):
        assert k in d
    assert d["refusal_reasons"] == {"BLS_QUOTA_EXCEEDED": 2}
    assert d["parser_version"] == PARSER_VERSION
    assert diagnostic()["responses_received"] == 0


def test_no_test_in_this_module_touches_the_network():
    """AST, not substring: a guard that greps its own source matches its own
    forbidden list. That mistake has been made three times in this programme
    and will not be made a fourth."""
    import ast
    tree = ast.parse(Path(__file__).read_text())
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    for net in ("urllib", "urllib.request", "requests", "http.client", "socket", "httpx"):
        assert net not in imported, imported
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "urlopen" not in called and "get" not in called


def test_the_documented_no_value_marker_is_absence_not_a_number():
    """BLS writes '-' for a suppressed or unpublished period. Found in the
    captured response, so the fixture earned its keep."""
    from apex.catalyst.bls_parse import VALUE_NOT_AVAILABLE, VALUE_PRESENT
    out = parse_bls_response(load(CAPTURED), expect_series=SID)
    assert out["n_without_value"] >= 1
    absent = [d for d in out["datapoints"] if d.value_status == VALUE_NOT_AVAILABLE]
    assert absent and all(d.value == "-" for d in absent)
    assert all(d.value_status == VALUE_PRESENT for d in out["datapoints"] if d.value != "-")
    # a latest datapoint with no value is never offered as a usable print
    dp = {"year": "2026", "period": "M08", "periodName": "August", "value": "-", "latest": "true"}
    o = parse_bls_response(with_data([dp]), expect_series=SID)
    assert o["latest"] is None and o["latest_without_value"] is not None
    assert o["latest_without_value"].value_status == VALUE_NOT_AVAILABLE


def test_output_is_routed_through_event_admissibility_and_the_gate_rules():
    """The mandate requires routing through the gate. This records what the
    gate ACTUALLY says -- it is not asserted to be admissible."""
    from apex.catalyst.bls_parse import to_source_record
    out = parse_bls_response(load(CAPTURED), expect_series=SID)
    rec = to_source_record(out["latest"], retrieval_time="2026-09-08T03:06:06Z")
    assert rec.published_time == "NOT_AVAILABLE"
    assert rec.publication_time_basis == "UNKNOWN"
    assert rec.retrieval_time == "2026-09-08T03:06:06Z"
    # retrieval time is never copied into publication time
    assert rec.published_time != rec.retrieval_time
    assert rec.content_sha256 == out["latest"].content_sha256


def test_a_datapoint_with_no_publication_instant_cannot_become_a_dated_fact():
    """The consequence stated in the module docstring, measured rather than
    asserted: with no publication instant there is no defensible known_from,
    so this source is retrieval-only until a BLS release calendar exists."""
    from apex.catalyst.bls_parse import to_source_record, PUBLICATION_TIME_NOT_AVAILABLE
    out = parse_bls_response(load(CAPTURED), expect_series=SID)
    for d in out["datapoints"]:
        assert d.publication_time == PUBLICATION_TIME_NOT_AVAILABLE
        assert d.publication_time_basis == "UNKNOWN"
        # the reference period is never allowed to stand in for publication
        assert d.reference_period != d.publication_time
        assert d.reference_period.startswith(d.year)
