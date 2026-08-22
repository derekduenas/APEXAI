"""Discrete dividend schedule — F "explicitly model dividends". A
schedule is either a real, sourced list of (ex_date, amount) events, or
an explicit CONFIRMED_NO_DIVIDENDS declaration -- there is no third,
implicit "empty means zero" path, because an empty list from a caller
who simply never looked is indistinguishable from a real ex-dividend
name with no upcoming payout, and conflating those is exactly the kind
of silent assumption this package refuses to make.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER


class DividendScheduleError(RuntimeError):
    pass


@dataclass(frozen=True)
class DividendSchedule:
    events: tuple              # tuple of (ex_date: str, amount: float)
    confirmed_no_dividends: bool
    source: str
    as_of: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.confirmed_no_dividends and self.events:
            raise DividendScheduleError(
                "confirmed_no_dividends=True cannot carry dividend events")
        if not self.confirmed_no_dividends and not self.events:
            raise DividendScheduleError(
                "an empty schedule must explicitly set confirmed_no_dividends=True "
                "-- an unconfirmed empty schedule is UNKNOWN, not zero")

    def as_record(self) -> dict:
        return asdict(self)

    def is_known(self) -> bool:
        return True   # a DividendSchedule can only ever be constructed in a known state


def pv_of_dividends(schedule: DividendSchedule | None, *, now, expiry, rate: float) -> float | None:
    """Present value of discrete dividends paid before expiry, for
    Black's escrowed-dividend spot adjustment. None when the schedule
    itself is unknown (caller passed None, never assumed zero)."""
    import math

    import pandas as pd
    if schedule is None:
        return None
    if schedule.confirmed_no_dividends:
        return 0.0
    now = pd.Timestamp(now)
    expiry = pd.Timestamp(expiry)
    if expiry.tzinfo is None:
        expiry = expiry.tz_localize(now.tzinfo)
    pv = 0.0
    for ex_date, amount in schedule.events:
        ex_ts = pd.Timestamp(ex_date)
        if ex_ts.tzinfo is None:
            ex_ts = ex_ts.tz_localize(now.tzinfo)
        if now < ex_ts <= expiry:
            t = (ex_ts - now).total_seconds() / (365.0 * 86400.0)
            pv += amount * math.exp(-rate * t)
    return pv
