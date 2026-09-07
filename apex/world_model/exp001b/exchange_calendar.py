"""NYSE regular-session calendar 2016-2026 for World Model research.

The regular session is defined in exchange-local wall time
(America/New_York, 09:30 to 16:00, early closes 13:00) and CONVERTED to UTC
per date. A fixed UTC window cannot represent it: the same UTC hour is
regular in summer and pre-market in winter, and an early close is a
different day, not a different clock.

Per-timestamp classification reproduces the governed rule of
apex.intraday.sessions.classify (wall-clock windows in America/New_York)
WITHOUT importing it: the World Model laboratory may import only within
apex.world_model (frozen authority law), so parity with the production
module is proven from the test side (tests/test_exchange_calendar.py)
rather than by import.

WHAT THE TABLES ARE
Rule-derived observed holidays plus two explicit tables (Good Friday and
special closures) and the early-close rule (July 3 / day after Thanksgiving
/ December 24 when those fall on a weekday and are not themselves observed
holidays).

A WRONG TABLE DOES NOT FAIL CLOSED -- CORRECTION OF AN EARLIER CLAIM
An earlier version of this file claimed a wrong entry "degrades to refused
rows, never to invented ones". That is FALSE and was reproduced:

  * an OMITTED early close makes the loader accept that day's 13:00-16:00
    ET bars as regular-session observations -- more rows, no refusal;
  * an ADDED early close makes the loader silently DISCARD valid afternoon
    bars -- fewer rows, no refusal (they are counted in
    dropped_outside_session, but nothing refuses).

Only a HOLIDAY error fails closed (NOT_A_SESSION), and only because the
loader is handed a session date. So the tables carry an explicit
VERIFICATION record, and session_bounds(require_verified=True) -- which the
experiment's loader always passes -- REFUSES any date outside the
independently reconciled window. That converts "unverified calendar" from a
silent distortion into a named refusal.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CALENDAR_VERSION = "NYSE_REGULAR_SESSION_CALENDAR_V0_2016_2026"
YEARS = range(2016, 2027)
REGULAR_OPEN = "09:30"
REGULAR_CLOSE = "16:00"
EARLY_CLOSE = "13:00"

# Independently reconciled against the primary exchange announcements, date
# by date, in results/exp001b_calendar_reconciliation_2016_2021.json.
VERIFICATION = {
    "window": ("2016-01-04", "2021-12-31"),
    "reconciliation": "results/exp001b_calendar_reconciliation_2016_2021.json",
    "primary_sources": [
        "NYSE Group 2016 Holiday Calendar and Early Closings (ICE IR, released 2014-12-08)",
        "NYSE Group Announces 2017 Holiday and Early Closings Calendar (ICE IR, released 2016-02-02)",
        "NYSE Group Announces 2018, 2019 and 2020 Holiday and Early Closings Calendar (ICE IR, released 2017-11-27)",
        "NYSE Group Announces 2019, 2020 and 2021 Holiday and Early Closings Calendar (ICE IR, released 2018-12-04)",
        "New York Stock Exchange to Honor President George H. W. Bush (ICE IR, 2018) -- 2018-12-05 closure",
    ],
    "outside_window": "NOT_INDEPENDENTLY_VERIFIED (2022-2026 tables are rule-derived only)",
}
VERIFIED_START, VERIFIED_END = VERIFICATION["window"]

GOOD_FRIDAY = {"2016-03-25", "2017-04-14", "2018-03-30", "2019-04-19", "2020-04-10",
               "2021-04-02", "2022-04-15", "2023-04-07", "2024-03-29", "2025-04-18",
               "2026-04-03"}
SPECIAL_CLOSURES = {"2018-12-05": "National Day of Mourning (G.H.W. Bush)",
                    "2025-01-09": "National Day of Mourning (J. Carter)"}


def _nth_weekday(y, m, weekday, n):
    d = date(y, m, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(days=7 * (n - 1))


def _last_weekday(y, m, weekday):
    d = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date, *, new_year=False):
    """Saturday -> Friday, Sunday -> Monday. New Year's on a Saturday is
    NOT observed on the prior Friday (exchange rule)."""
    if d.weekday() == 5:
        return None if new_year else d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def holidays() -> set:
    out = set()
    for y in YEARS:
        for d in (_observed(date(y, 1, 1), new_year=True), _nth_weekday(y, 1, 0, 3),
                  _nth_weekday(y, 2, 0, 3), _last_weekday(y, 5, 0),
                  _observed(date(y, 6, 19)) if y >= 2022 else None,
                  _observed(date(y, 7, 4)), _nth_weekday(y, 9, 0, 1),
                  _nth_weekday(y, 11, 3, 4), _observed(date(y, 12, 25))):
            if d is not None:
                out.add(d.isoformat())
    return out | GOOD_FRIDAY | set(SPECIAL_CLOSURES)


def early_closes() -> dict:
    hol = holidays()
    out = {}
    for y in YEARS:
        cands = [date(y, 7, 3), _nth_weekday(y, 11, 3, 4) + timedelta(days=1), date(y, 12, 24)]
        for d in cands:
            if d.weekday() < 5 and d.isoformat() not in hol:
                out[d.isoformat()] = EARLY_CLOSE
    return out


HOLIDAYS = frozenset(holidays())
EARLY_CLOSES = early_closes()


class NotASession(Exception):
    """The date is a weekend, a holiday or outside the calendar's range."""


