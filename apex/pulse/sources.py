"""CYCLE SOURCE ADAPTERS — what PULSE actually asks the world.

Being implemented somewhere in APEX is not the same as being QUERIED
by the running cycle. These adapters are the difference: they are what
turns "the composer can accept catalyst state" into "PULSE went and
got it".

Three principles:

  QUERY ONCE, ATTRIBUTE MANY. Catalyst events and BTC are GLOBAL state.
  Reading them 313 times would be 313 chances to observe a different
  world inside one packet's worth of time. They are read once per
  cycle, stamped with their own clock and a state hash, and every
  subject references that same identity.

  ABSENCE IS SPECIFIC. "We asked and there is no event" is a different
  fact from "we never asked" and from "the source is down". They get
  different names, permanently.

  NO FABRICATED SYNCHRONY. A catalyst event from 12:28 and a BTC book
  from 03:31:06 do not become simultaneous because they share a packet.
  Each keeps its as_of and known_from.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from apex.intraday.sessions import Session

SOURCES_VERSION = "PULSE_SOURCES_V0"

CATALYST_EVENTS = Path("/apex-data/core/catalyst/events.jsonl")
CATALYST_REACTIONS = Path("/apex-data/core/catalyst/reactions.jsonl")
BTC_BOOK = Path("/apex-data/core/btc/ws_book_ledger.g2.jsonl")
BTC_DERIVS = Path("/apex-data/core/btc/derivatives_ledger.jsonl")

# catalyst status vocabulary -- an absence must say WHICH absence
NO_RELEVANT_EVENT = "NO_RELEVANT_EVENT"
CATALYST_NOT_QUERIED = "CATALYST_NOT_QUERIED"
CATALYST_UNAVAILABLE = "CATALYST_UNAVAILABLE"
CATALYST_STALE = "CATALYST_STALE"
INTERPRETATION_NOT_AVAILABLE = "INTERPRETATION_NOT_AVAILABLE"


def _now():
    return datetime.now(timezone.utc)


def _tail(path: Path, n: int = 400) -> list:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-n:]
    out = []
    for x in lines:
        if x.strip():
            try:
                out.append(json.loads(x))
            except json.JSONDecodeError:
                continue
    return out


# ------------------------------------------------------- CATALYST

class CatalystIndex:
    """The catalyst ledger, read ONCE per cycle and causally fenced.

    The fence is on known_from and nothing else -- an event APEX could
    not yet have known does not exist for this cycle, however relevant
    it later proves."""

    def __init__(self, as_of, *, events=CATALYST_EVENTS,
                 reactions=CATALYST_REACTIONS):
        self.as_of = str(as_of)
        self.status = "OK"
        self.by_symbol: dict[str, list] = {}
        self.newest = None
        self.events_path, self.reactions_path = events, reactions
        try:
            if not Path(events).exists():
                self.status = CATALYST_UNAVAILABLE
                self.why = f"no catalyst ledger at {events}"
                return
            rows = [json.loads(x) for x in
                    Path(events).read_text().splitlines() if x.strip()]
        except Exception as e:                          # noqa: BLE001
            self.status = CATALYST_UNAVAILABLE
            self.why = f"{type(e).__name__} reading the catalyst ledger"
            return
        latest = {}
        for e in rows:
            if e.get("kind") != "catalyst_event":
                continue
            kf = str(e.get("known_from", "9999"))
            if kf > self.as_of:
                continue          # THE CAUSAL FENCE
            latest[e["event_id"]] = e
        for e in latest.values():
            kf = str(e.get("known_from", ""))
            if self.newest is None or kf > self.newest:
                self.newest = kf
            for sym in (e.get("affected_symbols") or []):
                self.by_symbol.setdefault(sym, []).append(e)
        self.total = len(latest)
        self.why = None

    def subjects_with_events(self) -> set:
        return set(self.by_symbol)

    def state_hash(self) -> str:
        return hashlib.sha256(
            f"{self.as_of}|{self.total if self.status == 'OK' else 0}"
            f"|{self.newest}".encode()).hexdigest()[:16]

    def for_subject(self, symbol: str) -> dict:
        """Everything causally known about this subject, with FACT and
        INTERPRETATION kept apart."""
        if self.status != "OK":
            return {"catalyst_status": self.status, "why": self.why,
                    "queried": False}
        evs = self.by_symbol.get(symbol) or []
        base = {"catalyst_status": (NO_RELEVANT_EVENT if not evs
                                    else "EVENTS_PRESENT"),
                "queried": True,
                "catalyst_state_hash": self.state_hash(),
                "events_known": len(evs),
                "ledger_events_causally_visible": self.total}
        if not evs:
            # queried successfully and there is genuinely nothing --
            # materially different from never having asked
            return base
        evs = sorted(evs, key=lambda e: str(e.get("known_from", "")))
        newest = evs[-1]

        def _ts(v):
            """Some sources publish no event time and write a
            sentinel. Absence of a timestamp is not a timestamp."""
            return (None if v is None
                    or str(v).strip() in ("", "NONE", "None", "null",
                                          "NULL", "N/A")
                    else v)

        base.update({
            # ---- OFFICIAL FACT
            "latest_event_id": newest.get("event_id"),
            "latest_event_time": _ts(newest.get("event_time")),
            "latest_event_known_from": _ts(
                newest.get("known_from")),
            "latest_event_first_seen": _ts(
                newest.get("first_seen")),
            "headline": newest.get("headline"),
            "factual_summary": newest.get("factual_summary"),
            "affected_symbols": newest.get("affected_symbols"),
            # these events carry no source/source_class field at all
            "source_class": "NOT_RECORDED_BY_THIS_LEDGER",
        })
        # ---- UNATTRIBUTED CLASSIFICATION. Present on every event,
        # with no recorded interpreter. Still interpretation, but it
        # may not borrow the credibility of an attributed model.
        base["classification_event_type"] = newest.get("event_type")
        base["classification_importance"] = newest.get("importance")

        # ---- ATTRIBUTED INTERPRETATION, with its own model + clock
        interp = newest.get("expectation_source")
        if interp and str(interp) not in ("NONE", "None", "null"):
            base.update({
                "model_id": interp,
                "interpretation_contract":
                    newest.get("expectation_contract_sha"),
                "interpretation_known_from": _ts(
                    newest.get("expectation_known_from")),
                "directional_expectation":
                    newest.get("directional_expectation"),
            })
        else:
            base["interpretation_status"] = INTERPRETATION_NOT_AVAILABLE
        return base


# ----------------------------------------------------- CROSS-ASSET

def cross_asset_state(*, session: Session, now=None) -> dict:
    """BTC state APEX genuinely owns. Read once, shared by every
    subject via one state hash.

    Rates, commodities and FX are NOT fabricated -- APEX does not own
    them and they stay absent."""
    now = now or _now()
    out = {"source": "apex_btc_stack", "as_of": None,
           "state_hash": None}
    book = _tail(BTC_BOOK, 60)
    snaps = [r for r in book if r.get("kind") == "ws_book_snapshot"]
    if not snaps:
        out["btc_status"] = "NOT_AVAILABLE"
        out["why"] = "no BTC book snapshots in the ledger tail"
        return out
    b = snaps[-1]
    kf = b.get("known_from") or b.get("event_time")
    age = None
    try:
        age = (now - datetime.fromisoformat(
            str(kf).replace("Z", "+00:00"))).total_seconds()
    except Exception:                                   # noqa: BLE001
        pass
    out.update({
        "as_of": str(kf),
        "btc_symbol": b.get("symbol"),
        "btc_venue": b.get("venue"),
        "btc_book_quality": b.get("book_quality_after"),
        "btc_price_unit": b.get("price_unit"),
        "btc_book_age_s": (round(age, 2) if age is not None
                           else "NOT_ESTIMABLE"),
    })
    for side in ("bid", "ask", "best_bid", "best_ask", "mid"):
        if side in b:
            out[f"btc_{side}"] = b[side]
    d = [r for r in _tail(BTC_DERIVS, 40)
         if r.get("kind") == "btc_derivatives_poll"]
    if d:
        latest = d[-1]
        out["btc_derivatives_known_from"] = latest.get("known_from")
        for k in ("funding_rate", "open_interest", "mark_price",
                  "index_price", "basis"):
            if k in latest:
                out[f"btc_{k}"] = latest[k]
    else:
        out["btc_derivatives"] = "NOT_AVAILABLE"
    # feeds APEX does not own are named, not invented
    out["rates"] = "NOT_AVAILABLE"
    out["commodities"] = "NOT_AVAILABLE"
    out["fx"] = "NOT_AVAILABLE"
    out["state_hash"] = hashlib.sha256(
        json.dumps({k: v for k, v in out.items()
                    if k != "state_hash"},
                   sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return out


# --------------------------------------------------------- OPTIONS

def options_state(symbol: str, *, spot, session: Session,
                  now=None) -> dict:
    """Staged options enrichment for ONE eligible subject.

    Before the options market opens this returns EXPECTED_ABSENCE, not
    a stale quote: Friday's final OPRA print is emphatically not
    Monday's premarket state."""
    now = now or _now()
    if session in (Session.PREMARKET, Session.CLOSED,
                   Session.POSTMARKET):
        return {"status": "SESSION_INAPPLICABLE",
                "source": "options_surface",
                "why": f"US options do not trade in {session.value} -- "
                       f"EXPECTED_ABSENCE. A prior session's closing "
                       f"quote is not current state."}
    if not spot:
        return {"status": "DATA_NOT_AVAILABLE",
                "source": "options_surface",
                "why": "no usable spot; a surface cannot be anchored"}
    from apex.organism import options_surface as osf
    try:
        today = now.date().isoformat()
        exps = [e for e in osf.td_expirations(symbol) if e >= today]
        if not exps:
            return {"status": "DATA_NOT_AVAILABLE",
                    "source": "thetadata",
                    "why": "no expirations at or after today"}
        exp = exps[0]
        surf = osf.surface_state(symbol, spot, [exp])
        out = {"source": "thetadata_v3", "as_of": now.isoformat(),
               "expiration": exp,
               "dte": (datetime.fromisoformat(exp).date()
                       - now.date()).days,
               "status": surf.get("status", "VALID")}
        for k, v in surf.items():
            if k not in ("status", "kind", "decision_power"):
                out[k] = v
        return out
    except Exception as e:                              # noqa: BLE001
        return {"status": "PROVIDER_FAILURE", "source": "thetadata",
                "why": f"{type(e).__name__}: {str(e)[:120]}"}
