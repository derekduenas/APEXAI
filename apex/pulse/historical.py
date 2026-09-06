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
  the completed day's high/low/close/vol   -> rebuilt from minute bars; the
                                              current session's daily bar is
                                              read for its OPENING PRICE ONLY
                                              (PULSE_ANCHOR_CONTRACT_V1)

PULSE-007. Two anchor-selection defects were measured against six sealed
live packets and are closed here; the contract they now obey lives in
apex.pulse.anchors and is stated there, once.

  ANCHOR-001  the prior daily bar was admitted by `stamp + 24h <= UTC
              midnight`. Alpaca stamps a daily bar at the session's ET
              midnight, so the most recent completed session was always
              dropped and the one before it returned. Measured on
              2026-09-01: replay handed back the 08-28 close where live
              carried 08-31, on 5 of 5 subjects that had a prior session.
  ANCHOR-002  the intraday window began at UTC midnight, which is 20:00 ET
              on the previous calendar day, so `dailyBar.o` was the first
              extended-hours print rather than the cash open. Measured on
              the same packets: the reconstructed "open" was a PREMARKET
              bar on 5 of 5.

Selection is now by SESSION DATE through the one exchange calendar, and the
session aggregate covers the regular session only.
  option OI, fundamentals, event times     -> only if their own
                                              known_from precedes t
  today's model reading yesterday's news   -> refused outright

