"""MARKET_TWIN_STATE_V0 — the immutable causal packet.

One packet answers exactly one question: WHAT DID THIS SUBJECT
ACTUALLY LOOK LIKE AT THIS MOMENT, AND HOW MUCH OF IT DO WE ACTUALLY
KNOW? It contains measurements and provenance. It contains no opinion,
no forecast and no authority.

THE FIELD IS THE UNIT, NOT THE NUMBER. Every measurement carries
value + quality + source + as_of + known_from + age, because the World
Model cannot calibrate on numbers whose trustworthiness and timing it
cannot see.

A PACKET IS NOT SYNCHRONOUS, AND MUST NOT PRETEND TO BE. Ingredients
arrive at materially different moments:

    NBBO              10:17:03.220
    latest trade      10:17:03.841
    Catalyst event    10:16:49
    options snapshot  10:16:57
    Tier-2 snapshot   10:17:04.714

That is fine. Hiding it behind one timestamp is not. A "10:17 state"
silently composed of facts from spread-out moments is a forgery with
good intentions, so every field keeps its own clock and the packet
reports its capture span and its oldest critical ingredient.

AS_OF vs KNOWN_FROM. `as_of` is when the fact was TRUE. `known_from`
is when APEX could first have KNOWN it. For a quote they coincide. For
an event they do not: an 8-K filed at 02:55 and published at 03:10 was
true at 02:55 and knowable at 03:10, and only the later one may gate a
decision.

MISSING IS NEVER ZERO. Seven states that a single NaN would flatten:

  VALID                 observed, fresh, sufficient
  STALE                 observed, but older than this feature tolerates
  UNKNOWN               we did not or could not look
  NOT_AVAILABLE         the source does not carry it at all
  NOT_ESTIMABLE         present but insufficient to compute honestly
  PROVIDER_ERROR        the source was asked and failed
  SESSION_INAPPLICABLE  meaningless in this session (premarket VWAP)

decision_power: NONE_STATE.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone

SCHEMA_VERSION = "MARKET_TWIN_STATE_V0"

VALID = "VALID"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
NOT_AVAILABLE = "NOT_AVAILABLE"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
PROVIDER_ERROR = "PROVIDER_ERROR"
SESSION_INAPPLICABLE = "SESSION_INAPPLICABLE"

QUALITIES = (VALID, STALE, UNKNOWN, NOT_AVAILABLE, NOT_ESTIMABLE,
             PROVIDER_ERROR, SESSION_INAPPLICABLE)
TRUSTWORTHY = (VALID,)

_ADOPT = {"NOT_ESTIMABLE": NOT_ESTIMABLE, "UNKNOWN": UNKNOWN,
          "NOT_AVAILABLE": NOT_AVAILABLE, "STALE": STALE,
          "PROVIDER_ERROR": PROVIDER_ERROR}

# Fields whose age materially changes what the state MEANS. The packet
# reports the worst of these explicitly, so a reader never has to scan
# every field to discover that its "current" price is four minutes old.
CRITICAL = ("mid", "spread_bps", "last_trade")

# Fields that are DEFINITIONALLY historical. A prior close is supposed
# to be a day old; counting it as capture latency would make both the
# span and the critical-age alarm meaningless. Their individual ages
# are still reported per field -- they are excluded from the CAPTURE
# metrics, never hidden.
ANCHOR = ("prior_close", "session_open", "premarket_first",
          "premarket_high", "premarket_low", "premarket_range_bps",
          "premarket_return_bps", "premarket_travel_bps",
          "overnight_first_gap_bps", "premarket_observations")


class TwinViolation(RuntimeError):
    """Raised when a packet would be sealed in an untruthful shape."""


def _utc(ts) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return (ts if ts.tzinfo else ts.replace(
            tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
    return str(ts)


def _parse(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    import re
    m = re.search(r"([+-]\d{2}:?\d{2})$", s)
    off, base = (m.group(1), s[:m.start()]) if m else ("+00:00", s)
    if "." in base:
        head, _, frac = base.partition(".")
        base = f"{head}.{frac[:6].ljust(6, '0')}"
    return datetime.fromisoformat(base + off)


@dataclass(frozen=True)
class Field:
    """One measurement, its trustworthiness, and its own clock."""
    value: object
    quality: str
    source: str = "UNSPECIFIED"
    as_of: str | None = None
    known_from: str | None = None
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
        if self.as_of and self.known_from and \
                _parse(self.known_from) < _parse(self.as_of):
            raise TwinViolation(
                f"known_from {self.known_from} precedes as_of "
                f"{self.as_of}: a fact cannot be knowable before it "
                f"is true")

    @property
    def usable(self) -> bool:
        return self.quality in TRUSTWORTHY

    def gate_time(self) -> str | None:
        """The time that may gate a decision: when APEX could KNOW."""
        return self.known_from or self.as_of

    def age_ms(self, at) -> float | None:
        g = self.gate_time()
        if not g:
            return None
        return round((_parse(at) - _parse(g)).total_seconds() * 1000, 1)

    def as_record(self, *, at=None) -> dict:
        d = {"v": self.value, "q": self.quality, "src": self.source}
        if self.as_of:
            d["as_of"] = self.as_of
        if self.known_from and self.known_from != self.as_of:
            d["known_from"] = self.known_from
        if at is not None:
            a = self.age_ms(at)
            if a is not None:
                d["age_ms"] = a
        if self.note:
            d["note"] = self.note
        return d


def ok(value, *, source, as_of=None, known_from=None,
       note=None) -> Field:
    """A measurement we actually made."""
    return Field(value, VALID, source, _utc(as_of), _utc(known_from),
                 note)


def absent(quality, *, source="UNSPECIFIED", note=None,
           as_of=None) -> Field:
    """An honest statement that we do not have the measurement."""
    if quality in TRUSTWORTHY:
        raise TwinViolation("absent() requires a non-VALID quality")
    return Field(None, quality, source, _utc(as_of), None, note)


def adopt(value, *, source, as_of=None, known_from=None,
          note=None) -> Field:
    """Wrap a value from an engine that already speaks a sentinel
    vocabulary, honouring its verdict instead of overriding it."""
    if isinstance(value, str) and value in _ADOPT:
        return absent(_ADOPT[value], source=source, note=note)
    if value is None:
        return absent(UNKNOWN, source=source, note=note)
    return ok(value, source=source, as_of=as_of, known_from=known_from,
              note=note)


@dataclass
class TwinState:
    """One subject, one moment. Sealed once, never edited."""
    subject: str
    scheduled_time: str
    capture_start: str
    state_complete_time: str
    market_session: str
    universe_version: str
    tier: str
    features: dict = dc_field(default_factory=dict)
    sources: dict = dc_field(default_factory=dict)
    notes: list = dc_field(default_factory=list)
    enrichment: dict = dc_field(default_factory=dict)
    evidence_class: str = "LIVE_PROSPECTIVE"
    capture_end: str | None = None

    def known_from(self) -> str:
        """The LATEST moment any ingredient became knowable. A state
        is not knowable before its last ingredient was."""
        stamps = [f.gate_time() for f in self.features.values()
                  if isinstance(f, Field) and f.gate_time()]
        stamps.append(self.state_complete_time)
        return max(stamps)

    def quality_census(self) -> dict:
        c = {}
        for f in self.features.values():
            if isinstance(f, Field):
                c[f.quality] = c.get(f.quality, 0) + 1
        return dict(sorted(c.items()))

    def missingness(self) -> float:
        total = len(self.features)
        if not total:
            return 1.0
        usable = sum(1 for f in self.features.values()
                     if isinstance(f, Field) and f.usable)
        return round(1.0 - usable / total, 4)

    def _ages(self):
        end = self.state_complete_time
        return {k: f.age_ms(end) for k, f in self.features.items()
                if isinstance(f, Field) and f.usable
                and f.age_ms(end) is not None}

    def state_id(self) -> str:
        """IDENTITY, not uniqueness of execution: the same economic
        observation recomputed after a restart or duplicate timer MUST
        produce the same id."""
        raw = "|".join((SCHEMA_VERSION, self.evidence_class, self.tier,
                        self.subject, self.scheduled_time,
                        self.universe_version))
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def seal(self) -> dict:
        if self.market_session is None:
            raise TwinViolation("market_session is required")
        end = self.state_complete_time
        ages = self._ages()
        crit = {k: v for k, v in ages.items() if k in CRITICAL}
        span_start = min([_parse(f.gate_time())
                          for k, f in self.features.items()
                          if isinstance(f, Field) and f.usable
                          and f.gate_time() and k not in ANCHOR]
                         or [_parse(end)])
        body = {
            "kind": "market_twin_state",
            "schema_version": SCHEMA_VERSION,
            "state_id": self.state_id(),
            "evidence_class": self.evidence_class,
            "tier": self.tier,
            "subject": self.subject,
            "scheduled_time": self.scheduled_time,
            "capture_start": self.capture_start,
            "capture_end": self.capture_end or end,
            "state_complete_time": end,
            "known_from": self.known_from(),
            "market_session": self.market_session,
            "universe_version": self.universe_version,
            "timing": {
                "capture_latency_ms": round(
                    (_parse(end) - _parse(self.capture_start)
                     ).total_seconds() * 1000, 1),
                # how far apart the OLDEST and NEWEST usable
                # ingredients actually are -- the honest width of this
                # "moment"
                "capture_span_ms": round(
                    (_parse(end) - span_start).total_seconds() * 1000,
                    1),
                "max_field_age_ms": max(ages.values()) if ages else None,
                "max_capture_age_ms": (
                    max([v for k, v in ages.items() if k not in ANCHOR],
                        default=None)),
                "anchor_fields_excluded_from_span": [
                    k for k in ages if k in ANCHOR],
                "max_critical_field_age_ms": (max(crit.values())
                                              if crit else None),
                "critical_fields": list(CRITICAL),
                "law": "a packet is NOT synchronous; each field keeps "
                       "its own clock and this block states how wide "
                       "the moment really is. Anchors (prior close, "
                       "premarket path) are definitionally historical "
                       "and are excluded from the CAPTURE metrics "
                       "while keeping their own per-field ages"},
            "sources": self.sources,
            "enrichment": self.enrichment or {
                "enriched": False,
                "reason": "NOT_ENRICHED",
                "why": "no enrichment was requested for this subject "
                       "in this cycle"},
            "features": {k: (v.as_record(at=end)
                             if isinstance(v, Field) else v)
                         for k, v in sorted(self.features.items())},
            "data_quality": {
                "census": self.quality_census(),
                "missingness": self.missingness(),
                "vocabulary": list(QUALITIES),
                "law": "only VALID may be consumed as a measurement; "
                       "every other state is an explicit statement "
                       "about what is not known"},
            "notes": self.notes,
            "law": "measurements and provenance only -- no forecast, "
                   "no selection, no authority",
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
    kf = packet.get("known_from")
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
        gate = f.get("known_from") or f.get("as_of")
        if gate and kf and _parse(gate) > _parse(kf):
            problems.append(
                f"{name}: ingredient knowable at {gate} is LATER than "
                f"the packet's known_from {kf}")
        if f.get("as_of") and f.get("known_from") and \
                _parse(f["known_from"]) < _parse(f["as_of"]):
            problems.append(
                f"{name}: known_from precedes as_of -- a fact cannot "
                f"be knowable before it is true")
    return problems
