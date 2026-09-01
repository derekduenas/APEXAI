"""HISTORICAL_MARKET_TWIN_FACTORY_V0 — the same state, as of then.

PARITY IS STRUCTURAL, NOT ASSERTED. There is exactly ONE composer.
Live PULSE feeds it a provider snapshot; this factory feeds it a
snapshot reconstructed from history. Every definition -- what a prior
close is, where the anchor sits, when a feature is SESSION_INAPPLICABLE
-- lives in the composer and therefore cannot drift between the two
paths. A second historical implementation of the same words is exactly
how an open-vs-entry mismatch is born.

THE ONLY THING THIS MODULE DOES is answer: what did the provider's
snapshot LOOK LIKE at time t, using nothing timestamped after t.

WHAT LEAKAGE LOOKS LIKE, AND WHY EACH IS BLOCKED:
  a bar whose window CLOSES after t        -> excluded; a 14:05 bar is
                                              not knowable at 14:03
  the session's final volume / high / low  -> recomputed from bars
                                              up to t only, never read
                                              from a completed daily
                                              aggregate
  a later revision of a prior close        -> the prior session's bars
                                              are themselves bounded
  option OI, fundamentals, event times     -> only if their own
                                              known_from precedes t
  today's model reading yesterday's news   -> refused outright

decision_power: NONE_STATE.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

from apex.organism import microstructure as ms
from apex.pulse.compose import _dt, compose

FACTORY_VERSION = "HISTORICAL_MARKET_TWIN_FACTORY_V0"
BARS = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


class LeakageViolation(RuntimeError):
    """Raised when a reconstruction would consume the future."""


def _bars(symbol, start, end, timeframe="1Min", limit=10000):
    """Bars whose window is CLOSED at or before `end`.

    Alpaca stamps a bar with its OPEN time, so a 1-minute bar stamped
    13:59 covers 13:59:00-13:59:59 and is not knowable until 14:00:00.
    Filtering on the stamp alone would leak up to one bar of future."""
    url = BARS.format(sym=symbol) + "?" + urllib.parse.urlencode(
        {"start": _dt(start).isoformat(), "end": _dt(end).isoformat(),
         "timeframe": timeframe, "limit": limit, "feed": "sip",
         "adjustment": "raw"})
    got = ms._get(url) or {}
    out = []
    width = timedelta(minutes=1) if timeframe == "1Min" \
        else timedelta(days=1)
    cutoff = _dt(end)
    for b in (got.get("bars") or []):
        if _dt(b["t"]) + width <= cutoff:
            out.append(b)
    return out


def snapshot_as_of(symbol: str, t, *, session_start=None) -> dict:
    """Reconstruct the provider snapshot shape as it stood at t.

    Returns the SAME keys live PULSE receives, so the shared composer
    cannot tell the two apart -- which is the point."""
    t = _dt(t)
    day_start = session_start or t.replace(hour=0, minute=0, second=0,
                                           microsecond=0)
    intraday = _bars(symbol, day_start, t)
    prior = _bars(symbol, t - timedelta(days=8), day_start,
                  timeframe="1Day")

    snap = {"_reconstructed_as_of": t.isoformat(),
            "_factory": FACTORY_VERSION}
    if prior:
        p = prior[-1]
        snap["prevDailyBar"] = {"c": p["c"], "v": p["v"], "t": p["t"]}
    if intraday:
        last = intraday[-1]
        # the session aggregate is REBUILT from observed bars, never
        # read from a completed daily bar that already contains the
        # rest of the day
        vol = sum(b["v"] for b in intraday)
        vwap_num = sum(b.get("vw", b["c"]) * b["v"] for b in intraday)
        snap["dailyBar"] = {
            "o": intraday[0]["o"],
            "h": max(b["h"] for b in intraday),
            "l": min(b["l"] for b in intraday),
            "c": last["c"], "v": vol,
            "vw": round(vwap_num / vol, 6) if vol else last["c"],
            "t": last["t"]}
        snap["minuteBar"] = {"v": last["v"], "c": last["c"],
                             "t": last["t"]}
        # historical NBBO would need the quote tape; the close of the
        # last completed bar is a PRICE, not a two-sided quote, so it
        # is offered as such and the composer will mark NBBO features
        # NOT_AVAILABLE rather than invent a spread
        snap["latestTrade"] = {"p": last["c"], "t": last["t"]}
    return snap


def quotes_as_of(symbol: str, t, *, lookback_s: int = 60) -> dict:
    """A real historical NBBO, when the quote tape is available.

    APEX owns SIP quote history, so the Twin does not have to fall
    back to candles for top-of-book -- the standing law is to use the
    tape we already paid for."""
    t = _dt(t)
    qs = ms.fetch_ticks(symbol,
                        (t - timedelta(seconds=lookback_s)).isoformat(),
                        t.isoformat(), what="quotes", max_pages=2)
    usable = [q for q in qs
              if _dt(q["t"]) <= t and q.get("bp") and q.get("ap")
              and q["ap"] > q["bp"] > 0]
    if not usable:
        return {}
    q = usable[-1]
    return {"bp": q["bp"], "ap": q["ap"], "bs": q.get("bs"),
            "as": q.get("as"), "t": q["t"]}


def twin_as_of(symbol: str, t, *, universe_version="HISTORICAL",
               rolling=None, with_quotes=True, deep=None,
               catalyst=None, options=None) -> dict:
    """Build MARKET_TWIN_STATE_V0 for a historical moment."""
    t = _dt(t)
    snap = snapshot_as_of(symbol, t)
    if with_quotes:
        q = quotes_as_of(symbol, t)
        if q:
            snap["latestQuote"] = q
    st = compose(subject=symbol, snapshot=snap,
                 scheduled_time=t.isoformat(),
                 capture_start=t.isoformat(),
                 complete_time=t.isoformat(),
                 universe_version=universe_version, rolling=rolling,
                 deep=deep, catalyst=catalyst, options=options,
                 evidence_class="HISTORICAL_REPLAY")
    st.sources["factory"] = FACTORY_VERSION
    st.notes.append(
        "HISTORICAL_REPLAY: reconstructed from data whose own "
        "timestamps precede the as-of moment. This is NOT prospective "
        "evidence and may never be pooled with live PULSE "
        "observations.")
    return st.seal()


def assert_no_future(packet: dict, t) -> list:
    """Independently verify that nothing in the packet post-dates t.

    Deliberately separate from construction: a builder that checks its
    own work proves only that it agrees with itself."""
    t = _dt(t)
    problems = []
    for name, f in (packet.get("features") or {}).items():
        if isinstance(f, dict) and f.get("as_of"):
            if _dt(f["as_of"]) > t:
                problems.append(
                    f"{name}: ingredient as_of {f['as_of']} is AFTER "
                    f"the as-of moment {t.isoformat()}")
    for key in ("known_from", "state_complete_time", "capture_start",
                "scheduled_time"):
        v = packet.get(key)
        if v and _dt(v) > t:
            problems.append(f"{key} {v} is AFTER {t.isoformat()}")
    if packet.get("evidence_class") != "HISTORICAL_REPLAY":
        problems.append(
            f"evidence_class {packet.get('evidence_class')!r} -- a "
            f"reconstruction must never be labelled live")
    return problems
