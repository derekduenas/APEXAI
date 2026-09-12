"""ANCHOR_FRESHNESS_POLICY_V1 -- an anchor is measured in SESSIONS, not seconds.

WHY THIS EXISTS (LIVE-ANCHOR-STALENESS-V1)
NKLA's sealed packet of 2026-09-01 carried a prior_close from 2025-02-24 --
553 days earlier -- flagged VALID. The vendor snapshot for a name that has
stopped printing keeps returning its last known daily bar, and PULSE had no
rule that said an anchor can be too old to describe the current market.
PULSE-009 made every derived field inherit its ingredients' trustworthiness;
this policy is what finally makes the anchor ingredient able to say no.

WHY SECONDS CANNOT EXPRESS IT
apex.pulse.freshness is a per-(source, session) tolerance in SECONDS, and it
is right for a quote. It cannot express an anchor. The immediately preceding
close is ~17.5 hours old at Tuesday's open, ~65 hours old at Monday's open,
~89 hours old after a long weekend, and every one of those is perfectly
current. Any seconds threshold wide enough for Tuesday-after-a-holiday is
wide enough to admit a bar from the previous week. The quantity that matters
is not elapsed time. It is WHICH SESSION the bar belongs to.

THE RULE, STATED ONCE

    prior_close is VALID if and only if its session is the exchange's
    IMMEDIATELY PRECEDING regular session for this packet.

There is no tuned number in that sentence. "Immediately preceding" is a
definition, resolved against the exchange calendar that already governs
PULSE (apex.intraday.sessions: weekends, the NYSE holiday list and early
closes, with DST handled by converting exchange-local wall time per date).
Nothing here is fitted to NKLA, to a P&L, or to an observed result; a
one-off threshold would have been exactly the wrong repair.

THE CASES THE POLICY MUST TELL APART

  CURRENT_SESSION_OPEN     the opening print of the session in progress. An
                           immutable event once observed, belonging to the
                           CURRENT session, so it is never subject to this
                           policy. A stale prior close must not make today's
                           cash open stale -- they are different sessions
                           and different facts.
  IMMEDIATELY_PRECEDING    the anchor's session is the trading day directly
                           before this packet's session. VALID.
  SESSIONS_MISSED          at least one regular session sits between the
                           anchor and now, so this instrument did not print
                           when the exchange was open. STALE, with the
                           expected session named and the gap recorded. The
                           VERDICT does not depend on how large the gap is:
                           one missed session and five hundred are both "not
                           the preceding session". A halted, delisted or
                           otherwise non-printing instrument lands here by
                           the same rule rather than by a special case.
  NO_PRIOR_SESSION         the vendor supplied no prior daily bar at all --
                           a new listing, or a name with no history in the
                           window. NOT_AVAILABLE: absent, never substituted.
  UNDATED                  a vendor record with no usable session date or
                           timestamp. NOT_ESTIMABLE: an anchor whose session
                           cannot be identified cannot be judged current,
                           and guessing is how a 2025 bar became VALID.
  NOT_A_PRIOR_SESSION      the record's session is the current one or later.
                           NOT_ESTIMABLE: whatever it is, it is not a PRIOR
                           close, and calling it one would be a fabrication.
  NOT_A_TRADING_SESSION    the record is dated on a day the exchange was
                           CLOSED -- a weekend or a holiday. NOT_ESTIMABLE:
                           the exchange held no regular session then, so
                           whatever the vendor is describing, it is not one.

REFERENCE SESSION. On a trading day the expected anchor is the trading day
before it, in every session state -- premarket, regular and postmarket all
look back to the same close. When the packet falls on a non-trading day the
most recent completed session IS the prior close, so the expected anchor is
that day itself.

CALENDAR COVERAGE. The verdict never counts across the gap: it compares the
anchor's session date with the ONE expected date, resolved backwards from
the packet's own session, so it is exact even when the anchor predates the
calendar's populated year. The gap size is reported as context and is
labelled when the calendar does not cover the whole span.

decision_power: NONE_STATE. This is a data-quality statement.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from apex.intraday.sessions import EARLY_CLOSES, ET, HOLIDAYS

ANCHOR_FRESHNESS_POLICY_VERSION = "ANCHOR_FRESHNESS_POLICY_V1"
DEFECT_CLOSED = "LIVE-ANCHOR-STALENESS-V1"
MAX_LOOKBACK_DAYS = 14          # a search bound, not a tolerance: no US
                                # exchange closes for 14 consecutive days

# classifications
CURRENT_SESSION_OPEN = "CURRENT_SESSION_OPEN"
IMMEDIATELY_PRECEDING = "IMMEDIATELY_PRECEDING"
SESSIONS_MISSED = "SESSIONS_MISSED"
NO_PRIOR_SESSION = "NO_PRIOR_SESSION"
UNDATED = "UNDATED"
NOT_A_PRIOR_SESSION = "NOT_A_PRIOR_SESSION"
NOT_A_TRADING_SESSION = "NOT_A_TRADING_SESSION"
CALENDAR_UNRESOLVED = "CALENDAR_UNRESOLVED"


class AnchorCalendarUnresolved(RuntimeError):
    """The expected prior session could not be resolved from the calendar."""


def _d(value) -> date | None:
    """The exchange SESSION DATE of a vendor stamp, or None if undated."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(ET).date()
    s = str(value).strip()
    if not s:
        return None
    # A DATE-ONLY record is already a session date. Reading it as UTC midnight
    # and converting to ET would move it back one session -- 2026-09-01 would
    # be read as the 2026-08-31 session, and a bar from the CURRENT session
    # would pass as the immediately preceding one.
    if "T" not in s and " " not in s:
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        # A timestamp with no zone is UTC by the packet's own convention.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET).date()


