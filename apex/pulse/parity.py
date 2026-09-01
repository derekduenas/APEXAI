"""LIVE / HISTORICAL SEMANTIC PARITY — declared, then verified.

Parity here is not a claim made in prose. There is exactly ONE
composer, so any feature both feeders can supply is equivalent BY
CONSTRUCTION: the definition of "prior close" or "session range
position" exists in one place and cannot drift. What differs is only
what each FEEDER can put in front of it.

This module states, per feature, which feeder can supply it and why --
and `audit()` checks the declaration against real packets, so a
manufactured parity claim fails rather than flatters.

NEVER MANUFACTURE PARITY TO MAKE THE DATASET LARGER. A feature marked
LIVE_ONLY is a feature the World Model must learn to live without in
training, and that is a smaller cost than training on a definition
that quietly meant something else in history.
"""
from __future__ import annotations

SEMANTICALLY_EQUIVALENT = "SEMANTICALLY_EQUIVALENT"
APPROXIMATE = "APPROXIMATE"
LIVE_ONLY = "LIVE_ONLY"
HISTORICAL_ONLY = "HISTORICAL_ONLY"
NOT_AVAILABLE = "NOT_AVAILABLE"

_SHARED = ("one composer serves both feeders, so the definition "
           "cannot drift between them")

MATRIX = {
    "mid": {
        "live": "alpaca snapshot latestQuote",
        "hist": "SIP quote tape, last NBBO at or before t",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED + "; both are a real two-sided NBBO midpoint",
        "limits": "historical NBBO needs the quote tape; a candle "
                  "close is NOT substituted"},
    "spread_bps": {
        "live": "alpaca snapshot latestQuote",
        "hist": "SIP quote tape", "status": SEMANTICALLY_EQUIVALENT,
        "history_start": "2016", "why": _SHARED, "limits": ""},
    "quote_age_s": {
        "live": "now - quote timestamp",
        "hist": "t - quote timestamp", "status": SEMANTICALLY_EQUIVALENT,
        "history_start": "2016", "why": _SHARED,
        "limits": "live age reflects provider latency; historical age "
                  "reflects tape sparsity. Same definition, different "
                  "typical magnitude"},
    "nbbo_size_imbalance": {
        "live": "snapshot quote sizes", "hist": "SIP quote tape sizes",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED + "; both withhold rather than zero-fill when "
                         "sizes are absent (PULSE-001)",
        "limits": "top of book only; not depth"},
    "prior_close": {
        "live": "snapshot prevDailyBar", "hist": "prior daily bar <= t",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED, "limits": "raw, unadjusted on both paths"},
    "prior_close_return_bps": {
        "live": "derived", "hist": "derived",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED, "limits": ""},
    "overnight_gap_bps": {
        "live": "derived", "hist": "derived",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED, "limits": ""},
    "cash_open_return_bps": {
        "live": "derived", "hist": "derived",
        "status": SEMANTICALLY_EQUIVALENT, "history_start": "2016",
        "why": _SHARED + "; SESSION_INAPPLICABLE before the cash open "
                         "on both paths", "limits": ""},
    "session_high": {
        "live": "snapshot dailyBar",
        "hist": "REBUILT from 1m bars closed at or before t",
        "status": APPROXIMATE, "history_start": "2016",
        "why": "the live daily aggregate is the provider's running "
               "session figure; the historical one is rebuilt from "
               "observed minute bars so it cannot contain the rest of "
               "the day",
        "limits": "the live provider aggregate may include "
                  "odd-lot/extended prints the 1m bar series treats "
                  "differently. Rebuilding is the SAFE direction: it "
                  "can only omit, never leak"},
    "session_low": {"live": "snapshot dailyBar",
                    "hist": "rebuilt from 1m bars", "status": APPROXIMATE,
                    "history_start": "2016",
                    "why": "same as session_high", "limits": "same"},
    "session_volume": {"live": "snapshot dailyBar",
                       "hist": "summed 1m bar volume",
                       "status": APPROXIMATE, "history_start": "2016",
                       "why": "same as session_high", "limits": "same"},
    "session_vwap": {"live": "provider vw",
                     "hist": "volume-weighted from 1m bars",
                     "status": APPROXIMATE, "history_start": "2016",
                     "why": "provider VWAP methodology is not "
                            "published; the historical one is "
                            "explicitly sum(vw*v)/sum(v) over observed "
                            "bars",
                     "limits": "DO NOT treat small divergences as "
                               "signal"},
    "vwap_distance_bps": {"live": "derived", "hist": "derived",
                          "status": APPROXIMATE, "history_start": "2016",
                          "why": "inherits session_vwap's status",
                          "limits": ""},
    "session_range_position": {"live": "derived", "hist": "derived",
                               "status": APPROXIMATE,
                               "history_start": "2016",
                               "why": "inherits session high/low",
                               "limits": ""},
    "relative_volume": {"live": "session vs prior session",
                        "hist": "session vs prior session",
                        "status": APPROXIMATE, "history_start": "2016",
                        "why": "inherits session_volume",
                        "limits": "a one-session baseline, NOT a "
                                  "multi-day average, and never one "
                                  "computed with future sessions"},
    "last_minute_volume": {"live": "snapshot minuteBar",
                           "hist": "last closed 1m bar",
                           "status": SEMANTICALLY_EQUIVALENT,
                           "history_start": "2016", "why": _SHARED,
                           "limits": ""},
    "ret_1m_bps": {"live": "PULSE rolling store",
                   "hist": "NOT reconstructible from PULSE's own "
                           "observation history",
                   "status": LIVE_ONLY, "history_start": "PULSE birth",
                   "why": "the rolling windows are built from PULSE's "
                          "OWN one-minute observations. History has no "
                          "record of what PULSE observed before PULSE "
                          "existed",
                   "limits": "a bar-derived historical equivalent is "
                             "possible but is a DIFFERENT measurement "
                             "and must not wear the same name"},
    "micro_*": {"live": "SIP tape via micro_state",
                "hist": "SIP tape via the same micro_state",
                "status": SEMANTICALLY_EQUIVALENT,
                "history_start": "2016",
                "why": "identical function on identical tape shape",
                "limits": "escalated subjects only; not every subject "
                          "every minute"},
    "catalyst_*": {"live": "catalyst context at now",
                   "hist": "events whose own known_from precedes t",
                   "status": APPROXIMATE, "history_start": "catalyst "
                                                           "ledger birth",
                   "why": "factual event records are causal; LLM "
                          "INTERPRETATION is not",
                   "limits": "a current model reading a historical "
                             "headline is NOT historical cognition. "
                             "Semantic fields are "
                             "NOT_HISTORICALLY_AVAILABLE unless a "
                             "contemporaneous record exists"},
    "opt_*": {"live": "ThetaData / OPRA at now",
              "hist": "ThetaData NBBO+trades; OI only where its own "
                      "as-of precedes t",
              "status": APPROXIMATE, "history_start": "2012",
              "why": "the same surface engine, but temporal "
                     "availability differs by field",
              "limits": "Friday-close quotes are NOT Monday-premarket "
                        "state; missing pre-open options are never "
                        "zero"},
}

