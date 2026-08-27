"""THE CATALYST PIPELINE — retrieval first, reasoning last.

    FETCH -> DURABLE RAW RECORD -> DEDUPE -> INTERPRET -> EVENT

The ordering is the guarantee. Raw evidence lands on disk, hashed and
immutable, BEFORE anything is allowed to think about it. If the
interpreter is slow, broken, or absent, the day's evidence still
exists and can be interpreted later. The reverse ordering loses the
day when the model has a bad minute.

THE INTERPRETER IS OPTIONAL BY DESIGN, AND SAYS SO. With no LLM
credential the pipeline still produces events: a Federal Reserve press
release IS an event, and its title, source and timestamp are facts we
read rather than facts we inferred. What is missing without a model is
INTERPRETATION -- mechanism hypotheses, sector mapping, relevance --
and every such event is stamped

    interpreter = "DETERMINISTIC_NO_LLM"

so that no downstream reader can mistake a title we copied for an
analysis we performed. A degraded sense that announces its degradation
is useful. One that quietly fills the gap is a liability.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.catalyst.events import (CatalystEvent, SourceObservation,
                                  dedup_key)
from apex.catalyst.sources import RawObservation, fetch_all
from apex.governance.chain_ledger import chain_append

RAW_LEDGER = Path("results/catalyst/raw_observations.jsonl")
EVENT_LEDGER = Path("results/catalyst/events.jsonl")
CYCLE_LEDGER = Path("results/catalyst/cycles.jsonl")
EDGEFORGE_OUTBOX = Path("results/outbox/catalyst_observations.jsonl")

# Source -> event type. Deterministic, because "what kind of thing is
# this" is answerable from the publisher without any reasoning.
SOURCE_EVENT_TYPE = {
    "FEDERAL_RESERVE_PRESS": "CENTRAL_BANK",
    "FEDERAL_RESERVE_MONETARY": "CENTRAL_BANK",
    "FEDERAL_RESERVE_SPEECHES": "CENTRAL_BANK",
    "FEDERAL_RESERVE_H15_RATES": "MACRO_RELEASE",
    "BUREAU_ECONOMIC_ANALYSIS": "MACRO_RELEASE",
    "SEC_EDGAR": "REGULATORY",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seen_ids(path: Path) -> set:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("source_observation_id"):
            out.add(r["source_observation_id"])
    return out


def persist_raw(observations: list, *, raw_ledger: Path | None = None
                ) -> dict:
    """Write raw evidence before anything interprets it.

    Already-seen documents are skipped, not rewritten: a feed that
    republishes the same item every poll must not manufacture new
    evidence out of the same document.
    """
    path = raw_ledger or RAW_LEDGER
    known = _seen_ids(path)
    written = []
    for o in observations:
        if o.source_observation_id in known:
            continue
        chain_append(path, o.as_record())
        known.add(o.source_observation_id)
        written.append(o)
    return {"kind": "raw_persistence", "offered": len(observations),
            "new": len(written), "already_known": len(observations) - len(written),
            "written": written, "ledger": str(path),
            "law": "raw evidence is persisted BEFORE interpretation"}


def _to_source_observation(o: RawObservation) -> SourceObservation:
    return SourceObservation(
        source=o.source, source_authority=o.source_authority,
        source_ref=o.locator, headline=o.title,
        published_time=o.published_time,
        retrieval_time=o.retrieved_time, body_excerpt=o.raw_excerpt)


def build_events(raws: list, *, session: str, release_sha: str = "UNKNOWN",
                 interpreter=None) -> dict:
    """Group raw documents into events. A hundred headlines about one
    thing become one event with a hundred observations."""
    events, updates = {}, []
    for o in raws:
        etype = SOURCE_EVENT_TYPE.get(o.source.split(":")[0], "OTHER")
        subjects = o.entity_hints or ("MARKET",)
        eid = dedup_key(event_type=etype, subjects=tuple(subjects),
                        headline=o.title, day=session)
        obs = _to_source_observation(o)
        if eid in events:
            updates.append(events[eid].add_observation(obs))
            continue
        ev = CatalystEvent(
            event_id=eid, event_type=etype,
            # the world's time is the publisher's; ours is retrieval
            event_time=o.published_time,
            first_seen=o.first_seen_time, known_from=o.known_from,
            scheduled=False, headline=o.title,
            # copied from the cited document, NOT summarised by a model
            factual_summary=o.title,
            affected_symbols=tuple(
                s for s in subjects if s.isupper() and len(s) <= 5),
            release_sha=release_sha,
            interpreter="DETERMINISTIC_NO_LLM")
        ev.add_observation(obs)
        events[eid] = ev

    enriched, interp_calls, interp_err, refused = 0, 0, None, 0
    if interpreter is not None and events:
        try:
            # batched when the client supports it: a cycle's new events
            # are one call, not one call each
            if hasattr(interpreter, "interpret_many"):
                r = interpreter.interpret_many(list(events.values()))
                interp_calls = r.get("calls", 0)
                enriched = r.get("interpreted", 0)
                refused = r.get("refused", 0)
                interp_err = r.get("error")
            else:
                for ev in events.values():
                    interp_calls += 1
                    if interpreter(ev):
                        enriched += 1
        except Exception as e:                # a broken brain is not
            interp_err = f"{type(e).__name__}: {e}"[:200]   # a broken
                                                            # pipeline

    return {"kind": "event_build", "events": list(events.values()),
            "n_events": len(events), "n_updates": len(updates),
            "updates": updates, "interpreter_calls": interp_calls,
            "interpreted": enriched, "refused": refused,
            "interpreter_error": interp_err,
            "law": "a hundred headlines are one event"}


def run_cycle(*, session: str, phase: str, release_sha: str = "UNKNOWN",
              interpreter=None, include_sec: bool = True,
              roots: dict | None = None) -> dict:
    """One complete catalyst cycle, sealed as a durable record.

    Never raises on a source failure. The cycle record states what was
    reached and what was not, so a quiet market and a broken retriever
    can always be told apart afterwards.
    """
    r = roots or {}
    raw_l = r.get("raw", RAW_LEDGER)
    ev_l = r.get("events", EVENT_LEDGER)
    cy_l = r.get("cycles", CYCLE_LEDGER)
    out_l = r.get("outbox", EDGEFORGE_OUTBOX)

    started = _now()
    sweep = fetch_all(release_sha=release_sha, include_sec=include_sec)
    persisted = persist_raw(sweep["observations"], raw_ledger=raw_l)
    built = build_events(persisted["written"], session=session,
                         release_sha=release_sha, interpreter=interpreter)

    for ev in built["events"]:
        chain_append(ev_l, ev.as_record())
        # neutral observation for EdgeForge -- no verdict, no direction
        chain_append(out_l, {
            "kind": "catalyst_observation", "session": session,
            "event_id": ev.event_id, "event_type": ev.event_type,
            "known_from": ev.known_from,
            "affected_symbols": list(ev.affected_symbols),
            "verification": ev.verification,
            "interpreter": ev.interpreter,
            "headline": ev.headline, "release_sha": release_sha,
            "decision_power": "NONE_OBSERVATIONAL"})

    rec = {"kind": "catalyst_cycle",
           "cycle_id": f"{session}:{phase}:{started}",
           "session": session, "phase": phase,
           "scheduled_time": phase, "actual_start": started,
           "actual_end": _now(),
           "sources_checked": sweep["sources_checked"],
           "sources_succeeded": sweep["sources_succeeded"],
           "sources_failed": sweep["sources_failed"],
           "coverage": sweep["coverage"],
           "failures": sweep["failures"],
           "raw_offered": persisted["offered"],
           "new_observations": persisted["new"],
           "new_events": built["n_events"],
           "updated_events": built["n_updates"],
           "llm_calls": built["interpreter_calls"],
           "interpreted": built["interpreted"],
           "last_error": built["interpreter_error"]
           or (json.dumps(sweep["failures"])[:200]
               if sweep["failures"] else None),
           "release_sha": release_sha,
           "decision_power": "SHADOW_CONTEXT_ONLY"}
    chain_append(cy_l, rec)
    rec["events"] = built["events"]
    return rec