def is_trading_day(d: date, *, holidays=None) -> bool:
    holidays = HOLIDAYS if holidays is None else holidays
    return d.weekday() < 5 and d.isoformat() not in holidays


def previous_trading_day(d: date, *, holidays=None, max_lookback=MAX_LOOKBACK_DAYS) -> date:
    """The trading day strictly before `d`."""
    for k in range(1, max_lookback + 1):
        cand = d - timedelta(days=k)
        if is_trading_day(cand, holidays=holidays):
            return cand
    raise AnchorCalendarUnresolved(
        "no trading day within %d days before %s" % (max_lookback, d.isoformat()))


def most_recent_trading_day(d: date, *, holidays=None, max_lookback=MAX_LOOKBACK_DAYS) -> date:
    """`d` itself when it is a session, else the last session before it."""
    if is_trading_day(d, holidays=holidays):
        return d
    return previous_trading_day(d, holidays=holidays, max_lookback=max_lookback)


def expected_anchor_session(packet_session_date, *, holidays=None) -> date:
    """The session a VALID prior_close must belong to.

    On a trading day: the trading day before it -- premarket, regular and
    postmarket all look back to the same close. On a non-trading day: the
    most recent completed session, which IS the prior close then."""
    d = _d(packet_session_date)
    if d is None:
        raise AnchorCalendarUnresolved("packet session date is undated")
    if is_trading_day(d, holidays=holidays):
        return previous_trading_day(d, holidays=holidays)
    return most_recent_trading_day(d, holidays=holidays)


def sessions_between(a: date, b: date, *, holidays=None) -> dict:
    """Regular sessions strictly between `a` and `b`, for CONTEXT only. The
    verdict never depends on this number; it is reported so an auditor can
    see the size of a gap. Flagged when the span leaves the populated
    calendar year, because unknown holidays would only reduce the count."""
    if a >= b:
        return {"count": 0, "calendar_covers_range": True}
    years = {int(h[:4]) for h in (HOLIDAYS if holidays is None else holidays)}
    covered = bool(years) and a.year in years and b.year in years
    n, cur = 0, a + timedelta(days=1)
    while cur < b:
        if is_trading_day(cur, holidays=holidays):
            n += 1
        cur += timedelta(days=1)
    return {"count": n, "calendar_covers_range": covered,
            "note": None if covered else
                    "the span leaves the populated holiday calendar, so this count is an upper "
                    "bound. The VERDICT does not use it: it compares the anchor's session with "
                    "the one expected session, resolved backwards from this packet."}


