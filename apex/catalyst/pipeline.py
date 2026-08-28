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
import os
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
           # durable, because a later reader asking "was there a
           # catalyst that day?" must be able to see WHERE we looked.
           # An absence is only ever an absence within these classes.
           "coverage_classes_reached":
               sweep.get("coverage_classes_reached", []),
           "coverage_classes_missing":
               sweep.get("coverage_classes_missing", []),
           "sources_yielding_nothing":
               sweep.get("sources_yielding_nothing", []),
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


# ------------------------------------------------------ reaction pass

# The reaction pass consumes A BAR STORE. It deliberately does not name
# a vendor: research modules that hardcode a market-data provider are
# exactly what the architecture firewall in test_architecture_claims
# exists to catch, and it caught this line. The concrete path is
# configuration, supplied by the unit that knows which sensor is live.
BARS_ROOT = Path(os.environ.get(
    "APEX_BARS_ROOT", "data/live/bars"))
REACTION_LEDGER = Path("results/catalyst/reactions.jsonl")
ATR_LOOKBACK_BARS = 60


def _load_bars(symbol: str, session: str, root: Path) -> list:
    f = root / f"{symbol}_{session}.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text()).get("bars", [])
    except (OSError, json.JSONDecodeError):
        return []


def _atr(bars: list) -> float | str:
    """True range mean over recent bars. DETERMINISTIC arithmetic -- a
    fabricated volatility would silently rescale every reaction."""
    window = [b for b in bars[-ATR_LOOKBACK_BARS:]
              if isinstance(b.get("high"), (int, float))
              and isinstance(b.get("low"), (int, float))]
    if len(window) < 5:
        return "NOT_ESTIMABLE"
    trs = [b["high"] - b["low"] for b in window]
    return sum(trs) / len(trs)


def eligible_events(*, session: str, close_utc,
                    events_ledger: Path | None = None,
                    now_utc: str | None = None) -> list:
    """Today's DURABLE catalyst events whose reaction is resolvable.

    The defect this replaces: the post-close seal was handed only the
    events discovered during the seal cycle itself -- which on a quiet
    seal is zero -- so a day with 945 catalyst events produced no
    reaction evidence at all. The engine was correct; it was pointed at
    the wrong population.

    The governed population is the session's accumulated event ledger,
    filtered to events that were known BEFORE the close and therefore
    have a measurable forward path inside the session.
    """
    from apex.catalyst.events import CatalystEvent, SourceObservation

    path = Path(events_ledger) if events_ledger is not None \
        else EVENT_LEDGER
    if not path.exists():
        return []
    close = str(close_utc)
    out, seen = [], set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") != "catalyst_event":
            continue
        kf = str(r.get("known_from", ""))
        # an event first known after the close has no in-session path
        if not kf or kf >= close:
            continue
        eid = r.get("event_id")
        if eid in seen:            # the ledger is append-only and an
            continue               # event may appear more than once
        seen.add(eid)
        try:
            ev = CatalystEvent(
                event_id=eid, event_type=r["event_type"],
                event_time=r["event_time"], first_seen=r["first_seen"],
                known_from=r["known_from"], scheduled=r["scheduled"],
                headline=r["headline"],
                factual_summary=r["factual_summary"],
                affected_symbols=tuple(r.get("affected_symbols") or ()),
                importance=r.get("importance", "UNKNOWN"),
                verification=r.get("verification", "UNVERIFIED"),
                release_sha=r.get("release_sha", "UNKNOWN"),
                interpreter=r.get("interpreter", "UNKNOWN"))
        except Exception:                              # noqa: BLE001
            continue
        for o in r.get("observations", []):
            try:
                ev.add_observation(SourceObservation(
                    source=o["source"],
                    source_authority=o["source_authority"],
                    source_ref=o["source_ref"], headline=o["headline"],
                    published_time=o["published_time"],
                    retrieval_time=o["retrieval_time"],
                    body_excerpt=o.get("body_excerpt", "")))
            except Exception:                          # noqa: BLE001
                continue
        out.append(ev)
    return out


def attach_reactions(*, session: str, events: list, close_utc,
                     bars_root: Path | None = None,
                     ledger: Path | None = None,
                     evidence_class: str = "PROSPECTIVE") -> dict:
    """Attach measured market behaviour to events AFTER the fact.

    Nothing here touches the sealed event record: a reaction is its own
    append-only row keyed by event_id. Measured strictly after
    known_from, so an event we learned of at 14:03 is never credited
    with the 14:01 move.
    """
    from apex.catalyst.reaction import classify, disagreement, measure

    root = bars_root or BARS_ROOT
    led = ledger or REACTION_LEDGER
    written, unmeasurable, disagreements = 0, 0, []

    for ev in events:
        for sym in (ev.affected_symbols or ()):
            bars = _load_bars(sym, session, root)
            if not bars:
                unmeasurable += 1
                continue
            atr = _atr(bars)
            r = measure(bars=bars, known_from=ev.known_from, atr=atr,
                        session_close=close_utc)
            if r.get("verdict") == "NO_PATH":
                unmeasurable += 1
                continue
            cls = classify(expectation="UNKNOWN", reaction=r, atr=atr)
            dis = disagreement(event=ev,
                               reaction_class=cls["reaction_class"])
            rec = {"kind": "catalyst_reaction", "session": session,
                   "event_id": ev.event_id, "symbol": sym,
                   "event_time": ev.event_time,
                   "known_from": ev.known_from, "atr": atr,
                   "source_lineage": [
                       {"source": o.source,
                        "source_authority": o.source_authority,
                        "source_ref": o.source_ref}
                       for o in ev.observations],
                   "market_data_lineage": str(root),
                   "interpreter": ev.interpreter,
                   "importance": ev.importance,
                   "evidence_class": evidence_class,
                   "reaction": r, "classification": cls,
                   "disagreement": dis,
                   "law": "measured after known_from; appended, never "
                          "merged into the sealed event",
                   "decision_power": "SHADOW_CONTEXT_ONLY"}
            chain_append(led, rec)
            written += 1
            if dis:
                disagreements.append(dis)

    return {"kind": "reaction_pass", "session": session,
            "evidence_class": evidence_class,
            "events_considered": len(events),
            "reactions_written": written,
            "unmeasurable": unmeasurable,
            "disagreements": disagreements,
            "n_disagreements": len(disagreements),
            "law": "an unmeasurable event is UNMEASURABLE, not neutral",
            "decision_power": "SHADOW_CONTEXT_ONLY"}
