"""Per-symbol continuity, computed SEPARATELY for trades, quotes and
bars — because they answer different questions and today's artifacts
conflated them.

WHY THIS EXISTS (measured 2026-08-18): universe_coverage.json reported
`continuous_coverage_fraction: 0.0` for all 164 symbols while the feed
delivered 11.9M trades and 18.7M quotes without stopping. A single
scalar "continuity" number cannot distinguish:

    - the provider genuinely stopped sending us data          (bad)
    - our process stalled and missed data that was sent       (bad)
    - the stock simply did not trade for ninety seconds       (normal)

Collapsing all three into one number made a mostly-healthy session look
identically broken to a genuinely broken one. This module keeps them as
separate, separately-reported facts.

THE NO-ACTIVITY LAW: NO_TRADES_OCCURRED must never be reported as
PROVIDER_DATA_GAP. A quiet symbol is not a broken feed. Quote activity
during a trade-silent interval is the discriminator, and when no quote
evidence exists either way the interval is UNDETERMINED -- never
silently blamed on the provider.

decision_power: NONE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

INTERVAL_CLASSES = (
    "OBSERVED",             # data present for this interval
    "NO_ACTIVITY",          # feed healthy, instrument simply silent
    "PROVIDER_GAP",         # provider did not deliver during a live socket
    "LOCAL_GAP",            # our process was not listening
    "INCOMPLETE",           # partial coverage within the interval
    "UNDETERMINED",         # not enough evidence to attribute -- never guessed
)


class SymbolContinuityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SymbolContinuity:
    symbol: str
    session_date: str
    expected_intervals: int
    observed_intervals: int
    provider_gap_intervals: int
    local_gap_intervals: int
    no_activity_intervals: int
    incomplete_intervals: int
    undetermined_intervals: int
    trade_continuity: float | None
    quote_continuity: float | None
    bar_continuity: float | None
    known_from: str
    as_of: str
    decision_power: str = "NONE"

    def __post_init__(self):
        total = (self.observed_intervals + self.provider_gap_intervals
                 + self.local_gap_intervals + self.no_activity_intervals
                 + self.incomplete_intervals + self.undetermined_intervals)
        if total != self.expected_intervals:
            raise SymbolContinuityError(
                f"interval classes must partition expected_intervals exactly: "
                f"{total} != {self.expected_intervals}")

    def as_record(self) -> dict:
        return {"kind": "symbol_continuity", **asdict(self)}


def classify_interval(*, had_trade: bool, had_quote: bool,
                      socket_open: bool, process_listening: bool,
                      partial_coverage: bool) -> str:
    """One interval, one honest label. Order matters: local and provider
    faults are established BEFORE any judgment about instrument
    activity, so a genuine outage is never excused as 'quiet stock'."""
    if not process_listening:
        return "LOCAL_GAP"
    if not socket_open:
        return "PROVIDER_GAP"
    if had_trade and partial_coverage:
        return "INCOMPLETE"
    if had_trade:
        return "OBSERVED"
    # No trade. A live quote stream proves the feed was working and the
    # instrument was merely silent -- that is NO_ACTIVITY, not a gap.
    if had_quote:
        return "NO_ACTIVITY"
    # No trade AND no quote on an open socket: we cannot tell a dead
    # provider from a dead-quiet instrument. Say so.
    return "UNDETERMINED"


def compute(*, symbol: str, session_date: str, interval_classes: list,
            known_from, now) -> SymbolContinuity:
    """`interval_classes`: one INTERVAL_CLASSES label per expected
    interval, in order. Continuity ratios are computed over DIFFERENT
    denominators on purpose:

      trade_continuity -- intervals with an actual print, over intervals
                          where a print was POSSIBLE (excludes local and
                          provider gaps, which say nothing about the
                          instrument)
      quote_continuity -- intervals where the feed proved itself live
                          (OBSERVED / INCOMPLETE / NO_ACTIVITY) over all
                          expected intervals
      bar_continuity   -- intervals that produced a COMPLETE bar over all
                          expected intervals
    """
    import pandas as pd
    bad = set(interval_classes) - set(INTERVAL_CLASSES)
    if bad:
        raise SymbolContinuityError(f"unknown interval class(es) {bad}")

    n = len(interval_classes)
    counts = {c: interval_classes.count(c) for c in INTERVAL_CLASSES}

    feed_provable = counts["OBSERVED"] + counts["INCOMPLETE"] + counts["NO_ACTIVITY"]
    instrument_possible = feed_provable          # excludes LOCAL/PROVIDER gaps
    trade_continuity = ((counts["OBSERVED"] + counts["INCOMPLETE"])
                        / instrument_possible) if instrument_possible else None
    quote_continuity = (feed_provable / n) if n else None
    bar_continuity = (counts["OBSERVED"] / n) if n else None

    return SymbolContinuity(
        symbol=symbol, session_date=session_date, expected_intervals=n,
        observed_intervals=counts["OBSERVED"],
        provider_gap_intervals=counts["PROVIDER_GAP"],
        local_gap_intervals=counts["LOCAL_GAP"],
        no_activity_intervals=counts["NO_ACTIVITY"],
        incomplete_intervals=counts["INCOMPLETE"],
        undetermined_intervals=counts["UNDETERMINED"],
        trade_continuity=trade_continuity, quote_continuity=quote_continuity,
        bar_continuity=bar_continuity,
        known_from=str(pd.Timestamp(known_from)), as_of=str(pd.Timestamp(now)))