def classify_prior_close(*, anchor_stamp, packet_session_date, present=True,
                         holidays=None) -> dict:
    """The whole policy, as a pure function. No I/O, no clock, no thresholds."""
    rec = {"policy": ANCHOR_FRESHNESS_POLICY_VERSION, "defect_closed": DEFECT_CLOSED,
           "anchor_stamp": None if anchor_stamp is None else str(anchor_stamp),
           "packet_session_date": None}
    if not present:
        rec.update(classification=NO_PRIOR_SESSION, fresh=False,
                   why="the vendor supplied no prior daily bar; a new listing or a name with no "
                       "history in the window. Absent, never substituted.")
        return rec
    pkt = _d(packet_session_date)
    if pkt is None:
        rec.update(classification=UNDATED, fresh=False,
                   why="the packet carries no usable session date, so no anchor can be judged "
                       "against it")
        return rec
    rec["packet_session_date"] = pkt.isoformat()
    anchor = _d(anchor_stamp)
    if anchor is None:
        rec.update(classification=UNDATED, fresh=False,
                   why="the vendor record carries no usable session date or timestamp; an anchor "
                       "whose session cannot be identified cannot be judged current")
        return rec
    rec["anchor_session_date"] = anchor.isoformat()
    try:
        expected = expected_anchor_session(pkt, holidays=holidays)
    except AnchorCalendarUnresolved as e:
        rec.update(classification=CALENDAR_UNRESOLVED, fresh=False, why=str(e))
        return rec
    rec["expected_anchor_session"] = expected.isoformat()
    rec["anchor_is_a_trading_day"] = is_trading_day(anchor, holidays=holidays)
    if not rec["anchor_is_a_trading_day"]:
        rec.update(classification=NOT_A_TRADING_SESSION, fresh=False,
                   why="the record is dated %s, a day the exchange held no regular session "
                       "(weekend or holiday); whatever it describes, it is not a session close"
                       % anchor.isoformat())
        return rec
    if anchor > expected:
        rec.update(classification=NOT_A_PRIOR_SESSION, fresh=False,
                   why="the record's session %s is the current session or later; whatever it is, "
                       "it is not a PRIOR close" % anchor.isoformat())
        return rec
    if anchor == expected:
        rec.update(classification=IMMEDIATELY_PRECEDING, fresh=True,
                   sessions_missed=0,
                   why="the anchor is the exchange's immediately preceding regular session (%s)"
                       % expected.isoformat())
        return rec
    gap = sessions_between(anchor, pkt, holidays=holidays)
    rec.update(classification=SESSIONS_MISSED, fresh=False,
               sessions_missed=gap["count"], calendar_covers_range=gap["calendar_covers_range"],
               gap_note=gap.get("note"),
               why="the anchor is from %s but the immediately preceding session is %s: at least "
                   "one regular session passed with no print from this instrument (a halt, a "
                   "delisting, or a name that simply stopped trading). It is a real number and "
                   "it does not describe the current market."
                   % (anchor.isoformat(), expected.isoformat()))
    return rec


def describe() -> dict:
    return {
        "version": ANCHOR_FRESHNESS_POLICY_VERSION,
        "defect_closed": DEFECT_CLOSED,
        "measured_in": "SESSIONS, not seconds",
        "rule": "prior_close is VALID if and only if its session is the exchange's immediately "
                "preceding regular session for this packet",
        "why_not_seconds": "the preceding close is ~17.5h old at Tuesday's open and ~89h old "
                           "after a long weekend; any seconds threshold wide enough for the "
                           "second admits a bar from the previous week",
        "calendar": "apex.intraday.sessions -- weekends, the NYSE holiday list and early closes, "
                    "DST resolved per date. No naive UTC-day arithmetic.",
        "classifications": {
            CURRENT_SESSION_OPEN: "the opening print of the session in progress; immutable once "
                                  "observed and never subject to this policy",
            IMMEDIATELY_PRECEDING: "VALID",
            SESSIONS_MISSED: "STALE -- at least one regular session passed with no print",
            NO_PRIOR_SESSION: "NOT_AVAILABLE -- no prior daily bar at all",
            UNDATED: "NOT_ESTIMABLE -- no usable session date or timestamp",
            NOT_A_PRIOR_SESSION: "NOT_ESTIMABLE -- the record is the current session or later",
            NOT_A_TRADING_SESSION: "NOT_ESTIMABLE -- the record is dated on a day the exchange "
                                   "was closed",
            CALENDAR_UNRESOLVED: "NOT_ESTIMABLE -- no trading day within the search bound"},
        "no_tuned_threshold": "the only boundary is zero missed sessions, which is the DEFINITION "
                              "of 'immediately preceding', not a fitted number. Nothing here was "
                              "chosen from NKLA, from P&L or from an observed result.",
        "search_bound_days": MAX_LOOKBACK_DAYS,
        "decision_power": "NONE_STATE",
    }
