"""THE TWIN COMPOSER — assemble MARKET_TWIN_STATE_V0 from primitives
APEX already owns.

This module deliberately computes almost nothing itself. Session logic,
microstructure, the options surface, catalyst context and cross-
sectional state are existing commissioned organs; re-implementing any
of them would create a second definition of the same word, which is
the defect class that produced open-vs-entry anchor mismatches. The
composer's whole job is to call them, wrap every result in a quality,
and refuse to let an absence look like a measurement.

EVERY FIELD ANSWERS TWO QUESTIONS: what is the value, and how much
should you trust it. A feature that cannot answer the second is not
emitted.

decision_power: NONE_STATE -- measurements only. No tag here means
buy, sell, attack or avoid.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from apex.intraday.sessions import Session, classify
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE,
                             PROVIDER_ERROR, SESSION_INAPPLICABLE,
                             STALE, UNKNOWN, TwinState, absent, adopt,
                             ok)

COMPOSER_VERSION = "PULSE_COMPOSE_V0"

TIER_1_DEEP = "TIER_1_DEEP"
TIER_2_BROAD = "TIER_2_BROAD"

# How old a top-of-book quote may be before it stops describing NOW.
# Wider outside regular hours because quoting genuinely thins out --
# a premarket quote 3 minutes old is normal, not a provider fault.
QUOTE_TOLERANCE_S = {Session.REGULAR: 120.0, Session.PREMARKET: 600.0,
                     Session.POSTMARKET: 600.0, Session.CLOSED: 3600.0}


_TZ = re.compile(r"([+-]\d{2}:?\d{2})$")


def _dt(ts) -> datetime:
    """Parse a provider timestamp WITHOUT losing its offset.

    Alpaca returns nanoseconds ("...04.900000000Z") and datetime
    accepts only microseconds, so the fraction must be truncated --
    but the timezone has to be separated FIRST. Truncating digits
    across the whole tail silently eats the offset and yields a naive
    datetime, which then compares against aware ones as if it were
    UTC. A timestamp bug is a causality bug."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    m = _TZ.search(s)
    off, base = (m.group(1), s[:m.start()]) if m else ("+00:00", s)
    if "." in base:
        head, _, frac = base.partition(".")
        base = f"{head}.{frac[:6].ljust(6, '0')}"
    return datetime.fromisoformat(base + off)


def _bps(a, b):
    return round((a / b - 1) * 1e4, 2) if (a and b) else None