for _k in ("ret_5m_bps", "ret_10m_bps", "ret_15m_bps", "ret_30m_bps",
           "ret_60m_bps"):
    MATRIX[_k] = dict(MATRIX["ret_1m_bps"])


def audit(live_packet: dict, hist_packet: dict) -> dict:
    """Check the declaration against real packets."""
    lf = set((live_packet.get("features") or {}))
    hf = set((hist_packet.get("features") or {}))
    findings, checked = [], 0
    for name, row in MATRIX.items():
        if name.endswith("*"):
            continue
        in_live, in_hist = name in lf, name in hf
        checked += 1
        if row["status"] in (SEMANTICALLY_EQUIVALENT, APPROXIMATE) \
                and not (in_live and in_hist):
            findings.append(
                f"{name}: declared {row['status']} but present "
                f"live={in_live} hist={in_hist}")
        if row["status"] == LIVE_ONLY and in_hist:
            hq = (hist_packet["features"][name] or {}).get("q")
            if hq == "VALID":
                findings.append(
                    f"{name}: declared LIVE_ONLY but the historical "
                    f"packet supplied a VALID value -- parity was "
                    f"manufactured")
    return {"features_declared": len(MATRIX), "checked": checked,
            "live_feature_count": len(lf), "hist_feature_count": len(hf),
            "findings": findings,
            "verdict": "PARITY_DECLARATION_HOLDS" if not findings
                       else "PARITY_DECLARATION_VIOLATED"}
