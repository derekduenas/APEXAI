"""PREMARKET_TIME_V1 — six distinct instants, because one timestamp was doing three jobs.

WHAT WAS WRONG, PRECISELY. `as_of_time` was set to `now()` at seal time and then used as three different things:
the packet's downstream availability, the packet's data cutoff, and the freshness of the underlying sources.

The review's correction is the one that matters: seal-time availability is **conservative for causality** -- the
sealed packet genuinely cannot be known before it is sealed, so `packet_known_from = packet_sealed_at` is right
and is NOT the defect. I previously called it unsafe, which was wrong.

The defect is that the SAME field also implied source freshness. A source observed at 13:20 and a packet sealed
at 13:25 are two different facts, and a reader asking "how stale was the data behind this?" got the seal time.

So the instants are separated and each is recorded for what it is."""
from __future__ import annotations

SCHEMA = "PREMARKET_TIME_V1"

SOURCE_FIELDS = ("source_event_time", "source_publication_time", "source_request_time",
                 "source_receipt_time", "source_known_from")
PACKET_FIELDS = ("packet_collection_started_at", "packet_data_cutoff", "ai_request_time", "ai_response_time",
                 "packet_created_at", "packet_sealed_at", "packet_known_from")

UNAVAILABLE = "UNAVAILABLE"

LAWS = (
    "packet_known_from >= packet_sealed_at -- the sealed packet cannot be known before it is sealed",
    "packet_data_cutoff is DERIVED from the accepted source observations, never from the seal clock",
    "sealing never rewrites a source timestamp",
    "per-source freshness = packet_data_cutoff - source_known_from, and is UNAVAILABLE when either is",
    "an unavailable timestamp stays UNAVAILABLE and is never defaulted to a clock reading",
    "a source whose known_from is AFTER the cutoff is REFUSED, not clipped",
    "a later revision is additive and never rewrites a sealed packet",
)


class PremarketTimeRefused(ValueError):
    """A timing claim that cannot be made honestly. Named, never silent."""


def source_observation(*, event_time=None, publication_time=None, request_time=None, receipt_time=None,
                       known_from=None) -> dict:
    """One source's five instants. `known_from` defaults to the RECEIPT instant -- when APEX could first have
    known it -- and never to the event time, which is when the world produced it."""
    kf = known_from if known_from is not None else receipt_time
    return {"source_event_time": event_time if event_time is not None else UNAVAILABLE,
            "source_publication_time": publication_time if publication_time is not None else UNAVAILABLE,
            "source_request_time": request_time if request_time is not None else UNAVAILABLE,
            "source_receipt_time": receipt_time if receipt_time is not None else UNAVAILABLE,
            "source_known_from": kf if kf is not None else UNAVAILABLE}


def data_cutoff(observations) -> float | str:
    """The packet's cutoff is the LATEST instant any accepted observation became knowable. Derived, not clocked."""
    kfs = [o["source_known_from"] for o in (observations or [])
           if isinstance(o.get("source_known_from"), (int, float))]
    return max(kfs) if kfs else UNAVAILABLE


def freshness_s(observation: dict, cutoff) -> float | str:
    kf = observation.get("source_known_from")
    if not isinstance(kf, (int, float)) or not isinstance(cutoff, (int, float)):
        return UNAVAILABLE
    return round(cutoff - kf, 6)


def packet_times(*, collection_started_at, observations, ai_request_time=None, ai_response_time=None,
                 created_at, sealed_at, known_from=None) -> dict:
    """Assemble and CHECK the packet's instants."""
    cutoff = data_cutoff(observations)
    kf = known_from if known_from is not None else sealed_at
    if isinstance(kf, (int, float)) and isinstance(sealed_at, (int, float)) and kf < sealed_at:
        raise PremarketTimeRefused(
            "PACKET_KNOWN_FROM_BEFORE_SEAL: %r < %r; a sealed packet cannot be knowable before it is sealed"
            % (kf, sealed_at))
    if isinstance(cutoff, (int, float)) and isinstance(sealed_at, (int, float)) and cutoff > sealed_at:
        raise PremarketTimeRefused(
            "DATA_CUTOFF_AFTER_SEAL: an observation became knowable at %r, after the seal at %r" % (cutoff, sealed_at))
    return {"schema": SCHEMA,
            "packet_collection_started_at": collection_started_at,
            "packet_data_cutoff": cutoff,
            "ai_request_time": ai_request_time if ai_request_time is not None else UNAVAILABLE,
            "ai_response_time": ai_response_time if ai_response_time is not None else UNAVAILABLE,
            "packet_created_at": created_at,
            "packet_sealed_at": sealed_at,
            "packet_known_from": kf,
            "laws": list(LAWS),
            "legacy_note": ("packets sealed before PREMARKET_TIME_V1 carry a single `as_of_time` that was the "
                            "SEAL instant. Their downstream availability is reconstructible from it; their "
                            "SOURCE FRESHNESS is NOT, and must be reported UNAVAILABLE rather than inferred.")}


def refuse_future_source(observation: dict, cutoff) -> None:
    kf = observation.get("source_known_from")
    if isinstance(kf, (int, float)) and isinstance(cutoff, (int, float)) and kf > cutoff:
        raise PremarketTimeRefused("SOURCE_KNOWN_AFTER_CUTOFF: %r > %r; a later arrival is not earlier evidence"
                                   % (kf, cutoff))
