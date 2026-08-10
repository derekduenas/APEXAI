"""Two-level reporting -- experiment validity vs programme-level inference.

    "We separate: experiment validity (protocol) and programme-level inference
     (ledger)."  -- ruling, 2026-08-09

LEVEL 1 -- EXPERIMENT VALIDITY. Decided by protocol section 10 and nothing else.
Mean IC >= 0.015, Newey-West t >= 2.5, robustness agreeing in sign at t >= 2.0,
and the decile criteria. These thresholds are pre-registered, and this layer
reads them from the frozen config. It does NOT consult the simulated null
reference, the research budget, or any other experiment's result. A verdict that
moved because of something learned after registration would not be a
pre-registered verdict.

LEVEL 2 -- INTERPRETATION. The same numbers, read in light of what was measured
about the estimator afterwards: the pre-registered `t >= 2.5` hurdle carries a
true one-sided size of ~1.9% rather than its nominal 0.621%, so a t-statistic
means less than it appears to. Reported alongside, never substituted for.

LEVEL 3 -- PROGRAMME INFERENCE. Family-wise context across the research budget,
owned by the ledger. Five separate pre-registered experiments accumulate error
even though each is individually valid.

WHY THE SEPARATION IS ENFORCED IN CODE

`experiment_verdict` is a pure function of the measured statistics and the
pre-registered thresholds. It takes no reference distribution, no ledger and no
alpha. It therefore CANNOT be influenced by anything discovered after
registration -- not because the author was careful, but because the information
is not in scope. `test_verdict.py` asserts that its signature stays that way.

`interpret` and the ledger's `report` supply the other two levels, and both are
clearly labelled as not determining promotion.
"""

from __future__ import annotations

from dataclasses import dataclass

PASS = "PASS"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ExperimentVerdict:
    """Level 1. Protocol section 10, and nothing else."""

    verdict: str
    mean_ic: float
    t_stat: float
    robustness_t: float
    criteria: dict
    failures: tuple

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "mean_ic": self.mean_ic,
            "t_stat": self.t_stat,
            "robustness_t": self.robustness_t,
            "criteria": self.criteria,
            "failures": list(self.failures),
            "authority": (
                "protocol section 10, pre-registered. THIS DETERMINES PROMOTION. "
                "Decided solely by the frozen thresholds; no post-registration "
                "measurement enters here."
            ),
        }


def experiment_verdict(
    *,
    mean_ic: float,
    t_stat: float,
    robustness_t: float,
    min_mean_ic: float,
    min_t_stat: float,
    min_robustness_t: float,
) -> ExperimentVerdict:
    """Apply protocol section 10 exactly as written.

    Deliberately takes no reference distribution, no ledger, and no alpha. The
    pre-registered decision cannot be a function of anything learned after
    pre-registration, so those inputs are absent rather than merely unused.
    """
    criteria = {
        "mean_ic_at_least": min_mean_ic,
        "t_stat_at_least": min_t_stat,
        "robustness_t_at_least": min_robustness_t,
    }

    # FAIL is reserved for a rejected hypothesis: mean IC at or below zero.
    # Section 2: "A significant negative IC is a failed experiment, not a
    # discovered reversal signal."
    if mean_ic <= 0:
        return ExperimentVerdict(
            verdict=FAIL,
            mean_ic=mean_ic,
            t_stat=t_stat,
            robustness_t=robustness_t,
            criteria=criteria,
            failures=("mean IC is at or below zero; the hypothesis is rejected",),
        )

    failures: list[str] = []
    if mean_ic < min_mean_ic:
        failures.append(f"mean IC {mean_ic:.5f} is below the {min_mean_ic} threshold")
    if t_stat < min_t_stat:
        failures.append(f"Newey-West t {t_stat:.2f} is below the {min_t_stat} threshold")
    if robustness_t < min_robustness_t:
        failures.append(
            f"non-overlapping robustness t {robustness_t:.2f} is below "
            f"{min_robustness_t}"
        )
    # Section 7: disagreement in SIGN between the two tests is inconclusive,
    # regardless of how strong either one looks on its own.
    if (t_stat > 0) != (robustness_t > 0):
        failures.append(
            "the primary and robustness tests disagree in sign, which section 7 "
            "routes to INCONCLUSIVE rather than to a pass"
        )

    return ExperimentVerdict(
        verdict=PASS if not failures else INCONCLUSIVE,
        mean_ic=mean_ic,
        t_stat=t_stat,
        robustness_t=robustness_t,
        criteria=criteria,
        failures=tuple(failures),
    )


@dataclass(frozen=True)
class Interpretation:
    """Level 2. What the pre-registered numbers actually mean, given the estimator."""

    pre_registered_t: float
    pre_registered_threshold: float
    nominal_one_sided_size: float
    measured_one_sided_size: float
    implied_percentile: float
    tstat_for_nominal_size: float

    def as_dict(self) -> dict:
        return {
            "pre_registered_t": round(self.pre_registered_t, 4),
            "pre_registered_threshold": self.pre_registered_threshold,
            "nominal_one_sided_size_at_threshold": round(self.nominal_one_sided_size, 5),
            "measured_one_sided_size_at_threshold": round(self.measured_one_sided_size, 5),
            "observed_t_percentile_under_null": round(self.implied_percentile, 5),
            "tstat_that_would_give_the_nominal_size": round(self.tstat_for_nominal_size, 3),
            "authority": (
                "INTERPRETATION ONLY. Does not determine promotion. The protocol "
                "is not amended (CONVENTIONS A-001); the pre-registered estimator "
                "and threshold stand, and this states what they are worth."
            ),
        }


def interpret(t_stat: float, threshold: float, reference) -> Interpretation:
    """Level 2: read the pre-registered statistic against its measured null.

    `reference` is the simulated null distribution of the SAME estimator at the
    SAME sample length. It appears here, in the reporting layer, and nowhere in
    `experiment_verdict`.
    """
    return Interpretation(
        pre_registered_t=float(t_stat),
        pre_registered_threshold=float(threshold),
        nominal_one_sided_size=reference.nominal_one_sided_size,
        measured_one_sided_size=reference.one_sided_size(threshold),
        implied_percentile=1.0 - reference.one_sided_size(t_stat),
        tstat_for_nominal_size=float(
            reference.quantile(1.0 - reference.nominal_one_sided_size)
        ),
    )


def full_report(verdict: ExperimentVerdict, interpretation: Interpretation, programme: dict) -> dict:
    """All three levels, kept visibly separate.

    The nesting is the point: a reader cannot mistake the interpretation or the
    programme context for the pre-registered decision, because they are not in
    the same object.
    """
    return {
        "experiment_validity": verdict.as_dict(),
        "interpretation": interpretation.as_dict(),
        "programme_inference": {
            **programme,
            "authority": (
                "ledger. Family-wise context across the research budget. Does not "
                "alter any individual experiment's pre-registered verdict."
            ),
        },
        "reading_order": [
            "experiment_validity decides promotion, on pre-registered criteria alone",
            "interpretation says what that t-statistic is actually worth",
            "programme_inference says what it is worth given everything else tested",
        ],
    }
