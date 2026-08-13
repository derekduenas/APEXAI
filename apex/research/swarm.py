"""The research swarm: roles with distinct epistemic jobs (Parts 2 and 8).

WHAT THE SWARM IS
-----------------
A protocol for assembling a research dossier from several roles that reason
DIFFERENTLY -- a theorist starts from a mechanism, an adversary tries to kill
it, a replication role asks whether it is really new. It is not ten agents
running the same correlation. The roles here are STRUCTURAL: each is a function
of the epistemic contract below, and the assembly preserves what they disagree
about rather than averaging it away.

WHAT THE SWARM MAY NOT DO
-------------------------
No role may register an experiment, spend a credit, reach the holdout, alter
APEX criteria or the protocol, or silently modify a hypothesis. The swarm's
only output is a `ResearchDossier` -- a record, not an experiment. There is no
numeric alpha score, no IC, no expected-return ranking anywhere in this module;
`RoleView` cannot express one.

DISAGREEMENT IS PRESERVED (Part 8)
----------------------------------
`assemble` does not resolve conflicting role views into a consensus. It records
every view, flags where the adversary's objections are unrebutted, and lets the
human gate see the disagreement. A swarm that manufactured agreement would be
hiding exactly the information a human needs to decide whether to spend a
credit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.research.hypothesis import HypothesisDossier
from apex.research.novelty import CombinationProposal, NoveltyAssessment

# The eight epistemic roles. Each has a DIFFERENT question, not a different
# dataset. Named so a reader can see the swarm is not homogeneous.
THEORIST = "economic_theorist"
FUNDAMENTAL = "fundamental_analyst"
MICROSTRUCTURE = "microstructure_analyst"
QUANT = "quantitative_researcher"
ADVERSARY = "adversarial_researcher"
PORTFOLIO = "portfolio_constructor"
REGIME = "regime_researcher"
REPLICATION = "replication_researcher"
ROLES = (THEORIST, FUNDAMENTAL, MICROSTRUCTURE, QUANT,
         ADVERSARY, PORTFOLIO, REGIME, REPLICATION)


class SwarmError(RuntimeError):
    """A swarm boundary was violated."""


@dataclass(frozen=True)
class RoleView:
    """One role's contribution. Prose and a stance -- never a number.

    `supports` is the role's stance on whether the idea is worth a human's
    attention, NOT a probability and NOT a score. `objections` are concrete and
    are preserved verbatim through assembly.
    """

    role: str
    supports: bool
    reasoning: str
    objections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise SwarmError(f"unknown role {self.role!r}; roles are {ROLES}")
        if not self.reasoning.strip():
            raise SwarmError(f"role {self.role} must give reasoning")
        # No `score`, `ic`, `confidence` float: Part 8 is structural.


@dataclass(frozen=True)
class ResearchDossier:
    """The swarm's output. A record for a human, never an experiment."""

    hypothesis: HypothesisDossier
    novelty: NoveltyAssessment
    role_views: tuple[RoleView, ...]
    combinations: tuple[CombinationProposal, ...] = ()

    def adversary_objections(self) -> tuple[str, ...]:
        return tuple(
            obj for v in self.role_views if v.role == ADVERSARY for obj in v.objections
        )

    def unrebutted(self) -> bool:
        """True when the adversary objected and no role explicitly rebuts it.

        Preserved, not resolved: the human gate reads this; the swarm does not
        act on it.
        """
        objs = self.adversary_objections()
        if not objs:
            return False
        rebuttals = " ".join(
            v.reasoning for v in self.role_views if v.role != ADVERSARY
        ).lower()
        return not any(obj.lower()[:20] in rebuttals for obj in objs)

    def dissent(self) -> tuple[str, ...]:
        """Every role that does NOT support, with its reasoning. Part 8."""
        return tuple(
            f"{v.role}: {v.reasoning}" for v in self.role_views if not v.supports
        )

    def as_dict(self) -> dict:
        return {
            "dossier_hash": self.hypothesis.dossier_hash,
            "provenance_hash": self.hypothesis.provenance_hash,
            "economic_mechanism": self.hypothesis.economic_mechanism,
            "feature_set": sorted(self.hypothesis.feature_set),
            "novelty": self.novelty.as_dict(),
            "role_views": [
                {"role": v.role, "supports": v.supports,
                 "reasoning": v.reasoning, "objections": list(v.objections)}
                for v in self.role_views
            ],
            "combinations": [
                {"class": c.combination_class, "features": list(c.feature_ids),
                 "economic_reason": c.economic_reason}
                for c in self.combinations
            ],
            "unrebutted_adversary_objections": self.unrebutted(),
            "dissent": list(self.dissent()),
            "descends_from_failure": self.hypothesis.requires_independent_rejustification(),
        }


def assemble(
    hypothesis: HypothesisDossier,
    novelty: NoveltyAssessment,
    role_views: tuple[RoleView, ...],
    combinations: tuple[CombinationProposal, ...] = (),
) -> ResearchDossier:
    """Assemble a dossier, PRESERVING disagreement (Part 8).

    Requires that the two roles whose whole job is to disconfirm -- the
    adversary and the replication researcher -- actually contributed. A dossier
    assembled without them would be a consensus of enthusiasts.
    """
    present = {v.role for v in role_views}
    for required in (ADVERSARY, REPLICATION):
        if required not in present:
            raise SwarmError(
                f"a dossier cannot be assembled without the {required}: the "
                f"swarm must include the roles whose job is to kill the idea."
            )
    return ResearchDossier(
        hypothesis=hypothesis,
        novelty=novelty,
        role_views=tuple(role_views),
        combinations=tuple(combinations),
    )
