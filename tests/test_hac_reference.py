"""The analytic null reference for the IC t-statistic.

Stage 2's calibration gate previously asserted that the pipeline's Newey-West
t-statistics reject at ~5% on null worlds. That expectation was wrong, and the
gate was failing for a reason that had nothing to do with APEX: a Bartlett-kernel
HAC estimator at lag 25 is DOWNWARD BIASED on the MA(19) autocovariance induced
by overlapping 20-day forward windows. The Bartlett weight at lag 19 is only
1 - 19/26 = 0.27, so roughly three quarters of the autocovariance that matters is
discarded.

The protocol pre-registers lag 25 and is NOT amended (user ruling, 2026-08-09).
Instead the gate is corrected: the pipeline's t-distribution is compared against
a reference distribution simulated from an independent analytic model of the null
process, for the SAME estimator, lag, kernel and sample length.

This is not the same move as widening a constant until the suite goes green:

  * the reference is derived from a model of the null process, never from
    observed pipeline output, so it cannot be tuned to whatever APEX happens
    to produce;
  * the resulting gate is TWO-SIDED -- the pipeline now also fails for being
    under-dispersed, which the old one-sided ceiling could never catch;
  * the grand-mean-IC assertion is untouched, and it remains the test that
    detects lookahead and survivorship contamination.
"""

from __future__ import annotations

import numpy as np
import pytest

from apex.evaluate.reference import (
    NullReference,
    consistency,
    hac_tstat,
    simulate_null_tstats,
)

# Modest replication count keeps the suite fast; the assertions below are all
# sized to be comfortably resolvable at this count.
REPS = 4000
SEED = 20260809


# ---------------------------------------------------------------------------
# the estimator itself
# ---------------------------------------------------------------------------


def test_hac_tstat_with_no_lag_is_the_ordinary_t_statistic():
    """lag 0 reduces the HAC variance to the plain sample variance."""
    rng = np.random.default_rng(0)
    x = rng.standard_normal(500)

    hac = hac_tstat(x, lag=0, kernel="bartlett")
    ordinary = x.mean() / np.sqrt(x.var(ddof=0) / x.size)

    assert hac == pytest.approx(ordinary, rel=1e-12)


def test_hac_tstat_matches_the_pipeline_estimator():
    """The reference must use the SAME estimator apex.evaluate.ic reports.

    A reference built on a subtly different estimator would compare the pipeline
    against the wrong yardstick and quietly excuse a real defect.
    """
    import pandas as pd

    from apex.evaluate.ic import newey_west_tstat

    rng = np.random.default_rng(7)
    x = np.convolve(rng.standard_normal(619), np.ones(20) / 20, mode="valid")

    mine = hac_tstat(x, lag=25, kernel="bartlett")
    theirs, _ = newey_west_tstat(pd.Series(x), lag=25)

    assert mine == pytest.approx(theirs, abs=0.01)


# ---------------------------------------------------------------------------
# the reference distribution
# ---------------------------------------------------------------------------


def test_non_overlapping_windows_give_a_standard_normal_reference():
    """Sanity on the machinery: with no overlap and no lag there is no bias.

    If this drifts from ~1.0 the simulator is broken, and every other number
    this module produces is meaningless.
    """
    ref = simulate_null_tstats(
        n_obs=1000, overlap=1, lag=0, kernel="bartlett", n_replications=REPS, seed=SEED
    )

    assert ref.sd == pytest.approx(1.0, abs=0.05)
    assert ref.rejection_rate(1.96) == pytest.approx(0.05, abs=0.015)


def test_overlapping_windows_make_bartlett_lag25_over_reject():
    """The documented defect, stated as an assertion rather than a comment.

    This is the number that makes the old '~5% expected' gate wrong.
    """
    ref = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )

    assert ref.sd > 1.15, (
        f"expected the Bartlett-25 estimator to be over-dispersed on overlapping "
        f"20-day windows; got sd(t) = {ref.sd:.3f}"
    )
    assert ref.rejection_rate(1.96) > 0.08


def test_truncating_at_the_true_ma_order_is_better_calibrated():
    """Confirms the diagnosis: the bias is the kernel's downweighting, not the lag.

    A truncated kernel at the true MA order keeps full weight on every
    autocovariance that is actually non-zero, and is close to correctly sized.
    """
    bartlett = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    truncated = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=19, kernel="truncated", n_replications=REPS, seed=SEED
    )

    assert truncated.sd < bartlett.sd
    assert truncated.rejection_rate(1.96) < bartlett.rejection_rate(1.96)


def test_the_bias_does_not_vanish_at_holdout_sample_length():
    """Rules out 'it is only a small-sample artifact of the compact null rig'.

    If the bias disappeared by ~1,100 observations it would not affect the real
    experiment and would need no disclosure. It does not disappear.
    """
    rig = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    holdout = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )

    assert holdout.rejection_rate(1.96) > 0.08, (
        "the HAC bias must still be present at holdout sample length, or the "
        "disclosure attached to every result is overstating the problem"
    )
    assert holdout.sd < rig.sd, "the bias should shrink with T, even if it does not vanish"


