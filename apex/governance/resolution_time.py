"""RESOLUTION TIME — processing time may never decide economics.

Written 2026-08-24 after Day-1 Defect A: a card whose sealed exit rule
said SESSION_CLOSE was resolved against the last bar that happened to
be in the database when the resolver ran (16:27 ET), which was an
after-hours print. The sign of the thesis verdict flipped on it.

    RESOLUTION_RULE   determines the eligible observation window.
    PROCESSING_TIME   must never determine the economic outcome.

A resolver may execute at 16:01, 16:27 or 19:00. For a SESSION_CLOSE
card all three must produce an identical economic resolution, because
the boundary belongs to the sealed rule and the trading calendar --
never to the clock on the wall when the job happened to run.

CALENDAR HONESTY. Most sessions close at 16:00 ET, but half-days and
holidays exist and a wrong assumption silently changes outcomes. Dates
this module has not explicitly verified are resolved as
ASSUMED_STANDARD and say so, so an unverified assumption is visible in
the record rather than buried in a default.

INSTRUMENT HONESTY. The underlying's session and the option's session
are not the same instrument. ETF options (SPY/QQQ/IWM) quote until
16:15 ET while their underlying stops at 16:00. Resolving an option
mark against the equity boundary -- or vice versa -- would be the same
class of error in a different costume.

decision_power: NONE -- a governance primitive.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date as _date
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
NOT_ESTIMABLE = "NOT_ESTIMABLE"

RESOLUTION_HORIZONS = ("REGULAR_SESSION_CLOSE", "STOP_OR_TARGET",
                       "FIXED_WINDOW", "EXPIRATION")

# Instrument classes and their official regular-session end (ET).
INSTRUMENT_CLOSE_ET = {
    "EQUITY": time(16, 0),
    "EQUITY_OPTION": time(16, 0),
    "ETF_OPTION": time(16, 15),      # SPY/QQQ/IWM et al quote past 16:00
    "INDEX_OPTION": time(16, 15),
}

# Symbols whose listed options quote in the extended 16:15 window.
ETF_OPTION_SYMBOLS = {"SPY", "QQQ", "IWM", "DIA", "EEM", "XLF", "GLD",
                      "TLT", "SLV", "EFA", "HYG", "XLE"}

# Explicitly verified 2026 US equity-market exceptions. Anything absent
# is ASSUMED_STANDARD and labelled as such.
HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}
HALF_DAYS_2026 = {                    # 13:00 ET equity close
    "2026-11-27", "2026-12-24",
}
VERIFIED_YEARS = {2026}


class ResolutionViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolutionBoundary:
    session: str
    instrument_class: str
    close_et: str
    close_utc: str
    calendar_pedigree: str           # VERIFIED | ASSUMED_STANDARD
    is_half_day: bool
    law: str = ("processing time may never determine economic "
                "resolution; the boundary belongs to the sealed rule")

    def as_record(self) -> dict:
        return {"kind": "resolution_boundary", **asdict(self)}


def instrument_class_for(symbol: str, *, option: bool) -> str:
    if not option:
        return "EQUITY"
    return ("ETF_OPTION" if symbol.upper() in ETF_OPTION_SYMBOLS
            else "EQUITY_OPTION")


def regular_session_close(session: str | _date, *,
                          instrument_class: str = "EQUITY"
                          ) -> ResolutionBoundary:
    """The official regular-session close for a date and instrument."""
    if instrument_class not in INSTRUMENT_CLOSE_ET:
        raise ResolutionViolation(
            f"unknown instrument_class {instrument_class!r}")
    s = str(session)[:10]
    d = datetime.strptime(s, "%Y-%m-%d").date()
    if d.weekday() >= 5 or s in HOLIDAYS_2026:
        raise ResolutionViolation(
            f"{s} is not a trading session (weekend or holiday); a "
            f"card cannot resolve at a close that does not exist")

    half = s in HALF_DAYS_2026
    if half:
        # on a half day the equity close is 13:00 and options follow the
        # same 15-minute extension where they have one
        base = time(13, 0)
        if instrument_class in ("ETF_OPTION", "INDEX_OPTION"):
            base = time(13, 15)
    else:
        base = INSTRUMENT_CLOSE_ET[instrument_class]

    pedigree = ("VERIFIED" if d.year in VERIFIED_YEARS
                else "ASSUMED_STANDARD")
    close_et = datetime.combine(d, base, tzinfo=ET)
    return ResolutionBoundary(
        session=s, instrument_class=instrument_class,
        close_et=close_et.isoformat(),
        close_utc=close_et.astimezone(timezone.utc).isoformat(),
        calendar_pedigree=pedigree, is_half_day=half)


def to_utc(ts, *, assume: str = "ET"):
    """One canonical timezone-aware representation.

    Day-1 Defect B was a naive ET timestamp compared against a naive
    UTC timestamp -- a four-hour offset that silently admitted 88
    minutes of pre-entry bars into a trade's realized path. Naive
    comparisons are not permitted anywhere downstream of this function.
    """
    import pandas as pd
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        zone = ET if assume.upper() == "ET" else timezone.utc
        t = t.tz_localize(zone)
    return t.tz_convert("UTC")


def eligible_window(*, entry_ts, session: str, symbol: str,
                    option: bool, horizon: str = "REGULAR_SESSION_CLOSE",
                    entry_assume: str = "ET") -> dict:
    """The causally eligible observation window for one sealed trade.

    A realized path may contain only observations strictly AFTER the
    entry and no later than the sealed boundary."""
    if horizon not in RESOLUTION_HORIZONS:
        raise ResolutionViolation(f"unknown horizon {horizon!r}")
    b = regular_session_close(
        session, instrument_class=instrument_class_for(symbol,
                                                       option=option))
    return {"kind": "eligible_window",
            "entry_utc": to_utc(entry_ts, assume=entry_assume).isoformat(),
            "boundary_utc": b.close_utc,
            "horizon": horizon,
            "boundary": b.as_record(),
            "law": "observations must satisfy entry < t <= boundary"}
