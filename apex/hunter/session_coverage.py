"""SessionCoverage — the first-class answer to "do we actually know what
happened since the true market open?"

Built in response to the 2026-08-17 Day-1 defect: ChartState treated the
first OBSERVED bar as session open (`open_t = times.iloc[0]`), silently
corrupting every session-anchored feature when live observation began
late. This module makes "was the true open observed, and is coverage
since then complete enough to trust" a computed, typed fact — never
inferred from where the data happens to start.

Built on the existing DST/holiday/early-close-aware calendar in
apex/intraday/sessions.py (classify, EARLY_CLOSES, HOLIDAYS,
expected_regular_minutes) — this module does not reimplement calendar
logic, it answers a narrower question against it: how much of the
required regular session is legitimately covered, continuously, as of T.

decision_power: NONE. This module computes coverage facts only; it does
not authorize, rank, or threshold anything.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from apex.intraday.sessions import (
    EARLY_CLOSES, ET, HOLIDAYS, Session, classify,
)

FULL = "FULL"
PARTIAL = "PARTIAL"
DEGRADED = "DEGRADED"
INVALID = "INVALID"

# below this fraction of required minutes actually observed (opening
# valid but with real holes), coverage reads DEGRADED rather than PARTIAL
DEGRADED_COVERAGE_FLOOR = 0.5


class SessionCoverageViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionCoverage:
    session_date: str
    exchange_calendar: str = "NYSE"
    session_open: str | None = None
    session_close: str | None = None

    required_start: str | None = None
    observed_start: str | None = None

    required_minutes: int = 0
    observed_minutes: int = 0
    missing_intervals: tuple = ()        # ((start_iso, end_iso), ...)

    continuous_since: str | None = None
    latest_observation: str | None = None

    coverage_fraction: float = 0.0

    opening_observed: bool = False
    session_anchor_valid: bool = False

    transport_source: str | None = None
    transport_birth: str | None = None

    quality: str = INVALID

    known_from: str | None = None
    as_of: str | None = None

    def as_record(self) -> dict:
        return {"kind": "session_coverage", **asdict(self)}


def _true_session_bounds(session_date: str) -> tuple:
    """(session_open_utc, session_close_utc) as tz-aware UTC Timestamps,
    or (None, None) if session_date is not a trading day (weekend or
    holiday) -- computed from the calendar, never from data."""
    d = pd.Timestamp(session_date)
    if d.weekday() >= 5 or session_date in HOLIDAYS:
        return None, None
    close_wall = EARLY_CLOSES.get(session_date, "16:00")
    ch, cm = map(int, close_wall.split(":"))
    open_local = pd.Timestamp(f"{session_date} 09:30", tz=ET)
    close_local = pd.Timestamp(session_date, tz=ET) + \
        pd.Timedelta(hours=ch, minutes=cm)
    return open_local.tz_convert("UTC"), close_local.tz_convert("UTC")


def compute_session_coverage(
    bars: "pd.DataFrame", session_date: str, as_of, *,
    transport_source: str | None = None,
    transport_birth: str | None = None,
    known_from: str | None = None,
) -> SessionCoverage:
    """Compute coverage from raw bars (ANY session filter, this function
    does its own) against the TRUE calendar session boundary. Never
    infers session_open from bars.

    `bars` must carry an `event_time_utc` column (bar START time, 1m
    width, completed-bar semantics matching visible_bars/ChartState).
    """
    t = pd.Timestamp(as_of)
    if t.tzinfo is None:
        raise SessionCoverageViolation("as_of must be tz-aware")
    session_open, session_close = _true_session_bounds(session_date)
    if session_open is None:
        return SessionCoverage(
            session_date=session_date, quality=INVALID,
            as_of=str(t), known_from=known_from,
            transport_source=transport_source,
            transport_birth=transport_birth)

    required_start = session_open
    required_end = min(t, session_close)
    required_minutes = max(
        0, int((required_end - required_start).total_seconds() // 60))

    if bars is None or not len(bars) or "event_time_utc" not in bars:
        return SessionCoverage(
            session_date=session_date,
            session_open=str(session_open), session_close=str(session_close),
            required_start=str(required_start), required_minutes=required_minutes,
            quality=INVALID, as_of=str(t), known_from=known_from,
            transport_source=transport_source, transport_birth=transport_birth)

    reg = bars[bars["event_time_utc"].map(
        lambda x: classify(x) is Session.REGULAR)]
    reg = reg[reg["event_time_utc"] + pd.Timedelta(minutes=1) <= t]
    # out-of-order input and duplicate bars are both legitimate transport
    # realities (a reconnect can redeliver, a bar can arrive late) --
    # never let either corrupt observed_start/observed_minutes
    reg = reg.sort_values("event_time_utc")
    reg = reg.drop_duplicates(subset="event_time_utc", keep="last")

    if reg.empty:
        return SessionCoverage(
            session_date=session_date,
            session_open=str(session_open), session_close=str(session_close),
            required_start=str(required_start), required_minutes=required_minutes,
            quality=INVALID, as_of=str(t), known_from=known_from,
            transport_source=transport_source, transport_birth=transport_birth)

    observed_start = reg["event_time_utc"].iloc[0]
    observed_minutes = int(len(reg))          # 1m bars, dedup upstream

    # missing_intervals: every regular-session minute in [required_start,
    # required_end) with no bar, run-length encoded (never a per-minute
    # list -- that would be unbounded on long gaps)
    all_minutes = pd.date_range(required_start, required_end,
                                freq="1min", inclusive="left")
    observed_set = set(reg["event_time_utc"])
    missing = [m for m in all_minutes if m not in observed_set]
    intervals = []
    if missing:
        run_start = missing[0]
        prev = missing[0]
        for m in missing[1:]:
            if (m - prev) > pd.Timedelta(minutes=1):
                intervals.append((str(run_start), str(prev + pd.Timedelta(minutes=1))))
                run_start = m
            prev = m
        intervals.append((str(run_start), str(prev + pd.Timedelta(minutes=1))))

    opening_observed = observed_start <= session_open
    # continuous_since: the start of the run of observed minutes leading
    # up to `t` with no gap -- None if even the most recent minute is
    # missing
    continuous_since = None
    if all_minutes.size and (all_minutes[-1] in observed_set
                             or observed_minutes and
                             reg["event_time_utc"].iloc[-1] + pd.Timedelta(minutes=1) >= required_end):
        run = required_end - pd.Timedelta(minutes=1)
        while run >= required_start and run in observed_set:
            run -= pd.Timedelta(minutes=1)
        continuous_since = str(run + pd.Timedelta(minutes=1))

    coverage_fraction = (round(observed_minutes / required_minutes, 4)
                        if required_minutes > 0 else 0.0)
    session_anchor_valid = bool(opening_observed and not (
        intervals and intervals[0][0] == str(session_open)))
    # anchor valid means: the run of bars covering the TRUE open exists
    # unbroken up to at least the first missing interval (or no missing
    # interval at all before the opening leg)
    if opening_observed and intervals:
        first_gap_start = pd.Timestamp(intervals[0][0])
        session_anchor_valid = first_gap_start > observed_start
    elif opening_observed:
        session_anchor_valid = True
    else:
        session_anchor_valid = False

    if not opening_observed:
        quality = INVALID
    elif not intervals:
        quality = FULL
    elif coverage_fraction >= DEGRADED_COVERAGE_FLOOR:
        quality = PARTIAL
    else:
        quality = DEGRADED

    return SessionCoverage(
        session_date=session_date,
        session_open=str(session_open), session_close=str(session_close),
        required_start=str(required_start), observed_start=str(observed_start),
        required_minutes=required_minutes, observed_minutes=observed_minutes,
        missing_intervals=tuple(intervals),
        continuous_since=continuous_since,
        latest_observation=str(reg["event_time_utc"].iloc[-1]),
        coverage_fraction=coverage_fraction,
        opening_observed=bool(opening_observed),
        session_anchor_valid=bool(session_anchor_valid),
        transport_source=transport_source, transport_birth=transport_birth,
        quality=quality, known_from=known_from, as_of=str(t))
