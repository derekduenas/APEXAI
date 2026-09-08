"""EVENT_INTELLIGENCE_ADMISSIBILITY_V0 -- may this event record enter research?

WHY THIS EXISTS AND WHY IT IS NOT A NEW EVENT MODEL
APEX already has an event contract. apex/catalyst/events.py holds
CatalystEvent with four clocks that are never conflated (event_time,
published_time, first_seen, known_from), source-authority tiers with a
fact-bearing subset, an event-type vocabulary, dedup that makes a hundred
headlines one event, CONFLICTED as a real state, and surprise fields whose
expectation carries its own provenance and known_from. Building a second
event model would duplicate all of it and let two records of the same event
disagree.

What APEX does NOT have is the gate: a decision, per record, about whether
that event may be used as research input, and the checks that decision needs.
This module is only that gate. It reads CatalystEvent, mutates nothing, and
adds the missing checks:

    * source CONTENT hashes, so a source that changes under us is caught
    * duplicate content across "independent" sources, so one wire story
      republished five times cannot look like five corroborations
    * publication time distinguished from retrieval time, with a declared
      basis -- the commonest silent leak in event research
    * future timestamps, in any clock
    * extraction provenance: which model, which version, when, under which
      prompt contract
    * entity resolution status, so an unresolved or ambiguous ticker is a
      refusal rather than a guess
    * a structural ban on probabilities and on trade or sizing fields

AUTHORITY: none. An admitted record is an OBSERVATION with provenance. It
carries no probability, no direction to act on, no size and no order. The
LLM may say what kind of event this is and what mechanism it hypothesises;
it may not say how likely anything is, and nothing here may reach PRIME,
ARENA, RISK, BOOK or the execution boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

CONTRACT = "EVENT_INTELLIGENCE_ADMISSIBILITY_V0"

AUTHORITY = {
    "contract": CONTRACT,
    "PROBABILITY_AUTHORITY": "NONE",
    "TRADING_AUTHORITY": "NONE",
    "ORDER_AUTHORITY": "NONE",
    "SIZING_AUTHORITY": "NONE",
    "PRIME_INPUT": "NOT_ADMITTED_BY_THIS_CONTRACT",
    "DECISION_POWER": "SHADOW_CONTEXT_ONLY",
}

# What an admitted record may be used as. Nothing here is a fact by default.
ADMISSIBLE_FACT = "ADMISSIBLE_FACT"              # >=1 fact-bearing source, no conflict
ADMISSIBLE_LEAD = "ADMISSIBLE_LEAD"              # only non-fact-bearing sources
ADMISSIBLE_CONFLICTED = "ADMISSIBLE_CONFLICTED"  # credible sources disagree; kept as a state
REFUSED = "REFUSED"

PUBLICATION_TIME_BASIS = ("MEASURED", "DECLARED_BY_SOURCE", "UNKNOWN")
ENTITY_STATUS = ("RESOLVED", "UNRESOLVED", "AMBIGUOUS")

# Field names that must never appear in an extraction payload. A probability
# an LLM produced is not a measurement, and a direction with a size is a
# trade instruction wearing an observation's clothes.
FORBIDDEN_PROBABILITY = re.compile(
    r"^(p|prob|probability|likelihood|confidence|odds|score|certainty)(_|$)|"
    r"(_|^)(probability|likelihood|confidence|odds)(_|$)", re.I)
FORBIDDEN_TRADE = re.compile(
    r"^(side|direction|signal|action|order|trade|position|size|quantity|qty|"
    r"notional|allocation|weight|target_price|stop|stop_loss|take_profit|"
    r"leverage|entry|exit)(_|$)", re.I)


class EventAdmissibilityRefused(Exception):
    """This record may not enter research. Named reason, no default."""


@dataclass(frozen=True)
class ExtractionProvenance:
    """Who produced this record, from what, when, under which contract."""
    extractor: str                  # "ANTHROPIC_SKILL" | "FINGPT" | "KEYWORD_BASELINE" | ...
    model: str
    model_version: str
    prompt_contract_sha: str
    extraction_time: str
    extractor_authority: str = "NON_AUTHORITATIVE_OBSERVATION"

    def __post_init__(self):
        for f in ("extractor", "model", "model_version", "prompt_contract_sha", "extraction_time"):
            if not str(getattr(self, f) or "").strip():
                raise EventAdmissibilityRefused(
                    "MISSING_EXTRACTION_PROVENANCE: %s is empty; an extraction whose model, "
                    "version, prompt contract or time is unknown cannot be reproduced or "
                    "attributed" % f)
        if self.extractor_authority != "NON_AUTHORITATIVE_OBSERVATION":
            raise EventAdmissibilityRefused(
                "EXTRACTOR_CLAIMS_AUTHORITY: %r. An extractor produces observations; it does "
                "not produce findings." % self.extractor_authority)


@dataclass(frozen=True)
class SourceRecord:
    """One publication, with the content hash the observation was made from."""
    source_id: str
    source_authority: str
    source_ref: str
    published_time: str
    retrieval_time: str
    content_sha256: str
    publication_time_basis: str = "UNKNOWN"

    def __post_init__(self):
        if not self.source_id or not self.source_ref:
            raise EventAdmissibilityRefused(
                "UNVERIFIED_SOURCE_IDENTITY: a source without an id and a stable reference is "
                "'news says', which is not provenance")
        if self.publication_time_basis not in PUBLICATION_TIME_BASIS:
            raise EventAdmissibilityRefused(
                "PUBLICATION_TIME_BASIS_UNKNOWN_VALUE: %r not in %s"
                % (self.publication_time_basis, list(PUBLICATION_TIME_BASIS)))
        if len(self.content_sha256 or "") != 64:
            raise EventAdmissibilityRefused(
                "SOURCE_CONTENT_UNHASHED: %s carries no content hash, so a later change to it "
                "could not be detected" % self.source_id)


def _t(value: str, what: str) -> datetime:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise EventAdmissibilityRefused("MALFORMED_TIME: %s=%r" % (what, value))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def content_sha256(raw: bytes | str) -> str:
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def _scan_payload(payload: dict) -> None:
    """Refuse probability and trade fields wherever they are nested."""
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = "%s.%s" % (path, k) if path else k
                if FORBIDDEN_PROBABILITY.search(k):
                    raise EventAdmissibilityRefused(
                        "LLM_PROBABILITY_PRESENT: field %r. An extractor may say what happened "
                        "and what mechanism it hypothesises; it may not say how likely anything "
                        "is. Probability is the World Model's, and only from a fitted estimator."
                        % p)
                if FORBIDDEN_TRADE.search(k):
                    raise EventAdmissibilityRefused(
                        "TRADE_FIELD_PRESENT: field %r. An observation carries no direction, "
                        "size, order or level." % p)
                walk(v, p)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                walk(v, "%s[%d]" % (path, i))
    walk(payload)


@dataclass
class EventAdmission:
    """The decision, with everything it was based on."""
    contract: str
    event_id: str
    status: str
    reason: str
    event_type: str
    event_time: str
    known_from: str
    extraction: dict
    sources: list
    entities: dict
    independent_source_count: int
    fact_bearing_source_count: int
    conflict: bool
    surprise: dict = field(default_factory=dict)
    mechanism_hypotheses: tuple = ()
    uncertainty: tuple = ()
    authority: dict = field(default_factory=lambda: dict(AUTHORITY))

    def canonical(self) -> str:
        """Deterministic serialisation: the same record always hashes the same."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)

    @property
    def record_sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    def as_record(self) -> dict:
        return {"kind": "event_admission", **json.loads(self.canonical()),
                "record_sha256": self.record_sha256}


