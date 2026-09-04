"""WORLD_MODEL_RESEARCH_BUDGET_V0 -- truthful search-burden accounting.

THE PROBLEM THIS EXISTS FOR
"Try things until something works" is the most reliable way to produce
a beautiful false result, and it never feels like cheating from the
inside: each attempt was reasonable, each was the first idea at the
time, and the final one is simply the one that got written up. The only
defence is a ledger that remembers what the researcher would rather
forget.

THE ACCOUNTING RULE (defined now, binding on every future brick)
Every research CHOICE is an attempt in a named category. A result may
only be reported alongside the counts of prior attempts in every
category that touched it. Compatibility runs (S2/S3 smoke) are recorded
as OBSERVATIONS, not variants: they were not optimised against and
receive no credit, but they are not erased either -- pretending a run
never happened is exactly the amnesia this ledger prevents.

The budget is IMMUTABLE. Registering an attempt returns a NEW budget
with a new hash; nothing is mutated in place, so a budget's hash is a
truthful statement of everything it has ever counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field

from apex.world_model.canonical import content_hash

BUDGET_VERSION = "WORLD_MODEL_RESEARCH_BUDGET_V0"

CATEGORIES = ("model_family", "hyperparameter_configuration",
              "feature_family_variant", "horizon_variant", "target_variant",
              "sampling_variant", "calibration_variant", "ablation_variant",
              "compatibility_observation")


class BudgetViolation(ValueError):
    pass


@dataclass(frozen=True)
class ResearchBudget:
    attempts: tuple = ()                 # (category, identity, note)

    def register(self, category: str, identity: str, note: str = "") -> "ResearchBudget":
        if category not in CATEGORIES:
            raise BudgetViolation("unknown budget category %r" % category)
        if not identity:
            raise BudgetViolation("an attempt must carry an identity")
        key = (category, identity)
        if any((a[0], a[1]) == key for a in self.attempts):
            raise BudgetViolation(
                "duplicate attempt %s/%s -- a repeated attempt is still an "
                "attempt and must be recorded as such, under a distinct "
                "identity" % key)
        return ResearchBudget(self.attempts + ((category, identity, note),))

    def counts(self) -> dict:
        c = {k: 0 for k in CATEGORIES}
        for cat, _, _ in self.attempts:
            c[cat] += 1
        return c

    def canonical(self) -> dict:
        return {"budget_version": BUDGET_VERSION,
                "attempts": [list(a) for a in self.attempts],
                "counts": self.counts()}

    @property
    def budget_hash(self) -> str:
        return content_hash(self.canonical())

    def burden_statement(self) -> dict:
        """What a future result must carry alongside itself."""
        c = self.counts()
        return {"model_families_considered": c["model_family"],
                "configurations_tried": c["hyperparameter_configuration"],
                "target_horizon_variants": c["horizon_variant"] + c["target_variant"],
                "feature_variants": c["feature_family_variant"],
                "prior_research_attempts": len(self.attempts),
                "compatibility_observations_not_credited":
                    c["compatibility_observation"],
                "budget_hash": self.budget_hash}


def wm0d_truth() -> ResearchBudget:
    """The synthetic research already performed, recorded honestly."""
    b = ResearchBudget()
    b = b.register("model_family", "M0_SYNTHETIC_BASELINE_V0",
                   "ridge lambda=1.0 gaussian; the one informative family")
    b = b.register("model_family", "N_BASELINE_NULL_V0",
                   "unconditional gaussian; the null comparator")
    b = b.register("horizon_variant", "H_15M", "frozen before any result")
    b = b.register("feature_family_variant", "WM0D_OBSERVABLE_FEATURES_V0",
                   "the one frozen observable set")
    b = b.register("compatibility_observation", "S2_smoke_WM0D",
                   "z=+7.71 observed; NOT optimised against; no credit")
    b = b.register("compatibility_observation", "S3_smoke_WM0D",
                   "z=+2.97 observed; NOT optimised against; no credit")
    return b
