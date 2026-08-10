"""Experiment validity and programme inference must not contaminate each other.

Ruling, 2026-08-09: "We separate experiment validity (protocol) and
programme-level inference (ledger)." And: "Do not retroactively tighten the
threshold."

The load-bearing test in this file is `test_the_verdict_cannot_see_the_reference`.
It asserts by SIGNATURE that the pre-registered decision function has no access
to the simulated null reference, to the ledger, or to any alpha. The separation
is then structural rather than a matter of the author's care: a future edit that
lets post-registration knowledge influence a pre-registered verdict breaks a
test rather than passing review.
"""

from __future__ import annotations

import inspect

import pytest

from apex.evaluate.reference import simulate_null_tstats
from apex.evaluate.verdict import (
    FAIL,
    INCONCLUSIVE,
    PASS,
    experiment_verdict,
    full_report,
    interpret,
)

# Protocol section 10, as pre-registered.
THRESHOLDS = {"min_mean_ic": 0.015, "min_t_stat": 2.5, "min_robustness_t": 2.0}


@pytest.fixture(scope="module")
def reference():
    return simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=4000, seed=20260809
    )


# ---------------------------------------------------------------------------
# THE SEPARATION
# ---------------------------------------------------------------------------


def test_the_verdict_cannot_see_the_reference():
    """The pre-registered decision takes no post-registration input.

    Not "does not use" -- CANNOT use. If a reference, a ledger or an alpha ever
    appears in this signature, a verdict could be influenced by something learned
    after the pre-registration was frozen, which is the exact failure the
    protocol's amendment rules exist to prevent.
    """
    parameters = set(inspect.signature(experiment_verdict).parameters)

    for forbidden in ("reference", "ledger", "alpha", "family_alpha", "budget", "n_tests"):
        assert forbidden not in parameters, (
            f"experiment_verdict accepts '{forbidden}', so a pre-registered "
            f"verdict could be changed by post-registration knowledge"
        )
    assert parameters == {
        "mean_ic",
        "t_stat",
        "robustness_t",
        "min_mean_ic",
        "min_t_stat",
        "min_robustness_t",
    }


def test_the_verdict_module_does_not_import_the_ledger():
    """Programme-level state must not be reachable from the decision layer."""
    import apex.evaluate.verdict as module

    source = inspect.getsource(module)
    assert "from apex.governance" not in source
    assert "import apex.governance" not in source


def test_the_three_levels_stay_in_separate_objects(reference):
    verdict = experiment_verdict(
        mean_ic=0.02, t_stat=2.7, robustness_t=2.3, **THRESHOLDS
    )
    report = full_report(
        verdict, interpret(2.7, 2.5, reference), {"credits_spent": 1, "budget": 5}
    )

    assert set(report) == {
        "experiment_validity",
        "interpretation",
        "programme_inference",
        "reading_order",
    }
    # Each level must state its own authority unambiguously: exactly one of the
    # three decides promotion, and the other two must disclaim it.
    assert "determines promotion" in report["experiment_validity"]["authority"].lower()
    assert "does not determine promotion" in report["interpretation"]["authority"].lower()
    assert "does not alter" in report["programme_inference"]["authority"].lower()


# ---------------------------------------------------------------------------
# LEVEL 1 -- PROTOCOL SECTION 10, EXACTLY AS WRITTEN
# ---------------------------------------------------------------------------


def test_a_clean_pass():
    verdict = experiment_verdict(mean_ic=0.02, t_stat=2.7, robustness_t=2.3, **THRESHOLDS)

    assert verdict.verdict == PASS
    assert not verdict.failures


def test_a_result_exactly_on_the_pre_registered_hurdle_passes():
    """It must NOT be retroactively tightened to the family-wise threshold.

    t = 2.5 clears section 10. That the family-wise-corrected bar would be ~2.8
    is reported at level 3 and changes nothing here.
    """
    verdict = experiment_verdict(mean_ic=0.015, t_stat=2.5, robustness_t=2.0, **THRESHOLDS)

    assert verdict.verdict == PASS


def test_a_negative_ic_is_a_failure_not_a_reversal_signal():
    """Section 2: direction is specified in advance."""
    verdict = experiment_verdict(mean_ic=-0.03, t_stat=-4.0, robustness_t=-3.5, **THRESHOLDS)

    assert verdict.verdict == FAIL


def test_the_right_sign_but_weak_significance_is_inconclusive():
    verdict = experiment_verdict(mean_ic=0.016, t_stat=1.8, robustness_t=1.2, **THRESHOLDS)

    assert verdict.verdict == INCONCLUSIVE
    assert any("Newey-West" in f for f in verdict.failures)


def test_disagreeing_tests_are_inconclusive_however_strong_the_primary():
    """Section 7: 'If they disagree in sign... the experiment is inconclusive.'"""
    verdict = experiment_verdict(mean_ic=0.04, t_stat=6.0, robustness_t=-2.4, **THRESHOLDS)

    assert verdict.verdict == INCONCLUSIVE
    assert any("disagree in sign" in f for f in verdict.failures)


def test_an_ic_below_threshold_but_positive_is_inconclusive_not_failed():
    verdict = experiment_verdict(mean_ic=0.004, t_stat=2.6, robustness_t=2.1, **THRESHOLDS)

    assert verdict.verdict == INCONCLUSIVE


# ---------------------------------------------------------------------------
# LEVEL 2 -- INTERPRETATION
# ---------------------------------------------------------------------------


def test_interpretation_reports_both_nominal_and_measured_size(reference):
    payload = interpret(2.7, 2.5, reference).as_dict()

    assert payload["nominal_one_sided_size_at_threshold"] == pytest.approx(0.00621, abs=1e-4)
    assert payload["measured_one_sided_size_at_threshold"] > 0.012
    assert "not amended" in payload["authority"]


def test_interpretation_states_the_t_that_would_have_given_the_nominal_size(reference):
    """The honest translation: 'to be as significant as 2.5 sounds, you needed X'."""
    payload = interpret(2.7, 2.5, reference).as_dict()

    assert payload["tstat_that_would_give_the_nominal_size"] > 2.5


def test_a_stronger_result_sits_higher_in_the_null_distribution(reference):
    weak = interpret(2.0, 2.5, reference)
    strong = interpret(4.0, 2.5, reference)

    assert strong.implied_percentile > weak.implied_percentile


def test_interpretation_never_returns_a_verdict(reference):
    """It informs; it does not decide."""
    payload = interpret(2.7, 2.5, reference).as_dict()

    assert "verdict" not in payload
    for value in payload.values():
        assert value not in (PASS, FAIL, INCONCLUSIVE)
