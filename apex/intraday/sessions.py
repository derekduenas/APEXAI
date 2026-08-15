"""Session/calendar logic: UTC canonical, exchange interpretation separate.

Handles DST (sessions are defined in exchange-local wall time and CONVERTED
to UTC per date), early closes, holidays, and the constitutional rule that
a missing minute is DATA, never a forward-fill.
"""

from __future__ import annotations

from enum import Enum
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


class Session(Enum):
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    POSTMARKET = "POSTMARKET"
    CLOSED = "CLOSED"


# early closes by date (extend from an authoritative calendar at ingestion;
# fixture-grade seed here, marked as such)
EARLY_CLOSES = {"2026-11-27": "13:00"}
HOLIDAYS = set()   # populated from the vendor calendar at ingestion


def classify(ts_utc, early_closes=None, holidays=None) -> Session:
    """Session of a UTC timestamp, via exchange-local wall time (DST-safe:
    the SAME UTC hour maps to different sessions across a DST boundary,
    which is exactly the counterexample the tests run)."""
    early_closes = EARLY_CLOSES if early_closes is None else early_closes
    holidays = HOLIDAYS if holidays is None else holidays
    local = pd.Timestamp(ts_utc).tz_convert(ET)
    d = str(local.date())
    if local.weekday() >= 5 or d in holidays:
        return Session.CLOSED
    close_wall = early_closes.get(d, "16:00")
    hm = local.strftime("%H:%M")
    if "04:00" <= hm < "09:30":
        return Session.PREMARKET
    if "09:30" <= hm < close_wall:
        return Session.REGULAR
    if close_wall <= hm < "20:00":
        return Session.POSTMARKET
    return Session.CLOSED


def expected_regular_minutes(date: str, early_closes=None) -> int:
    early_closes = EARLY_CLOSES if early_closes is None else early_closes
    close_wall = early_closes.get(date, "16:00")
    h, m = map(int, close_wall.split(":"))
    return (h - 9) * 60 + (m - 30)
