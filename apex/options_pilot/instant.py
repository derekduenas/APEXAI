"""ONE CANONICAL TIMESTAMP REPRESENTATION for OPTIONS-PILOT-001 (OPERATING-LOOP-001, item 2).

THE CANONICAL INSTANT IS AN EXACT INTEGER NUMBER OF MICROSECONDS since the UNIX epoch.

Why an integer and not a float. Records serialize instants with
`datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")`, which prints WHOLE MICROSECONDS. A float
epoch therefore does not survive a round trip: the string that comes back parses to a value that can be up to half a
microsecond LARGER than the float it was written from. Comparing that against a full-precision clock reading refused
forecasts created at exactly the current instant, and that defect silently discarded 7 of 12 scans of the loop
demonstration (docs/LOOP_DEMONSTRATION_CORRECTIONS.md §2).

CONVERSION AND ROUNDING, DECLARED.
    float epoch  -> canonical:  datetime.fromtimestamp(epoch, tz=UTC), then the exact integer microsecond offset from
                                1970-01-01T00:00:00Z. `fromtimestamp` rounds the float to the nearest microsecond,
                                ties to even. This is the SAME conversion the serializer performs, so the canonical
                                integer is exactly the microsecond that will be written to disk.
    ISO string   -> canonical:  `parse_utc` then the same integer offset. `fromisoformat` is exact on a microsecond
                                string, so string -> canonical -> string is the identity.
    canonical    -> string:     `to_utc_string`, exact.
    canonical    -> float:      micros / 1_000_000. Exact for every instant this system records (|micros| < 2**53).

THE COMPARISON RULE. Two instants are compared as canonical INTEGERS and nothing else:

    equal     iff canonical_micros(a) == canonical_micros(b)
    a after b iff canonical_micros(a) >  canonical_micros(b)

NO EPSILON IS ADDED. The previous repair compared `created > now + 1e-6`, which accepted an instant one full
microsecond in the future -- the NEXT REPRESENTABLE INSTANT, a genuinely future timestamp. That tolerance is removed
here: an instant one microsecond ahead of the clock is in the future and is refused. Equality at the canonical
granularity is what the earlier defect actually needed, and equality is what this module provides.

SOURCE TIMESTAMPS ARE PRESERVED SEPARATELY. Canonicalization is for COMPARISON and for the system's own record
fields. Whatever a provider or a recorded file said -- its own string, its own precision, its own field name -- is
kept verbatim alongside, via `stamp(...)`, and is never overwritten by the canonical value."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .clock import ClockRefused, check_reading, is_real, parse_utc, to_utc_string

CANONICAL_UNIT = "MICROSECOND"
MICROS_PER_SECOND = 1_000_000
GRANULARITY_S = 1.0 / MICROS_PER_SECOND
EPOCH_DT = datetime(1970, 1, 1, tzinfo=timezone.utc)
ONE_MICROSECOND = timedelta(microseconds=1)

CONVERSION_RULE = (
    "CANONICAL_INSTANT_V1: an instant is an exact integer of microseconds since 1970-01-01T00:00:00Z. A float epoch "
    "is converted with datetime.fromtimestamp(epoch, tz=UTC) -- nearest microsecond, ties to even -- which is the "
    "same conversion the record serializer performs, so the canonical integer is exactly the microsecond written to "
    "disk and read back. Instants are compared as integers; no epsilon is added, so the next representable future "
    "instant (+1 microsecond) is in the future and is refused. Source timestamps are preserved verbatim, separately.")

# instants outside this band cannot be represented as a microsecond datetime on any supported platform
MIN_MICROS = (datetime(1, 1, 1, tzinfo=timezone.utc) - EPOCH_DT) // ONE_MICROSECOND
MAX_MICROS = (datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc) - EPOCH_DT) // ONE_MICROSECOND


def canonical_micros(value, *, field: str = "instant") -> int:
    """The canonical instant of a float epoch or an ISO-8601 UTC string: exact integer microseconds.

    Refuses booleans, non-finite floats, naive or unparseable strings, and instants outside the representable band."""
    if isinstance(value, str):
        epoch = parse_utc(value, field=field)
    elif is_real(value):
        epoch = check_reading(value, field=field)
    else:
        raise ClockRefused("%s: not an instant (need a finite epoch or an ISO-8601 UTC string), got %r" % (field, value))
    try:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as e:
        raise ClockRefused("%s: instant not representable: %r (%s)" % (field, value, e)) from e
    micros = (dt - EPOCH_DT) // ONE_MICROSECOND
    if not (MIN_MICROS <= micros <= MAX_MICROS):
        raise ClockRefused("%s: instant outside the representable band: %r" % (field, value))
    return int(micros)


def from_micros(micros: int) -> float:
    """Canonical integer -> epoch float. Exact for every instant this system records."""
    if not isinstance(micros, int) or isinstance(micros, bool):
        raise ClockRefused("from_micros: canonical instants are exact ints, got %r" % (micros,))
    return micros / float(MICROS_PER_SECOND)


def canonical_epoch(value, *, field: str = "instant") -> float:
    """The float epoch of the canonical instant: quantized to the microsecond that will be persisted."""
    return from_micros(canonical_micros(value, field=field))


def canonical_utc(value, *, field: str = "instant") -> str:
    return to_utc_string(canonical_epoch(value, field=field))


def compare(a, b, *, field: str = "instant") -> int:
    """-1, 0 or +1 on the CANONICAL integers. No epsilon."""
    x, y = canonical_micros(a, field=field + ".a"), canonical_micros(b, field=field + ".b")
    return (x > y) - (x < y)


def is_after(a, b, *, field: str = "instant") -> bool:
    """True iff `a` is a LATER canonical instant than `b`. The next representable instant (+1us) IS after."""
    return compare(a, b, field=field) > 0


def is_before(a, b, *, field: str = "instant") -> bool:
    return compare(a, b, field=field) < 0


def same_instant(a, b, *, field: str = "instant") -> bool:
    return compare(a, b, field=field) == 0


def stamp(value, *, source=None, source_field: str | None = None, field: str = "instant") -> dict:
    """A recorded instant: the canonical value AND the source's own timestamp, preserved separately and unaltered."""
    micros = canonical_micros(value, field=field)
    out = {"canonical_us": micros, "epoch": from_micros(micros), "utc": to_utc_string(from_micros(micros)),
           "unit": CANONICAL_UNIT, "rule": CONVERSION_RULE}
    if source is not None or source_field is not None:
        out["source"] = {"value": source, "field": source_field,
                         "note": "as supplied by the source; never rewritten by canonicalization"}
    return out


def round_trips(value) -> bool:
    """True iff canonicalizing, serializing and re-parsing returns the SAME canonical instant. Used by tests to prove
    the round trip is the identity at the declared precision."""
    a = canonical_micros(value)
    return canonical_micros(to_utc_string(from_micros(a))) == a
