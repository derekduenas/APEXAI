"""BLS_RESPONSE_PARSER_V0 -- read what the provider actually said.

WHAT WENT WRONG
`fetch_bls` did `json.loads(body)["Results"]["series"][0]["data"]` inside a
try/except that reported every failure as "unexpected shape". The BLS v2
API answers a refused request with a perfectly well-formed document:

    {"status": "REQUEST_NOT_PROCESSED", "responseTime": 0,
     "message": ["...daily threshold..."], "Results": {}}

`Results` is present and empty, so the lookup raises KeyError('series') and
APEX recorded a SCHEMA problem for what was actually a QUOTA problem. The
provider had explained itself in `status` and `message`, and the adapter
never read either field. Measured on this host: 8-9 successful cycles per
day, every day, then failure for the rest of the day -- three series times
eight cycles is 24 requests against an unregistered daily allowance of 25.

WHAT THIS PARSER DOES
Reads `status` first, then `message`, then the payload. Every outcome is a
named refusal; nothing is guessed and nothing unknown is accepted.

TIMESTAMPS, AND A DEFECT THIS FIXES
The old adapter set `published_time` to the reference period label -- the
string "2026-July". A reference period is what the number MEASURES, not when
it was PUBLISHED. This endpoint carries no release timestamp at all, so
publication time is NOT_AVAILABLE and says so; the period travels separately
as `reference_period`. Retrieval time is never promoted into publication
time, and known_from stays retrieval time.

A consequence, stated rather than hidden: an observation with no publication
time cannot pass apex.catalyst.event_admissibility, which refuses
PUBLICATION_TIME_UNKNOWN. BLS datapoints are therefore retrieval-only
observations until a BLS release calendar supplies real release instants.
That is a data-acquisition finding, not something to paper over.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

PARSER_VERSION = "BLS_RESPONSE_PARSER_V0"

# The only response variants this parser will act on. BLS documents both.
STATUS_SUCCEEDED = "REQUEST_SUCCEEDED"
STATUS_NOT_PROCESSED = "REQUEST_NOT_PROCESSED"
SUPPORTED_STATUSES = (STATUS_SUCCEEDED, STATUS_NOT_PROCESSED)

PUBLICATION_TIME_NOT_AVAILABLE = "NOT_AVAILABLE"
# "M01".."M12" are months; M13 is an annual average, which is not a release.
_PERIOD_RX = re.compile(r"^M(0[1-9]|1[0-3])$")
_YEAR_RX = re.compile(r"^(19|20)\d{2}$")
_VALUE_RX = re.compile(r"^-?\d+(\.\d+)?$")
# BLS writes a bare "-" for a period that exists but whose value is not
# available (suppressed, or not yet published). It is a DOCUMENTED absence,
# not a malformed field -- found in the captured response at index 9 -- and
# it must never be read as a number or as a release.
NO_VALUE_MARKER = "-"
VALUE_PRESENT, VALUE_NOT_AVAILABLE = "PRESENT", "NOT_AVAILABLE_MARKER"

# Quota exhaustion is the one refusal an operator must be able to act on, so
# it gets its own reason rather than being folded into a generic failure.
_QUOTA_HINTS = ("threshold", "daily limit", "request limit", "exceeded")


class BLSResponseRefused(RuntimeError):
    """The response was read and refused. Named reason, never a guess."""


@dataclass(frozen=True)
class BLSDatapoint:
    """One released statistic, with its clocks kept apart."""
    series_id: str
    year: str
    period: str                       # "M07"
    period_name: str                  # "July"
    value: str                        # kept as the provider's string
    reference_period: str             # "2026-M07" -- what it MEASURES
    latest: bool
    value_status: str = VALUE_PRESENT
    publication_time: str = PUBLICATION_TIME_NOT_AVAILABLE
    publication_time_basis: str = "UNKNOWN"
    footnotes: tuple = ()
    parser_version: str = PARSER_VERSION

    @property
    def content_sha256(self) -> str:
        """Content identity of the datapoint itself, independent of when it
        was fetched -- so a re-fetch of an unchanged print is not new
        evidence, and a revision of the same period IS."""
        return hashlib.sha256(
            ("%s|%s|%s|%s" % (self.series_id, self.year, self.period, self.value)).encode()
        ).hexdigest()

    def as_record(self) -> dict:
        return {"kind": "bls_datapoint", "series_id": self.series_id,
                "reference_period": self.reference_period, "value": self.value,
                "value_status": self.value_status,
                "latest": self.latest, "publication_time": self.publication_time,
                "publication_time_basis": self.publication_time_basis,
                "content_sha256": self.content_sha256,
                "parser_version": self.parser_version,
                "law": "reference period is not publication time; retrieval time is neither"}


def _refuse(reason: str, detail: str = "") -> None:
    raise BLSResponseRefused("%s%s" % (reason, (": " + detail) if detail else ""))


def parse_bls_response(raw: bytes | str, *, expect_series: str) -> dict:
    """Parse one BLS v2 timeseries response for exactly one series.

    Returns {"datapoints": [...], "raw_sha256": ..., "status": ...}.
    Raises BLSResponseRefused on anything it is not documented to accept."""
    if raw is None or (isinstance(raw, (bytes, str)) and len(raw) == 0):
        _refuse("BLS_EMPTY_RESPONSE", "zero bytes from the provider")
    body = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    raw_sha = hashlib.sha256(body.encode()).hexdigest()
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as e:
        _refuse("BLS_MALFORMED_JSON", str(e)[:120])
    if not isinstance(doc, dict):
        _refuse("BLS_MALFORMED_JSON", "top level is %s, not an object" % type(doc).__name__)

    status = doc.get("status")
    if status is None:
        _refuse("BLS_NO_STATUS", "the provider always states a status; its absence is not a payload")
    if status not in SUPPORTED_STATUSES:
        _refuse("BLS_UNSUPPORTED_STATUS", "%r is not a documented variant (%s)"
                % (status, ", ".join(SUPPORTED_STATUSES)))
    messages = doc.get("message") or []
    if status == STATUS_NOT_PROCESSED:
        joined = " ".join(str(m) for m in messages).lower()
        if any(h in joined for h in _QUOTA_HINTS):
            _refuse("BLS_QUOTA_EXCEEDED", "; ".join(str(m) for m in messages)[:200]
                    or "provider refused without a message")
        _refuse("BLS_REQUEST_NOT_PROCESSED", "; ".join(str(m) for m in messages)[:200]
                or "provider refused without a message")

    results = doc.get("Results")
    if not isinstance(results, dict):
        _refuse("BLS_NO_RESULTS", "Results is %s" % type(results).__name__)
    if "series" not in results:
        _refuse("BLS_NO_SERIES", "REQUEST_SUCCEEDED but Results carries no series")
    series = results["series"]
    if not isinstance(series, list):
        _refuse("BLS_SERIES_NOT_A_LIST", type(series).__name__)
    if len(series) == 0:
        _refuse("BLS_NO_SERIES", "series list is empty")
    if len(series) > 1:
        _refuse("BLS_MULTIPLE_SERIES", "asked for %s, received %d series (%s)"
                % (expect_series, len(series),
                   ",".join(str(s.get("seriesID")) for s in series[:4])))
    s0 = series[0]
    if not isinstance(s0, dict):
        _refuse("BLS_SERIES_MALFORMED", type(s0).__name__)
    sid = s0.get("seriesID")
    if sid != expect_series:
        _refuse("BLS_SERIES_MISMATCH", "asked for %s, received %r" % (expect_series, sid))
    data = s0.get("data")
    if data is None:
        _refuse("BLS_NO_DATA", "series %s carries no data array" % sid)
    if not isinstance(data, list):
        _refuse("BLS_DATA_NOT_A_LIST", type(data).__name__)
    if not data:
        _refuse("BLS_EMPTY_SERIES", "series %s returned zero datapoints" % sid)

    points, seen = [], set()
    for i, d in enumerate(data):
        if not isinstance(d, dict):
            _refuse("BLS_DATAPOINT_MALFORMED", "index %d is %s" % (i, type(d).__name__))
        year, period = str(d.get("year", "")), str(d.get("period", ""))
        value, pname = str(d.get("value", "")), str(d.get("periodName", ""))
        if not _YEAR_RX.match(year):
            _refuse("BLS_BAD_YEAR", "%r at index %d" % (year, i))
        if not _PERIOD_RX.match(period):
            _refuse("BLS_BAD_PERIOD", "%r at index %d (only M01-M13 are documented)" % (period, i))
        if value == NO_VALUE_MARKER:
            value_status = VALUE_NOT_AVAILABLE
        elif _VALUE_RX.match(value):
            value_status = VALUE_PRESENT
        else:
            _refuse("BLS_BAD_VALUE", "%r at index %d" % (value, i))
        key = (year, period)
        if key in seen:
            _refuse("BLS_DUPLICATE_PERIOD", "%s %s appears twice; the provider is not "
                                            "supposed to repeat a period in one response"
                    % (year, period))
        seen.add(key)
        points.append(BLSDatapoint(
            series_id=sid, year=year, period=period, period_name=pname, value=value,
            reference_period="%s-%s" % (year, period),
            latest=str(d.get("latest", "")).lower() == "true", value_status=value_status,
            footnotes=tuple(sorted(
                str(f.get("text")) for f in (d.get("footnotes") or []) if isinstance(f, dict) and f.get("text")))))
    latest = [p for p in points if p.latest]
    if len(latest) > 1:
        _refuse("BLS_MULTIPLE_LATEST", "%d datapoints claim to be the latest" % len(latest))
    top = latest[0] if latest else None
    # a period marked latest but carrying no value is a real state, and it is
    # NOT a usable print: the caller is handed it separately so it can never
    # be mistaken for a released number
    usable = top if (top is not None and top.value_status == VALUE_PRESENT) else None
    return {"parser_version": PARSER_VERSION, "status": status, "series_id": sid,
            "raw_sha256": raw_sha, "datapoints": points,
            "latest": usable, "latest_without_value": top if usable is None else None,
            "n_datapoints": len(points),
            "n_without_value": sum(1 for p in points if p.value_status == VALUE_NOT_AVAILABLE),
            "provider_messages": [str(m) for m in messages]}


def diagnostic(counters: dict | None = None) -> dict:
    """The shape of the per-source health record this parser can support.

    Kept here rather than in the service so a caller can build it without
    importing the network layer."""
    c = dict(counters or {})
    return {"kind": "bls_source_diagnostic", "parser_version": PARSER_VERSION,
            "responses_received": c.get("responses_received", 0),
            "accepted_records": c.get("accepted_records", 0),
            "refused_records": c.get("refused_records", 0),
            "refusal_reasons": c.get("refusal_reasons", {}),
            "last_source_contact_utc": c.get("last_source_contact_utc"),
            "last_successful_parse_utc": c.get("last_successful_parse_utc"),
            "last_persisted_event_utc": c.get("last_persisted_event_utc"),
            "note": "a refused response is a measured state, not a silence"}


def to_source_record(d: "BLSDatapoint", *, retrieval_time: str):
    """Hand a parsed datapoint to the admissibility gate in the gate's own
    vocabulary. Nothing is invented on the way: the datapoint has no
    publication instant, so the record says so and lets the gate rule.

    Kept as a function returning the gate's SourceRecord rather than a second
    event model -- APEX already has one CatalystEvent and will not grow a
    rival."""
    from apex.catalyst.event_admissibility import SourceRecord
    return SourceRecord(
        source_id="BLS",
        source_authority="PRIMARY_OFFICIAL",
        source_ref="https://data.bls.gov/timeseries/%s" % d.series_id,
        published_time=d.publication_time,          # NOT_AVAILABLE, honestly
        retrieval_time=retrieval_time,              # never promoted upward
        content_sha256=d.content_sha256,
        publication_time_basis=d.publication_time_basis)