def admit(event, *, extraction: ExtractionProvenance, sources: list,
          entity_status: dict, now_utc: str, payload: dict | None = None,
          recheck_content: dict | None = None) -> EventAdmission:
    """Decide whether one event record may enter research.

    event            an apex.catalyst.events.CatalystEvent (read, never mutated)
    sources          SourceRecord per publication, each with a content hash
    entity_status    symbol -> RESOLVED | UNRESOLVED | AMBIGUOUS
    now_utc          the instant this decision is being made
    payload          the raw extraction dict, scanned for forbidden fields
    recheck_content  source_id -> hash observed NOW, to catch mutation
    """
    from apex.catalyst.events import FACT_BEARING          # read-only import

    now = _t(now_utc, "now_utc")
    if not sources:
        raise EventAdmissibilityRefused("NO_SOURCE: an event with no publication is not an observation")

    known_from = getattr(event, "known_from", None)
    if not str(known_from or "").strip() or str(known_from).upper() in ("NONE", "UNKNOWN"):
        raise EventAdmissibilityRefused(
            "MISSING_KNOWN_FROM: without the instant APEX could first have acted on this event, "
            "no research join to a market state can be checked for leakage")
    kf = _t(known_from, "known_from")
    et = _t(getattr(event, "event_time"), "event_time")
    if kf > now or et > now:
        raise EventAdmissibilityRefused(
            "FUTURE_TIMESTAMP: known_from=%s event_time=%s are ahead of now=%s"
            % (known_from, getattr(event, "event_time"), now_utc))

    seen_content, independent = {}, 0
    for s in sources:
        pub, ret = _t(s.published_time, "published_time"), _t(s.retrieval_time, "retrieval_time")
        if pub > now or ret > now:
            raise EventAdmissibilityRefused(
                "FUTURE_TIMESTAMP: source %s published=%s retrieved=%s vs now=%s"
                % (s.source_id, s.published_time, s.retrieval_time, now_utc))
        if s.publication_time_basis == "UNKNOWN":
            raise EventAdmissibilityRefused(
                "PUBLICATION_TIME_UNKNOWN: %s does not say how its publication time was "
                "obtained; an unknown basis is usually the retrieval time wearing a "
                "publication label" % s.source_id)
        if pub == ret and s.publication_time_basis != "MEASURED":
            raise EventAdmissibilityRefused(
                "PUBLICATION_IS_RETRIEVAL: %s reports publication == retrieval (%s) without a "
                "MEASURED basis. Treating the moment we fetched a page as the moment it was "
                "published makes every event look later than it was." % (s.source_id, s.published_time))
        if kf < pub:
            raise EventAdmissibilityRefused(
                "KNOWN_FROM_PRECEDES_PUBLICATION: known_from=%s is before %s published at %s"
                % (known_from, s.source_id, s.published_time))
        if recheck_content is not None and s.source_id in recheck_content:
            if recheck_content[s.source_id] != s.content_sha256:
                raise EventAdmissibilityRefused(
                    "SOURCE_CONTENT_MUTATED: %s was %s when observed and is %s now; a source "
                    "that changes under a record invalidates it"
                    % (s.source_id, s.content_sha256[:16], recheck_content[s.source_id][:16]))
        if s.content_sha256 in seen_content:
            raise EventAdmissibilityRefused(
                "DUPLICATE_SOURCE_CONTENT: %s and %s carry identical content (%s). One wire "
                "story republished is one observation, not two corroborations."
                % (seen_content[s.content_sha256], s.source_id, s.content_sha256[:16]))
        seen_content[s.content_sha256] = s.source_id
        independent += 1

    bad = {k: v for k, v in (entity_status or {}).items() if v != "RESOLVED"}
    for sym in getattr(event, "affected_symbols", ()) or ():
        if sym not in (entity_status or {}):
            bad[sym] = "UNRESOLVED"
    if bad:
        raise EventAdmissibilityRefused(
            "ENTITY_NOT_RESOLVED: %s. A wrong attribution is worse than an honest unknown."
            % json.dumps(bad, sort_keys=True))
    for k, v in (entity_status or {}).items():
        if v not in ENTITY_STATUS:
            raise EventAdmissibilityRefused("ENTITY_STATUS_UNKNOWN_VALUE: %s=%r" % (k, v))

    if payload is not None:
        _scan_payload(payload)

    fact_bearing = sum(1 for s in sources if s.source_authority in FACT_BEARING)
    conflict = getattr(event, "verification", "UNVERIFIED") == "CONFLICTED"
    if conflict:
        status, reason = ADMISSIBLE_CONFLICTED, ("credible sources disagree; admitted as a "
                                                 "conflicted observation, never as a fact")
    elif fact_bearing:
        status, reason = ADMISSIBLE_FACT, "at least one fact-bearing source, no conflict"
    else:
        status, reason = ADMISSIBLE_LEAD, ("no fact-bearing source; usable to know something "
                                           "happened, never to assert what")

    surprise = {k: getattr(event, k, "NOT_ESTIMABLE")
                for k in ("expected_value", "actual_value", "prior_value", "surprise",
                          "expectation_source", "expectation_known_from")}
    return EventAdmission(
        contract=CONTRACT, event_id=getattr(event, "event_id"), status=status, reason=reason,
        event_type=getattr(event, "event_type"), event_time=getattr(event, "event_time"),
        known_from=known_from, extraction=asdict(extraction),
        sources=[asdict(s) for s in sources], entities=dict(entity_status or {}),
        independent_source_count=independent, fact_bearing_source_count=fact_bearing,
        conflict=conflict, surprise=surprise,
        mechanism_hypotheses=tuple(getattr(event, "mechanism_hypotheses", ()) or ()),
        uncertainty=tuple(getattr(event, "uncertainty", ()) or ()))


# ------------------------------------------------------------- baseline
KEYWORD_RULES = (
    ("EARNINGS", ("earnings", "eps", "quarterly results", "q1", "q2", "q3", "q4")),
    ("GUIDANCE", ("guidance", "outlook", "forecast cut", "raises outlook")),
    ("MA", ("merger", "acquisition", "to acquire", "takeover")),
    ("REGULATORY", ("fda", "approval", "regulator", "antitrust", "sec charges")),
    ("MACRO_RELEASE", ("cpi", "payrolls", "gdp", "inflation", "jobs report")),
    ("CENTRAL_BANK", ("fed", "fomc", "rate decision", "ecb", "boj")),
)


def keyword_baseline_event_type(headline: str) -> str:
    """The simplest thing that could work: a deterministic keyword map.

    It exists so that any LLM extractor must beat something, and so the
    future evaluation has a comparator that costs nothing and leaks nothing.
    First match in declared order wins; no match is UNKNOWN, never a guess."""
    h = (headline or "").lower()
    for event_type, words in KEYWORD_RULES:
        if any(w in h for w in words):
            return event_type
    return "UNKNOWN"
