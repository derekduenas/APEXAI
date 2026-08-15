"""The ReplayClock and event bus: information is revealed sequentially,
deterministically, in bounded memory.

THE RULE: a minute bar timestamped 09:30 describes 09:30:00-09:30:59 and
becomes visible at its COMPLETION (09:31:00), never before. At 09:30:59 the
clock refuses to show it. This is where intraday lookahead dies or thrives;
it dies here, and the counterexamples prove the refusal.

Determinism: same partitions + config + window -> the same typed event
stream -> the same stream hash. Memory: partitions are consumed via
generators one day at a time; nothing materializes the full history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from apex.intraday.contract import IntradayDataError
from apex.intraday.sessions import Session, classify


class EventType(Enum):
    SESSION_STATE = "SESSION_STATE"
    BAR_AVAILABLE = "BAR_AVAILABLE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    REFERENCE_UPDATE = "REFERENCE_UPDATE"
    DATA_HEALTH = "DATA_HEALTH"


@dataclass(frozen=True)
class ReplayEvent:
    event_type: EventType
    visible_at_utc: str          # when the agent may see it
    payload: dict


BAR_RESOLUTION = pd.Timedelta(minutes=1)


class ReplayClock:
    """Sequential reveal. `now` only advances; queries beyond `now` refuse."""

    def __init__(self, start_utc):
        self.now = pd.Timestamp(start_utc)
        if self.now.tzinfo is None:
            raise IntradayDataError("replay time must be timezone-aware UTC")

    def advance_to(self, ts_utc) -> None:
        t = pd.Timestamp(ts_utc)
        if t < self.now:
            raise IntradayDataError("the clock does not run backwards")
        self.now = t

    def bar_visible(self, bar_event_time_utc) -> bool:
        """A bar stamped T covers [T, T+1min) and is visible from T+1min."""
        completion = pd.Timestamp(bar_event_time_utc) + BAR_RESOLUTION
        return completion <= self.now

    def require_visible(self, bar_event_time_utc) -> None:
        if not self.bar_visible(bar_event_time_utc):
            raise IntradayDataError(
                f"bar {bar_event_time_utc} completes at "
                f"{pd.Timestamp(bar_event_time_utc) + BAR_RESOLUTION} but the "
                f"clock reads {self.now}: NO LOOKAHEAD THROUGH BAR "
                f"CONSTRUCTION.")


def replay_events(bars_by_day, start_utc, end_utc, *,
                  dataset_fingerprint: str, adapter_version: str,
                  config_hash: str):
    """Generator of typed events in visibility order, one day-partition at a
    time (bounded memory). `bars_by_day` is an iterator of (date, DataFrame)
    -- the caller streams partitions; this function never concatenates them.
    A missing minute yields NOTHING (absence is data); a duplicate
    (symbol, minute) raises."""
    start, end = pd.Timestamp(start_utc), pd.Timestamp(end_utc)
    last_session = None
    for date, frame in bars_by_day:
        if frame.duplicated(subset=["provider_symbol", "event_time_utc"]).any():
            raise IntradayDataError(
                f"partition {date}: duplicate (symbol, minute) rows cannot be "
                f"silently accepted")
        frame = frame.sort_values("event_time_utc")
        for _, row in frame.iterrows():
            t = pd.Timestamp(row["event_time_utc"])
            visible = t + BAR_RESOLUTION
            if visible < start or visible > end:
                continue
            sess = classify(visible)
            if sess != last_session:
                yield ReplayEvent(EventType.SESSION_STATE, str(visible),
                                  {"session": sess.value})
                last_session = sess
            yield ReplayEvent(EventType.BAR_AVAILABLE, str(visible), {
                "provider_symbol": row["provider_symbol"],
                "bar_time": str(t),
                "open": row["open"], "high": row["high"],
                "low": row["low"], "close": row["close"],
                "volume": row["volume"],
            })


def stream_hash(events, *, dataset_fingerprint, adapter_version,
                config_hash) -> str:
    """Canonical hash of the full event stream + its provenance tuple.
    Same inputs -> same hash, or replay is not replay."""
    h = hashlib.sha256()
    h.update(json.dumps({"fp": dataset_fingerprint, "av": adapter_version,
                         "cfg": config_hash}, sort_keys=True).encode())
    for e in events:
        h.update(json.dumps({"t": e.event_type.value, "v": e.visible_at_utc,
                             "p": e.payload}, sort_keys=True,
                            default=str).encode())
    return h.hexdigest()
