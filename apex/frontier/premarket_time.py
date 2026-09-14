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

# R5: WIRED INTO PRODUCTION. Until R5 this module was imported by tests and by nothing else -- R1 built the time
# model, R2's evidence file PRINTED a PREMARKET_TIME_V1 block that the HARNESS computed, and the producer went on
# writing a single `as_of_time` that meant three different things. The staged CLI, the durable stage records, the
# Captain input and the sealed packet now all carry this model, and the packet that carries it is a new schema
# version rather than a quiet redefinition of the old one.

SOURCE_FIELDS = ("source_event_time", "source_publication_time", "source_request_time",
                 "source_receipt_time", "source_known_from",
                 # R5 additions: a timestamp without its basis and its zone is a number, not a fact.
                 "availability_basis", "source_timezone", "normalization")
PACKET_FIELDS = ("packet_collection_started_at", "packet_data_cutoff", "ai_request_time", "ai_response_time",
                 "packet_created_at", "packet_sealed_at", "packet_known_from",
                 "latest_accepted_known_from", "per_source_known_from", "per_source_freshness_s")

STAGE_FIELDS = ("market_date", "stage", "target_instant", "window_opens", "window_closes", "process_started_at",
                "capture_started_at", "capture_finished_at", "normalization_finished_at",
                "absorption_finished_at", "disposition", "lateness_s", "code_identity", "config_identity")

UNAVAILABLE = "UNAVAILABLE"

# How `source_known_from` was decided. A reader that cannot tell an explicit provider availability stamp from
# "this is when the bytes reached us" cannot reason about latency at all.
BASIS_RECEIPT = "RECEIPT_INSTANT"              # we knew it when the response arrived
BASIS_PUBLICATION = "PROVIDER_PUBLICATION"     # the provider stated when it published
BASIS_EXPLICIT = "PROVIDER_AVAILABILITY"       # the provider stated when it became available to us
BASIS_UNAVAILABLE = "UNAVAILABLE"

NORM_ACCEPTED = "ACCEPTED"
NORM_REFUSED_FUTURE = "REFUSED_AS_FUTURE"
NORM_UNAVAILABLE = "MARKED_UNAVAILABLE"
NORM_EXCLUDED_STALE = "EXCLUDED_AS_STALE"

UNAVAILABLE_NO_CONTENT = "UNAVAILABLE_NO_CONTENT_FROM_THIS_SOURCE"

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
                       known_from=None, source_id=None, source_kind=None, source_timezone=None,
                       normalization=None, availability_basis=None, carries_content=True) -> dict:
    """One source's instants, plus what decided them. `known_from` defaults to the RECEIPT instant -- when APEX
    could first have known it -- and never to the event time, which is when the world produced it."""
    kf, basis = known_from, availability_basis
    if kf is None:
        kf, basis = receipt_time, (basis or BASIS_RECEIPT)
    elif basis is None:
        basis = BASIS_EXPLICIT
    return {"source_id": source_id if source_id is not None else UNAVAILABLE,
            "source_kind": source_kind if source_kind is not None else UNAVAILABLE,
            "source_event_time": event_time if event_time is not None else UNAVAILABLE,
            "source_publication_time": publication_time if publication_time is not None else UNAVAILABLE,
            "source_request_time": request_time if request_time is not None else UNAVAILABLE,
            "source_receipt_time": receipt_time if receipt_time is not None else UNAVAILABLE,
            "source_known_from": kf if kf is not None else UNAVAILABLE,
            "availability_basis": basis if kf is not None else BASIS_UNAVAILABLE,
            "source_timezone": source_timezone if source_timezone is not None else UNAVAILABLE,
            "normalization": normalization if normalization is not None else NORM_ACCEPTED,
            # CONTENT vs PROBE. "We asked SEC EDGAR at 09:20 and nothing matched" is real information and is
            # recorded, but it is not a piece of NEWS from 09:20. Mixing the two makes every source look
            # perfectly fresh forever, because the probe receipt always equals the cutoff -- a freshness number
            # that can never indicate staleness is not a freshness number. So they are separated here and
            # per-source freshness is computed over CONTENT only.
            "carries_content": bool(carries_content)}