decision_power: NONE_STATE.
"""
from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

from apex.intraday.sessions import Session, classify
from apex.organism import microstructure as ms
from apex.pulse import anchors
from apex.pulse.compose import _dt, compose

FACTORY_VERSION = "HISTORICAL_MARKET_TWIN_FACTORY_V0.2"
FACTORY_HISTORY = {
    "V0": "anchor selection by timestamp arithmetic against a UTC-midnight cutoff "
          "(ANCHOR-001) and an intraday window that began at UTC midnight (ANCHOR-002)",
    "V0.1": "PULSE-007: selection by session date through apex.pulse.anchors; the "
            "session aggregate covers the regular session only; the current session's "
            "daily bar contributes its opening price and nothing else",
    "V0.2": "PULSE-008: the quote ingredient may be pinned to its own recorded instant "
            "via quote_as_of, because a packet is not synchronous and each ingredient "
            "carries its own clock. Bars remain bounded by t. Default behaviour is "
            "unchanged: with quote_as_of=None the quote is selected at t exactly as in V0.1. "
            "QUOTE-BOUNDARY-001 also closed: the vendor query is widened past the requested "
            "instant so the boundary event is returned at all, while the LOCAL cutoff that "
            "decides admission is untouched"}
BARS = "https://data.alpaca.markets/v2/stocks/{sym}/bars"


class LeakageViolation(RuntimeError):
    """Raised when a reconstruction would consume the future."""


def _bars(symbol, start, end, timeframe="1Min", limit=10000,
          closed_only=True):
    """Vendor bars for a window.

    For MINUTE bars, `closed_only` keeps only bars whose window is CLOSED
    at or before `end`: Alpaca stamps a bar with its OPEN time, so a bar
    stamped 13:59 covers 13:59:00-13:59:59 and is not knowable until
    14:00:00. Filtering on the stamp alone would leak up to one bar.

    For DAILY bars the same arithmetic was ANCHOR-001: a daily bar is
    stamped at the session's ET midnight, so `stamp + 24h` compares a
    timezone-shifted instant against a cutoff that is not a session
    boundary at all. Daily bars are therefore returned UNFILTERED and the
    caller selects by SESSION DATE through apex.pulse.anchors, which is
    the only place that knows what a session is."""
    url = BARS.format(sym=symbol) + "?" + urllib.parse.urlencode(
        {"start": _dt(start).isoformat(), "end": _dt(end).isoformat(),
         "timeframe": timeframe, "limit": limit, "feed": "sip",
         "adjustment": "raw"})
    got = ms._get(url) or {}
    bars = got.get("bars") or []
    if timeframe != "1Min" or not closed_only:
        return bars
    cutoff = _dt(end)
    return [b for b in bars
            if _dt(b["t"]) + timedelta(minutes=1) <= cutoff]


def snapshot_as_of(symbol: str, t, *, session_start=None) -> dict:
    """Reconstruct the provider snapshot shape as it stood at t.

    Returns the SAME keys live PULSE receives, so the shared composer
    cannot tell the two apart -- which is the point. Every anchor obeys
    PULSE_ANCHOR_CONTRACT_V1; the provenance of each is recorded so an
    auditor can see WHICH session each number came from without rerunning
    anything."""
    t = _dt(t)
    session = classify(t)
    snap = {"_reconstructed_as_of": t.isoformat(),
            "_factory": FACTORY_VERSION,
            "_anchor_contract": anchors.ANCHOR_CONTRACT,
            "_session": session.value,
            "_session_date": anchors.session_date(t),
            "_anchor_provenance": {}}
    prov = snap["_anchor_provenance"]

    # ---- daily bars: ONE query, two selections, both by session date
    daily = _bars(symbol, session_start or anchors.prior_lookback_start(t), t,
                  timeframe="1Day")
    prior = anchors.select_prior_daily(daily, t)
    if prior:
        snap["prevDailyBar"] = {"c": prior["c"], "v": prior["v"], "t": prior["t"]}
        prov["prior_close"] = {"session_date": anchors.session_date(prior["t"]),
                               "bar_t": prior["t"], "rule": "last session strictly before "
                               "the current session date", "adjustment": "raw"}
    else:
        prov["prior_close"] = {"absent": "no regular session in the lookback window",
                               "sessions_offered": [anchors.session_date(b["t"]) for b in daily]}

    # ---- the current session's aggregate exists only once the cash open has
    #      happened. In PREMARKET/CLOSED the composer marks the dependent
    #      features SESSION_INAPPLICABLE; manufacturing inputs for them here
    #      is how ANCHOR-002 produced a premarket price called an "open".
    if session in (Session.REGULAR, Session.POSTMARKET):
        open_utc = anchors.cash_open_utc(t)
        minutes = anchors.regular_minute_bars(
            _bars(symbol, open_utc, t, timeframe="1Min"), t)
        open_price, open_prov = anchors.select_current_daily_open(daily, t)
        agg = anchors.rebuild_session_aggregate(
            minutes, open_price=open_price,
            open_provenance=open_prov if open_price is not None else None)
        if agg:
            prov["cash_open"] = agg.pop("_open_provenance")
            prov["session_aggregate"] = {
                "rebuilt_fields": agg.pop("_rebuilt_fields"),
                "minute_bars_used": agg.pop("_minute_bars_used"),
                "window_start": open_utc.isoformat(), "window_end": t.isoformat()}
            snap["dailyBar"] = agg
            last = minutes[-1]
            snap["minuteBar"] = {"v": last["v"], "c": last["c"], "t": last["t"]}
            # historical NBBO would need the quote tape; the close of the
            # last completed bar is a PRICE, not a two-sided quote, so it
            # is offered as such and the composer will mark NBBO features
            # NOT_AVAILABLE rather than invent a spread
            snap["latestTrade"] = {"p": last["c"], "t": last["t"]}
        else:
            prov["session_aggregate"] = {
                "absent": "no completed regular minute bar at or before the as-of instant"}
    else:
        prov["session_aggregate"] = {
            "absent": "session is %s: no cash open has occurred" % session.value}
    return snap


def quotes_as_of(symbol: str, t, *, lookback_s: int = 60,
                 boundary_margin_s: float = 1.0) -> dict:
    """A real historical NBBO, when the quote tape is available.

    APEX owns SIP quote history, so the Twin does not have to fall
    back to candles for top-of-book -- the standing law is to use the
    tape we already paid for.

    QUOTE-BOUNDARY-001 (PULSE-008). The vendor's `end` parameter does not
    return the event AT the boundary. Querying with end = t therefore never
    yielded the quote the live packet actually used, and the local filter
    then selected the previous event -- 1.6 ms earlier on SPY, 173 ms on
    AAL. Prices usually survived that; SIZES did not, which is why
    nbbo_size_imbalance kept disagreeing after every other cause had been
    ruled out. Measured on all five reconcilable frozen packets: with
    end = t the exact event was absent 5 of 5; with a one-second margin it
    was present 5 of 5, at a gap of exactly 0.000 ms, and bid size, ask size
    and mid all matched live exactly.

    THE MARGIN DOES NOT RELAX THE CUTOFF. The vendor window is widened; the
    LOCAL filter `_dt(q["t"]) <= t` is unchanged and remains the only thing
    that decides admission. Events after t are fetched and discarded, and a
    test asserts that they can never be selected."""
    t = _dt(t)
    qs = ms.fetch_ticks(symbol,
                        (t - timedelta(seconds=lookback_s)).isoformat(),
                        (t + timedelta(seconds=boundary_margin_s)).isoformat(),
                        what="quotes", max_pages=2)
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
               catalyst=None, options=None, quote_as_of=None) -> dict:
    """Build MARKET_TWIN_STATE_V0 for a historical moment.

    `t` bounds every BAR ingredient. `quote_as_of`, when given, selects the
    NBBO at the instant the packet being mirrored actually observed one --
    see apex.pulse.observation. It may be earlier OR later than `t` by the
    composition lag; it may never exceed the caller's own causal bound, which
    the caller asserts (this function records what it used and refuses
    nothing on its behalf)."""
    t = _dt(t)
    snap = snapshot_as_of(symbol, t)
    if with_quotes:
        qt = _dt(quote_as_of) if quote_as_of is not None else t
        q = quotes_as_of(symbol, qt)
        snap["_quote_as_of_requested"] = qt.isoformat()
        snap["_quote_selection"] = ("observation_time" if quote_as_of is not None
                                    else "reconstruction_time_t")
        sel_t = (q or {}).get("t")
        snap["_anchor_provenance"]["quote"] = {
            "requested_at": qt.isoformat(),
            "selected_event_t": sel_t,
            "exact_instant_reached": bool(sel_t and _dt(sel_t) == qt),
            "gap_to_requested_ms": (round((qt - _dt(sel_t)).total_seconds() * 1000, 3)
                                    if sel_t else None),
            "rule": "last two-sided NBBO at or before the requested instant",
            "boundary_defect_closed": "QUOTE-BOUNDARY-001",
            "offset_from_bar_cutoff_s": round((qt - t).total_seconds(), 6)}
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
    st.sources["anchor_contract"] = anchors.ANCHOR_CONTRACT
    st.notes.append("anchor_provenance: %s" % snap.get("_anchor_provenance"))
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
