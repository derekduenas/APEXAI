"""THE TWIN COMPOSER — assemble MARKET_TWIN_STATE_V0 from primitives
APEX already owns.

This module deliberately computes almost nothing itself. Session
logic, microstructure, the options surface, catalyst context and
cross-sectional state are existing commissioned organs; a second
implementation of the same word is how open-vs-entry anchor
mismatches are born. The composer calls them, wraps every result in a
quality and a clock, and refuses to let an absence look like a
measurement.

FACTS AND INTERPRETATIONS ARE NEVER MIXED. A filing's timestamp is an
official fact. A model's opinion that the filing is "CENTRAL_BANK
policy" is an interpretation, carrying its own model id, version and
known_from. When that classification is wrong -- and one already has
been -- it must remain visible AS a semantic-model error rather than
being quietly corrected inside the factual record.

decision_power: NONE_STATE -- measurements only. Nothing here means
buy, sell, attack or avoid.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from apex.intraday.sessions import Session, classify
from apex.pulse import freshness
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE,
                             PROVIDER_ERROR, SESSION_INAPPLICABLE,
                             STALE, UNKNOWN, TwinState, absent, adopt,
                             ok)

COMPOSER_VERSION = "PULSE_COMPOSE_V0"

TIER_1_DEEP = "TIER_1_DEEP"
TIER_2_BROAD = "TIER_2_BROAD"

_TZ = re.compile(r"([+-]\d{2}:?\d{2})$")


def _dt(ts) -> datetime:
    """Parse a provider timestamp WITHOUT losing its offset.

    Alpaca returns nanoseconds and datetime accepts microseconds, so
    the fraction must be truncated -- but the timezone has to be split
    off FIRST. Truncating across the whole tail eats the offset and
    yields a naive datetime that then compares as if it were UTC. A
    timestamp bug is a causality bug."""
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
            deep=None, catalyst=None, options=None, cross_asset=None,
            premarket_path=None, enrichment=None,
            tier=TIER_2_BROAD, evidence_class="LIVE_PROSPECTIVE",
            capture_end=None) -> TwinState:
    """One subject, one moment, fully provenanced."""
    now = _dt(complete_time)
    session = classify(now)
    st = TwinState(subject=subject, scheduled_time=str(scheduled_time),
                   capture_start=str(capture_start),
                   state_complete_time=str(complete_time),
                   capture_end=str(capture_end) if capture_end else None,
                   market_session=session.value,
                   universe_version=universe_version, tier=tier,
                   evidence_class=evidence_class)
    st.sources["composer"] = COMPOSER_VERSION
    st.sources["freshness_policy"] = freshness.FRESHNESS_POLICY_VERSION
    if enrichment:
        st.enrichment = enrichment
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
    bp, ap, qt = q.get("bp"), q.get("ap"), q.get("t")
    mid = None
    if bp and ap and ap > bp > 0:
        age = (now - _dt(qt)).total_seconds() if qt else None
        verdict = freshness.is_fresh("sip_quote", session, age)
        mid = (bp + ap) / 2

        def qual(v, **kw):
            return (ok(v, **kw) if verdict["fresh"]
                    else absent(STALE, source="alpaca_sip",
                                note=verdict["why"]))

        F["mid"] = qual(round(mid, 6), source="alpaca_sip", as_of=qt)
        F["spread_bps"] = qual(round((ap - bp) / mid * 1e4, 3),
                               source="alpaca_sip", as_of=qt)
        F["spread_rel"] = qual(round((ap - bp) / mid, 8),
                               source="alpaca_sip", as_of=qt)
        F["quote_age_s"] = (ok(round(age, 2), source="alpaca_sip",
                               as_of=qt) if age is not None
                            else absent(NOT_ESTIMABLE,
                                        source="alpaca_sip"))
        # PULSE-001: sizes are a separate question from prices
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
        for k in ("mid", "spread_bps", "spread_rel", "quote_age_s",
                  "touch_size", "nbbo_size_imbalance"):
            F[k] = absent(NOT_AVAILABLE, source="alpaca_sip",
                          note="no valid two-sided NBBO")

    trade = snapshot.get("latestTrade") or {}
    if trade.get("p"):
        tage = ((now - _dt(trade["t"])).total_seconds()
                if trade.get("t") else None)
        tv = freshness.is_fresh("sip_trade", session, tage)
        F["last_trade"] = (ok(trade["p"], source="alpaca_sip",
                              as_of=trade.get("t")) if tv["fresh"]
                           else absent(STALE, source="alpaca_sip",
                                       note=tv["why"]))
    else:
        F["last_trade"] = absent(NOT_AVAILABLE, source="alpaca_sip")

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

    d_open = day.get("o")
    if session in (Session.PREMARKET, Session.CLOSED):
        for k, why in (("cash_open_return_bps",
                        f"no cash open has occurred in "
                        f"{session.value}"),
                       ("overnight_gap_bps",
                        "the gap is defined at the cash open")):
            F[k] = absent(SESSION_INAPPLICABLE, source="derived",
                          note=why)
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
                      ("session_vwap", "vw"), ("session_volume", "v"),
                      ("session_open", "o")):
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
    pv = (snapshot.get("prevDailyBar") or {}).get("v")
    F["relative_volume"] = (
        ok(round(day["v"] / pv, 4), source="derived",
           as_of=day.get("t"))
        if (day.get("v") and pv)
        else absent(NOT_ESTIMABLE, source="derived",
                    note="requires a session and a prior-session "
                         "volume; a ONE-SESSION baseline, never one "
                         "computed with future sessions"))
    F["last_minute_volume"] = (
        ok(minute["v"], source="alpaca_sip", as_of=minute.get("t"))
        if minute.get("v") is not None
        else absent(NOT_AVAILABLE, source="alpaca_sip"))

    # ------------------------------- rolling path (PULSE's own eyes)
    if rolling is not None and mid:
        rolling.observe(subject, at=now, price=mid, volume=day.get("v"))
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

    # ------------------------------------------- premarket path
    if premarket_path is not None and mid:
        premarket_path.observe(subject, at=now, price=mid,
                               volume=day.get("v"))
        path = premarket_path.path(subject, at=now, prior_close=prev)
        if path["status"] == "OBSERVED":
            for key, fname in (("first_price", "premarket_first"),
                               ("high", "premarket_high"),
                               ("low", "premarket_low"),
                               ("range_bps", "premarket_range_bps"),
                               ("premarket_return_bps",
                                "premarket_return_bps"),
                               ("premarket_travel_bps",
                                "premarket_travel_bps"),
                               ("overnight_first_gap_bps",
                                "overnight_first_gap_bps")):
                v = path.get(key)
                F[fname] = (ok(v, source="pulse_premarket",
                               as_of=path["last_at"],
                               note=("THIN: only "
                                     f"{path['observations']} "
                                     "premarket observations")
                               if path["thin"] else None)
                            if v is not None
                            else absent(NOT_ESTIMABLE,
                                        source="pulse_premarket"))
            F["premarket_observations"] = ok(
                path["observations"], source="pulse_premarket",
                as_of=path["last_at"])
        else:
            for fname in ("premarket_first", "premarket_high",
                          "premarket_low", "premarket_range_bps",
                          "premarket_return_bps",
                          "premarket_travel_bps",
                          "overnight_first_gap_bps",
                          "premarket_observations"):
                F[fname] = absent(UNKNOWN, source="pulse_premarket",
                                  note=path["why"])

    # ---------------------------------------- TIER 1 microstructure
    if deep is not None:
        st.sources["microstructure"] = "apex.organism.microstructure"
        for k in ("spread_bps_median", "nbbo_imbalance_mean",
                  "microprice_disp_bps_mean", "net_signed_volume",
                  "signed_buy_volume", "signed_sell_volume",
                  "trade_intensity_per_s", "quote_intensity_per_s",
                  "short_horizon_vol_bps_per_min",
                  "impact_bps_per_1k_signed", "mid_return_bps",
                  "touch_size_change_frac", "abnormal_trade_size"):
            if k in deep:
                F[f"micro_{k}"] = adopt(deep[k], source="micro_state",
                                        as_of=deep.get("as_of"))
        if deep.get("status") == NOT_ESTIMABLE:
            F["micro_status"] = absent(
                NOT_ESTIMABLE, source="micro_state",
                note=str(deep.get("why", "insufficient tape")))
    elif tier == TIER_1_DEEP:
        F["micro_status"] = absent(
            UNKNOWN, source="micro_state",
            note="subject is Tier-1 but deep state was not supplied "
                 "this cycle")

    # ------------------------------- catalyst: FACT vs INTERPRETATION
    if catalyst is not None:
        st.sources["catalyst"] = "apex.catalyst.context"
        for k in ("events_known", "latest_event_time",
                  "latest_event_known_from", "source_class"):
            if k in catalyst:
                F[f"catalyst_fact_{k}"] = adopt(
                    catalyst[k], source="catalyst_official_record",
                    as_of=catalyst.get("latest_event_time"),
                    known_from=catalyst.get("latest_event_known_from"))
        # INTERPRETATION is separately sourced and separately dated,
        # so a misclassification stays visible as a model error
        for k in ("environment", "directional_support", "event_type",
                  "importance", "mechanism",
                  "reaction_disagreements"):
            if k in catalyst:
                F[f"catalyst_semantic_{k}"] = adopt(
                    catalyst[k],
                    source=f"catalyst_llm:"
                           f"{catalyst.get('model_id', 'UNKNOWN')}",
                    known_from=catalyst.get("interpretation_known_from"),
                    note="SEMANTIC INTERPRETATION, not an official "
                         "fact; a wrong label must remain observable "
                         "as a model error")
        if evidence_class == "HISTORICAL_REPLAY" and \
                not catalyst.get("contemporaneous_interpretation"):
            F["catalyst_semantic_environment"] = absent(
                NOT_AVAILABLE, source="catalyst_llm",
                note="NOT_HISTORICALLY_AVAILABLE: a current model "
                     "reading an old event is not contemporaneous "
                     "cognition")
    else:
        F["catalyst_fact_events_known"] = absent(
            UNKNOWN, source="catalyst_official_record",
            note="catalyst not consulted for this subject this cycle")

    # -------------------------------------------------- cross-asset
    if cross_asset is not None:
        st.sources["cross_asset"] = cross_asset.get("source", "UNKNOWN")
        for k, v in cross_asset.items():
            if k in ("source", "as_of"):
                continue
            F[f"xasset_{k}"] = adopt(v, source=cross_asset.get(
                "source", "cross_asset"), as_of=cross_asset.get("as_of"))
    else:
        F["xasset_btc"] = absent(
            NOT_AVAILABLE, source="cross_asset",
            note="no cross-asset feed supplied this cycle; APEX does "
                 "not fabricate an institutional data stack it does "
                 "not own")

    # ------------------------------------------------ options state
    if options is not None:
        st.sources["options"] = options.get("source",
                                            "apex.organism."
                                            "options_surface")
        for k, v in options.items():
            if k in ("source", "as_of", "status"):
                continue
            F[f"opt_{k}"] = adopt(v, source=options.get("source",
                                                        "options"),
                                  as_of=options.get("as_of"))
    elif session in (Session.PREMARKET, Session.CLOSED):
        F["opt_state"] = absent(
            SESSION_INAPPLICABLE, source="options_surface",
            note="US options do not trade in this session -- "
                 "EXPECTED_ABSENCE. Friday's closing OPRA quote is "
                 "not Monday premarket state")
    else:
        F["opt_state"] = absent(
            UNKNOWN, source="options_surface",
            note="options enrichment is STAGED: not run for every "
                 "subject every minute. See the enrichment block for "
                 "why this subject was not enriched")
    return st