def accepted(observations) -> list:
    return [o for o in (observations or []) if o.get("normalization") == NORM_ACCEPTED]


def per_source_known_from(observations, *, content_only=True) -> dict:
    """The LATEST instant each source's CONTENT became knowable. Per source, because one global freshness number
    is how a stale feed hides behind a fresh one."""
    out = {}
    for o in accepted(observations):
        if content_only and not o.get("carries_content", True):
            continue
        kf, sid = o.get("source_known_from"), o.get("source_kind") or o.get("source_id")
        if isinstance(kf, (int, float)):
            out[sid] = max(out.get(sid, kf), kf)
    return out


def per_source_last_probe(observations) -> dict:
    """When each source was last ASKED, content or not. `known_from` says how old the news is; this says whether
    anybody is still talking to the provider. A source that is fresh on one and ancient on the other is a source
    that is up and quiet; ancient on both is a source that is down."""
    return per_source_known_from(observations, content_only=False)


def per_source_freshness(observations, cutoff) -> dict:
    """How old each source's newest CONTENT is at the cutoff. A source that was probed but produced nothing
    reports UNAVAILABLE_NO_CONTENT_FROM_THIS_SOURCE -- never 0.0, which would read as perfectly fresh."""
    kf = per_source_known_from(observations)
    seen = per_source_last_probe(observations)
    return {k: (round(cutoff - kf[k], 6) if k in kf and isinstance(cutoff, (int, float))
                else UNAVAILABLE_NO_CONTENT) for k in seen}


def data_cutoff(observations, *, content_only=False) -> float | str:
    """The packet's cutoff is the LATEST instant any ACCEPTED observation became knowable. Derived, not clocked.

    A refused observation cannot move the cutoff -- otherwise refusing a future arrival would still let it push
    the declared cutoff forward and make every other source look staler than it is."""
    kfs = [o["source_known_from"] for o in accepted(observations)
           if isinstance(o.get("source_known_from"), (int, float))
           and (o.get("carries_content", True) or not content_only)]
    return max(kfs) if kfs else UNAVAILABLE


def freshness_s(observation: dict, cutoff) -> float | str:
    kf = observation.get("source_known_from")
    if not isinstance(kf, (int, float)) or not isinstance(cutoff, (int, float)):
        return UNAVAILABLE
    return round(cutoff - kf, 6)


