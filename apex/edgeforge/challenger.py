"""SHADOW CHALLENGER FACTORY + PROMOTION LADDER + VOI + REPRODUCIBILITY.

Phases 21, 23, 26.

A SHADOW CHALLENGER is a candidate frozen into an immutable definition
the moment it survives research. From that instant no hindsight edit is
possible: a materially changed challenger is a CHILD, never a revision.
This is what lets a challenger's forward record mean something -- a rule
edited while being evaluated has no forward record at all, only a
flattering present.

THE LADDER STOPS SHORT ON PURPOSE:

    DISCOVERY_ONLY -> REGISTERED_HYPOTHESIS -> RESEARCH_CANDIDATE ->
    HISTORICALLY_VALIDATED -> SHADOW_CHALLENGER -> PROSPECTIVE_SHADOW ->
    PAPER_REVIEW

PAPER_REVIEW is the end of EdgeForge's reach. PAPER_AUTHORIZED is not
on this ladder and cannot be reached from inside this package.

VALUE OF INFORMATION (23) asks what a proposed feed would CHANGE, not
what it would add. More data is not automatically more intelligence; it
is always more cost, more latency and more failure surface.

REPRODUCIBILITY (26) is binary. A result whose inputs cannot be
reconstructed is RESULT_UNVERIFIABLE, which is not a lesser result --
it is not a result.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

NOT_ESTIMABLE = "NOT_ESTIMABLE"

PROMOTION_LADDER = (
    "DISCOVERY_ONLY", "REGISTERED_HYPOTHESIS", "RESEARCH_CANDIDATE",
    "HISTORICALLY_VALIDATED", "SHADOW_CHALLENGER", "PROSPECTIVE_SHADOW",
    "PAPER_REVIEW",
)
TERMINAL_RUNG = "PAPER_REVIEW"
FORBIDDEN_RUNGS = ("PAPER_EXPLORATORY", "PAPER_AUTHORIZED",
                   "TINY_LIVE", "LIVE_SCALE")


class ChallengerViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ShadowChallenger:
    """Sealed at birth. Edits are impossible; children are not."""
    challenger_id: str
    birth_timestamp: str
    sealed_rules: dict
    feature_requirements: tuple
    execution_assumptions: dict
    invalidation: dict
    exit_rule: str
    risk_basis: str
    eligible_universe: tuple
    expected_failure_conditions: tuple
    parent_challenger_id: str | None = None
    mutation_reason: str | None = None
    rung: str = "SHADOW_CHALLENGER"
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if self.rung in FORBIDDEN_RUNGS:
            raise ChallengerViolation(
                f"{self.rung!r} is not reachable from EdgeForge; the "
                f"ladder ends at {TERMINAL_RUNG}")
        if self.rung not in PROMOTION_LADDER:
            raise ChallengerViolation(f"unknown rung {self.rung!r}")
        if not self.expected_failure_conditions:
            raise ChallengerViolation(
                "a challenger that does not say how it expects to fail "
                "cannot be evaluated fairly when it does")

    def definition_hash(self) -> str:
        body = {k: v for k, v in asdict(self).items()
                if k not in ("birth_timestamp",)}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()

    def as_record(self) -> dict:
        return {"kind": "shadow_challenger", **asdict(self),
                "definition_hash": self.definition_hash()}


def seal_challenger(**kw) -> ShadowChallenger:
    kw.setdefault("birth_timestamp",
                  datetime.now(timezone.utc).isoformat())
    return ShadowChallenger(**kw)


def mutate_challenger(parent: ShadowChallenger, *, suffix: str,
                      mutation_reason: str, **changes) -> ShadowChallenger:
    """A materially changed challenger is a new child with a fresh
    forward record -- never an edit that inherits the parent's."""
    if not mutation_reason:
        raise ChallengerViolation("a mutation without a reason is drift")
    if "challenger_id" in changes or "parent_challenger_id" in changes:
        raise ChallengerViolation("lineage fields are not editable")
    body = asdict(parent)
    body.update(changes)
    body.update({"challenger_id": f"{parent.challenger_id}{suffix}",
                 "parent_challenger_id": parent.challenger_id,
                 "mutation_reason": mutation_reason,
                 "birth_timestamp":
                     datetime.now(timezone.utc).isoformat(),
                 "rung": "SHADOW_CHALLENGER"})
    return ShadowChallenger(**body)


