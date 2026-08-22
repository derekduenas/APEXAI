"""PATTERN STATE -- what the Observatory knows about one configuration.

HIGH_ALIGNMENT DOES NOT MEAN TRADE. It means every declared component of
a pre-registered family is present at acceptable input quality. Whether
that has ever preceded anything is a separate question answered by the
outcome resolver against baselines, and until it is answered the
probability fields stay disabled.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

DISCOVERED, FORMING, DEVELOPING = "DISCOVERED", "FORMING", "DEVELOPING"
HIGH_ALIGNMENT, BROKEN, EXPIRED = "HIGH_ALIGNMENT", "BROKEN", "EXPIRED"
STATUSES = (DISCOVERED, FORMING, DEVELOPING, HIGH_ALIGNMENT, BROKEN, EXPIRED)

PROBABILITY_NOT_ESTIMABLE = "PROBABILITY_NOT_ESTIMABLE"
UNCALIBRATED = "UNCALIBRATED"

# Support required before a distribution may even be ATTEMPTED. These are
# gates, not targets, and clearing them earns the right to compute -- not
# the right to claim.
MIN_PROSPECTIVE_N = 30
MIN_DISTINCT_SESSIONS = 10
MIN_DISTINCT_SYMBOLS = 5
MIN_DISTINCT_REGIMES = 2


@dataclass(frozen=True)
class PatternState:
    pattern_id: str
    family_id: str
    subject: str
    market: str
    sleeve_relevance: tuple

    first_seen: str
    last_updated: str
    known_from: str

    components_required: tuple
    components_present: tuple
    components_missing: tuple
    regime: str | None

    sequence_progress: dict
    input_quality: dict

    historical_n: int
    prospective_n: int
    distinct_sessions: int
    distinct_symbols: int
    distinct_regimes: int

    similarity: dict
    novelty: str
    ood: str

    supporting_evidence: tuple
    contradicting_evidence: tuple
    falsifiers: tuple

    forward_distribution_status: str
    direction_distribution: str | dict
    magnitude_distribution: str | dict
    timing_distribution: str | dict
    calibration_status: str

    current_status: str
    independence: dict
    reasoning: tuple = ()
    # LINEAGE (schema v2). pattern_id is FAMILY-SCOPED; conjunction_id is
    # the underlying content-addressed conjunction the family matched.
    # Before v2 these were the same value, which is exactly how P004 and
    # P006 shared identities 3 times on 2026-08-20 (92/246 rows).
    conjunction_id: str | None = None
    pattern_id_schema_version: int = 1

    def as_dict(self) -> dict:
        return {
            "kind": "pattern_state", "pattern_id": self.pattern_id,
            "family_id": self.family_id, "subject": self.subject,
            "market": self.market,
            "sleeve_relevance": list(self.sleeve_relevance),
            "first_seen": self.first_seen, "last_updated": self.last_updated,
            "known_from": self.known_from,
            "components_required": list(self.components_required),
            "components_present": list(self.components_present),
            "components_missing": list(self.components_missing),
            "regime": self.regime,
            "sequence_progress": dict(self.sequence_progress),
            "input_quality": dict(self.input_quality),
            "historical_n": self.historical_n,
            "prospective_n": self.prospective_n,
            "distinct_sessions": self.distinct_sessions,
            "distinct_symbols": self.distinct_symbols,
            "distinct_regimes": self.distinct_regimes,
            "similarity": dict(self.similarity), "novelty": self.novelty,
            "ood": self.ood,
            "supporting_evidence": list(self.supporting_evidence),
            "contradicting_evidence": list(self.contradicting_evidence),
            "falsifiers": list(self.falsifiers),
            "forward_distribution_status": self.forward_distribution_status,
            "direction_distribution": self.direction_distribution,
            "magnitude_distribution": self.magnitude_distribution,
            "timing_distribution": self.timing_distribution,
            "calibration_status": self.calibration_status,
            "current_status": self.current_status,
            "independence": dict(self.independence),
            "reasoning": list(self.reasoning),
            "conjunction_id": self.conjunction_id,
            "pattern_id_schema_version": self.pattern_id_schema_version,
            "high_alignment_means_trade": False,
            "best_expression": "NOT_EVALUATED",
            "decision_power": OBSERVATORY_POWER,
        }

    def support_sufficient(self) -> bool:
        return (self.prospective_n >= MIN_PROSPECTIVE_N
                and self.distinct_sessions >= MIN_DISTINCT_SESSIONS
                and self.distinct_symbols >= MIN_DISTINCT_SYMBOLS
                and self.distinct_regimes >= MIN_DISTINCT_REGIMES)


def build(*, conjunction, family, quality_verdict: dict,
          sequence_state=None, contradiction=None, support: dict | None = None,
          now, known_from) -> PatternState:
    """`support`: the output of `apex.pattern_observatory.support.aggregate()`
    -- real cross-session counts, KNOWN_FROM-FILTERED so this pattern's own
    support can never include evidence from later than `now`. Omitting
    `support` (the default) means every count stays 0 and the probability
    gate stays permanently closed -- which is what happened for the whole
    of 2026-08-19's Observatory build until this was wired the next
    evening. Passing a real aggregation is what lets the gate ever open."""
    support = support or {}
    present = tuple(sorted(set(conjunction.components)
                           & set(family.components_required)))
    missing = tuple(sorted(set(family.components_required) - set(present)))

    seq = ({"state": sequence_state.state,
            "completion_fraction": sequence_state.completion_fraction,
            "current_step": sequence_state.current_step,
            "expected_next_step": sequence_state.expected_next_step,
            "observed_order": list(sequence_state.observed_order)}
           if sequence_state else {"state": "NOT_TRACKED"})

    reasoning = []
    if not quality_verdict.get("estimable"):
        status = FORMING
        reasoning.append(
            f"required features not estimable: "
            f"{quality_verdict.get('blocking_features')}")
    elif missing:
        status = DEVELOPING if len(present) > 1 else FORMING
        reasoning.append(f"{len(present)}/{len(family.components_required)} "
                         f"required components present")
    else:
        status = HIGH_ALIGNMENT
        reasoning.append("all required components present at acceptable "
                         "input quality -- this is ALIGNMENT, not a trade")

    if contradiction is not None and contradiction.burden in ("MATERIAL",
                                                              "HEAVY"):
        reasoning.append(f"contradiction burden {contradiction.burden}")

    # FAMILY-SCOPED IDENTITY (schema v2, the 2026-08-20 collision fix).
    # build() owns this computation so no caller can ever skip it and
    # fall back to the shared conjunction-level hash.
    from apex.pattern_observatory.conjunction import (
        PATTERN_ID_SCHEMA_VERSION, family_pattern_id,
    )
    pid = family_pattern_id(
        family_id=family.family_id, subject=conjunction.subject,
        conjunction_id=conjunction.pattern_id,
        first_seen=conjunction.first_seen)

    return PatternState(
        pattern_id=pid, family_id=family.family_id,
        conjunction_id=conjunction.pattern_id,
        pattern_id_schema_version=PATTERN_ID_SCHEMA_VERSION,
        subject=conjunction.subject, market=conjunction.market,
        sleeve_relevance=family.sleeves,
        first_seen=conjunction.first_seen, last_updated=str(now),
        known_from=str(known_from),
        components_required=family.components_required,
        components_present=present, components_missing=missing,
        regime=getattr(conjunction, "regime", None),
        sequence_progress=seq, input_quality=quality_verdict,
        historical_n=support.get("historical_n", 0),
        prospective_n=support.get("prospective_n", 0),
        distinct_sessions=support.get("distinct_sessions", 0),
        distinct_symbols=support.get("distinct_symbols", 0),
        distinct_regimes=support.get("distinct_regimes", 0),
        similarity=support.get("similarity", {"status": "NOT_ESTIMABLE"}),
        novelty=support.get("novelty", "UNKNOWN"),
        ood=support.get("ood", "NOT_ESTIMABLE"),
        supporting_evidence=(tuple(contradiction.supporting)
                             if contradiction else ()),
        contradicting_evidence=(tuple(contradiction.contradicting)
                                + tuple(contradiction.universal_hits)
                                if contradiction else ()),
        falsifiers=tuple(w for _, w in
                         __import__("apex.pattern_observatory.contradiction",
                                    fromlist=["CONTRADICTIONS"])
                         .CONTRADICTIONS.get(family.family_id, ())
                         if isinstance(_, str)),
        forward_distribution_status=PROBABILITY_NOT_ESTIMABLE,
        direction_distribution=PROBABILITY_NOT_ESTIMABLE,
        magnitude_distribution=PROBABILITY_NOT_ESTIMABLE,
        timing_distribution=PROBABILITY_NOT_ESTIMABLE,
        calibration_status=UNCALIBRATED,
        current_status=status, independence=conjunction.independence,
        reasoning=tuple(reasoning))
