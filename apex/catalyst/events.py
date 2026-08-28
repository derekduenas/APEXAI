"""CATALYST EVENTS — provenance, dedup, and the refusal to know things.

One event generates a hundred headlines. Creating a hundred catalysts
would let a single Fed sentence look like a hundred independent
observations, and every downstream count -- including anything
EdgeForge eventually measures -- would be inflated by the news cycle
rather than by the world.

So the unit of record is the EVENT, and headlines attach to it as
SOURCE OBSERVATIONS. New information about a known event produces an
EVENT_UPDATE, never a second event.

FOUR TIMES, NEVER CONFLATED:

    event_time      when the thing happened in the world
    published_time  when a source published it
    first_seen      when APEX first observed any source for it
    known_from      the earliest instant APEX could have acted on it
                    -- which is first_seen, NOT event_time

That distinction is the whole causal firewall. A Fed decision at 14:00
that APEX did not see until 14:03 has known_from 14:03, and any
research joining it to a 14:01 market state is reading the future.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

SOURCE_AUTHORITY = ("PRIMARY_OFFICIAL", "COMPANY_DIRECT", "WIRE",
                    "FINANCIAL_PRESS", "AGGREGATOR", "UNVERIFIED")

# Only these may carry a fact on their own. Everything below WIRE is a
# discovery lead: useful for finding out that something happened, never
# sufficient to assert what happened.
FACT_BEARING = ("PRIMARY_OFFICIAL", "COMPANY_DIRECT", "WIRE")

EVENT_TYPES = (
    "MACRO_RELEASE", "CENTRAL_BANK", "EARNINGS", "GUIDANCE",
    "CORPORATE_ACTION", "MA", "REGULATORY", "LEGAL", "ANALYST_ACTION",
    "PRODUCT", "MANAGEMENT", "GEOPOLITICAL", "SUPPLY_CHAIN",
    "EXCHANGE_NOTICE", "OTHER", "UNKNOWN")

VERIFICATION = ("VERIFIED", "UNVERIFIED", "CONFLICTED")

IMPORTANCE = ("CRITICAL", "HIGH", "MODERATE", "LOW", "UNKNOWN")


class CatalystViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceObservation:
    """One publication of one event. Never a catalyst by itself."""
    source: str
    source_authority: str
    source_ref: str                  # url or stable document id
    headline: str
    published_time: str
    retrieval_time: str
    body_excerpt: str = ""

    def __post_init__(self):
        if self.source_authority not in SOURCE_AUTHORITY:
            raise CatalystViolation(
                f"unknown source_authority {self.source_authority!r}")
        if not self.source_ref:
            raise CatalystViolation(
                f"{self.source!r} supplied no source_ref: 'news says' "
                f"is not provenance")

    def as_record(self) -> dict:
        return {"kind": "source_observation", **asdict(self)}


def _norm(text: str) -> str:
    """Normalize a headline for dedup: lowercase, strip punctuation and
    the wire furniture that makes one event look like five."""
    t = text.lower()
    t = re.sub(r"\b(breaking|update \d+|exclusive|live|watch)\b", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


def dedup_key(*, event_type: str, subjects: tuple, headline: str,
              day: str) -> str:
    """Same type, same subjects, same day, similar words = same event.

    Deliberately coarse. Over-merging two related headlines costs one
    observation; under-merging inflates every count downstream."""
    toks = sorted(set(_norm(headline).split()))[:8]
    key = "|".join([event_type, ",".join(sorted(subjects)), day,
                    " ".join(toks)])
    return "EV_" + hashlib.sha256(key.encode()).hexdigest()[:16]


@dataclass
class CatalystEvent:
    """One thing that happened, with everything APEX knows about it."""
    event_id: str
    event_type: str
    event_time: str
    first_seen: str
    known_from: str
    scheduled: bool
    headline: str
    factual_summary: str
    affected_symbols: tuple = ()
    affected_sectors: tuple = ()
    affected_assets: tuple = ()
    observations: list = field(default_factory=list)
    verification: str = "UNVERIFIED"
    importance: str = "UNKNOWN"
    mechanism_hypotheses: tuple = ()
    uncertainty: tuple = ()
    # WHAT THE CATALYST IMPLIES, not what anyone should do. Held apart
    # from the factual fields above because it is INTERPRETATION: the
    # brain reasoning from a mechanism, never something a source said.
    # Without it the Reaction Engine sees UNKNOWN for every event and
    # "good news, price fails" is undetectable -- which is most of why
    # Catalyst exists.
    directional_expectation: str = "UNKNOWN"
    expectation_source: str = "NONE"
    expectation_contract_sha: str = "NONE"
    expectation_known_from: str = "NONE"
    expected_value: float | str = "NOT_ESTIMABLE"
    actual_value: float | str = "NOT_ESTIMABLE"
    prior_value: float | str = "NOT_ESTIMABLE"
    surprise: float | str = "NOT_ESTIMABLE"
    market_state_at_event: dict = field(default_factory=dict)
    release_sha: str = "UNKNOWN"
    interpreter: str = "UNKNOWN"
    authority: str = "SHADOW_CONTEXT_ONLY"

    def __post_init__(self):
        if self.event_type not in EVENT_TYPES:
            raise CatalystViolation(
                f"unknown event_type {self.event_type!r}")
        if self.verification not in VERIFICATION:
            raise CatalystViolation(
                f"unknown verification {self.verification!r}")
        if self.importance not in IMPORTANCE:
            raise CatalystViolation(
                f"unknown importance {self.importance!r}")
        from apex.catalyst.reaction import DIRECTIONAL_EXPECTATION
        if self.directional_expectation not in DIRECTIONAL_EXPECTATION:
            raise CatalystViolation(
                f"unknown directional_expectation "
                f"{self.directional_expectation!r}")
        if (self.directional_expectation != "UNKNOWN"
                and self.expectation_source != "LLM_DERIVED_INTERPRETATION"):
            raise CatalystViolation(
                "a directional expectation may only come from an LLM "
                "interpretation; it is never a source fact, and "
                "recording it as one would let a reading become "
                "evidence")
        if self.known_from < self.first_seen:
            raise CatalystViolation(
                f"known_from {self.known_from} precedes first_seen "
                f"{self.first_seen}: APEX cannot act on an event before "
                f"it observed any source for it")

    def add_observation(self, obs: SourceObservation) -> dict:
        """Attach another publication. Returns an EVENT_UPDATE record --
        never a new event."""
        self.observations.append(obs)
        if obs.source_authority in FACT_BEARING and \
                self.verification == "UNVERIFIED":
            self.verification = "VERIFIED"
        return {"kind": "event_update", "event_id": self.event_id,
                "added_source": obs.source, "source_ref": obs.source_ref,
                "observation_count": len(self.observations),
                "verification": self.verification,
                "law": "a hundred headlines are one event"}

    @property
    def fact_bearing_sources(self) -> int:
        return sum(1 for o in self.observations
                   if o.source_authority in FACT_BEARING)

    def as_record(self) -> dict:
        d = asdict(self)
        d["observations"] = [o.as_record() for o in self.observations]
        return {"kind": "catalyst_event", **d,
                "decision_power": "SHADOW_CONTEXT_ONLY"}


def verify(event: CatalystEvent, *, conflicting: bool = False) -> str:
    """A claim is VERIFIED only on a fact-bearing source. Credible
    sources that disagree produce CONFLICTED, which is a real state --
    collapsing it to one side would be inventing certainty."""
    if conflicting:
        return "CONFLICTED"
    return "VERIFIED" if event.fact_bearing_sources else "UNVERIFIED"


def compute_surprise(*, actual, consensus) -> dict:
    """DETERMINISTIC. The LLM may interpret a surprise; it may never
    compute one, because a hallucinated number reads exactly like a
    measured one."""
    if not isinstance(actual, (int, float)) or \
            not isinstance(consensus, (int, float)):
        return {"surprise": "NOT_ESTIMABLE",
                "why": "actual or consensus unavailable -- an invented "
                       "consensus is worse than no surprise"}
    return {"surprise": round(actual - consensus, 6),
            "actual": actual, "consensus": consensus,
            "computed_by": "DETERMINISTIC_ARITHMETIC"}