def packet_times(*, collection_started_at, observations, ai_request_time=None, ai_response_time=None,
                 created_at, sealed_at, known_from=None, declared_cutoff=None) -> dict:
    """Assemble and CHECK the packet's instants."""
    cutoff = declared_cutoff if declared_cutoff is not None else data_cutoff(observations)
    kf = known_from if known_from is not None else sealed_at
    if isinstance(kf, (int, float)) and isinstance(sealed_at, (int, float)) and kf < sealed_at:
        raise PremarketTimeRefused(
            "PACKET_KNOWN_FROM_BEFORE_SEAL: %r < %r; a sealed packet cannot be knowable before it is sealed"
            % (kf, sealed_at))
    if isinstance(cutoff, (int, float)) and isinstance(sealed_at, (int, float)) and cutoff > sealed_at:
        raise PremarketTimeRefused(
            "DATA_CUTOFF_AFTER_SEAL: an observation became knowable at %r, after the seal at %r" % (cutoff, sealed_at))
    # THE DECLARED CUTOFF and THE LATEST ACCEPTED ARRIVAL are two different facts. The cutoff is the instant the
    # packet stopped accepting input; the latest accepted arrival is the newest thing that actually got in. They
    # are equal only by coincidence, and a reader that conflates them cannot tell a quiet feed from a late one.
    latest = data_cutoff(observations, content_only=True)
    probe_latest = data_cutoff(observations)
    if isinstance(cutoff, (int, float)) and isinstance(probe_latest, (int, float)) and probe_latest > cutoff:
        raise PremarketTimeRefused(
            "ACCEPTED_INPUT_AFTER_DECLARED_CUTOFF: an accepted observation became knowable at %r, after the "
            "declared cutoff %r" % (probe_latest, cutoff))
    if isinstance(cutoff, (int, float)) and isinstance(latest, (int, float)) and latest > cutoff:
        raise PremarketTimeRefused(
            "ACCEPTED_INPUT_AFTER_DECLARED_CUTOFF: an accepted observation became knowable at %r, after the "
            "declared cutoff %r" % (latest, cutoff))
    for o in accepted(observations or []):
        refuse_future_source(o, cutoff)
    return {"schema": SCHEMA,
            "packet_collection_started_at": collection_started_at,
            "packet_data_cutoff": cutoff,
            "latest_accepted_known_from": latest,
            "per_source_known_from": per_source_known_from(observations),
            "per_source_last_probe": per_source_last_probe(observations),
            "per_source_freshness_s": per_source_freshness(observations, cutoff),
            "ai_request_time": ai_request_time if ai_request_time is not None else UNAVAILABLE,
            "ai_response_time": ai_response_time if ai_response_time is not None else UNAVAILABLE,
            "packet_created_at": created_at,
            "packet_sealed_at": sealed_at,
            "packet_known_from": kf,
            "laws": list(LAWS),
            "legacy_note": ("packets sealed before PREMARKET_TIME_V1 carry a single `as_of_time` that was the "
                            "SEAL instant. Their downstream availability is reconstructible from it; their "
                            "SOURCE FRESHNESS is NOT, and must be reported UNAVAILABLE rather than inferred.")}


def collection_times(*, collection_started_at, observations, declared_cutoff, created_at) -> dict:
    """The time block as it exists BEFORE the seal. `seal()` completes it with the seal instant and re-checks the
    laws; nothing here invents a seal time it does not have."""
    latest = data_cutoff(observations, content_only=True)
    return {"schema": SCHEMA,
            "packet_collection_started_at": collection_started_at,
            "packet_data_cutoff": declared_cutoff,
            "latest_accepted_known_from": latest,
            "per_source_known_from": per_source_known_from(observations),
            "per_source_last_probe": per_source_last_probe(observations),
            "per_source_freshness_s": per_source_freshness(observations, declared_cutoff),
            "ai_request_time": UNAVAILABLE, "ai_response_time": UNAVAILABLE,
            "packet_created_at": created_at,
            "packet_sealed_at": UNAVAILABLE, "packet_known_from": UNAVAILABLE,
            "laws": list(LAWS)}


def provider_declared_future(observation: dict, as_of) -> bool:
    """Is this a PROVIDER-DECLARED availability later than the instant the stage is reasoning about?

    The distinction matters and is the whole point. A receipt three seconds after the stage started is latency.
    A provider stamping 'this became available at 09:40' while we reason as of 08:15 is a claim about the future,
    and it is refused -- the same rule catalyst_state already applies to EDGAR's known_from_utc, now applied at
    every source boundary instead of one."""
    if observation.get("availability_basis") not in (BASIS_EXPLICIT, BASIS_PUBLICATION):
        return False
    kf = observation.get("source_known_from")
    return isinstance(kf, (int, float)) and isinstance(as_of, (int, float)) and kf > as_of


def refuse_future_source(observation: dict, cutoff) -> None:
    kf = observation.get("source_known_from")
    if isinstance(kf, (int, float)) and isinstance(cutoff, (int, float)) and kf > cutoff:
        raise PremarketTimeRefused("SOURCE_KNOWN_AFTER_CUTOFF: %r > %r; a later arrival is not earlier evidence"
                                   % (kf, cutoff))