def compose(*, subject, snapshot, scheduled_time, capture_start,
            complete_time, universe_version, rolling=None,
            deep=None, catalyst=None, options=None,
            tier=TIER_2_BROAD, evidence_class="LIVE_PROSPECTIVE"
            ) -> TwinState:
    """One subject, one moment, fully provenanced."""
    now = _dt(complete_time)
    session = classify(now)
    st = TwinState(subject=subject, scheduled_time=str(scheduled_time),
                   capture_start=str(capture_start),
                   state_complete_time=str(complete_time),
                   market_session=session.value,
                   universe_version=universe_version, tier=tier,
                   evidence_class=evidence_class)
    st.sources["composer"] = COMPOSER_VERSION
    F = st.features

    if not isinstance(snapshot, dict) or not snapshot:
        F["snapshot"] = absent(PROVIDER_ERROR, source="alpaca_sip",
                               note="no snapshot returned")
        return st
    st.sources["snapshot"] = "alpaca_sip_v2_snapshots"

    q = snapshot.get("latestQuote") or {}
    prev = (snapshot.get("prevDailyBar") or {}).get("c")
    day = snapshot.get("dailyBar") or {}
    minute = snapshot.get("minuteBar") or {}

    # ------------------------------------------------ NBBO / spread
    bp, ap = q.get("bp"), q.get("ap")
    qt = q.get("t")
    mid = None
    if bp and ap and ap > bp > 0:
        age = (now - _dt(qt)).total_seconds() if qt else None
        tol = QUOTE_TOLERANCE_S.get(session, 600.0)
        fresh = age is not None and age <= tol
        mid = (bp + ap) / 2
        qual = ok if fresh else (lambda v, **k: absent(
            STALE, source="alpaca_sip",
            note=f"quote {age:.0f}s old exceeds the {tol:.0f}s "
                 f"{session.value} tolerance"))
        F["mid"] = qual(round(mid, 6), source="alpaca_sip", as_of=qt)
        F["spread_bps"] = qual(round((ap - bp) / mid * 1e4, 3),
                               source="alpaca_sip", as_of=qt)
        F["quote_age_s"] = (ok(round(age, 2), source="alpaca_sip",
                               as_of=qt) if age is not None
                            else absent(NOT_ESTIMABLE,
                                        source="alpaca_sip"))
        # sizes are a separate question from prices -- PULSE-001
        if isinstance(q.get("bs"), (int, float)) and \
                isinstance(q.get("as"), (int, float)) and \
                (q["bs"] + q["as"]) > 0:
            F["touch_size"] = qual(q["bs"] + q["as"],
                                   source="alpaca_sip", as_of=qt)
            F["nbbo_size_imbalance"] = qual(
                round((q["bs"] - q["as"]) / (q["bs"] + q["as"]), 4),
                source="alpaca_sip", as_of=qt)
        else:
            for k in ("touch_size", "nbbo_size_imbalance"):
                F[k] = absent(NOT_ESTIMABLE, source="alpaca_sip",
                              note="quote carries no usable sizes; "
                                   "missing size is not zero size")
    else:
        for k in ("mid", "spread_bps", "quote_age_s", "touch_size",
                  "nbbo_size_imbalance"):
            F[k] = absent(NOT_AVAILABLE, source="alpaca_sip",
                          note="no valid two-sided NBBO")

    # ----------------------------------------------------- anchors
    F["prior_close"] = (ok(prev, source="alpaca_sip",
                           as_of=(snapshot.get("prevDailyBar") or {}
                                  ).get("t"))
                        if prev else absent(NOT_AVAILABLE,
                                            source="alpaca_sip"))
    F["prior_close_return_bps"] = (
        ok(_bps(mid, prev), source="derived", as_of=qt)
        if (mid and prev) else absent(
            NOT_ESTIMABLE, source="derived",
            note="requires both a live mid and a prior close"))

    # the cash open exists only once the regular session has begun
    d_open = day.get("o")
    if session in (Session.PREMARKET, Session.CLOSED):
        F["cash_open_return_bps"] = absent(
            SESSION_INAPPLICABLE, source="derived",
            note=f"no cash open has occurred in {session.value}")
        F["overnight_gap_bps"] = absent(
            SESSION_INAPPLICABLE, source="derived",
            note="the gap is defined at the cash open")
    else:
        F["cash_open_return_bps"] = (
            ok(_bps(mid, d_open), source="derived", as_of=qt)
            if (mid and d_open) else absent(NOT_ESTIMABLE,
                                            source="derived"))
        F["overnight_gap_bps"] = (
            ok(_bps(d_open, prev), source="derived",
               as_of=day.get("t"))
            if (d_open and prev) else absent(NOT_ESTIMABLE,
                                             source="derived"))

    # ------------------------------------------- session structure
    for name, key in (("session_high", "h"), ("session_low", "l"),
                      ("session_vwap", "vw"), ("session_volume", "v")):
        v = day.get(key)
        F[name] = (ok(v, source="alpaca_sip", as_of=day.get("t"))
                   if v is not None
                   else absent(NOT_AVAILABLE, source="alpaca_sip"))
    hi, lo = day.get("h"), day.get("l")
    F["session_range_position"] = (
        ok(round((mid - lo) / (hi - lo), 4), source="derived",
           as_of=qt)
        if (mid and hi and lo and hi > lo)
        else absent(NOT_ESTIMABLE, source="derived",
                    note="requires a live mid and a non-degenerate "
                         "session range"))
    F["vwap_distance_bps"] = (
        ok(_bps(mid, day.get("vw")), source="derived", as_of=qt)
        if (mid and day.get("vw")) else absent(NOT_ESTIMABLE,
                                               source="derived"))
    F["relative_volume"] = (
        ok(round(day["v"] / (snapshot.get("prevDailyBar") or {})["v"],
                 4), source="derived", as_of=day.get("t"))
        if day.get("v") and (snapshot.get("prevDailyBar") or {}).get("v")
        else absent(NOT_ESTIMABLE, source="derived",
                    note="requires both a session and a prior-session "
                         "volume; NOT a full-day baseline"))
    F["last_minute_volume"] = (
        ok(minute["v"], source="alpaca_sip", as_of=minute.get("t"))
        if minute.get("v") is not None
        else absent(NOT_AVAILABLE, source="alpaca_sip"))

    # -------------------------------- rolling causal path (PULSE's own)
    if rolling is not None and mid:
        rolling.observe(subject, at=now, price=mid,
                        volume=day.get("v"))
        for m in (1, 5, 10, 15, 30, 60):
            r = rolling.ret_bps(subject, m, now=now)
            F[f"ret_{m}m_bps"] = (
                ok(r["value"], source="pulse_rolling",
                   as_of=r.get("newest"),
                   note=f"coverage {r['coverage']:.2f}")
                if r["value"] is not None
                else absent(NOT_ESTIMABLE, source="pulse_rolling",
                            note=r.get("detail", "insufficient "
                                                 "observed window")))
    else:
        for m in (1, 5, 10, 15, 30, 60):
            F[f"ret_{m}m_bps"] = absent(
                UNKNOWN, source="pulse_rolling",
                note="no rolling history for this subject yet")

    # ---------------------------------------- TIER 1 microstructure
    if deep is not None:
        st.sources["microstructure"] = "apex.organism.microstructure"
        for k in ("spread_bps_median", "nbbo_imbalance_mean",
                  "microprice_disp_bps_mean", "net_signed_volume",
                  "trade_intensity_per_s", "quote_intensity_per_s",
                  "short_horizon_vol_bps_per_min",
                  "impact_bps_per_1k_signed", "mid_return_bps"):
            if k in deep:
                F[f"micro_{k}"] = adopt(deep[k],
                                        source="micro_state",
                                        as_of=deep.get("as_of"))
        if deep.get("status") == NOT_ESTIMABLE:
            F["micro_status"] = absent(
                NOT_ESTIMABLE, source="micro_state",
                note=str(deep.get("why", "insufficient tape")))

    # ------------------------------------------- catalyst / events
    if catalyst is not None:
        st.sources["catalyst"] = "apex.catalyst.context"
        for k in ("environment", "directional_support", "events_known",
                  "reaction_disagreements"):
            if k in catalyst:
                F[f"catalyst_{k}"] = adopt(catalyst[k],
                                           source="catalyst_context")
    else:
        F["catalyst_environment"] = absent(
            UNKNOWN, source="catalyst_context",
            note="catalyst context not consulted for this subject "
                 "in this cycle")

    # ------------------------------------------------ options state
    if options is not None:
        st.sources["options"] = "apex.organism.options_surface"
        for k in ("atm_iv", "implied_move_bps", "skew_25d",
                  "term_slope", "nbbo_width_rel"):
            if k in options:
                F[f"opt_{k}"] = adopt(options[k],
                                      source="options_surface",
                                      as_of=options.get("as_of"))
    else:
        F["opt_escalated"] = absent(
            UNKNOWN, source="options_surface",
            note="options enrichment is STAGED: not run for every "
                 "subject every minute")
    return st