def test_reference_is_deterministic_given_its_seed():
    """Protocol section 31: a result that cannot be reproduced does not count."""
    first = simulate_null_tstats(
        n_obs=400, overlap=20, lag=25, kernel="bartlett", n_replications=500, seed=99
    )
    second = simulate_null_tstats(
        n_obs=400, overlap=20, lag=25, kernel="bartlett", n_replications=500, seed=99
    )

    assert np.array_equal(first.t_stats, second.t_stats)
    assert first.digest == second.digest


# ---------------------------------------------------------------------------
# the disclosure number
# ---------------------------------------------------------------------------


def test_preregistered_threshold_is_looser_than_it_reads():
    """Quantifies what t >= 2.5 actually buys, for the results header.

    Nominal one-sided size at t = 2.5 is 0.621%. The measured size is several
    times that. This number is DISCLOSED with every result rather than being
    corrected away, per the user ruling of 2026-08-09.
    """
    ref = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )

    size = ref.one_sided_size(2.5)

    assert size > 0.0124, (
        f"measured one-sided size {size:.3%} at t >= 2.5 is not materially above "
        f"the 0.621% nominal figure; the disclosure would be unnecessary"
    )
    assert size < 0.05, (
        f"measured one-sided size {size:.3%} would mean the pre-registered "
        f"threshold is no more stringent than a conventional 5% test, which "
        f"would be a reason to reopen the ruling not to disclose"
    )


def test_family_wise_error_over_the_research_budget_is_reported():
    """Section 4/5: five holdout credits multiply the per-test size.

    The ledger applies a Holm correction, but the UNCORRECTED family-wise rate
    is what makes the correction necessary, so the reference can state it.
    """
    ref = simulate_null_tstats(
        n_obs=1133, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )

    single = ref.one_sided_size(2.5)
    family = ref.family_wise_size(2.5, n_tests=5)

    assert family > single
    assert family == pytest.approx(1.0 - (1.0 - single) ** 5, rel=1e-12)


# ---------------------------------------------------------------------------
# the gate: does it actually detect a broken pipeline?
# ---------------------------------------------------------------------------


def test_sample_drawn_from_the_reference_is_judged_consistent():
    ref = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    rng = np.random.default_rng(4)
    observed = rng.choice(ref.t_stats, size=40, replace=False)

    verdict = consistency(observed, ref)

    assert verdict.consistent, verdict.explain()


def test_inflated_tstats_are_caught():
    """A lookahead bug inflates the t-statistics. The gate must fail on that."""
    ref = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    rng = np.random.default_rng(4)
    observed = rng.choice(ref.t_stats, size=40, replace=False) + 2.0

    verdict = consistency(observed, ref)

    assert not verdict.consistent
    assert "shifted" in verdict.explain() or "location" in verdict.explain()


def test_under_dispersed_tstats_are_caught():
    """The old one-sided ceiling could not see this failure mode at all.

    A pipeline whose cross-section is collapsing, or whose IC series is being
    averaged over too few names, produces t-statistics that are too TIGHT. That
    is just as much a defect as over-rejection.
    """
    ref = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    rng = np.random.default_rng(4)
    observed = rng.choice(ref.t_stats, size=40, replace=False) * 0.2

    verdict = consistency(observed, ref)

    assert not verdict.consistent
    assert "dispersion" in verdict.explain()


def test_verdict_reports_its_own_power():
    """An under-powered gate must say so rather than passing quietly.

    Eight seeds cannot distinguish a correctly-sized test from a badly broken
    one. The verdict carries that fact so a green result on a small sweep is not
    mistaken for evidence.
    """
    ref = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=REPS, seed=SEED
    )
    rng = np.random.default_rng(4)

    weak = consistency(rng.choice(ref.t_stats, size=8, replace=False), ref)
    strong = consistency(rng.choice(ref.t_stats, size=400, replace=True), ref)

    assert weak.power_to_detect_unit_shift < strong.power_to_detect_unit_shift
    assert weak.underpowered
    assert not strong.underpowered


def test_reference_rejects_an_ic_series_whose_autocorrelation_is_wrong():
    """The reference is only valid if the real IC series really is MA(overlap).

    This turns 'the pipeline matches the reference' into a genuine claim about
    the pipeline: if APEX's IC autocorrelation does not decay to zero by the
    overlap horizon, the analytic model does not describe it and the comparison
    is void.
    """
    ref = simulate_null_tstats(
        n_obs=606, overlap=20, lag=25, kernel="bartlett", n_replications=200, seed=SEED
    )

    rng = np.random.default_rng(1)
    good = np.convolve(rng.standard_normal(625), np.ones(20) / 20, mode="valid")
    assert ref.describes_autocorrelation_of(good)

    # An AR(1) with long memory has autocorrelation well past the overlap.
    bad = np.zeros(606)
    noise = rng.standard_normal(606)
    for i in range(1, 606):
        bad[i] = 0.99 * bad[i - 1] + noise[i]
    assert not ref.describes_autocorrelation_of(bad)


def test_null_reference_is_a_frozen_value_object():
    ref = simulate_null_tstats(
        n_obs=200, overlap=20, lag=25, kernel="bartlett", n_replications=100, seed=1
    )
    assert isinstance(ref, NullReference)
    with pytest.raises(Exception):
        ref.n_obs = 5  # type: ignore[misc]