def advance(current: str, *, evidence: dict) -> dict:
    """Move one rung, and only with the evidence that rung requires."""
    if current not in PROMOTION_LADDER:
        raise ChallengerViolation(f"unknown rung {current!r}")
    i = PROMOTION_LADDER.index(current)
    if current == TERMINAL_RUNG:
        return {"kind": "promotion", "from": current, "to": current,
                "advanced": False,
                "why": "PAPER_REVIEW is the end of EdgeForge's reach; "
                       "further authority is an operator decision"}
    nxt = PROMOTION_LADDER[i + 1]
    required = {
        "REGISTERED_HYPOTHESIS": ("registered", "falsifiers"),
        "RESEARCH_CANDIDATE": ("mechanism", "competing_explanations"),
        "HISTORICALLY_VALIDATED": ("world_evidence", "beats_baselines",
                                   "adversary_survived"),
        "SHADOW_CHALLENGER": ("sealed_definition",),
        "PROSPECTIVE_SHADOW": ("prospective_sessions",),
        "PAPER_REVIEW": ("prospective_evidence_sufficient",),
    }[nxt]
    missing = [r for r in required if not evidence.get(r)]
    return {"kind": "promotion", "from": current,
            "to": nxt if not missing else current,
            "advanced": not missing, "missing_evidence": missing,
            "law": "each rung is earned by the evidence that rung "
                   "names; nothing skips",
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 23

def value_of_information(*, feed_name: str, decisions_changed: int,
                         decisions_observed: int,
                         losses_avoided, opportunities_found,
                         discrimination_delta, execution_delta,
                         cost_monthly, latency_ms, complexity: str,
                         new_failure_modes: tuple) -> dict:
    """What would this feed CHANGE? Not what would it add."""
    rate = (decisions_changed / decisions_observed
            if decisions_observed else NOT_ESTIMABLE)
    measurable = [x for x in (losses_avoided, opportunities_found,
                              discrimination_delta, execution_delta)
                  if isinstance(x, (int, float))]
    verdict = ("INSUFFICIENT_EVIDENCE" if not measurable
               or not isinstance(rate, float)
               else "CHANGES_DECISIONS" if rate > 0
               else "CHANGES_NOTHING_OBSERVED")
    return {"kind": "value_of_information", "feed": feed_name,
            "decision_change_rate": (round(rate, 4)
                                     if isinstance(rate, float) else rate),
            "losses_avoided": losses_avoided,
            "opportunities_found": opportunities_found,
            "discrimination_delta": discrimination_delta,
            "execution_delta": execution_delta,
            "cost_monthly": cost_monthly, "latency_ms": latency_ms,
            "complexity": complexity,
            "new_failure_modes": list(new_failure_modes),
            "verdict": verdict,
            "law": "a feed that does not change decisions is not a "
                   "moat, it is overhead -- and it always adds cost, "
                   "latency and failure surface",
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 26

REPRO_FIELDS = ("code_sha", "dataset_boundary", "source_registry",
                "genome_hash", "experiment_id", "world_generator_version",
                "world_set_hash", "candidate_attack_definition",
                "correction_lineage")


def reproducibility_manifest(**fields) -> dict:
    """Binary. A result whose inputs cannot be reconstructed is not a
    weaker result -- it is not a result."""
    missing = [f for f in REPRO_FIELDS if not fields.get(f)]
    return {"kind": "reproducibility_manifest",
            **{f: fields.get(f) for f in REPRO_FIELDS},
            "missing": missing,
            "verdict": ("REPRODUCIBLE" if not missing
                        else "RESULT_UNVERIFIABLE"),
            "law": "RESULT_UNVERIFIABLE is not a lesser grade of result; "
                   "it is the absence of one",
            "decision_power": "NONE_RESEARCH"}
