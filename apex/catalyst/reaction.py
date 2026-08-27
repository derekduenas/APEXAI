"""MARKET REACTION — the headline is not the intelligence.

What a catalyst SAYS is cheap; every participant reads the same words.
What the market DID about it is the observation, and the interesting
case is when the two disagree:

    good news the tape cannot lift
    bad news the tape refuses to break
    a hawkish line and equities rally anyway
    a clean break with no identifiable catalyst at all

Those are the states an event-driven analyst hunts. This module
measures them arithmetically and labels them DESCRIPTIVELY. Every label
here carries exactly zero assumed alpha -- they are research
candidates, and EdgeForge decides whether any of them are worth
anything.

CAUSALITY: reaction is measured strictly AFTER known_from, never after
event_time. An event that happened at 14:00 and was observed at 14:03
is measured from 14:03, because 14:00-14:03 was not available to
anybody acting on APEX's information.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from apex.catalyst.events import CatalystViolation
from apex.ops.timebase import require_aware, to_utc

HORIZONS_MIN = (1, 5, 15, 30, 60)

REACTION_CLASS = (
    "EXPECTED_REACTION", "UNDER_REACTION", "OVER_REACTION",
    "FAILED_POSITIVE_REACTION", "FAILED_NEGATIVE_REACTION",
    "REVERSAL_AFTER_REACTION", "NO_IDENTIFIABLE_REACTION", "UNKNOWN")

DIRECTIONAL_EXPECTATION = ("POSITIVE", "NEGATIVE", "AMBIGUOUS",
                           "UNKNOWN")

# A move must clear this to count as a reaction rather than drift. It
# is a MEASUREMENT floor in volatility units, not an economic
# threshold: below it the tape has not said anything distinguishable.
REACTION_FLOOR_ATR = 0.25


def measure(*, bars, known_from, atr, session_close,
            source: str = "MARKET_BAR") -> dict:
    """Signed price path at governed horizons after known_from.

    `bars` may include anything; only bars strictly after known_from
    and no later than the official close are used."""
    kf = require_aware(to_utc(known_from, source="MARKET_BAR"),
                       what="known_from")
    close_t = require_aware(to_utc(session_close, source="MARKET_BAR"),
                            what="session_close")
    fut = []
    for b in bars:
        t = to_utc(b["event_time_utc"], source=source)
        if kf < t <= close_t:
            fut.append((t, b))
    fut.sort()
    if not fut:
        return {"kind": "market_reaction", "verdict": "NO_PATH",
                "why": "no bars between known_from and the official "
                       "close -- the event is unmeasurable, not neutral",
                "decision_power": "SHADOW_CONTEXT_ONLY"}

    ref = fut[0][1]["open"] if "open" in fut[0][1] else fut[0][1]["close"]
    out = {}
    for m in HORIZONS_MIN:
        cutoff = kf + timedelta(minutes=m)
        seg = [b for t, b in fut if t <= cutoff]
        if not seg:
            out[f"{m}m"] = "NOT_ESTIMABLE"
            continue
        last = seg[-1]["close"]
        out[f"{m}m"] = {
            "return_pct": round((last - ref) / ref * 100, 4),
            "return_atr": (round((last - ref) / atr, 4)
                           if atr else "NOT_ESTIMABLE"),
            "bars": len(seg)}
    closing = fut[-1][1]["close"]
    highs = [b["high"] for _t, b in fut]
    lows = [b["low"] for _t, b in fut]
    vols = [b.get("volume", 0) for _t, b in fut]
    return {"kind": "market_reaction",
            "reference_price": ref,
            "known_from": kf.isoformat(),
            "horizons": out,
            "to_close": {"return_pct": round((closing - ref) / ref * 100, 4),
                         "return_atr": (round((closing - ref) / atr, 4)
                                        if atr else "NOT_ESTIMABLE")},
            "mfe_pct": round((max(highs) - ref) / ref * 100, 4),
            "mae_pct": round((min(lows) - ref) / ref * 100, 4),
            "median_volume": (round(statistics.median(vols), 1)
                              if vols else "NOT_ESTIMABLE"),
            "n_bars": len(fut),
            "law": "measured from known_from, never from event_time",
            "decision_power": "SHADOW_CONTEXT_ONLY"}


def classify(*, expectation: str, reaction: dict, atr,
             horizon: str = "15m") -> dict:
    """Label the disagreement between what a catalyst implied and what
    the tape did. DESCRIPTIVE ONLY -- no label here has been shown to
    predict anything, and treating one as a signal would be exactly
    the headline-trading this package forbids."""
    if expectation not in DIRECTIONAL_EXPECTATION:
        raise CatalystViolation(
            f"unknown directional expectation {expectation!r}")
    if reaction.get("verdict") == "NO_PATH":
        return {"kind": "reaction_classification",
                "reaction_class": "UNKNOWN",
                "why": "no measurable path",
                "decision_power": "SHADOW_CONTEXT_ONLY"}

    h = reaction["horizons"].get(horizon)
    if not isinstance(h, dict):
        return {"kind": "reaction_classification",
                "reaction_class": "UNKNOWN",
                "why": f"horizon {horizon} not estimable",
                "decision_power": "SHADOW_CONTEXT_ONLY"}
    r_atr = h.get("return_atr")
    if not isinstance(r_atr, (int, float)):
        return {"kind": "reaction_classification",
                "reaction_class": "UNKNOWN",
                "why": "ATR unavailable; a percentage move is not "
                       "comparable across instruments",
                "decision_power": "SHADOW_CONTEXT_ONLY"}

    moved = abs(r_atr) >= REACTION_FLOOR_ATR
    to_close = reaction["to_close"].get("return_atr")
    reversed_later = (isinstance(to_close, (int, float)) and moved
                      and (to_close > 0) != (r_atr > 0)
                      and abs(to_close) >= REACTION_FLOOR_ATR)

    if expectation == "UNKNOWN":
        cls = ("NO_IDENTIFIABLE_REACTION" if not moved else "UNKNOWN")
    elif expectation == "AMBIGUOUS":
        cls = "UNKNOWN"
    elif not moved:
        cls = ("FAILED_POSITIVE_REACTION" if expectation == "POSITIVE"
               else "FAILED_NEGATIVE_REACTION")
    else:
        agrees = (r_atr > 0) == (expectation == "POSITIVE")
        if not agrees:
            cls = ("FAILED_POSITIVE_REACTION"
                   if expectation == "POSITIVE"
                   else "FAILED_NEGATIVE_REACTION")
        elif reversed_later:
            cls = "REVERSAL_AFTER_REACTION"
        elif abs(r_atr) >= 3 * REACTION_FLOOR_ATR:
            cls = "OVER_REACTION"
        else:
            cls = "EXPECTED_REACTION"

    return {"kind": "reaction_classification",
            "reaction_class": cls,
            "expectation": expectation,
            "horizon": horizon,
            "return_atr": r_atr,
            "moved_beyond_floor": moved,
            "reversed_by_close": reversed_later,
            "floor_atr": REACTION_FLOOR_ATR,
            "law": "descriptive only -- zero assumed alpha; EdgeForge "
                   "decides whether any of these classes matter",
            "decision_power": "SHADOW_CONTEXT_ONLY"}


def disagreement(*, event, reaction_class: str) -> dict | None:
    """Surface the case worth studying: the tape contradicting the
    news. Returns None when there is nothing interesting, because a
    detector that always fires detects nothing."""
    interesting = ("FAILED_POSITIVE_REACTION", "FAILED_NEGATIVE_REACTION",
                   "REVERSAL_AFTER_REACTION", "OVER_REACTION")
    if reaction_class not in interesting:
        return None
    return {"kind": "CATALYST_REACTION_DISAGREEMENT",
            "event_id": getattr(event, "event_id", "UNKNOWN"),
            "event_type": getattr(event, "event_type", "UNKNOWN"),
            "reaction_class": reaction_class,
            "question": "the market was told something and did not do "
                        "what the words implied -- why?",
            "status": "RESEARCH_CANDIDATE",
            "not_tradeable": True,
            "decision_power": "SHADOW_CONTEXT_ONLY"}
