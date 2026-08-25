"""RESEARCH FACTORY — the loop, and the report that refuses to flatter.

Phases 18 and 27.

The factory runs after a completed session and turns sealed reality
into research: ingest, genomes, outcomes, hypotheses, credibility, gate
value, discovery, worlds, tournament, adversary, surface, registry,
edge health, brief.

RESEARCH BUDGET. Exploration is unlimited and cheap. CONFIRMATION is
governed and must never be consumed automatically -- the factory can
generate ten thousand candidates overnight, and if it could also spend
confirmatory credits on them it would exhaust the project's entire
statistical budget by breakfast.

THE FRONTIER REPORT LEADS WITH WHAT FAILED. Nulls, killed edges,
candidates beaten by naive baselines, model disagreements, health
warnings and research debt come before anything promising -- because a
report that opens with its best finding is a sales document, and this
one has to survive being read by someone hostile.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

NOT_ESTIMABLE = "NOT_ESTIMABLE"

PIPELINE_STAGES = (
    "INGEST_SEALED_REALITY", "BUILD_GENOMES", "RESOLVE_OUTCOMES",
    "UPDATE_HYPOTHESES", "UPDATE_CREDIBILITY", "RUN_GATE_VALUE",
    "RUN_FRONTIER_DISCOVERY", "BUILD_CANDIDATE_EDGE_DNA",
    "GENERATE_WORLDS", "ATTACK_TOURNAMENT", "GENERATOR_OPTIMISM",
    "ADVERSARY",
    "EDGE_SURFACE", "REGISTER_RESULT", "UPDATE_EDGE_HEALTH",
    "PRODUCE_RESEARCH_BRIEF",
)

COMPUTE_TIERS = ("SMOKE", "RESEARCH", "DEEP_RESEARCH")


class FactoryViolation(RuntimeError):
    pass


@dataclass
class ResearchRun:
    session: str
    tier: str = "SMOKE"
    stages: dict = field(default_factory=dict)
    confirmatory_credits_consumed: int = 0
    started_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if self.tier not in COMPUTE_TIERS:
            raise FactoryViolation(f"unknown compute tier {self.tier!r}")

    def stage(self, name: str, result: dict, *,
              consumes_confirmatory: bool = False) -> None:
        if name not in PIPELINE_STAGES:
            raise FactoryViolation(f"undeclared stage {name!r}")
        if consumes_confirmatory:
            raise FactoryViolation(
                "the factory may not consume a confirmatory credit "
                "automatically: it can generate ten thousand candidates "
                "overnight, and spending credits on them would exhaust "
                "the project's statistical budget by breakfast. "
                "Confirmation requires explicit authority.")
        self.stages[name] = result

    def completed(self) -> list:
        return [s for s in PIPELINE_STAGES if s in self.stages]

    def missing(self) -> list:
        return [s for s in PIPELINE_STAGES if s not in self.stages]


def frontier_report(run: ResearchRun, *, discoveries: list = (),
                    nulls: list = (), killed_by_adversary: list = (),
                    inferior_to_baseline: list = (),
                    disagreements: list = (),
                    gate_value: dict | None = None,
                    accelerant_candidates: list = (),
                    edge_health_warnings: list = (),
                    world_model_health: dict | None = None,
                    sample_sufficiency: dict | None = None,
                    research_debt: list = ()) -> dict:
    """The brief. Failures first, deliberately."""
    negative = (list(nulls) + list(killed_by_adversary)
                + list(inferior_to_baseline))
    return {
        "kind": "edgeforge_frontier_report",
        "session": run.session, "tier": run.tier,
        "stages_completed": run.completed(),
        "stages_missing": run.missing(),
        "confirmatory_credits_consumed": run.confirmatory_credits_consumed,

        # --- what did NOT work, first
        "null_results": list(nulls),
        "edges_killed_by_adversary": list(killed_by_adversary),
        "inferior_to_simple_baseline": list(inferior_to_baseline),
        "n_negative_findings": len(negative),

        # --- what the machine is unsure about
        "model_disagreements": list(disagreements),
        "edge_health_warnings": list(edge_health_warnings),
        "world_model_health": world_model_health or NOT_ESTIMABLE,
        "sample_sufficiency": sample_sufficiency or NOT_ESTIMABLE,
        "research_debt": list(research_debt),

        # --- and only then, what might be something
        "gate_value": gate_value or NOT_ESTIMABLE,
        "new_hypotheses": list(discoveries),
        "capital_accelerant_candidates": list(accelerant_candidates),

        "reading_order_law": ("failures lead because a report that "
                              "opens with its best finding is a sales "
                              "document"),
        "significance_law": ("economic significance outranks "
                             "architectural sophistication; nothing "
                             "here is an edge until prospective "
                             "evidence says so"),
        "promotes_nothing": True,
        "decision_power": "NONE_RESEARCH",
    }


def world_budget(tier: str, *, candidate_is_interesting: bool = False,
                 pipeline_valid: bool = False,
                 generator_valid: bool = False) -> dict:
    """Staged compute. Millions of worlds before validation is not
    research, it is a heating bill."""
    from apex.edgeforge.world_foundry import COMPUTE_LADDER
    if tier not in COMPUTE_TIERS:
        raise FactoryViolation(f"unknown tier {tier!r}")
    allowed = tier
    blockers = []
    if tier != "SMOKE":
        if not pipeline_valid:
            blockers.append("pipeline not validated at SMOKE")
        if not generator_valid:
            blockers.append("generator not validated")
    if tier == "DEEP_RESEARCH" and not candidate_is_interesting:
        blockers.append("candidate not yet interesting enough")
    if blockers:
        allowed = "SMOKE"
    return {"kind": "world_budget", "requested": tier,
            "granted": allowed, "n_worlds": COMPUTE_LADDER[allowed],
            "blockers": blockers,
            "law": "world counts rise only when the pipeline and the "
                   "generator have earned them",
            "decision_power": "NONE_RESEARCH"}
