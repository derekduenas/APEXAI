"""Exact time-to-expiry — F "use exact time-to-expiry, not crude
integer DTE". A contract expiring in 6 hours and one expiring in 23
hours both round to "0 DTE" under integer day-counting; that distinction
matters enormously for theta and for IV solving near expiry. This
module always returns a fractional-year float computed from real
timestamps.
"""
from __future__ import annotations

import pandas as pd

DAYS_PER_YEAR = 365.0
US_EQUITY_OPTION_EXPIRY_TIME_ET = "16:00:00"   # standard equity option expiry


class TimeToExpiryError(RuntimeError):
    pass


def expiry_timestamp(expiry_date: str, *, tz: str = "America/New_York") -> pd.Timestamp:
    """`expiry_date`: 'YYYY-MM-DD'. Standard US equity options expire at
    market close (16:00 ET), not midnight -- treating expiry as midnight
    silently gives every same-day contract 16 extra hours of fake life."""
    ts = pd.Timestamp(f"{expiry_date} {US_EQUITY_OPTION_EXPIRY_TIME_ET}")
    if ts.tzinfo is None:
        ts = ts.tz_localize(tz)
    return ts


def year_fraction(now, expiry_date: str) -> float:
    """Actual/365, sub-day precision. Negative or zero results (an
    already-expired contract) are refused rather than silently clamped
    -- a caller with a stale `now` needs to know, not get a fake 0."""
    now = pd.Timestamp(now)
    exp = expiry_timestamp(expiry_date)
    if now.tzinfo is None:
        now = now.tz_localize(exp.tzinfo)
    delta_seconds = (exp - now).total_seconds()
    if delta_seconds <= 0:
        raise TimeToExpiryError(
            f"expiry {expiry_date} is not in the future relative to {now} -- "
            f"this contract has already expired")
    return delta_seconds / (DAYS_PER_YEAR * 86400.0)
