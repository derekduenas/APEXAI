"""Live input-quality gate — operator directive: model correctness is
necessary, but market-input correctness dominates. Perfect Greeks
computed from stale/wide/broken quotes are still garbage. Every live-
fed OptionAnalyticsState carries quote age, depth, underlying age,
rate-source age, and dividend certainty; when any of these are weak,
this module's `cap` degrades state_quality -- the expression engine is
never handed a precise-looking number built on a bad input.

Absent (None) inputs mean "not measured" and impose NO cap -- this
keeps every synthetic/test-driven canonical_state() call (which never
supplies these) unaffected; only the live runtime, which always
measures them, exercises real degradation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.option_analytics import OPTION_ANALYTICS_POWER

LIVE_QUALITY_LEVELS = ("HIGH", "MODERATE", "LOW")
DIVIDEND_CONFIDENCE_LEVELS = ("REAL_SCHEDULE", "CONFIRMED_NONE", "UNKNOWN")

MAX_QUOTE_AGE_S_HIGH = 5.0
MAX_QUOTE_AGE_S_MODERATE = 30.0
MAX_UNDERLYING_AGE_S_HIGH = 5.0
MAX_UNDERLYING_AGE_S_MODERATE = 30.0
MAX_RATE_SOURCE_AGE_DAYS_HIGH = 7.0
MAX_RATE_SOURCE_AGE_DAYS_MODERATE = 30.0
MIN_DEPTH_HIGH = 5
MIN_DEPTH_MODERATE = 1


class LiveQualityError(RuntimeError):
    pass


def rank(level: str) -> int:
    return {"HIGH": 3, "MODERATE": 2, "LOW": 1}[level]


@dataclass(frozen=True)
class LiveQuoteQuality:
    quote_age_s: float | None
    underlying_age_s: float | None
    rate_source_age_days: float | None
    bid_size: int | None
    ask_size: int | None
    dividend_confidence: str
    cap: str | None            # None = not measured, no degradation imposed
    known_from: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.dividend_confidence not in DIVIDEND_CONFIDENCE_LEVELS:
            raise LiveQualityError(
                f"unknown dividend_confidence {self.dividend_confidence!r}")
        if self.cap is not None and self.cap not in LIVE_QUALITY_LEVELS:
            raise LiveQualityError(f"unknown cap {self.cap!r}")

    def as_record(self) -> dict:
        return {"kind": "live_quote_quality", **asdict(self)}


def classify_live_quality(*, known_from, quote_age_s: float | None = None,
                          underlying_age_s: float | None = None,
                          rate_source_age_days: float | None = None,
                          bid_size: int | None = None, ask_size: int | None = None,
                          dividend_confidence: str = "UNKNOWN") -> LiveQuoteQuality:
    nothing_measured = (quote_age_s is None and underlying_age_s is None
                        and rate_source_age_days is None and bid_size is None
                        and ask_size is None and dividend_confidence == "UNKNOWN")
    if nothing_measured:
        import pandas as pd
        return LiveQuoteQuality(
            quote_age_s=None, underlying_age_s=None, rate_source_age_days=None,
            bid_size=None, ask_size=None, dividend_confidence="UNKNOWN", cap=None,
            known_from=str(pd.Timestamp(known_from)))

    levels = []
    if quote_age_s is not None:
        levels.append("HIGH" if quote_age_s <= MAX_QUOTE_AGE_S_HIGH else
                      "MODERATE" if quote_age_s <= MAX_QUOTE_AGE_S_MODERATE else "LOW")
    if underlying_age_s is not None:
        levels.append("HIGH" if underlying_age_s <= MAX_UNDERLYING_AGE_S_HIGH else
                      "MODERATE" if underlying_age_s <= MAX_UNDERLYING_AGE_S_MODERATE else "LOW")
    if rate_source_age_days is not None:
        levels.append("HIGH" if rate_source_age_days <= MAX_RATE_SOURCE_AGE_DAYS_HIGH else
                      "MODERATE" if rate_source_age_days <= MAX_RATE_SOURCE_AGE_DAYS_MODERATE
                      else "LOW")
    if bid_size is not None and ask_size is not None:
        depth = min(bid_size, ask_size)
        levels.append("HIGH" if depth >= MIN_DEPTH_HIGH else
                      "MODERATE" if depth >= MIN_DEPTH_MODERATE else "LOW")
    if dividend_confidence in ("REAL_SCHEDULE", "CONFIRMED_NONE"):
        levels.append("HIGH")
    elif dividend_confidence == "UNKNOWN":
        levels.append("LOW")

    cap = min(levels, key=rank) if levels else None
    import pandas as pd
    return LiveQuoteQuality(
        quote_age_s=quote_age_s, underlying_age_s=underlying_age_s,
        rate_source_age_days=rate_source_age_days, bid_size=bid_size, ask_size=ask_size,
        dividend_confidence=dividend_confidence, cap=cap,
        known_from=str(pd.Timestamp(known_from)))
