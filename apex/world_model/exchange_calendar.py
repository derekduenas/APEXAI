"""NYSE regular-session calendar 2016-2026 for World Model research.

The regular session is defined in exchange-local wall time
(America/New_York, 09:30 to 16:00, early closes 13:00) and CONVERTED to UTC
per date. A fixed UTC window cannot represent it: the same UTC hour is
regular in summer and pre-market in winter, and an early close is a
different day, not a different clock.

Per-timestamp classification is delegated to the governed machinery in
apex.intraday.sessions.classify, fed with the multi-year tables below.

WHAT THE TABLES ARE
Rule-derived observed holidays plus two explicit tables (Good Friday and
special closures) and the early-close rule (July 3 / day after Thanksgiving
/ December 24 when those fall on a weekday and are not themselves observed
holidays). Verified against the reproduction fixtures and the corpus' own
inception dates; NOT independently verified against every year's exchange
notice -- state this when citing. A wrong table degrades to refused rows
(SESSION_DATE_MISMATCH / NOT_A_SESSION), never to invented ones.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apex.intraday import sessions as S

ET = ZoneInfo("America/New_York")
CALENDAR_VERSION = "NYSE_REGULAR_SESSION_CALENDAR_V0_2016_2026"
YEARS = range(2016, 2027)
REGULAR_OPEN = "09:30"
REGULAR_CLOSE = "16:00"
EARLY_CLOSE = "13:00"

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


def session_bounds(session_date: str) -> dict:
    """UTC open/close instants of the regular session on `session_date`
    (an exchange-local calendar date). Refuses non-sessions by name."""
    d = date.fromisoformat(session_date)
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
            "calendar_version": CALENDAR_VERSION}


def classify_utc(ts_utc: float) -> str:
    """Governed classification (apex.intraday.sessions.classify) with the
    multi-year tables. Returns the Session enum's value."""
    return S.classify(datetime.fromtimestamp(ts_utc, timezone.utc),
                      early_closes=EARLY_CLOSES, holidays=HOLIDAYS).value


def local_date(ts_utc: float) -> str:
    return datetime.fromtimestamp(ts_utc, timezone.utc).astimezone(ET).date().isoformat()
