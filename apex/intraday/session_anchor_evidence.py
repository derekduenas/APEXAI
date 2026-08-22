"""SessionAnchorEvidence — immutable, captured-at-the-open proof that
the true 09:30 ET anchor was observed LIVE.

WHY THIS EXISTS (measured 2026-08-18): the session-integrity
certification could not certify 10 of 14 symbols -- not because their
anchors were wrong, but because the only surviving artifact is a rolling
400-bar window whose first bar reflects RETENTION, not capture start.
The evidence needed to answer the question was destroyed by retention
before anyone asked. Four symbols certified only because they happened
to stay under the retention cap.

This fixes the EVIDENCE problem, not the anchor. It writes an
append-only record early in the session, while the opening facts are
still live, so later truncation cannot erase them.

THE NO-RETROACTIVE-CLAIM LAW: `capture()` records `known_from` as the
moment the evidence was actually taken and stamps
`reconstructed_after_the_fact`. A record built post-close from REST
history is still useful, but it is marked as such and can never
masquerade as live-known. `certify()` refuses to treat a reconstructed
record as live proof.

decision_power: NONE.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

LEDGER = Path("results/intraday/session_anchor_evidence.jsonl")

ANCHOR_SOURCES = (
    "LIVE_FIRST_REGULAR_TRADE",     # strongest: we saw the opening print
    "LIVE_FIRST_REGULAR_QUOTE",     # feed live at the open, no print yet
    "LIVE_FIRST_COMPLETED_BAR",     # first completed regular-session bar
    "POST_CLOSE_RECONSTRUCTION",    # honest, but NOT live proof
    "UNKNOWN",
)

LIVE_SOURCES = ("LIVE_FIRST_REGULAR_TRADE", "LIVE_FIRST_REGULAR_QUOTE",
                "LIVE_FIRST_COMPLETED_BAR")

# an anchor observation this far past the scheduled open is not evidence
# that the open itself was observed.
ANCHOR_TOLERANCE_S = 120.0


class SessionAnchorEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionAnchorEvidence:
    symbol: str
    session_date: str
    exchange_calendar: str
    scheduled_open: str
    scheduled_close: str

    first_regular_trade_time: str | None
    first_regular_quote_time: str | None
    first_completed_regular_bar: str | None

    opening_anchor_source: str
    opening_anchor_valid: bool

    opening_bar_open: float | None
    opening_bar_high: float | None
    opening_bar_low: float | None
    opening_bar_close: float | None
    opening_bar_volume: float | None

    known_from: str
    as_of: str
    provider: str
    transport_birth: str | None
    reconstructed_after_the_fact: bool
    decision_power: str = "NONE"

    def __post_init__(self):
        if self.opening_anchor_source not in ANCHOR_SOURCES:
            raise SessionAnchorEvidenceError(
                f"unknown opening_anchor_source {self.opening_anchor_source!r}")
        if self.opening_anchor_valid and self.reconstructed_after_the_fact:
            raise SessionAnchorEvidenceError(
                "a post-hoc reconstruction may never be marked "
                "opening_anchor_valid -- it is not live proof")
        if (self.opening_anchor_valid
                and self.opening_anchor_source not in LIVE_SOURCES):
            raise SessionAnchorEvidenceError(
                f"opening_anchor_valid requires a LIVE source, got "
                f"{self.opening_anchor_source!r}")

    def as_record(self) -> dict:
        return {"kind": "session_anchor_evidence", **asdict(self)}


def _earliest(*candidates):
    vals = [c for c in candidates if c is not None]
    return min(vals) if vals else None


def capture(*, symbol: str, session_date: str, scheduled_open,
            scheduled_close, now, provider: str,
            first_regular_trade_time=None, first_regular_quote_time=None,
            first_completed_regular_bar=None, opening_bar: dict | None = None,
            transport_birth: str | None = None,
            exchange_calendar: str = "NYSE",
            reconstructed_after_the_fact: bool = False) -> SessionAnchorEvidence:
    """Capture the anchor facts AS OF `now`. Call this early in the
    session -- its whole purpose is to exist before retention truncates
    the underlying bars."""
    import pandas as pd
    now = pd.Timestamp(now)
    sched_open = pd.Timestamp(scheduled_open)

    def _ts(v):
        return str(pd.Timestamp(v)) if v is not None else None

    trade_t = _ts(first_regular_trade_time)
    quote_t = _ts(first_regular_quote_time)
    bar_t = _ts(first_completed_regular_bar)

    if reconstructed_after_the_fact:
        source = "POST_CLOSE_RECONSTRUCTION"
    elif trade_t is not None:
        source = "LIVE_FIRST_REGULAR_TRADE"
    elif quote_t is not None:
        source = "LIVE_FIRST_REGULAR_QUOTE"
    elif bar_t is not None:
        source = "LIVE_FIRST_COMPLETED_BAR"
    else:
        source = "UNKNOWN"

    earliest = _earliest(trade_t, quote_t, bar_t)
    valid = False
    if source in LIVE_SOURCES and earliest is not None:
        delta = (pd.Timestamp(earliest) - sched_open).total_seconds()
        # observed at or before the open (premarket coverage counts), or
        # within a small tolerance of it
        valid = delta <= ANCHOR_TOLERANCE_S

    ob = opening_bar or {}
    return SessionAnchorEvidence(
        symbol=symbol, session_date=session_date,
        exchange_calendar=exchange_calendar, scheduled_open=str(sched_open),
        scheduled_close=str(pd.Timestamp(scheduled_close)),
        first_regular_trade_time=trade_t, first_regular_quote_time=quote_t,
        first_completed_regular_bar=bar_t, opening_anchor_source=source,
        opening_anchor_valid=valid,
        opening_bar_open=ob.get("open"), opening_bar_high=ob.get("high"),
        opening_bar_low=ob.get("low"), opening_bar_close=ob.get("close"),
        opening_bar_volume=ob.get("volume"),
        known_from=str(now), as_of=str(now), provider=provider,
        transport_birth=transport_birth,
        reconstructed_after_the_fact=reconstructed_after_the_fact)


def persist(ev: SessionAnchorEvidence) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, ev.as_record())


def read_for(session_date: str, path: Path | None = None) -> dict:
    p = path or LEDGER
    if not p.exists():
        return {}
    out: dict = {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("session_date") == session_date:
            out[r.get("symbol")] = r        # last write per symbol wins
    return out


def certify(session_date: str, required_symbols: tuple,
            path: Path | None = None) -> dict:
    """Session-level verdict from LIVE evidence only. A symbol with no
    record, or with only a post-hoc reconstruction, is NOT certified --
    silence and hindsight are both refused."""
    have = read_for(session_date, path)
    live_valid, reconstructed, missing, live_invalid = [], [], [], []
    for s in required_symbols:
        r = have.get(s)
        if r is None:
            missing.append(s)
        elif r.get("reconstructed_after_the_fact"):
            reconstructed.append(s)
        elif r.get("opening_anchor_valid"):
            live_valid.append(s)
        else:
            live_invalid.append(s)

    if live_invalid:
        verdict = "SESSION_ANCHOR_INVALID"
    elif missing or reconstructed:
        verdict = "SESSION_ANCHOR_UNPROVEN"
    else:
        verdict = "SESSION_ANCHOR_PROVEN_LIVE"

    return {
        "kind": "session_anchor_certification", "session_date": session_date,
        "verdict": verdict, "required": len(required_symbols),
        "live_valid": sorted(live_valid), "live_invalid": sorted(live_invalid),
        "reconstructed_only": sorted(reconstructed), "missing": sorted(missing),
        "decision_power": "NONE",
    }
