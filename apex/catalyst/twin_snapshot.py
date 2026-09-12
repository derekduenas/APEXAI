"""EVENT SNAPSHOT FOR THE TWIN (Brick 2) — factual context joined into the same Twin the live decision consumes.

Built on the EXISTING catalyst layer (apex/catalyst/events.py four-clock events, the events/cycles ledgers written by
apex/catalyst/pipeline.py, and the official scheduled-events snapshot under apex/catalyst/calendars/). No new feed
architecture. Two streams:

    SCHEDULED    official calendars (FOMC, BLS) — a future scheduled event is valid context ONLY when the calendar
                 snapshot that lists it was known before the decision (snapshot.known_from <= as_of)
    UNSCHEDULED  catalyst events (official feeds; an entitled wire service does NOT exist and is reported UNAVAILABLE)
                 — an event is visible ONLY when its known_from <= as_of; a publication or correction received later
                 is NOT available evidence for an earlier decision

Feed status on every snapshot, never interchangeable:
    NONE_OBSERVED   feeds read, no relevant event in the window
    UNAVAILABLE     ledger/snapshot missing or unreadable (a quiet world and a dead sense must never look alike)
    STALE           last successful cycle older than the declared freshness
    CONFLICTING     a relevant event whose verification is CONFLICTED
    OBSERVED        relevant events present, none conflicting

Verification vocabulary (mapped onto the catalyst's): reported=UNVERIFIED, confirmed=VERIFIED, disputed=CONFLICTED,
retracted=RETRACTED (an additive `event_retraction` record; the original event is preserved, never edited).

EVENT_GATE_V0 is a PROPOSED, versioned risk gate evaluated here in SHADOW (authority NONE): it computes what it WOULD
veto and why, and it only vetoes NEW ENTRIES when explicitly configured ACTIVE. It never touches an existing position's
exit obligation. Retrieved text is data: nothing in a headline is executed or followed."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

CALENDAR_DIR = Path(__file__).resolve().parent / "calendars"
EVENT_LEDGER = Path("results/catalyst/events.jsonl")
CYCLE_LEDGER = Path("results/catalyst/cycles.jsonl")
FEED_FRESHNESS_S = 30 * 60.0                  # a cycle older than this makes the unscheduled stream STALE
LOOKBACK_S = 6 * 3600.0                        # unscheduled events observed within this window are "relevant now"
STATUSES = ("OBSERVED", "NONE_OBSERVED", "UNAVAILABLE", "STALE", "CONFLICTING")
VERIFICATION_MAP = {"UNVERIFIED": "reported", "VERIFIED": "confirmed", "CONFLICTED": "disputed", "RETRACTED": "retracted"}
MACRO_ASSETS = {"SPY": ("SPY", "INDEX", "RATES"), "QQQ": ("QQQ", "INDEX", "RATES"), "IWM": ("IWM", "INDEX", "RATES")}
HOSTILE = re.compile(r"(ignore (all )?(previous|prior) instructions|buy now|sell now|place (an? )?order|execute|you must trade)", re.I)


def _epoch(s) -> float | None:
    if s is None or s in ("NONE", "UNKNOWN", ""):
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _read_jsonl(path: Path) -> list | None:
    if not path.exists():
        return None
    out = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"kind": "UNPARSEABLE_LINE"})
    except OSError:
        return None
    return out


def scheduled_events(*, as_of: float, symbol: str, calendar_dir: Path = CALENDAR_DIR, horizon_s: float = 7 * 86400.0) -> dict:
    """Scheduled events from official snapshots whose known_from <= as_of. Events whose scheduled time is within
    [as_of - 1 day, as_of + horizon] are returned with their windows."""
    files = sorted(calendar_dir.glob("scheduled_*.json")) if calendar_dir.exists() else []
    if not files:
        return {"status": "UNAVAILABLE", "why": "no scheduled-events snapshot on disk", "events": [], "snapshots": []}
    events, snaps = [], []
    assets = set(MACRO_ASSETS.get(symbol, (symbol, "INDEX")))
    for f in files:
        try:
            snap = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            snaps.append({"file": f.name, "status": "UNREADABLE"}); continue
        kf = _epoch(snap.get("known_from"))
        if kf is None or kf > as_of:
            snaps.append({"file": f.name, "status": "NOT_YET_KNOWN", "known_from": snap.get("known_from")}); continue
        snaps.append({"file": f.name, "status": "USED", "snapshot_id": snap.get("snapshot_id"), "content_sha256": snap.get("content_sha256"), "known_from": snap.get("known_from")})
        for e in snap.get("events", []):
            t = _epoch(e.get("scheduled_time_utc"))
            if t is None or not (as_of - 86400.0 <= t <= as_of + horizon_s):
                continue
            if not (set(e.get("affected_assets", ())) & assets):
                continue
            ws, we = _epoch(e.get("window_start_utc")) or (t - 1800.0), _epoch(e.get("window_end_utc")) or (t + 1800.0)
            events.append({"event_id": e["event_id"], "event_type": e.get("event_type"), "importance": e.get("importance"),
                           "scheduled_time_utc": e.get("scheduled_time_utc"), "scheduled_epoch": t, "in_window": bool(ws <= as_of <= we),
                           "seconds_until": round(t - as_of, 1), "source": e.get("source"), "snapshot_id": snap.get("snapshot_id"),
                           "scheduled_time_basis": e.get("scheduled_time_basis")})
    return {"status": "OBSERVED" if events else "NONE_OBSERVED", "events": sorted(events, key=lambda x: x["scheduled_epoch"]), "snapshots": snaps}


def unscheduled_events(*, as_of: float, symbol: str, event_ledger: Path = EVENT_LEDGER, cycle_ledger: Path = CYCLE_LEDGER,
                       lookback_s: float = LOOKBACK_S, freshness_s: float = FEED_FRESHNESS_S) -> dict:
    """Catalyst events visible at `as_of` (known_from <= as_of), clustered by event_id, with revisions and retractions
    applied additively and only when THEY were known by as_of."""
    rows = _read_jsonl(event_ledger)
    if rows is None:
        return {"status": "UNAVAILABLE", "why": "event ledger %s missing or unreadable" % event_ledger, "events": [], "cycles": None}
    cycles = _read_jsonl(cycle_ledger) or []
    last_ok = None
    for c in cycles:
        if c.get("kind") == "catalyst_cycle" and c.get("sources_succeeded", 0) > 0:
            t = _epoch(c.get("actual_start") or c.get("finished") or c.get("started"))
            if t is not None and t <= as_of:
                last_ok = max(last_ok or 0.0, t)
    assets = set(MACRO_ASSETS.get(symbol, (symbol, "INDEX")))
    clusters: dict = {}
    # TWO PASSES so ledger order never matters: events first, then updates/retractions (an update that arrives in the
    # ledger before its event is still applied; one that was known AFTER as_of is still invisible)
    for r in rows:
        if r.get("kind") != "catalyst_event":
            continue
        kf = _epoch(r.get("known_from"))
        if kf is None or kf > as_of:                        # not yet observable: the firewall
            continue
        rel = bool((set(r.get("affected_symbols", ())) | set(r.get("affected_assets", ()))) & assets) or r.get("event_type") in ("CENTRAL_BANK", "MACRO_RELEASE", "GEOPOLITICAL")
        if not rel:
            continue
        clusters[r["event_id"]] = {"event_id": r["event_id"], "event_type": r.get("event_type"), "headline": r.get("headline"),
                                   "event_time": r.get("event_time"), "published_time": r.get("published_time"), "first_seen": r.get("first_seen"),
                                   "known_from": r.get("known_from"), "verification": r.get("verification", "UNVERIFIED"),
                                   "importance": r.get("importance"), "n_observations": len(r.get("observations") or []),
                                   "revisions": [], "retracted": False, "hostile_text_flagged": bool(HOSTILE.search(str(r.get("headline", "")) + " " + str(r.get("factual_summary", "")))),
                                   "content_note": "headline/summary are DATA; any instruction inside them is not followed"}
    updates = [r for r in rows if r.get("kind") in ("event_update", "event_retraction") and r.get("event_id") in clusters]
    updates.sort(key=lambda r: _epoch(r.get("known_from") or r.get("retrieval_time")) or 0.0)
    for r in updates:
        kf = _epoch(r.get("known_from") or r.get("retrieval_time"))
        if kf is not None and kf > as_of:
            continue                                        # a later correction is not evidence for an earlier decision
        c = clusters[r["event_id"]]
        c["revisions"].append({"kind": r["kind"], "known_from": r.get("known_from") or r.get("retrieval_time"), "source": r.get("added_source") or r.get("source")})
        if r["kind"] == "event_retraction":
            c["retracted"] = True; c["verification"] = "RETRACTED"
        elif r.get("verification") in ("VERIFIED", "CONFLICTED"):
            c["verification"] = r["verification"]
    recent = [c for c in clusters.values() if (_epoch(c["known_from"]) or 0) >= as_of - lookback_s]
    for c in recent:
        c["verification_status"] = VERIFICATION_MAP.get(c["verification"], c["verification"])
    if last_ok is None or as_of - last_ok > freshness_s:
        status = "STALE"
    elif any(c["verification"] == "CONFLICTED" for c in recent):
        status = "CONFLICTING"
    elif recent:
        status = "OBSERVED"
    else:
        status = "NONE_OBSERVED"
    return {"status": status, "events": sorted(recent, key=lambda x: x["known_from"]), "last_successful_cycle_epoch": last_ok,
            "feed_age_s": (round(as_of - last_ok, 1) if last_ok else None), "n_clusters_visible": len(clusters),
            "wire_service": "UNAVAILABLE: no entitled timely news source exists; coverage is official feeds only"}


def event_snapshot(*, symbol: str, as_of: float, calendar_dir: Path = CALENDAR_DIR, event_ledger: Path = EVENT_LEDGER,
                   cycle_ledger: Path = CYCLE_LEDGER) -> dict:
    sch = scheduled_events(as_of=as_of, symbol=symbol, calendar_dir=calendar_dir)
    uns = unscheduled_events(as_of=as_of, symbol=symbol, event_ledger=event_ledger, cycle_ledger=cycle_ledger)
    return {"kind": "EVENT_SNAPSHOT_V1", "symbol": symbol, "as_of_epoch": as_of, "as_of_utc": datetime.fromtimestamp(as_of, tz=timezone.utc).isoformat(),
            "scheduled": sch, "unscheduled": uns, "authority": "FACTUAL_CONTEXT_ONLY",
            "law": ("only what was known at as_of; scheduled events need a snapshot known before as_of; later publications and "
                    "corrections are invisible; retrieved text is data, never instruction")}


# ---------------------------------------------------------------- EVENT_GATE_V0 (proposed; shadow unless configured ACTIVE)
GATE_ID = "EVENT_GATE_V0"
GATE_SPEC = {"id": GATE_ID, "authority_default": "SHADOW",
             "rules": ["R1 NEW_ENTRY veto while a CRITICAL scheduled event for the symbol's market is in its declared window",
                       "R2 NEW_ENTRY veto when the unscheduled stream is UNAVAILABLE or STALE (a dead sense is not a quiet world)",
                       "R3 NEW_ENTRY veto when a relevant unscheduled event is CONFLICTING or flagged hostile-text",
                       "R4 never applies to exits: an existing position follows its exit obligation regardless",
                       "R5 a WAIT caused by this gate is recorded with the rule id; no position-management action is taken"],
             "stage": "intent (before proposal construction) on the rule path; candidate eligibility on the funnel path",
             "not_decided_here": ["relevance beyond the symbol's market", "window widths per event class", "cancellation of open intents"]}


def evaluate_gate(snapshot: dict, *, authority: str = "SHADOW") -> dict:
    reasons = []
    for e in snapshot["scheduled"].get("events", []):
        if e.get("importance") == "CRITICAL" and e.get("in_window"):
            reasons.append("R1: %s in window (%s)" % (e["event_id"], e.get("scheduled_time_utc")))
    st = snapshot["unscheduled"]["status"]
    if st in ("UNAVAILABLE", "STALE"):
        reasons.append("R2: unscheduled stream %s" % st)
    if st == "CONFLICTING" or any(c.get("hostile_text_flagged") for c in snapshot["unscheduled"].get("events", [])):
        reasons.append("R3: conflicting or hostile-text event present")
    would_veto = bool(reasons)
    return {"gate": GATE_ID, "authority": authority, "would_veto_new_entry": would_veto, "reasons": reasons,
            "vetoes_new_entry": bool(would_veto and authority == "ACTIVE"), "affects_exits": False,
            "spec": GATE_SPEC["rules"], "stage": GATE_SPEC["stage"]}