def session_bounds(session_date: str, *, require_verified: bool = False) -> dict:
    """UTC open/close instants of the regular session on `session_date`
    (an exchange-local calendar date). Refuses non-sessions by name.

    require_verified=True additionally refuses any date whose calendar entry
    has not been independently reconciled against the exchange record. The
    experiment's loader always passes it, because a silently wrong early
    close changes the data without refusing anything."""
    d = date.fromisoformat(session_date)
    if require_verified and not (VERIFIED_START <= session_date <= VERIFIED_END):
        raise NotASession(
            "CALENDAR_NOT_VERIFIED: %s is outside the independently reconciled window %s..%s; "
            "the entry for this date is rule-derived only, and a wrong early close would change "
            "the session silently rather than refuse" % (session_date, VERIFIED_START, VERIFIED_END))
    if d.year not in YEARS:
        raise NotASession("OUTSIDE_CALENDAR_RANGE: %s not in %d..%d" % (session_date, YEARS[0], YEARS[-1]))
    if d.weekday() >= 5:
        raise NotASession("WEEKEND: %s" % session_date)
    if session_date in HOLIDAYS:
        raise NotASession("HOLIDAY: %s" % session_date)
    close_wall = EARLY_CLOSES.get(session_date, REGULAR_CLOSE)
    o = datetime.combine(d, datetime.strptime(REGULAR_OPEN, "%H:%M").time(), tzinfo=ET)
    c = datetime.combine(d, datetime.strptime(close_wall, "%H:%M").time(), tzinfo=ET)
    return {"session_date": session_date, "open_utc": o.astimezone(timezone.utc).timestamp(),
            "close_utc": c.astimezone(timezone.utc).timestamp(),
            "early_close": session_date in EARLY_CLOSES,
            "regular_minutes": int((c - o).total_seconds() // 60),
            "utc_offset_hours": o.utcoffset().total_seconds() / 3600.0,
            "calendar_version": CALENDAR_VERSION,
            "calendar_entry_verified": VERIFIED_START <= session_date <= VERIFIED_END,
            "calendar_verified_window": list(VERIFICATION["window"])}


def classify_utc(ts_utc: float) -> str:
    """Same rule as apex.intraday.sessions.classify (parity-tested):
    PREMARKET 04:00-09:30, REGULAR 09:30-close, POSTMARKET close-20:00,
    else CLOSED; weekends and holidays CLOSED. Exchange-local wall clock."""
    local = datetime.fromtimestamp(ts_utc, timezone.utc).astimezone(ET)
    d = local.date().isoformat()
    if local.weekday() >= 5 or d in HOLIDAYS:
        return "CLOSED"
    close_wall = EARLY_CLOSES.get(d, REGULAR_CLOSE)
    hm = local.strftime("%H:%M")
    if "04:00" <= hm < REGULAR_OPEN:
        return "PREMARKET"
    if REGULAR_OPEN <= hm < close_wall:
        return "REGULAR"
    if close_wall <= hm < "20:00":
        return "POSTMARKET"
    return "CLOSED"


def local_date(ts_utc: float) -> str:
    return datetime.fromtimestamp(ts_utc, timezone.utc).astimezone(ET).date().isoformat()
