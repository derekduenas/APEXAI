"""TIMESTAMPED EVENT CAPTURE — the event-world archive starts now.

The same law that started the forward clock applies to events: every
clean event observation not recorded today can never be recreated with
the same epistemic purity later. This module polls SEC EDGAR's current
8-K feed (the canonical, exchange-grade catalyst stream: earnings,
guidance, M&A, departures, material agreements) and appends each NEW
filing to a chained events ledger.

THE PIT FIELDS (the whole point):
  event_time_utc   EDGAR's acceptance timestamp (when the market could
                   first have known via EDGAR)
  known_from_utc   OUR capture time — the honest as-of boundary; APEX may
                   never reason about an event before its OWN known_from,
                   whatever EDGAR's timestamp says.

NOT WIRED TO ANY DECISION: the Catalyst seat and HUNTER-003 stay DORMANT
until a versioned governance ruling. This is archival infrastructure
only — building the memory the future Catalyst Analyst will need, so
that when it activates it has months of clean timestamped history behind
it instead of none.

Dedupe by accession number (EDGAR's unique filing id). Poll cost: one
request per cycle against SEC's public feed with the registered
User-Agent — well within SEC fair-use guidance.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

EVENTS_LEDGER = Path("results/events/edgar_events.jsonl")
FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
            "&type=8-K&company=&dateb=&owner=include&count=100&output=atom")
ATOM = "{http://www.w3.org/2005/Atom}"
CAPTURE_VERSION = "edgar_event_capture_v1"


def parse_feed(xml_bytes: bytes, known_from_utc: str) -> list:
    """Atom -> event dicts. Malformed entries are skipped and counted,
    never guessed at."""
    root = ET.fromstring(xml_bytes)
    out, skipped = [], 0
    for e in root.findall(f"{ATOM}entry"):
        try:
            title = (e.findtext(f"{ATOM}title") or "").strip()
            updated = (e.findtext(f"{ATOM}updated") or "").strip()
            eid = (e.findtext(f"{ATOM}id") or "").strip()
            accession = eid.rsplit("accession-number=", 1)[-1] \
                if "accession-number=" in eid else eid.rsplit("/", 1)[-1]
            link = e.find(f"{ATOM}link")
            href = link.get("href") if link is not None else None
            summary = (e.findtext(f"{ATOM}summary") or "").strip()[:300]
            form = title.split(" - ", 1)[0].strip() if " - " in title else ""
            company = title.split(" - ", 1)[1].strip() if " - " in title \
                else title
            if not accession or not updated:
                skipped += 1
                continue
            out.append({
                "kind": "edgar_event",
                "accession": accession,
                "form_type": form or "8-K",
                "company_raw": company[:200],
                "event_time_utc": str(pd.Timestamp(updated).tz_convert("UTC"))
                if pd.Timestamp(updated).tzinfo
                else str(pd.Timestamp(updated, tz="US/Eastern")
                         .tz_convert("UTC")),
                "known_from_utc": known_from_utc,
                "source": "SEC_EDGAR_CURRENT_ATOM",
                "url": href, "summary_raw": summary,
                "capture_version": CAPTURE_VERSION,
                "decision_wiring": "NONE_DORMANT_ARCHIVE_ONLY",
            })
        except Exception:                                   # noqa: BLE001
            skipped += 1
    if skipped:
        out.append({"kind": "edgar_capture_note",
                    "known_from_utc": known_from_utc,
                    "malformed_entries_skipped": skipped})
    return out


def known_accessions(ledger: Path = EVENTS_LEDGER) -> set:
    import json
    acc = set()
    if not ledger.exists():
        return acc
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:                                   # noqa: BLE001
            continue
        if r.get("kind") == "edgar_event":
            acc.add(r.get("accession"))
    return acc


def capture_once(client, ledger: Path = EVENTS_LEDGER) -> dict:
    """One poll: fetch feed, parse, append only NEW accessions (chained)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from nightly_pull import _chain_append
    now = str(pd.Timestamp.now(tz="UTC"))
    raw = client._get(FEED_URL)
    events = parse_feed(raw, now)
    seen = known_accessions(ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    new = 0
    for ev in events:
        if ev["kind"] == "edgar_event" and ev["accession"] in seen:
            continue
        _chain_append(ledger, ev)
        new += ev["kind"] == "edgar_event"
    result = {"captured_at": now, "feed_entries": sum(
        1 for e in events if e["kind"] == "edgar_event"), "new": new}
    # FEED HEALTH ARTIFACT (2026-08-17): a quiet-weekend poll appends
    # nothing, so ledger mtime cannot distinguish "polled and empty" from
    # "not polling" -- LAB-04's disease. The catalyst Eyes read THIS
    # (atomic overwrite, the crypto_health pattern), never the newest
    # event's timestamp.
    try:
        import json as _json
        import os as _os
        hp = ledger.parent / "capture_health.json"
        tmp = hp.with_suffix(".tmp")
        tmp.write_text(_json.dumps({"artifact": "edgar_capture_health_v1",
                                    "last_poll_utc": now, **result,
                                    "status": "OK"}))
        _os.replace(tmp, hp)
    except Exception:                                       # noqa: BLE001
        pass
    return result
