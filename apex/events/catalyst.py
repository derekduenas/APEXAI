"""CatalystState — the Event Eyes. WHY IS IT MOVING, as a typed answer.

T1 item 6. Assembled from the EDGAR archive the event clock has been
writing 24/7 (results/events/edgar_events.jsonl). Three states, and the
distinction between the last two is the whole point:

    KNOWN_CATALYST       a filing for THIS issuer is visible as of T
    NO_KNOWN_CATALYST    the feed is healthy, the identity bridge worked,
                         and nothing matched — a MEASURED absence
    EVENT_UNCERTAIN      the question cannot currently be answered: the
                         identity bridge is unavailable, or the archive
                         is stale. NOT the same as "no news."

PIT LAW: an event exists for APEX only from its known_from_utc — the
moment OUR archive captured it, not the moment SEC accepted it. Monday's
question "did APEX know about the 8-K when it decided?" is answered by
that field alone.

HONEST LIMITATION, stated rather than fudged: EDGAR events carry CIK and
company name, not tickers. Without a caller-supplied symbol->CIK bridge
this module answers EVENT_UNCERTAIN — it does not guess by fuzzy name
matching, because a wrong catalyst attribution is worse than an honest
unknown.

decision_power = NONE_OBSERVATIONAL_EPOCH1. The frozen Hunter never sees
this; it exists so we can prospectively measure whether catalyst-aware
setups behave differently.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

OBSERVATIONAL = "NONE_OBSERVATIONAL_EPOCH1"
EVENTS_LEDGER = Path("results/events/edgar_events.jsonl")

KNOWN_CATALYST = "KNOWN_CATALYST"
NO_KNOWN_CATALYST = "NO_KNOWN_CATALYST"
EVENT_UNCERTAIN = "EVENT_UNCERTAIN"

LOOKBACK_HOURS = 72          # how far back an event still "explains" a move
FEED_STALE_HOURS = 12        # older than this, the archive may be down

_CIK_RX = re.compile(r"\((\d{7,10})\)")


@dataclass(frozen=True)
class CatalystState:
    symbol: str
    as_of: str
    status: str
    events: tuple = ()                    # newest first, PIT-visible only
    reason: str = ""
    feed_last_known_from: str | None = None
    decision_power: str = OBSERVATIONAL

    def as_record(self) -> dict:
        return {"kind": "catalyst_state", **asdict(self)}


def _load_events(path: Path = EVENTS_LEDGER) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") == "edgar_event":
            out.append(r)
    return out


def _cik_of_event(ev: dict) -> str | None:
    m = _CIK_RX.search(ev.get("company_raw") or "")
    return m.group(1).lstrip("0") if m else None


def catalyst_state(symbol: str, as_of, *, cik: str | None = None,
                   events: list | None = None) -> CatalystState:
    """The typed answer to WHY IS IT MOVING, as of T.

    `cik`: this symbol's SEC identity, from a caller-owned bridge. None
    means the bridge is unavailable and the honest answer is UNCERTAIN.
    """
    import pandas as pd
    t = pd.Timestamp(as_of)
    if t.tzinfo is None:
        raise ValueError("as_of must be tz-aware (PIT law)")
    rows = _load_events() if events is None else [
        e for e in events if e.get("kind") == "edgar_event"]

    # PIT choke point: known_from_utc, never event_time_utc
    visible = [e for e in rows
               if e.get("known_from_utc")
               and pd.Timestamp(e["known_from_utc"]) <= t]

    newest_known = (max((e["known_from_utc"] for e in visible), default=None)
                    if visible else None)

    if not rows:
        return CatalystState(symbol=symbol, as_of=str(t),
                             status=EVENT_UNCERTAIN,
                             reason="event archive absent or empty: the "
                                    "catalyst question cannot be answered")
    if newest_known is None or (
            t - pd.Timestamp(newest_known)
            > pd.Timedelta(hours=FEED_STALE_HOURS)):
        return CatalystState(symbol=symbol, as_of=str(t),
                             status=EVENT_UNCERTAIN,
                             feed_last_known_from=newest_known,
                             reason=f"archive stale (> {FEED_STALE_HOURS}h "
                                    f"since last capture): silence may be "
                                    f"a dead feed, not a quiet issuer")
    if cik is None:
        return CatalystState(symbol=symbol, as_of=str(t),
                             status=EVENT_UNCERTAIN,
                             feed_last_known_from=newest_known,
                             reason="no symbol->CIK bridge supplied; "
                                    "refusing fuzzy name matching — a wrong "
                                    "catalyst attribution is worse than an "
                                    "honest unknown")

    want = str(cik).lstrip("0")
    window = t - pd.Timedelta(hours=LOOKBACK_HOURS)
    matched = []
    for e in visible:
        if _cik_of_event(e) == want and \
                pd.Timestamp(e["event_time_utc"]) >= window:
            matched.append({
                "form_type": e.get("form_type"),
                "event_time": str(e.get("event_time_utc")),
                "known_from": str(e.get("known_from_utc")),
                "source": e.get("source"),
                "accession": e.get("accession"),
                "url": e.get("url"),
            })
    matched.sort(key=lambda m: m["event_time"], reverse=True)
    if matched:
        return CatalystState(symbol=symbol, as_of=str(t),
                             status=KNOWN_CATALYST,
                             events=tuple(matched[:5]),
                             feed_last_known_from=newest_known)
    return CatalystState(symbol=symbol, as_of=str(t),
                         status=NO_KNOWN_CATALYST,
                         feed_last_known_from=newest_known,
                         reason=f"feed healthy, identity bridged, no "
                                f"filing in {LOOKBACK_HOURS}h — a MEASURED "
                                f"absence")
