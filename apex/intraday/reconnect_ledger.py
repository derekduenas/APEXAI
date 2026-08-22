"""Alpaca reconnect event ledger — every reconnect becomes a DURABLE,
inspectable event, and the counter can never again drift from reality.

WHY THIS EXISTS (measured 2026-08-18): alpaca_fabric_health.json
reported counters.reconnects = 388 while `grep -i reconnect
logs/alpaca_fabric.log` returned ZERO matches. Root cause:
AlpacaRealtimeFabric._run() incremented `self.counters["reconnects"]`
whenever websocket.run_forever() returned, with no log line and no
persisted event -- so 388 was an uninterpretable scalar. It was
impossible to answer the only question that matters ("did those
reconnects damage the information stream?") from the artifact.

THE COUNTER LAW: no reconnect counter may increment without a durable
event. reconcile() compares counter vs ledger and returns
COUNTER_LEDGER_MISMATCH when they disagree -- an unexplained 388 is now
a health state, not a mystery.

CAUSE CODES ARE NOT INTERCHANGEABLE. "the socket dropped" and "this
symbol simply did not trade for 90 seconds" are different facts with
different implications, and conflating them is how a quiet stock gets
misreported as a data outage.

decision_power: NONE. This module records and classifies; it authorizes
nothing and changes no threshold.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

LEDGER = Path("results/intraday/alpaca_reconnect_events.jsonl")

# Each of these is a DISTINCT fact. They may never be collapsed.
REASON_CODES = (
    "NETWORK_RECONNECT",      # our socket died (local network / transport)
    "PROVIDER_RECONNECT",     # provider closed or cycled the connection
    "RESUBSCRIBE",            # subscription set re-sent, socket stayed up
    "HEARTBEAT_TIMEOUT",      # ping/pong deadline missed
    "NO_TRADES_OCCURRED",     # feed healthy, symbol simply did not print
    "NO_QUOTES_OCCURRED",     # feed healthy, no quote update for symbol
    "BAR_INCOMPLETE",         # bar built from partial in-minute coverage
    "PROVIDER_DATA_GAP",      # provider acknowledged / evidenced missing data
    "LOCAL_PROCESS_GAP",      # our process stalled (GC, CPU starvation, sleep)
    "MESSAGE_STREAM_STALE",   # L2 remedy watchdog: no data frame AND no
                              # pong for LIVENESS_STALE_S -- the only
                              # staleness that may kill a connection
    "UNKNOWN_CAUSE",          # reconnect observed, no diagnostic evidence --
                              # Phase 11 law: say UNKNOWN and attach the raw
                              # telemetry, never a confident label the
                              # evidence cannot support
)

# Codes that represent an actual transport interruption -- only these
# may increment the reconnect counter.
TRANSPORT_INTERRUPTION_CODES = (
    "NETWORK_RECONNECT", "PROVIDER_RECONNECT", "HEARTBEAT_TIMEOUT",
    "LOCAL_PROCESS_GAP", "UNKNOWN_CAUSE", "MESSAGE_STREAM_STALE",
)

SOCKET_STATES = ("OPEN", "CLOSED", "CONNECTING", "UNKNOWN")
STREAM_STATES = ("SUBSCRIBED", "UNSUBSCRIBED", "DEGRADED", "UNKNOWN")

RECONCILIATION_STATES = ("RECONCILED", "COUNTER_LEDGER_MISMATCH")


class ReconnectLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReconnectEvent:
    event_id: str
    event_time: str
    known_from: str
    reason: str
    exception: str | None
    socket_state_before: str
    socket_state_after: str
    trade_stream_state: str
    quote_stream_state: str
    subscriptions_expected: int | None
    subscriptions_restored: int | None
    disconnect_duration_ms: float | None
    first_message_after_reconnect: str | None
    symbols_missing_before: tuple
    symbols_missing_after: tuple
    source: str
    decision_power: str = "NONE"
    # Phase 11 (2026-08-20): raw diagnostic evidence -- close code/msg,
    # exception type/repr, queue+worker gauges AT the event, run_forever
    # return. The `reason` is DERIVED from this; the evidence itself is
    # always persisted so a wrong derivation stays auditable.
    telemetry: dict | None = None

    def __post_init__(self):
        if self.reason not in REASON_CODES:
            raise ReconnectLedgerError(f"unknown reason code {self.reason!r}")
        for s in (self.socket_state_before, self.socket_state_after):
            if s not in SOCKET_STATES:
                raise ReconnectLedgerError(f"unknown socket state {s!r}")
        for s in (self.trade_stream_state, self.quote_stream_state):
            if s not in STREAM_STATES:
                raise ReconnectLedgerError(f"unknown stream state {s!r}")

    def as_record(self) -> dict:
        return {"kind": "alpaca_reconnect_event", **asdict(self)}

    def is_transport_interruption(self) -> bool:
        return self.reason in TRANSPORT_INTERRUPTION_CODES


def make_event(*, event_id: str, event_time, known_from, reason: str,
               source: str, exception: str | None = None,
               socket_state_before: str = "UNKNOWN",
               socket_state_after: str = "UNKNOWN",
               trade_stream_state: str = "UNKNOWN",
               quote_stream_state: str = "UNKNOWN",
               subscriptions_expected: int | None = None,
               subscriptions_restored: int | None = None,
               disconnect_duration_ms: float | None = None,
               first_message_after_reconnect: str | None = None,
               symbols_missing_before: tuple = (),
               symbols_missing_after: tuple = (),
               telemetry: dict | None = None) -> ReconnectEvent:
    import pandas as pd
    return ReconnectEvent(
        event_id=event_id, event_time=str(pd.Timestamp(event_time)),
        known_from=str(pd.Timestamp(known_from)), reason=reason,
        exception=exception, socket_state_before=socket_state_before,
        socket_state_after=socket_state_after,
        trade_stream_state=trade_stream_state,
        quote_stream_state=quote_stream_state,
        subscriptions_expected=subscriptions_expected,
        subscriptions_restored=subscriptions_restored,
        disconnect_duration_ms=disconnect_duration_ms,
        first_message_after_reconnect=first_message_after_reconnect,
        symbols_missing_before=tuple(symbols_missing_before),
        symbols_missing_after=tuple(symbols_missing_after),
        telemetry=telemetry, source=source)


def persist(event: ReconnectEvent) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, event.as_record())


def read_all(path: Path | None = None) -> list:
    p = path or LEDGER
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def reconcile(counter_value: int, path: Path | None = None,
              since: str | None = None) -> dict:
    """THE COUNTER LAW. A reconnect counter that exceeds its durable
    event record is not 'mostly fine' -- it is unexplained, and this
    returns COUNTER_LEDGER_MISMATCH so health surfaces it instead of
    printing a bare integer nobody can interpret.

    `since` (2026-08-20 windowing fix): the counter is PER-PROCESS but
    the ledger file is MULTI-DAY. The 2026-08-20 forensics compared the
    day's counter (278) against the whole file (644 = Wed 366 + Thu 278)
    and mislabeled a perfectly reconciled day COUNTER_LEDGER_MISMATCH.
    Pass the process start (or session open) as `since` to window the
    ledger to the counter's own lifetime; omitting it keeps the old
    whole-file behavior for whole-file counters."""
    events = read_all(path)
    if since is not None:
        events = [e for e in events
                  if str(e.get("event_time", "")) >= str(since)]
    transport_events = [e for e in events
                        if e.get("reason") in TRANSPORT_INTERRUPTION_CODES]
    ledger_count = len(transport_events)
    reconciled = (counter_value == ledger_count)
    return {
        "kind": "reconnect_counter_reconciliation",
        "counter_value": counter_value,
        "window_since": since,
        "ledger_transport_event_count": ledger_count,
        "ledger_total_event_count": len(events),
        "state": "RECONCILED" if reconciled else "COUNTER_LEDGER_MISMATCH",
        "unexplained_increments": max(0, counter_value - ledger_count),
        "reason_breakdown": _reason_breakdown(events),
        "decision_power": "NONE",
    }


def _reason_breakdown(events: list) -> dict:
    out: dict = {}
    for e in events:
        r = e.get("reason", "UNKNOWN")
        out[r] = out.get(r, 0) + 1
    return dict(sorted(out.items()))
