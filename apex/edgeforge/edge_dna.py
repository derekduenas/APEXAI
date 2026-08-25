"""EDGE DNA — the persistent identity of a candidate edge.

An edge is not a backtest number. It is a MECHANISM with a required
state, a path profile, a failure surface, an execution reality, a
capacity envelope, and -- non-negotiably -- an answer to the question
that decides whether it belongs to us at all:

    WHY IS THIS MORE ATTRACTIVE TO OUR ACCOUNT SIZE THAN TO GIANT
    CAPITAL?

Smallness is not automatically an advantage. A candidate facing HIGH
giant competition with WHY_SMALL_WINS = UNKNOWN is flagged, because it
is probably someone else's edge that we are late to.

LINEAGE. Edges evolve; definitions never mutate in place. A materially
changed mechanism births a child (EDGE_00417 -> EDGE_00417B) carrying
its parent's id and the mutation reason, so the family history of every
idea stays reconstructible.

Every DNA is born with authority RESEARCH_ONLY. Promotion is a separate
bridge (REGISTERED_HYPOTHESIS -> VALIDATED -> SHADOW_CHALLENGER ->
PAPER_EXPLORATORY -> ...) that EdgeForge cannot cross by itself.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

NOT_ESTIMABLE = "NOT_ESTIMABLE"

WHY_SMALL_WINS = (
    "CAPACITY_TOO_SMALL", "FOOTPRINT_ADVANTAGE",
    "TEMPORARY_DISLOCATION", "SHORT_SIGNAL_HALF_LIFE",
    "EXTREME_SELECTIVITY", "OPTIONALITY_TO_REMAIN_FLAT",
    "FORCED_PARTICIPANT", "MISPRICED_CONVEXITY",
    "LOW_DOLLAR_OPPORTUNITY_FOR_INSTITUTION", "CROSS_SLEEVE_NICHE",
    "OTHER_EVIDENCED", "UNKNOWN",
)

GIANT_RISK = ("LOW", "MODERATE", "HIGH", NOT_ESTIMABLE)

EDGE_AUTHORITY = ("RESEARCH_ONLY",)          # V0: the only authority

EDGE_HEALTH = ("BIRTH", "EMERGING", "HEALTHY", "WEAKENING", "DECAYING",
               "BROKEN", NOT_ESTIMABLE)


class EdgeDNAViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class CapitalEvolution:
    """How the edge behaves as OUR account grows. NOT_ESTIMABLE until
    empirical evidence exists -- an invented capacity ceiling is a plan
    to be surprised."""
    minimum_useful_account: float | str = NOT_ESTIMABLE
    ideal_account_range: tuple | str = NOT_ESTIMABLE
    capacity_ceiling: float | str = NOT_ESTIMABLE
    expected_footprint: str = NOT_ESTIMABLE
    liquidity_limit: str = NOT_ESTIMABLE
    scaling_decay: str = NOT_ESTIMABLE

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SmallWinsAssessment:
    reason: str
    evidence: tuple = ()
    giant_competition_risk: str = NOT_ESTIMABLE
    flag: str = "NONE"

    def __post_init__(self):
        if self.reason not in WHY_SMALL_WINS:
            raise EdgeDNAViolation(
                f"why_small_wins {self.reason!r} is not a declared "
                f"category")
        if self.giant_competition_risk not in GIANT_RISK:
            raise EdgeDNAViolation(
                f"giant risk {self.giant_competition_risk!r} undeclared")
        if self.reason != "UNKNOWN" and not self.evidence:
            raise EdgeDNAViolation(
                "a claimed small-capital advantage requires evidence; "
                "without it the honest category is UNKNOWN")

    @classmethod
    def build(cls, *, reason: str, evidence: tuple = (),
              giant_competition_risk: str = NOT_ESTIMABLE
              ) -> "SmallWinsAssessment":
        flag = "NONE"
        if giant_competition_risk == "HIGH" and reason == "UNKNOWN":
            flag = ("GIANT_TERRAIN_NO_SMALL_ADVANTAGE -- this is "
                    "probably someone else's edge, and we are late")
        return cls(reason=reason, evidence=evidence,
                   giant_competition_risk=giant_competition_risk,
                   flag=flag)

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EdgeDNA:
    edge_id: str
    birth_timestamp: str
    discovery_origin: str
    mechanism: str
    required_state: dict
    supporting_evidence: tuple = ()
    contradicting_evidence: tuple = ()
    competing_explanations: tuple = ()
    path_profile: dict = field(default_factory=dict)
    tail_profile: dict = field(default_factory=dict)
    execution_profile: dict = field(default_factory=dict)
    best_known_expression: str = NOT_ESTIMABLE
    failure_surface: dict = field(default_factory=dict)
    signal_half_life: str = NOT_ESTIMABLE
    capacity_suitability: str = NOT_ESTIMABLE
    our_expected_footprint: str = NOT_ESTIMABLE
    crowding: str = NOT_ESTIMABLE
    forced_participant_strength: str = NOT_ESTIMABLE
    tail_asymmetry: str = NOT_ESTIMABLE
    why_small_wins: dict = field(default_factory=dict)
    capital_evolution: dict = field(default_factory=dict)
    capital_accelerant: dict = field(default_factory=dict)
    historical_support: dict = field(default_factory=dict)
    prospective_support: dict = field(
        default_factory=lambda: {"n": 0, "note": "none yet"})
    calibration: str = "NONE_FITTED"
    edge_health: str = "BIRTH"
    authority: str = "RESEARCH_ONLY"
    parent_edge_id: str | None = None
    mutation_reason: str | None = None
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if self.authority not in EDGE_AUTHORITY:
            raise EdgeDNAViolation(
                f"V0 edges hold RESEARCH_ONLY authority; "
                f"{self.authority!r} is a self-promotion attempt")
        if self.edge_health not in EDGE_HEALTH:
            raise EdgeDNAViolation(f"health {self.edge_health!r} undeclared")
        if not self.competing_explanations:
            raise EdgeDNAViolation(
                f"{self.edge_id}: an edge with no competing explanation "
                f"is a story, not a mechanism")
        if not self.why_small_wins:
            raise EdgeDNAViolation(
                f"{self.edge_id}: WHY_SMALL_WINS must be assessed, even "
                f"when the honest answer is UNKNOWN")

    def as_record(self) -> dict:
        return {"kind": "edge_dna", **asdict(self)}


def mutate(parent: EdgeDNA, *, child_suffix: str, mutation_reason: str,
           **changes) -> EdgeDNA:
    """Birth a child edge; the parent definition is never altered."""
    if not mutation_reason:
        raise EdgeDNAViolation("a mutation without a reason is drift")
    banned = {"edge_id", "parent_edge_id", "mutation_reason",
              "birth_timestamp", "authority"}
    if banned & set(changes):
        raise EdgeDNAViolation(
            f"fields {sorted(banned & set(changes))} are lineage-owned")
    body = asdict(parent)
    body.update(changes)
    body.update({
        "edge_id": f"{parent.edge_id}{child_suffix}",
        "parent_edge_id": parent.edge_id,
        "mutation_reason": mutation_reason,
        "birth_timestamp": datetime.now(timezone.utc).isoformat(),
        "authority": "RESEARCH_ONLY",
        "edge_health": "BIRTH",
        "prospective_support": {"n": 0,
                                "note": "a child edge inherits no "
                                        "prospective support"},
    })
    return EdgeDNA(**body)


def capital_accelerant_assessment(*, explicit_downside: bool,
                                  favorable_tail_evidence: str,
                                  holding_period: str,
                                  capital_efficiency: str,
                                  footprint: str,
                                  mechanism_credibility: str,
                                  execution_survivability: str) -> dict:
    """Research classification only -- no thresholds, no authority.

    The question on record: can this edge meaningfully accelerate
    small-account geometric growth without disproportionate ruin
    contribution? V0 answers with a descriptive checklist, because a
    scored answer would be a learned threshold nobody has earned."""
    return {"kind": "capital_accelerant_assessment",
            "classification": "CAPITAL_ACCELERANT_CANDIDATE",
            "grants_capital_authority": False,
            "checklist": {
                "explicit_downside": explicit_downside,
                "favorable_tail_evidence": favorable_tail_evidence,
                "holding_period": holding_period,
                "capital_efficiency": capital_efficiency,
                "footprint": footprint,
                "mechanism_credibility": mechanism_credibility,
                "execution_survivability": execution_survivability},
            "law": "a classification, not a threshold; ruin remains "
                   "unacceptable and capital remains Capital's",
            "decision_power": "NONE_RESEARCH"}
