"""PULSE_ANCHOR_CONTRACT_V1 -- what "prior close" and "cash open" mean.

WHY THIS FILE EXISTS
The live feeder and the historical feeder disagreed about which session an
anchor belongs to, and the disagreement was invisible because both went
through the same composer. A shared composer proves the two paths apply the
same FORMULA. It proves nothing about whether they were handed the same
INPUTS. PULSE-007 measured the gap on six sealed packets from
2026-09-01T13:45:00Z:

    prior_close   live = the 2026-08-31 session close
                  replay = the 2026-08-28 session close   (5 of 5 subjects)
    dailyBar.o    live = the regular-session opening print
                  replay = the first bar of a window that began at UTC
                           midnight, i.e. a PREMARKET bar   (5 of 5)

Two independent defects with two independent causes, both in the historical
feeder, neither in the composer:

  ANCHOR-001  daily-bar admission by stamp + 24h against a UTC-midnight
              cutoff. The market-data provider stamps a daily bar at the
              session's ET midnight (04:00Z under EDT), so
              `stamp + 1 day <= UTC midnight of t` silently drops the most
              recent completed session and hands back the one before it.
  ANCHOR-002  the intraday window started at UTC midnight, which is 20:00
              ET on the PREVIOUS calendar day. The first bar in that window
              is late post-market or premarket, never the cash open, so
              `dailyBar.o` was not an opening price at all.

THE CONTRACT, STATED ONCE

  SESSION            the exchange trading session, identified by its ET
                     calendar date. Weekends, the NYSE holiday list and
                     early closes come from apex.intraday.sessions -- one
                     calendar for the whole system, DST handled by
                     converting exchange-local wall time per date.

  PRIOR CLOSE        the closing price of the most recent REGULAR session
                     STRICTLY BEFORE the session that contains the as-of
                     instant. Selected by comparing SESSION DATES, never by
                     arithmetic on a timestamp. If the vendor supplies no
                     bar for a date, that date was not a session -- the
                     vendor's own bar list is the calendar of record for
                     selection, and the holiday list is the cross-check.

  CASH OPEN          the opening print of the current REGULAR session:
                     09:30 ET, or the early-close session's same 09:30
                     open. It is NOT the first extended-hours print.

  PRICE CONVENTION   RAW and unadjusted on both sides -- the live snapshot
                     is raw, and the historical read pins the unadjusted
                     series. A split or dividend between the prior session
                     and now would otherwise move the anchor without any
                     price having moved.

  MISSING ANCHOR     absent, never substituted. No prior session in the
                     lookback (a new listing, a long halt, a name that
                     stopped printing) yields no prevDailyBar, and the
                     composer marks the dependent features NOT_AVAILABLE.
                     A stale anchor from an arbitrary earlier date is a
                     wrong number wearing a valid quality flag.

  BEFORE THE OPEN    in PREMARKET and CLOSED there is no current-session
                     cash open, so no current-session aggregate is built.
                     The composer already marks cash_open_return_bps and
                     overnight_gap_bps SESSION_INAPPLICABLE there; this
                     module refuses to manufacture the inputs they would
                     have used.

  CORRECTION         a vendor history endpoint returns the record AS IT
  AVAILABILITY       STANDS AT RETRIEVAL TIME. Nothing in a bar says when
                     its current value became available, so a bar corrected
                     after the fact is indistinguishable from the value
                     published then. This module therefore reconstructs
                     WHICH RECORD a moment refers to. It does NOT establish
                     as-known-at availability, and
                     HISTORICAL_AS_KNOWN_AVAILABILITY stays NOT_PROVEN
                     until a point-in-time source or a vendor revision feed
                     exists. Nothing here authorises corpus admission.

  LEAK DISCIPLINE    the current session's daily bar is consulted for its
                     OPENING PRICE ONLY, through an explicit field
                     allow-list, because the open is fixed at 09:30 and
                     cannot change with the rest of the day. High, low,
                     close, volume and VWAP of the current session are
                     REBUILT from minute bars whose windows closed at or
                     before the as-of instant, exactly as before. The
                     allow-list is enforced in code and tested, so the
                     completed-day fields cannot reach a packet even by
                     accident.

decision_power: NONE_STATE.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from apex.intraday.sessions import EARLY_CLOSES, ET, HOLIDAYS, Session, classify

ANCHOR_CONTRACT = "PULSE_ANCHOR_CONTRACT_V1"
REGULAR_OPEN_WALL = time(9, 30)
REGULAR_CLOSE_WALL = time(16, 0)
# The ONLY field the current session's daily bar may contribute.
CURRENT_DAILY_ALLOWED_FIELDS = ("o",)
PRIOR_LOOKBACK_DAYS = 12          # covers a long weekend plus a holiday week

DEFECTS_CLOSED = {
    "ANCHOR-001": "prior daily bar admitted by stamp+24h against a UTC-midnight cutoff; "
                  "selected the session before the intended one",
    "ANCHOR-002": "intraday window opened at UTC midnight (20:00 ET previous day), so the "
                  "reconstructed dailyBar.o was an extended-hours print, not the cash open",
}


class AnchorViolation(RuntimeError):
    """An anchor could not be selected under the contract. Never repaired
    by substitution -- the caller reports the absence."""


def _dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def session_date(ts) -> str:
    """The exchange session date (ET calendar date) a UTC instant belongs to."""
    return _dt(ts).astimezone(ET).date().isoformat()


def is_trading_day(date_str: str, *, holidays=None) -> bool:
    holidays = HOLIDAYS if holidays is None else holidays
    d = datetime.fromisoformat(date_str).date()
    return d.weekday() < 5 and date_str not in holidays


def regular_window(date_str: str, *, early_closes=None, holidays=None):
    """(open_utc, close_utc) for one session date. DST-safe: the wall clock
    is fixed and the UTC offset is resolved per date. Early closes move the
    close only -- the open is 09:30 on every session."""
    early_closes = EARLY_CLOSES if early_closes is None else early_closes
    if not is_trading_day(date_str, holidays=holidays):
        raise AnchorViolation("%s is not a regular trading session" % date_str)
    d = datetime.fromisoformat(date_str).date()
    close_wall = early_closes.get(date_str)
    if close_wall:
        h, m = map(int, close_wall.split(":"))
        close_t = time(h, m)
    else:
        close_t = REGULAR_CLOSE_WALL
    o = datetime.combine(d, REGULAR_OPEN_WALL, tzinfo=ET).astimezone(timezone.utc)
    c = datetime.combine(d, close_t, tzinfo=ET).astimezone(timezone.utc)
    return o, c


def cash_open_utc(ts, **kw) -> datetime:
    """The cash open of the session containing `ts`."""
    return regular_window(session_date(ts), **kw)[0]


def prior_lookback_start(ts) -> datetime:
    """Start of the daily-bar query window. Wide enough that a holiday week
    still contains a prior session; the SELECTION, not the window, decides."""
    return _dt(ts) - timedelta(days=PRIOR_LOOKBACK_DAYS)


def select_prior_daily(bars, as_of):
    """The daily bar of the most recent session STRICTLY BEFORE the session
    containing `as_of`. Pure: no I/O, no clock. Returns None when the
    vendor supplied no such session -- absence is an answer."""
    today = session_date(as_of)
    eligible = [b for b in (bars or []) if session_date(b["t"]) < today]
    if not eligible:
        return None
    return max(eligible, key=lambda b: session_date(b["t"]))


def select_current_daily_open(bars, as_of):
    """The current session's opening print, taken from the current session's
    daily bar and NOTHING else. Returns (value, provenance) or (None, why)."""
    today = session_date(as_of)
    for b in (bars or []):
        if session_date(b["t"]) == today:
            o = b.get("o")
            if o is None:
                return None, "current-session daily bar carries no open"
            return o, {"source": "vendor_daily_bar_open", "bar_t": b["t"],
                       "session_date": today, "fields_used": list(CURRENT_DAILY_ALLOWED_FIELDS)}
    return None, "vendor supplied no daily bar for the current session"


def regular_minute_bars(bars, as_of, **kw):
    """Minute bars of the CURRENT regular session whose window closed at or
    before `as_of`. Extended-hours bars are excluded: they are not part of
    the session aggregate the live snapshot reports."""
    t = _dt(as_of)
    o, c = regular_window(session_date(t), **kw)
    end = min(t, c)
    out = []
    for b in (bars or []):
        bt = _dt(b["t"])
        if bt >= o and bt + timedelta(minutes=1) <= end:
            out.append(b)
    return sorted(out, key=lambda b: _dt(b["t"]))


def rebuild_session_aggregate(minute_bars, *, open_price=None, open_provenance=None):
    """The current session's aggregate, rebuilt from observed minute bars.

    `open_price` is the contract's cash open when the vendor daily bar
    supplied one; otherwise the first regular minute bar's open is used and
    the provenance says so. High/low/close/volume/VWAP are ALWAYS rebuilt --
    they are the fields that would leak the rest of the day."""
    if not minute_bars:
        return None
    vol = sum(b["v"] for b in minute_bars)
    vwap_num = sum(b.get("vw", b["c"]) * b["v"] for b in minute_bars)
    last = minute_bars[-1]
    if open_price is None:
        open_price = minute_bars[0]["o"]
        open_provenance = {"source": "first_regular_minute_bar_open",
                           "bar_t": minute_bars[0]["t"],
                           "limitation": "the consolidated opening auction print may differ "
                                         "from the first minute bar's open"}
    return {"o": open_price, "h": max(b["h"] for b in minute_bars),
            "l": min(b["l"] for b in minute_bars), "c": last["c"], "v": vol,
            "vw": round(vwap_num / vol, 6) if vol else last["c"], "t": last["t"],
            "_open_provenance": open_provenance,
            "_rebuilt_fields": ["h", "l", "c", "v", "vw"],
            "_minute_bars_used": len(minute_bars)}


def contract() -> dict:
    """The machine-readable contract, for sealing into evidence."""
    return {
        "contract": ANCHOR_CONTRACT,
        "prior_close": "close of the most recent regular session strictly before the "
                       "session containing the as-of instant; selected by session date",
        "cash_open": "the opening print of the current regular session (09:30 ET), not "
                     "the first extended-hours print",
        "session_identity": "ET calendar date; weekends, NYSE holidays and early closes "
                            "from apex.intraday.sessions; DST resolved per date",
        "price_convention": "RAW / unadjusted on both feeders",
        "missing_anchor": "absent, never substituted",
        "before_the_open": "no current-session aggregate is constructed in PREMARKET or CLOSED",
        "leak_discipline": {"current_session_daily_bar_fields_used": list(CURRENT_DAILY_ALLOWED_FIELDS),
                            "rebuilt_from_minute_bars": ["h", "l", "c", "v", "vw"]},
        "correction_availability": "vendor history is as-of-retrieval; this contract fixes WHICH "
                                   "record a moment refers to and does NOT establish as-known-at "
                                   "availability",
        "defects_closed": DEFECTS_CLOSED,
    }
