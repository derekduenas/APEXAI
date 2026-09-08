#!/usr/bin/env python3
"""EVENT_SOURCE_CERTIFICATION_V0 -- can any event source answer WHEN APEX COULD HAVE KNOWN?

Read-only. It opens event stores, measures their timestamp semantics, and
classifies each source and field. It admits nothing, runs no experiment,
computes no feature, and reads no market price row.

THE GOVERNING RULE
An event is not historically admissible because its event date is known. It
is admissible only if some field establishes when APEX could have known it.
A store whose earliest record is the day capture was switched on has no
history, however many events it holds since.

    python scripts/event_source_certify.py <outdir>
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

CONTRACT = "EVENT_SOURCE_CERTIFICATION_V0"

ADMISSIBLE = "ADMISSIBLE"
ADMISSIBLE_WITH_LIMITATIONS = "ADMISSIBLE_WITH_LIMITATIONS"
PROSPECTIVE_ONLY = "PROSPECTIVE_ONLY"
NOT_ADMISSIBLE = "NOT_ADMISSIBLE"
UNTRACED = "UNTRACED"
NOT_AN_EVENT_SOURCE = "NOT_AN_EVENT_SOURCE"

# A store's ROLE decides which question to ask of it. Asking an operational
# log for a publication timestamp and then calling it inadmissible would
# blame a file for not being something it never claimed to be.
ROLE_EVENT_STREAM = "EVENT_STREAM"
ROLE_OBSERVATION_STREAM = "OBSERVATION_STREAM"
ROLE_OPERATIONAL_LOG = "OPERATIONAL_LOG"
ROLE_DATASET_MANIFEST = "DATASET_MANIFEST"
ROLE_PIT_REFERENCE = "PIT_REFERENCE"

# Fields that answer "when could APEX have known this?" for their role.
KNOWN_FROM_EQUIVALENT = ("known_from", "first_seen_time", "first_seen", "decided_asof")

# The families the brief asks about. Every one is listed even when nothing
# for it exists on this host: an absent source is a finding, not a gap in
# the report.
FAMILIES = {
    "scheduled_macro_releases": "FOMC/CPI/NFP style releases with a published calendar",
    "earnings_dates_and_releases": "per-issuer earnings timing and content",
    "sec_filings": "EDGAR 8-K/10-Q/10-K and friends",
    "corporate_actions": "splits, dividends, symbol changes",
    "analyst_revisions": "estimate and rating changes",
    "news": "wire and press coverage",
    "options_implied_events": "event timing implied by the option surface",
    "political_geopolitical": "policy and geopolitical events",
    "social_alternative": "social and alternative data",
}

CANDIDATES = [
    dict(source_id="apex_catalyst_events", family="news", provider="APEX Catalyst (own capture)",
         location="/apex-data/core/catalyst/events.jsonl", role=ROLE_EVENT_STREAM),
    dict(source_id="apex_catalyst_raw_observations", family="news", provider="APEX Catalyst (own capture)",
         location="/apex-data/core/catalyst/raw_observations.jsonl", role=ROLE_OBSERVATION_STREAM),
    dict(source_id="apex_catalyst_cycles", family="news", provider="APEX Catalyst (own capture)",
         location="/apex-data/core/catalyst/cycles.jsonl", role=ROLE_OPERATIONAL_LOG),
    dict(source_id="edgar_events_ledger", family="sec_filings", provider="SEC EDGAR via APEX event clock",
         location="results/events/edgar_events.jsonl", role=ROLE_EVENT_STREAM),
    dict(source_id="options_history_manifest", family="options_implied_events", provider="ThetaData via APEX acquisition",
         location="/apex-data/history-a/options_history/manifest.jsonl", role=ROLE_DATASET_MANIFEST),
    dict(source_id="etf_continuous_integrity", family="corporate_actions", provider="Alpaca SIP via APEX acquisition",
         location="/apex-data/history-b/etf_continuous/integrity.jsonl", role=ROLE_DATASET_MANIFEST),
    dict(source_id="pit_singlename_membership", family="corporate_actions", provider="APEX PIT universe build",
         location="/apex-data/history-b/pit_singlename/membership_v1.jsonl", role=ROLE_PIT_REFERENCE),
]

TIME_FIELDS = ("event_time", "published_time", "publication_time", "retrieved_time",
               "retrieval_time", "first_seen", "first_seen_time", "known_from",
               "acquired_at", "decided_asof")


def sha256_of(p: Path, limit=None) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(v):
    """ISO first, RFC-2822 second, and record which one worked. A store whose
    times are RFC-2822 is not malformed -- but a consumer that only speaks
    ISO will refuse every record, which is a real integration finding."""
    if v is None:
        return None, "ABSENT"
    s = str(v).strip()
    if not s or s.upper() in ("NONE", "UNKNOWN", "NOT_ESTIMABLE"):
        return None, "SENTINEL"
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)), "ISO8601"
    except ValueError:
        pass
    try:
        d = parsedate_to_datetime(s)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)), "RFC2822"
    except (TypeError, ValueError):
        return None, "UNPARSEABLE"


def scan_jsonl(path: Path, max_records=None) -> dict:
    """Field inventory, timestamp semantics, duplicates and coverage.
    Reads only structure and timestamps; no price row, no outcome."""
    fields, formats, n, bad = Counter(), Counter(), 0, 0
    times = {f: [] for f in TIME_FIELDS}
    content_hashes, event_ids, sources, authorities = Counter(), Counter(), Counter(), Counter()
    pub_eq_ret = 0
    pub_present = 0
    kf_before_pub = 0
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n += 1
            if max_records and n > max_records:
                n -= 1
                break
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            fields.update(d.keys())
            for f in TIME_FIELDS:
                if f in d:
                    t, fmt = parse_time(d[f])
                    formats["%s:%s" % (f, fmt)] += 1
                    if t:
                        times[f].append(t)
            for h in ("raw_text_hash", "content_sha256", "sha256", "entry_hash"):
                if d.get(h):
                    content_hashes[(h, d[h])] += 1
                    break
            if d.get("event_id"):
                event_ids[d["event_id"]] += 1
            if d.get("source"):
                sources[str(d["source"])[:60]] += 1
            if d.get("source_authority"):
                authorities[d["source_authority"]] += 1
            pt = d.get("published_time") or d.get("publication_time")
            rt = d.get("retrieved_time") or d.get("retrieval_time")
            if pt is not None:
                pub_present += 1
                if rt is not None and str(pt) == str(rt):
                    pub_eq_ret += 1
            kf, _ = parse_time(d.get("known_from"))
            pth, _ = parse_time(pt)
            if kf and pth and kf < pth:
                kf_before_pub += 1
    cov = {}
    for f, vals in times.items():
        if vals:
            cov[f] = {"n": len(vals), "min": min(vals).isoformat(), "max": max(vals).isoformat()}
    dupes = {"%s=%s" % (k[0], k[1][:16]): c for k, c in content_hashes.items() if c > 1}
    return {"records": n, "malformed_lines": bad,
            "fields": dict(fields.most_common()),
            "time_field_formats": dict(formats.most_common()),
            "coverage_by_time_field": cov,
            "duplicate_content_hashes": {"distinct_repeated": len(dupes), "examples": dict(list(dupes.items())[:5])},
            "repeated_event_ids": {k: v for k, v in event_ids.items() if v > 1},
            "sources": dict(sources.most_common(12)),
            "source_authorities": dict(authorities.most_common()),
            "publication_time_present": pub_present,
            "publication_equals_retrieval": pub_eq_ret,
            "known_from_before_publication": kf_before_pub}


def classify(cand: dict, scan: dict | None, present: bool) -> dict:
    """Source-level and field-level admission status, with the reason.

    The role decides the question. An operational log or a dataset manifest
    is NOT_AN_EVENT_SOURCE -- a separate finding from an event source that
    fails admission."""
    role = cand.get("role", ROLE_EVENT_STREAM)
    if not present:
        return {"status": UNTRACED, "role": role,
                "reason": "declared in code or expected by family but absent on this host",
                "fields": {}}
    cov = scan["coverage_by_time_field"]
    if role in (ROLE_OPERATIONAL_LOG, ROLE_DATASET_MANIFEST):
        return {"status": NOT_AN_EVENT_SOURCE, "role": role,
                "reason": ("this store is a %s, not an event stream; it carries no per-event "
                           "publication or known-from field and was never meant to. Its value here "
                           "is coverage and receipt evidence, recorded below." % role.lower()),
                "coverage_start": (min((v["min"] for v in cov.values()), default=None) or "")[:10] or None,
                "coverage_end": (max((v["max"] for v in cov.values()), default=None) or "")[:10] or None,
                "time_fields_present": sorted(cov), "fields": {}}
    kf = next((cov[f] for f in KNOWN_FROM_EQUIVALENT if f in cov), None)
    pub = cov.get("published_time") or cov.get("publication_time")
    fields = {}
    for f in scan["fields"]:
        if f in ("known_from", "first_seen", "first_seen_time"):
            fields[f] = ADMISSIBLE if kf else NOT_ADMISSIBLE
        elif f in ("published_time", "publication_time"):
            if not pub:
                fields[f] = NOT_ADMISSIBLE
            elif scan["publication_equals_retrieval"] > 0:
                fields[f] = ADMISSIBLE_WITH_LIMITATIONS
            else:
                fields[f] = ADMISSIBLE
        elif f in ("retrieved_time", "retrieval_time"):
            fields[f] = ADMISSIBLE
        elif f == "event_time":
            fmts = {k.split(":")[1] for k in scan["time_field_formats"] if k.startswith("event_time:")}
            fields[f] = ADMISSIBLE_WITH_LIMITATIONS if fmts - {"ISO8601"} else ADMISSIBLE
        elif f in ("expected_value", "actual_value", "prior_value", "surprise"):
            fields[f] = NOT_ADMISSIBLE            # sentinel-only in this store; see report
        elif f in ("directional_expectation", "importance", "mechanism_hypotheses"):
            fields[f] = ADMISSIBLE_WITH_LIMITATIONS
        else:
            fields[f] = ADMISSIBLE
    # source level: history is what decides
    if not kf:
        return {"status": NOT_ADMISSIBLE, "role": role,
                "reason": ("no known-from equivalent field (%s): cannot establish when APEX could "
                           "have known any record" % ", ".join(KNOWN_FROM_EQUIVALENT)),
                "fields": fields}
    start, end = kf["min"][:10], kf["max"][:10]
    ev = cov.get("event_time") or cov.get("published_time")
    lead = None
    if ev:
        lead = {"earliest_event_or_publication": ev["min"][:10], "earliest_known_from": start,
                "note": ("event dates reach back to %s while APEX could not have known any of them "
                         "before %s: the gap is exactly what makes this store prospective"
                         % (ev["min"][:10], start))}
    if role == ROLE_PIT_REFERENCE:
        status = ADMISSIBLE_WITH_LIMITATIONS
        reason = ("point-in-time reference with decided_asof spanning %s..%s; admissible as "
                  "membership/reference at those decision dates, NOT as an event stream" % (start, end))
    else:
        status = PROSPECTIVE_ONLY
        reason = ("earliest known-from is %s: the store begins when capture was switched on, so it "
                  "carries no information about any earlier period" % start)
    if scan["known_from_before_publication"]:
        status, reason = NOT_ADMISSIBLE, ("%d records claim known_from before their publication time"
                                          % scan["known_from_before_publication"])
    out = {"status": status, "role": role, "reason": reason, "coverage_start": start,
           "coverage_end": end, "fields": fields}
    if lead:
        out["event_date_versus_known_from"] = lead
    return out


class EventSourceRefused(Exception):
    """A source may not be used for the requested purpose and window."""


PURPOSES = ("TRAINING", "VALIDATION", "EVALUATION", "PROSPECTIVE")


def assert_usable_for(entry: dict, *, purpose: str, window_start: str, window_end: str) -> dict:
    """The enforcement the certification exists for.

    A certified status is not a permission slip. This refuses the actual
    combination of source, purpose and window -- which is where a
    PROSPECTIVE_ONLY source silently becomes a historical one."""
    if purpose not in PURPOSES:
        raise EventSourceRefused("UNKNOWN_PURPOSE: %r not in %s" % (purpose, list(PURPOSES)))
    status = entry.get("admission_status")
    sid = entry.get("source_id", "?")
    if status in (NOT_ADMISSIBLE, UNTRACED, NOT_AN_EVENT_SOURCE):
        raise EventSourceRefused("SOURCE_NOT_ADMISSIBLE: %s is %s -- %s"
                                 % (sid, status, entry.get("reason", "")))
    start, end = entry.get("coverage_start"), entry.get("coverage_end")
    if not start or not end:
        raise EventSourceRefused("NO_COVERAGE_INTERVAL: %s cannot be bounded in time" % sid)
    if status == PROSPECTIVE_ONLY and purpose != "PROSPECTIVE":
        raise EventSourceRefused(
            "PROSPECTIVE_ONLY_SOURCE: %s could not have been known before %s, so it cannot serve "
            "%s over %s..%s. Its event dates reaching further back are not knowledge."
            % (sid, start, purpose, window_start, window_end))
    if window_start < start or window_end > end:
        raise EventSourceRefused(
            "WINDOW_OUTSIDE_COVERAGE: %s covers %s..%s; requested %s..%s"
            % (sid, start, end, window_start, window_end))
    return {"source_id": sid, "purpose": purpose, "window": [window_start, window_end],
            "status": status, "usable": True,
            "limitations": entry.get("reason", "")}


def main(outdir: str) -> int:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry, manifest, matrix = [], [], []
    for cand in CANDIDATES:
        p = Path(cand["location"])
        if not p.is_absolute():
            p = repo / p
        present = p.exists()
        entry = dict(cand)
        entry["resolved_path"] = str(p)
        entry["present"] = present
        scan = None
        if present:
            st = p.stat()
            entry.update(size_bytes=st.st_size, mtime_utc=datetime.fromtimestamp(
                st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                content_sha256=sha256_of(p))
            scan = scan_jsonl(p)
            entry["scan"] = scan
        cls = classify(cand, scan, present)
        entry["certification"] = cls
        registry.append(entry)
        manifest.append({"source_id": cand["source_id"], "family": cand["family"],
                         "provider": cand["provider"], "location": str(p), "present": present,
                         "content_sha256": entry.get("content_sha256"),
                         "size_bytes": entry.get("size_bytes"),
                         "records": (scan or {}).get("records"),
                         "coverage_start": cls.get("coverage_start"),
                         "coverage_end": cls.get("coverage_end"),
                         "admission_status": cls["status"], "reason": cls["reason"],
                         "field_eligibility": cls["fields"],
                         "certified_utc": now, "certifier": CONTRACT})
        for f, s in cls["fields"].items():
            matrix.append({"source_id": cand["source_id"], "field": f, "status": s})

    families = {}
    for fam, desc in FAMILIES.items():
        srcs = [r for r in registry if r["family"] == fam]
        present_srcs = [r for r in srcs if r["present"]]
        order = [NOT_AN_EVENT_SOURCE, NOT_ADMISSIBLE, UNTRACED, PROSPECTIVE_ONLY,
                 ADMISSIBLE_WITH_LIMITATIONS, ADMISSIBLE]
        best = max((r["certification"]["status"] for r in present_srcs),
                   key=lambda s: order.index(s), default=UNTRACED)
        families[fam] = {"description": desc, "candidates_declared": len(srcs),
                         "candidates_present": len(present_srcs), "best_status": best,
                         "sources": [r["source_id"] for r in srcs]}

    (out / "EVENT_SOURCE_REGISTRY_V0.json").write_text(json.dumps(
        {"contract": CONTRACT, "produced_utc": now, "families": families,
         "sources": registry}, indent=1, sort_keys=False, default=str))
    (out / "EVENT_SOURCE_MANIFEST_V0.json").write_text(json.dumps(
        {"contract": "EVENT_SOURCE_MANIFEST_V0", "produced_utc": now,
         "law": "a manifest records what a source IS; it admits nothing",
         "sources": manifest}, indent=1, default=str))
    (out / "EVENT_SOURCE_ELIGIBILITY_MATRIX_V0.json").write_text(json.dumps(
        {"contract": "EVENT_SOURCE_ELIGIBILITY_MATRIX_V0", "produced_utc": now,
         "statuses": [ADMISSIBLE, ADMISSIBLE_WITH_LIMITATIONS, PROSPECTIVE_ONLY,
                      NOT_ADMISSIBLE, UNTRACED],
         "field_rows": matrix}, indent=1, default=str))
    summary = {f["source_id"]: f["admission_status"] for f in manifest}
    print(json.dumps({"sources": summary,
                      "families": {k: v["best_status"] for k, v in families.items()},
                      "historically_admissible_sources":
                          [k for k, v in summary.items() if v in (ADMISSIBLE, ADMISSIBLE_WITH_LIMITATIONS)]},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
