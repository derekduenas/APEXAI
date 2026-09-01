"""MARKET_TWIN_STATE_V0 — the immutable causal packet.

One packet answers exactly one question: WHAT DID THIS SUBJECT
ACTUALLY LOOK LIKE AT THIS MOMENT, AND HOW MUCH OF IT DO WE ACTUALLY
KNOW? It contains measurements and provenance. It contains no opinion,
no forecast and no authority.

THE FIELD IS THE UNIT, NOT THE NUMBER. Every measurement is a Field
carrying value + quality + source + as_of, because the World Model
cannot calibrate on numbers whose trustworthiness it cannot see. A
bare float that might be missing, stale, or fabricated is worse than
no field at all: it is a lie with a decimal point.

MISSING IS NEVER ZERO. The quality vocabulary distinguishes seven
states that a single NaN would flatten into one:

  VALID                 observed, fresh, sufficient
  STALE                 observed, but older than this feature tolerates
  UNKNOWN               we did not or could not look
  NOT_AVAILABLE         the source does not carry it at all
  NOT_ESTIMABLE         present but insufficient to compute honestly
  PROVIDER_ERROR        the source was asked and failed
  SESSION_INAPPLICABLE  meaningless in this session (premarket VWAP)

KNOWN_FROM IS DERIVED, NOT DECLARED. A packet's known_from is the
LATEST contributing observation time, because a state is not knowable
before its last ingredient existed. A 10:01 packet completed at
10:01:05 was known at 10:01:05, and saying otherwise is the same class
of error as an open-vs-entry anchor mismatch.

decision_power: NONE_STATE — this module measures and records. It
never selects, sizes, forecasts or approves.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone

SCHEMA_VERSION = "MARKET_TWIN_STATE_V0"

# ---------------------------------------------------- quality vocabulary
VALID = "VALID"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
PROVIDER_ERROR = "PROVIDER_ERROR"
SESSION_INAPPLICABLE = "SESSION_INAPPLICABLE"

QUALITIES = (VALID, STALE, UNKNOWN, NOT_AVAILABLE, NOT_ESTIMABLE,
             PROVIDER_ERROR, SESSION_INAPPLICABLE)
# only VALID may be consumed as a measurement; everything else is an
# explicit statement about what we do not know
TRUSTWORTHY = (VALID,)

# the vocabulary a sub-engine may already speak, mapped in rather than
# reinvented (apex/organism/microstructure.py, options_surface.py and
# feature_sufficiency.py all emit NOT_ESTIMABLE already)
_ADOPT = {"NOT_ESTIMABLE": NOT_ESTIMABLE, "UNKNOWN": UNKNOWN,
          "NOT_AVAILABLE": NOT_AVAILABLE, "STALE": STALE,
          "PROVIDER_ERROR": PROVIDER_ERROR}


class TwinViolation(RuntimeError):
    """Raised when a packet would be sealed in an untruthful shape."""


def _utc(ts) -> str:
    if isinstance(ts, datetime):
        return (ts if ts.tzinfo else ts.replace(
            tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    return str(ts)


@dataclass(frozen=True)
class Field:
    """One measurement and everything needed to distrust it."""
    value: object
    quality: str
    source: str = "UNSPECIFIED"
    as_of: str | None = None
    note: str | None = None

    def __post_init__(self):
        if self.quality not in QUALITIES:
            raise TwinViolation(
                f"quality {self.quality!r} is not in the vocabulary "
                f"{QUALITIES}")
        if self.quality in TRUSTWORTHY and self.value is None:
            raise TwinViolation(
                f"a {self.quality} field may not carry value None -- "
                f"absence has its own quality states")
        if self.quality not in TRUSTWORTHY and isinstance(
                self.value, (int, float)) and not isinstance(
                    self.value, bool):
            raise TwinViolation(
                f"a {self.quality} field carries the number "
                f"{self.value!r}: an untrustworthy field must not "
                f"present a consumable measurement")

    @property
    def usable(self) -> bool:
        return self.quality in TRUSTWORTHY

    def as_record(self) -> dict:
        d = {"v": self.value, "q": self.quality, "src": self.source}
        if self.as_of:
            d["as_of"] = self.as_of
        if self.note:
            d["note"] = self.note
        return d


def ok(value, *, source, as_of=None, note=None) -> Field:
    """A measurement we actually made."""
    return Field(value, VALID, source, _utc(as_of) if as_of else None,
                 note)


def absent(quality, *, source="UNSPECIFIED", note=None) -> Field:
    """An honest statement that we do not have the measurement."""
    if quality in TRUSTWORTHY:
        raise TwinViolation("absent() requires a non-VALID quality")
    return Field(None, quality, source, None, note)


def adopt(value, *, source, as_of=None, note=None) -> Field:
    """Wrap a value from an engine that already speaks a sentinel
    vocabulary, honouring its verdict instead of overriding it."""
    if isinstance(value, str) and value in _ADOPT:
        return absent(_ADOPT[value], source=source, note=note)
    if value is None:
        return absent(UNKNOWN, source=source, note=note)
    return ok(value, source=source, as_of=as_of, note=note)


# ------------------------------------------------------------- packet

@dataclass
class TwinState:
    """One subject, one moment. Sealed once, never edited."""
    subject: str
    scheduled_time: str
    capture_start: str
    state_complete_time: str
    market_session: str
    universe_version: str
    tier: str                       # TIER_1_DEEP | TIER_2_BROAD
    features: dict = dc_field(default_factory=dict)
    sources: dict = dc_field(default_factory=dict)
    notes: list = dc_field(default_factory=list)
    evidence_class: str = "LIVE_PROSPECTIVE"

    # ------------------------------------------------ derived truth
    def known_from(self) -> str:
        """The LATEST contributing observation time. A state is not
        knowable before its last ingredient existed."""
        stamps = [f.as_of for f in self.features.values()
                  if isinstance(f, Field) and f.as_of]
        stamps.append(self.state_complete_time)
        return max(stamps)

    def quality_census(self) -> dict:
        c = {q: 0 for q in QUALITIES}
        for f in self.features.values():
            if isinstance(f, Field):
                c[f.quality] += 1
        return {k: v for k, v in c.items() if v}

    def missingness(self) -> float:
        total = len(self.features)
        if not total:
            return 1.0
        usable = sum(1 for f in self.features.values()
                     if isinstance(f, Field) and f.usable)
        return round(1.0 - usable / total, 4)

    def freshness_seconds(self) -> float | str:
        """How old the OLDEST usable ingredient is at completion."""
        stamps = [f.as_of for f in self.features.values()
                  if isinstance(f, Field) and f.usable and f.as_of]
        if not stamps:
            return NOT_ESTIMABLE
        end = datetime.fromisoformat(self.state_complete_time)
        oldest = min(datetime.fromisoformat(s) for s in stamps)
        return round((end - oldest).total_seconds(), 3)

    def state_id(self) -> str:
        """IDENTITY, not uniqueness of execution. The same economic
        observation recomputed after a restart or a duplicate timer
        MUST produce the same id, so the store can recognise it as one
        observation rather than two."""
        raw = "|".join((SCHEMA_VERSION, self.evidence_class, self.tier,
                        self.subject, self.scheduled_time,
                        self.universe_version))
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------- sealing
    def seal(self) -> dict:
        if self.market_session is None:
            raise TwinViolation("market_session is required")
        body = {
            "kind": "market_twin_state",
            "schema_version": SCHEMA_VERSION,
            "state_id": self.state_id(),
            "evidence_class": self.evidence_class,
            "tier": self.tier,
            "subject": self.subject,
            "scheduled_time": self.scheduled_time,
            "capture_start": self.capture_start,
            "state_complete_time": self.state_complete_time,
            "known_from": self.known_from(),
            "capture_latency_s": round(
                (datetime.fromisoformat(self.state_complete_time)
                 - datetime.fromisoformat(self.capture_start)
                 ).total_seconds(), 3),
            "market_session": self.market_session,
            "universe_version": self.universe_version,
            "sources": self.sources,
            "features": {k: (v.as_record() if isinstance(v, Field)
                             else v)
                         for k, v in sorted(self.features.items())},
            "data_quality": {
                "census": self.quality_census(),
                "missingness": self.missingness(),
                "oldest_usable_ingredient_age_s":
                    self.freshness_seconds(),
                "vocabulary": list(QUALITIES),
                "law": "only VALID may be consumed as a measurement; "
                       "every other state is an explicit statement "
                       "about what is not known"},
            "notes": self.notes,
            "law": "measurements and provenance only -- this packet "
                   "carries no forecast, no selection and no "
                   "authority",
            "decision_power": "NONE_STATE"}
        body["packet_hash"] = hashlib.sha256(
            json.dumps(body, sort_keys=True,
                       default=str).encode()).hexdigest()
        return body


def verify_packet(packet: dict) -> list:
    """Recompute what a reader must not take on trust."""
    problems = []
    if packet.get("schema_version") != SCHEMA_VERSION:
        return [f"schema_version {packet.get('schema_version')!r}"]
    body = {k: v for k, v in packet.items() if k != "packet_hash"}
    if hashlib.sha256(json.dumps(body, sort_keys=True,
                                 default=str).encode()).hexdigest() \
            != packet.get("packet_hash"):
        problems.append("PACKET_HASH_MISMATCH: the packet was altered "
                        "after sealing")
    for name, f in (packet.get("features") or {}).items():
        if not isinstance(f, dict):
            continue
        if f.get("q") not in QUALITIES:
            problems.append(f"{name}: quality {f.get('q')!r} is not "
                            f"in the vocabulary")
        if f.get("q") not in TRUSTWORTHY and isinstance(
                f.get("v"), (int, float)) and not isinstance(
                    f.get("v"), bool):
            problems.append(
                f"{name}: quality {f.get('q')} but carries the number "
                f"{f.get('v')!r} -- missing must never look like a "
                f"measurement")
    kf = packet.get("known_from")
    for name, f in (packet.get("features") or {}).items():
        if isinstance(f, dict) and f.get("as_of") and kf \
                and f["as_of"] > kf:
            problems.append(
                f"{name}: ingredient as_of {f['as_of']} is LATER than "
                f"the packet's known_from {kf}")
    return problems
