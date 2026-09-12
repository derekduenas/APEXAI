"""LLM enrichment schema (M5): source-linked event records with clocks, dedup, extraction uncertainty and
prompt/model versions. No LLM is called by this build (`NoLLMClient` refuses). A FUTURE SCHEDULE is a
known covariate; a future RELEASE, a revised historical narrative, or a realized surprise is not
knowable before its publication time and is refused as a covariate at any earlier as-of."""
from __future__ import annotations

from apex.options_pilot.clock import ClockRefused, parse_utc
from apex.worldmodel_wb.contracts import digest

KINDS = ("SCHEDULED_EVENT", "RELEASE", "NEWS", "FILING")


class EnrichmentRefused(ValueError):
    pass


class NoLLMClient:
    def extract(self, *a, **k):
        raise EnrichmentRefused("NO_LLM_CLIENT: this build makes no model calls; enrichment records must come from a reviewed extractor")


def event_record(*, kind: str, source_url: str, source_id: str, event_time_utc: str, publication_time_utc: str, receipt_time_utc: str,
                 text_digest: str, extraction: dict, prompt_version: str, model_version: str, scheduled_time_utc: str | None = None) -> dict:
    if kind not in KINDS:
        raise EnrichmentRefused("KIND_UNKNOWN: %r" % kind)
    if not source_url or not source_id:
        raise EnrichmentRefused("SOURCE_LINK_MISSING")
    try:
        ev, pub, rcv = parse_utc(event_time_utc, field="event_time"), parse_utc(publication_time_utc, field="publication_time"), parse_utc(receipt_time_utc, field="receipt_time")
        sched = parse_utc(scheduled_time_utc, field="scheduled_time") if scheduled_time_utc else None
    except ClockRefused as e:
        raise EnrichmentRefused(str(e))
    if pub < ev or rcv < pub:
        raise EnrichmentRefused("CLOCKS_OUT_OF_ORDER: event <= publication <= receipt is required")
    if not isinstance(extraction, dict) or "uncertainty" not in extraction or not (0.0 <= float(extraction["uncertainty"]) <= 1.0):
        raise EnrichmentRefused("EXTRACTION_UNCERTAINTY_REQUIRED in [0, 1]")
    if kind == "SCHEDULED_EVENT" and sched is None:
        raise EnrichmentRefused("SCHEDULED_TIME_REQUIRED")
    rec = {"kind": "enrichment_event", "event_kind": kind, "source_url": source_url, "source_id": source_id, "event_time_utc": event_time_utc,
           "publication_time_utc": publication_time_utc, "receipt_time_utc": receipt_time_utc, "scheduled_time_utc": scheduled_time_utc,
           "text_digest": text_digest, "extraction": extraction, "prompt_version": prompt_version, "model_version": model_version,
           "known_from_epoch": pub, "dedup_key": digest({"src": source_url, "id": source_id, "text": text_digest}),
           "authority": "NONE: may not alter tool permissions, trading limits, forecasts or risk"}
    rec["record_digest"] = digest({k: v for k, v in rec.items() if k != "record_digest"})
    return rec


def usable_as_covariate(rec: dict, *, as_of_epoch: float) -> dict:
    """A SCHEDULE is usable once known; a release/news/filing only from its publication time."""
    known = rec["known_from_epoch"]
    if rec["event_kind"] == "SCHEDULED_EVENT":
        return {"usable": known <= as_of_epoch, "why": None if known <= as_of_epoch else "SCHEDULE_NOT_YET_KNOWN", "as": "known covariate: the schedule"}
    if known > as_of_epoch:
        return {"usable": False, "why": "PUBLISHED_AFTER_AS_OF: a future release or realized surprise cannot be a covariate", "as": None}
    return {"usable": True, "why": None, "as": "published fact (with extraction uncertainty %.2f)" % float(rec["extraction"]["uncertainty"])}


def dedupe(records: list) -> dict:
    seen, kept, dropped = set(), [], 0
    for r in records:
        if r["dedup_key"] in seen:
            dropped += 1; continue
        seen.add(r["dedup_key"]); kept.append(r)
    return {"kept": kept, "dropped_duplicates": dropped}
