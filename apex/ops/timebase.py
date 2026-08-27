"""ONE CANONICAL TIME BOUNDARY — the ET/UTC defect class ends here.

Three separate ET-vs-UTC errors occurred in a single week:

  2026-08-24  Defect B: pre-entry contamination -- a UTC-naive vs
              ET-naive comparison admitted 112 bars from BEFORE the
              position existed, and the reported MFE occurred eleven
              minutes before entry.
  2026-08-25  the MSFT card timestamp read as ambiguous until the
              pedigree was traced by hand.
  2026-08-26  my cohort analysis treated ET-naive scan `T` as UTC,
              shifted every forward path four hours, and silently
              collapsed the ATTACK cohort to n=1.

Three occurrences is not operator error. It is a defect CLASS, and the
cause is structural: APEX stores some timestamps ET-naive (option cards
and scans, written from wall clock) and others UTC-aware (market bars).
Naive strings carry no evidence of which convention produced them, so
every consumer re-derives the answer and eventually one of them guesses
wrong.

THE RULE. Internally everything is timezone-AWARE UTC. At every
ingestion boundary the source timezone is DECLARED, never inferred. A
naive timestamp with no declared source contract is refused rather
than assumed -- because assuming is exactly what produced all three
incidents.

decision_power: NONE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Declared source contracts. A reader that does not appear here has not
# said what its timestamps mean, and must not be guessed at.
SOURCE_CONTRACTS = {
    "OPTIONS_CARD": "ET_NAIVE",       # written from ET wall clock
    "OPTIONS_SCAN": "ET_NAIVE",
    "BTC_LEDGER": "UTC_AWARE",
    "MARKET_BAR": "UTC_AWARE",        # event_time_utc, ISO with Z
    "HEARTBEAT": "UTC_AWARE",
    "CHAIN_LEDGER": "UTC_AWARE",
    "ORCHESTRATOR": "UTC_AWARE",
}

CONVENTIONS = ("ET_NAIVE", "UTC_AWARE", "UTC_NAIVE")


class TimebaseViolation(RuntimeError):
    pass


def to_utc(value, *, source: str) -> datetime:
    """The ONE conversion. `source` must be a declared contract.

    Refuses an undeclared source instead of defaulting, because a
    default is a guess wearing a keyword argument."""
    convention = SOURCE_CONTRACTS.get(source)
    if convention is None:
        raise TimebaseViolation(
            f"undeclared timestamp source {source!r}. Declare its "
            f"contract in SOURCE_CONTRACTS -- a default here is how "
            f"three ET/UTC incidents happened in one week")
    t = (value if isinstance(value, datetime)
         else datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    if t.tzinfo is not None:
        return t.astimezone(timezone.utc)
    if convention == "ET_NAIVE":
        # DST-correct by construction: zoneinfo resolves the offset for
        # this specific date, so an August 14:42 is EDT and a January
        # 14:42 is EST without anyone remembering the difference.
        return t.replace(tzinfo=ET).astimezone(timezone.utc)
    if convention == "UTC_NAIVE":
        return t.replace(tzinfo=timezone.utc)
    raise TimebaseViolation(
        f"{source} is declared {convention} but produced a NAIVE "
        f"timestamp {value!r}: the contract and the data disagree, and "
        f"guessing which is right is the defect")


def require_aware(t: datetime, *, what: str) -> datetime:
    if t.tzinfo is None:
        raise TimebaseViolation(
            f"{what} is timezone-naive inside the system; only "
            f"ingestion boundaries may see naive values")
    return t.astimezone(timezone.utc)


def causal_window(events, *, entry, boundary, source: str,
                  time_key: str = "event_time_utc") -> list:
    """Events STRICTLY after entry and no later than the sealed
    boundary. The filter that Defect B got wrong.

    Both edges matter: `>` excludes the pre-entry bars that once
    produced an MFE eleven minutes before the position existed, and
    `<=` excludes the after-hours print that once flipped a verdict's
    sign."""
    e = require_aware(entry, what="entry")
    b = require_aware(boundary, what="resolution boundary")
    if b <= e:
        raise TimebaseViolation(
            "resolution boundary is not after entry; this window can "
            "only be empty or backwards")
    out = []
    for ev in events:
        t = to_utc(ev[time_key], source=source)
        if e < t <= b:
            out.append(ev)
    return out
