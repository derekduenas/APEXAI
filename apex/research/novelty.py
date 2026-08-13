"""Novelty and combination control (Parts 5 and 6).

NOVELTY IS A CLASSIFICATION, NOT A SCORE (Part 6)
-------------------------------------------------
Before a hypothesis reaches the screen it is compared against the feature
library, the closed experiments, and every prior dossier -- surviving and
rejected. The result is one of NOVEL / RECOMBINATION / REDUNDANT / MODIFICATION
/ DUPLICATE. There is no "novelty score"; a number would invite ranking, and
ranking hypotheses by anything computed here is how the multiple-comparisons
problem migrates into the free layer.

A RECOMBINATION IS NOT DISQUALIFIED (Part 5)
--------------------------------------------
Combining independent feature families is the entire point of the library. But
a combination must carry an ECONOMIC reason for the features belonging
together -- not "they had the highest IC", which this layer cannot compute and
must never learn. `CombinationProposal` therefore requires a prose rationale
and refuses to exist without one, and the engine proposes only the bounded,
named combination classes below. It does not search.
"""

from __future__ import annotations

from dataclasses import dataclass

from apex.research.hypothesis import (
    DUPLICATE,
    MODIFICATION,
    NOVEL,
    RECOMBINATION,
    REDUNDANT,
    HypothesisDossier,
    HypothesisError,
)

# The only combination classes the engine may propose. No search space beyond
# these, and each instance must be individually, economically justified.
ADDITIVE = "additive"
MULTIPLICATIVE = "multiplicative"
RANK_COMPOSITE = "rank_composite"
CONDITIONAL = "conditional_interaction"
ORTHOGONALISED = "orthogonalised"
REGIME_CONDITIONED = "regime_conditioned"
COMBINATION_CLASSES = (
    ADDITIVE, MULTIPLICATIVE, RANK_COMPOSITE,
    CONDITIONAL, ORTHOGONALISED, REGIME_CONDITIONED,
)


@dataclass(frozen=True)
class NoveltyAssessment:
    classification: str
    reasons: tuple[str, ...]
    nearest_prior: str = ""     # dossier_hash or experiment id it resembles

    def as_dict(self) -> dict:
        return {
            "classification": self.classification,
            "reasons": list(self.reasons),
            "nearest_prior": self.nearest_prior,
        }


@dataclass(frozen=True)
class CombinationProposal:
    """A bounded, economically justified combination of named features."""

    combination_class: str
    feature_ids: tuple[str, ...]
    economic_reason: str

    def __post_init__(self) -> None:
        if self.combination_class not in COMBINATION_CLASSES:
            raise HypothesisError(
                f"combination_class must be one of {COMBINATION_CLASSES}; got "
                f"{self.combination_class!r}"
            )
        if len(self.feature_ids) < 2:
            raise HypothesisError("a combination needs at least two features")
        if not self.economic_reason.strip():
            raise HypothesisError(
                "a combination must state WHY these features belong together. "
                "'they had the highest IC' is not admissible and is not "
                "computable here."
            )
        # No numeric field exists on this object: there is nowhere to put a
        # score, a weight sweep, or an IC. Part 5 is structural.


def classify_novelty(
    hypothesis: HypothesisDossier,
    *,
    known_feature_ids: set[str],
    experiment_signatures: dict[str, set[str]],
    prior_dossiers: dict[str, set[str]],
) -> NoveltyAssessment:
    """Classify a hypothesis against everything already on record.

    `experiment_signatures` maps experiment id -> the feature_ids it used
    (APEX-001 its price block, APEX-002 {nsi}). `prior_dossiers` maps
    dossier_hash -> feature_id set for every previously assembled hypothesis,
    surviving OR rejected -- the file-drawer denominator matters here too.
    """
    fs = set(hypothesis.feature_set)

    unknown = fs - known_feature_ids
    if unknown:
        return NoveltyAssessment(
            classification=REDUNDANT,
            reasons=(f"names feature_ids not in the registry: {sorted(unknown)}; "
                     f"a hypothesis over undefined features cannot be assessed",),
        )

    # DUPLICATE: identical feature set to a prior dossier.
    for h, prior_fs in prior_dossiers.items():
        if prior_fs == fs and h != hypothesis.dossier_hash:
            return NoveltyAssessment(
                classification=DUPLICATE,
                reasons=("identical feature set to a prior dossier",),
                nearest_prior=h,
            )

    # MODIFICATION: same feature set as a closed experiment.
    for exp, sig in experiment_signatures.items():
        if sig == fs:
            return NoveltyAssessment(
                classification=MODIFICATION,
                reasons=(f"same feature set as {exp}; a re-parameterisation of a "
                         f"closed experiment is a modification, not a new idea",),
                nearest_prior=exp,
            )

    # REDUNDANT: a strict subset of a single closed experiment's features.
    for exp, sig in experiment_signatures.items():
        if fs and fs < sig:
            return NoveltyAssessment(
                classification=REDUNDANT,
                reasons=(f"feature set is a subset of {exp}'s inputs",),
                nearest_prior=exp,
            )

    # RECOMBINATION: draws on features from more than one prior mechanism.
    touched = [exp for exp, sig in experiment_signatures.items() if fs & sig]
    if len(fs) > 1 and touched:
        return NoveltyAssessment(
            classification=RECOMBINATION,
            reasons=(f"combines features overlapping prior work {sorted(touched)} "
                     f"with others; must carry an economic reason to combine",),
            nearest_prior=touched[0],
        )

    return NoveltyAssessment(
        classification=NOVEL,
        reasons=("no prior experiment or dossier uses this feature set",),
    )
