"""Event-world archive: PIT fields, dedupe, malformed honesty, dormancy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apex.events.capture import known_accessions, parse_feed

FIXTURE = b"""<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>8-K - ACME CORP (0001234567) (Filer)</title>
  <link rel="alternate" href="https://www.sec.gov/Archives/x.htm"/>
  <summary>Item 2.02 Results of Operations</summary>
  <updated>2026-08-15T16:31:02-04:00</updated>
  <id>urn:tag:sec.gov,2008:accession-number=0001234567-26-000042</id>
</entry>
<entry>
  <title>8-K - BROKEN ENTRY</title>
  <id>urn:tag:sec.gov,2008:accession-number=0009999999-26-000001</id>
</entry>
</feed>"""


def test_parse_pit_fields_and_malformed_honesty():
    evs = parse_feed(FIXTURE, "2026-08-16T01:00:00+00:00")
    good = [e for e in evs if e["kind"] == "edgar_event"]
    assert len(good) == 1
    e = good[0]
    assert e["accession"] == "0001234567-26-000042"
    assert e["form_type"] == "8-K"
    assert "ACME" in e["company_raw"]
    assert e["event_time_utc"].startswith("2026-08-15 20:31:02")  # ET->UTC
    assert e["known_from_utc"] == "2026-08-16T01:00:00+00:00"
    assert e["decision_wiring"] == "NONE_DORMANT_ARCHIVE_ONLY"
    note = [e for e in evs if e["kind"] == "edgar_capture_note"]
    assert note and note[0]["malformed_entries_skipped"] == 1


def test_dedupe_by_accession(tmp_path):
    from nightly_pull import _chain_append
    led = tmp_path / "ev.jsonl"
    _chain_append(led, {"kind": "edgar_event", "accession": "A-1"})
    _chain_append(led, {"kind": "edgar_capture_note"})
    assert known_accessions(led) == {"A-1"}


def test_capture_once_idempotent(tmp_path):
    from apex.events.capture import capture_once

    class FakeClient:
        def _get(self, url):
            return FIXTURE
    led = tmp_path / "ev.jsonl"
    s1 = capture_once(FakeClient(), led)
    s2 = capture_once(FakeClient(), led)
    assert s1["new"] == 1 and s2["new"] == 0     # second poll adds nothing
    rows = [json.loads(x) for x in led.read_text().splitlines()]
    assert sum(r.get("kind") == "edgar_event" for r in rows) == 1
