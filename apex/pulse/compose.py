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
from apex.pulse import anchor_freshness, derived, freshness
from apex.pulse.twin import (NOT_AVAILABLE, NOT_ESTIMABLE,
                             PROVIDER_ERROR, SESSION_INAPPLICABLE,
                             STALE, UNKNOWN, TwinState, absent, adopt,
                             ok)

# ANCHOR_FRESHNESS_POLICY_V1 classification -> the governed quality state it
# takes. Kept distinct on purpose: a stale anchor, an absent one and an
# undated one are three different facts and must not be flattened into one.
_ANCHOR_QUALITY = {
    anchor_freshness.SESSIONS_MISSED: STALE,
    anchor_freshness.NO_PRIOR_SESSION: NOT_AVAILABLE,
    anchor_freshness.UNDATED: NOT_ESTIMABLE,
    anchor_freshness.NOT_A_PRIOR_SESSION: NOT_ESTIMABLE,
    anchor_freshness.NOT_A_TRADING_SESSION: NOT_ESTIMABLE,
    anchor_freshness.CALENDAR_UNRESOLVED: NOT_ESTIMABLE,
}

COMPOSER_VERSION = "PULSE_COMPOSE_V0.2"
COMPOSER_HISTORY = {
    "V0": "the freshness verdict was applied where a value was READ and did not travel to what "
          "was BUILT from it. NKLA 2026-09-01: mid/spread_bps/nbbo_size_imbalance STALE on a "
          "553-day-old quote, while prior_close_return_bps (-2869.94), cash_open_return_bps, "
          "vwap_distance_bps and session_range_position were computed from that same refused mid "
          "and marked VALID (DERIVED-FIELD-STALENESS-001)",
    "V0.1": "PULSE-009: every derived field is built through apex.pulse.derived under a declared "
            "dependency map. A derived field is VALID only when every ingredient is VALID; "
            "otherwise it carries the ingredient's absence reason or STALE, with the culprit "
            "named, and no value. Independent fields are untouched: a stale quote does not reach "
            "prior_close. The rolling and premarket stores are only OBSERVED with a usable mid, "
            "so an untrusted price cannot enter PULSE's own memory.",
    "V0.2": "PULSE-010: the prior-session anchor is judged by ANCHOR_FRESHNESS_POLICY_V1 -- "
            "VALID only when its session is the exchange's immediately preceding regular "
            "session. NKLA 2026-09-01 carried a prior_close from 2025-02-24 marked VALID "
            "(LIVE-ANCHOR-STALENESS-V1). The anchor now carries its own quality and the "
            "PULSE-009 dependency map does the rest: prior_close_return_bps, "
            "overnight_gap_bps and relative_volume follow it, while the current session's "
            "cash open and aggregates do not."}

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

        # PULSE-009: the ingredients are admitted ONCE, as fields with their
        # own quality, and every quote-derived value is built from them. The
        # freshness verdict is carried on the ingredient, so it reaches
        # everything downstream instead of stopping at the first reader.
        stale_note = None if verdict["fresh"] else verdict["why"]
        ing = {
            "raw:quote.bid": (derived.raw_field(bp, source="alpaca_sip", as_of=qt)
                              if verdict["fresh"] else
                              absent(STALE, source="alpaca_sip", note=stale_note)),
            "raw:quote.ask": (derived.raw_field(ap, source="alpaca_sip", as_of=qt)
                              if verdict["fresh"] else
                              absent(STALE, source="alpaca_sip", note=stale_note)),
            "raw:quote.timestamp": (ok(qt, source="alpaca_sip", as_of=qt) if qt
                                    else absent(NOT_AVAILABLE, source="alpaca_sip")),
        }
        sizes_usable = (isinstance(q.get("bs"), (int, float))
                        and isinstance(q.get("as"), (int, float))
                        and not isinstance(q.get("bs"), bool)
                        and not isinstance(q.get("as"), bool)
                        and (q["bs"] + q["as"]) > 0)
        # PULSE-001: sizes are a separate question from prices
        size_absent = absent(NOT_ESTIMABLE, source="alpaca_sip",
                             note="quote carries no usable sizes; "
                                  "missing size is not zero size")
        for key, val in (("raw:quote.bid_size", q.get("bs")),
                         ("raw:quote.ask_size", q.get("as"))):
            ing[key] = (size_absent if not sizes_usable
                        else derived.raw_field(val, source="alpaca_sip", as_of=qt)
                        if verdict["fresh"] else
                        absent(STALE, source="alpaca_sip", note=stale_note))

        F["mid"] = derived.derive("mid", ing, lambda: round((bp + ap) / 2, 6),
                                  source="alpaca_sip", as_of=qt)
        F["spread_bps"] = derived.derive(
            "spread_bps", ing, lambda: round((ap - bp) / ((bp + ap) / 2) * 1e4, 3),
            source="alpaca_sip", as_of=qt)
        F["spread_rel"] = derived.derive(
            "spread_rel", ing, lambda: round((ap - bp) / ((bp + ap) / 2), 8),
            source="alpaca_sip", as_of=qt)
        # DERIVED_FIELD_CONTRACT_V1, STALENESS_IS_THE_MEASUREMENT: quote_age_s
        # reports HOW OLD the quote is, so an old quote must not delete it. It
        # depends on the timestamp, never on the prices.
        F["quote_age_s"] = derived.derive(
            "quote_age_s", ing, lambda: round(age, 2) if age is not None else None,
            source="alpaca_sip", as_of=qt)
        F["touch_size"] = derived.derive(
            "touch_size", ing, lambda: q["bs"] + q["as"], source="alpaca_sip", as_of=qt)
        F["nbbo_size_imbalance"] = derived.derive(
            "nbbo_size_imbalance", ing,
            lambda: round((q["bs"] - q["as"]) / (q["bs"] + q["as"]), 4),
            source="alpaca_sip", as_of=qt)
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
    # PULSE-009: the INDEPENDENT fields are built first, each from its own
    # single source, and the derived fields are then built FROM THEM rather
    # than from raw locals. That is the whole repair: dependency, in one
    # direction, visible in the code.
    # PULSE-010: the anchor is judged in SESSIONS against the exchange
    # calendar, never in seconds. A real number from the wrong session is
    # still the wrong number, and PULSE-009 propagation carries the verdict
    # to everything built on it.
    prev_bar = snapshot.get("prevDailyBar") or {}
    anchor_verdict = anchor_freshness.classify_prior_close(
        anchor_stamp=prev_bar.get("t"),
        packet_session_date=scheduled_time,
        present=bool(prev_bar) and prev is not None)
    st.sources["anchor_freshness"] = anchor_freshness.ANCHOR_FRESHNESS_POLICY_VERSION
    if anchor_verdict["fresh"]:
        F["prior_close"] = ok(prev, source="alpaca_sip", as_of=prev_bar.get("t"),
                              note=anchor_verdict["why"])
    else:
        F["prior_close"] = absent(_ANCHOR_QUALITY[anchor_verdict["classification"]],
                                  source="alpaca_sip", as_of=prev_bar.get("t") or None,
                                  note=anchor_verdict["why"])
    F["prior_close_session"] = (
        ok(anchor_verdict["anchor_session_date"], source="alpaca_sip",
           as_of=prev_bar.get("t"),
           note="the exchange session this anchor belongs to; expected %s"
                % anchor_verdict.get("expected_anchor_session"))
        if anchor_verdict.get("anchor_session_date")
        else absent(NOT_AVAILABLE, source="alpaca_sip",
                    note=anchor_verdict["why"]))

    # ------------------------------------------- session structure
    for name, key in (("session_high", "h"), ("session_low", "l"),
                      ("session_vwap", "vw"), ("session_volume", "v"),
                      ("session_open", "o")):
        v = day.get(key)
        F[name] = (ok(v, source="alpaca_sip", as_of=day.get("t"))
                   if v is not None
                   else absent(NOT_AVAILABLE, source="alpaca_sip"))

    d_open = day.get("o")
    premarket_or_closed = session in (Session.PREMARKET, Session.CLOSED)
    D = {k: F[k] for k in ("mid", "prior_close", "session_open", "session_high",
                           "session_low", "session_vwap", "session_volume")}

    F["prior_close_return_bps"] = derived.derive(
        "prior_close_return_bps", D, lambda: _bps(F["mid"].value, prev), as_of=qt)
    F["cash_open_return_bps"] = derived.derive(
        "cash_open_return_bps", D, lambda: _bps(F["mid"].value, d_open), as_of=qt,
        session_inapplicable=("no cash open has occurred in %s" % session.value
                              if premarket_or_closed else None))
    F["overnight_gap_bps"] = derived.derive(
        "overnight_gap_bps", D, lambda: _bps(d_open, prev), as_of=day.get("t"),
        session_inapplicable=("the gap is defined at the cash open"
                              if premarket_or_closed else None))
    F["session_range_position"] = derived.derive(
        "session_range_position", D,
        lambda: (round((F["mid"].value - day["l"]) / (day["h"] - day["l"]), 4)
                 if day["h"] > day["l"] else None), as_of=qt,
        note="requires a live mid and a non-degenerate session range")
    F["vwap_distance_bps"] = derived.derive(
        "vwap_distance_bps", D, lambda: _bps(F["mid"].value, day.get("vw")), as_of=qt)

    pv = prev_bar.get("v")
    # the prior-session VOLUME comes off the same bar as the prior close, so
    # it inherits the same anchor verdict: one stale bar, one verdict.
    prior_volume_field = (
        derived.raw_field(pv, source="alpaca_sip", as_of=prev_bar.get("t"),
                          note="requires a session and a prior-session volume; a ONE-SESSION "
                               "baseline, never one computed with future sessions")
        if anchor_verdict["fresh"]
        else absent(_ANCHOR_QUALITY[anchor_verdict["classification"]], source="alpaca_sip",
                    as_of=prev_bar.get("t") or None, note=anchor_verdict["why"]))
    F["relative_volume"] = derived.derive(
        "relative_volume",
        {"session_volume": F["session_volume"],
         "raw:prior_session.volume": prior_volume_field},
        lambda: round(day["v"] / pv, 4) if pv else None, as_of=day.get("t"))
    F["last_minute_volume"] = (
        ok(minute["v"], source="alpaca_sip", as_of=minute.get("t"))
        if minute.get("v") is not None
        else absent(NOT_AVAILABLE, source="alpaca_sip"))

    # ------------------------------- rolling path (PULSE's own eyes)
    # PULSE-009: observe PULSE's own memory only with a USABLE mid. Feeding a
    # refused price into the rolling store would carry the contamination into
    # later cycles, where no quality flag could reach it any more.
    if rolling is not None and F["mid"].usable:
        rolling.observe(subject, at=now, price=F["mid"].value, volume=day.get("v"))
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
    if premarket_path is not None and F["mid"].usable:
        premarket_path.observe(subject, at=now, price=F["mid"].value,
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
        st.sources["catalyst"] = "apex.catalyst.events(fenced)"
        status = catalyst.get("catalyst_status")
        # the status itself is a FACT about the query, and it
        # distinguishes "asked, nothing there" from "never asked"
        F["catalyst_fact_status"] = adopt(
            status, source="catalyst_official_record",
            as_of=catalyst.get("latest_event_known_from"))
        if not catalyst.get("queried"):
            F["catalyst_fact_events_known"] = absent(
                PROVIDER_ERROR, source="catalyst_official_record",
                note=str(catalyst.get("why", status)))
        else:
            for k in ("events_known", "latest_event_id",
                      "latest_event_time", "latest_event_known_from",
                      "latest_event_first_seen", "headline",
                      "source_class", "catalyst_state_hash",
                      "ledger_events_causally_visible"):
                if k in catalyst:
                    F[f"catalyst_fact_{k}"] = adopt(
                        catalyst[k],
                        source="catalyst_official_record",
                        as_of=catalyst.get("latest_event_time"),
                        known_from=catalyst.get(
                            "latest_event_known_from"))
        # INTERPRETATION is separately sourced and separately dated,
        # so a misclassification stays visible as a model error
        # UNATTRIBUTED classification: interpretation with no
        # recorded interpreter. It may not borrow a model's
        # credibility, so it gets its own source name.
        for k in ("classification_event_type",
                  "classification_importance"):
            if k in catalyst:
                F[f"catalyst_semantic_{k}"] = adopt(
                    catalyst[k],
                    source="catalyst_classifier:UNATTRIBUTED",
                    known_from=catalyst.get(
                        "latest_event_known_from"),
                    note="CLASSIFICATION with no recorded "
                         "interpreter -- interpretation, not fact, "
                         "and not attributable to a model")
        model = catalyst.get("model_id")
        if model:
            for k in ("directional_expectation",
                      "interpretation_contract"):
                if k in catalyst:
                    F[f"catalyst_semantic_{k}"] = adopt(
                        catalyst[k], source=f"catalyst_llm:{model}",
                        known_from=catalyst.get(
                            "interpretation_known_from"),
                        note="ATTRIBUTED SEMANTIC INTERPRETATION, not "
                             "an official fact; a wrong label must "
                             "remain observable as a model error")
        elif catalyst.get("queried") and catalyst.get("events_known"):
            F["catalyst_semantic_directional_expectation"] = absent(
                NOT_AVAILABLE, source="catalyst_llm",
                note="INTERPRETATION_NOT_AVAILABLE: this event has no "
                     "attributed interpreter")
        if evidence_class == "HISTORICAL_REPLAY" and \
                not catalyst.get("contemporaneous_interpretation"):
            # BOTH interpretation layers are suppressed. An
            # unattributed classification applied today to a
            # historical event is no more contemporaneous than an
            # attributed one -- if anything it is worse, because it
            # cannot even name whose opinion it is.
            for k in ("catalyst_semantic_event_type",
                      "catalyst_semantic_classification_event_type",
                      "catalyst_semantic_classification_importance",
                      "catalyst_semantic_directional_expectation"):
                F[k] = absent(
                    NOT_AVAILABLE, source="catalyst_llm",
                    note="NOT_HISTORICALLY_AVAILABLE: a current model "
                         "reading an old event is not contemporaneous "
                         "cognition")
    else:
        F["catalyst_fact_status"] = absent(
            UNKNOWN, source="catalyst_official_record",
            note="CATALYST_NOT_QUERIED: this cycle never asked, which "
                 "is materially different from asking and finding "
                 "nothing")

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
        st.sources["options"] = options.get("source", "options_surface")
        status = options.get("status")
        src = options.get("source", "options")
        if status in ("SESSION_INAPPLICABLE", "DATA_NOT_AVAILABLE",
                      "PROVIDER_FAILURE", "NOT_ESTIMABLE"):
            F["opt_state"] = absent(
                {"SESSION_INAPPLICABLE": SESSION_INAPPLICABLE,
                 "DATA_NOT_AVAILABLE": NOT_AVAILABLE,
                 "PROVIDER_FAILURE": PROVIDER_ERROR,
                 "NOT_ESTIMABLE": NOT_ESTIMABLE}[status],
                source=src, note=str(options.get("why", status)))
        else:
            F["opt_state"] = ok("QUERIED", source=src,
                                as_of=options.get("as_of"))
            for k, v in options.items():
                if k in ("source", "as_of", "status", "why"):
                    continue
                F[f"opt_{k}"] = adopt(v, source=src,
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
