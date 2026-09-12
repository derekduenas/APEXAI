"""CAUSAL CLOCK CONTRACT for OPTIONS-PILOT-001.

Timestamps are parsed, never compared as strings. Every recorded instant is a
timezone-aware ISO-8601 string normalised to UTC with a "Z" suffix AND an
epoch float, so a reader can check both without re-parsing. Clock readings
are finite floats. Booleans are rejected everywhere a number is required.

Field meanings (all UTC):
  reference_time      the bar the forecast is issued from (its event_time)
  target_end          reference_time + horizon, exactly
  input_event_time    the newest input observation's own event time
  input_available     when that observation became available (bar_complete)
  input_cutoff        the latest availability the forecast was allowed to use
  created             when the forecast object was produced
  persisted           when the boundary's append receipt was obtained
  intent_expiry       after which an intent may not be executed
  quote_request       clock reading immediately BEFORE asking the provider
  quote_receipt       clock reading immediately AFTER the provider returned
  quote_market_ts     the provider's own timestamp on the quote (asserted by
                      the provider; its meaning is recorded, not assumed)

Order proofs use ledger sequence numbers; timestamps are validated for
internal consistency and for not lying in the future of the controlled clock.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


class ClockRefused(ValueError):
    """A timestamp or clock reading that does not satisfy the contract."""


def is_real(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_exact_int(x) -> bool:
    return type(x) is int


def parse_utc(value, *, field: str) -> float:
    """Timezone-aware ISO-8601 string -> epoch seconds (float). Refuses
    non-strings, naive datetimes, unparseable text, and non-finite results."""
    if not isinstance(value, str) or not value:
        raise ClockRefused("%s: not a timestamp string: %r" % (field, value))
    txt = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as e:
        raise ClockRefused("%s: unparseable timestamp %r (%s)" % (field, value, e)) from e
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ClockRefused("%s: naive timestamp %r (no timezone)" % (field, value))
    epoch = dt.timestamp()
    if not math.isfinite(epoch):
        raise ClockRefused("%s: non-finite instant %r" % (field, value))
    return float(epoch)


def to_utc_string(epoch: float) -> str:
    if not is_real(epoch):
        raise ClockRefused("epoch is not a finite real: %r" % (epoch,))
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def check_reading(x, *, field: str = "clock") -> float:
    if not is_real(x):
        raise ClockRefused("%s: clock reading must be a finite real, got %r" % (field, x))
    return float(x)


class Clock:
    """A controlled clock: fixtures set it; production reads the wall."""

    def __init__(self, now_fn):
        self._now = now_fn

    def now(self) -> float:
        return check_reading(self._now(), field="clock.now")

    def now_utc(self) -> str:
        return to_utc_string(self.now())
