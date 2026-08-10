"""STAGE 2 -- the null test rig.

This is the single most important component in the project. If the pipeline
reports positive IC on random scores or on a random walk, there is a lookahead
or survivorship bug and every later result is fiction.

Four families of assertion, and the last two matter as much as the first two:

  NULL         -- on a geometric random walk with no cross-sectional
                  predictability, mean IC and decile spread are indistinguishable
                  from zero.

  CALIBRATION  -- across many independent null worlds the Newey-West t-statistic
                  behaves like a standard normal. "Not significant on one seed"
                  is a much weaker claim than "correctly calibrated across
                  forty", and only the second one rules out a rig whose standard
                  errors are wrong.

  SHUFFLE      -- destroying the score's information destroys the IC. This
                  proves the measured IC is a property of the SCORE and not of
                  the evaluation machinery.

  POSITIVE     -- a known injected signal is recovered, and recovery scales with
  CONTROL         the injected size. Without this, every null assertion above is
                  equally satisfied by a pipeline that is simply dead.

Thresholds are self-calibrating wherever possible: the grand-mean test uses the
observed dispersion across seeds rather than a hardcoded band, so the suite
cannot be turned green by quietly widening a constant.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.evaluate.ic import evaluate_ic
from apex.evaluate.reference import ConsistencyVerdict, autocorrelation, consistency
from tests.conftest import null_ic_series, null_sweep, reference_for

# Assertions that cannot run until a real vendor is wired in (Stage 4). Declared
# here, reported by pytest's `-ra` summary on every run, and never silently
# absent.
DEFERRED_UNTIL_REAL_DATA = [
    "shuffled APEX Score produces IC ~ 0 on REAL data (kickoff Stage 2, item 3)",
]


# ---------------------------------------------------------------------------
# NULL
# ---------------------------------------------------------------------------


def test_random_walk_ic_is_not_significant(null_run, config):
    """A random walk must not clear the protocol's own H1 threshold."""
    _, evaluation = null_run
    limit = float(config.get("null_rig.single_panel_max_abs_t"))
    t_stat = evaluation.ic_daily.t_stat

    assert np.isfinite(t_stat), "IC t-statistic did not compute on the null panel"
    assert abs(t_stat) < limit, (
        f"a geometric random walk produced |t| = {abs(t_stat):.2f} >= {limit}, "
        f"which would PASS H1. mean IC = {evaluation.ic_daily.mean:.5f} over "
        f"{evaluation.ic_daily.n_periods} dates. This is a lookahead or "
        f"survivorship bug, not a discovery."
    )


def test_random_walk_decile_spread_is_not_significant(null_run, config):
    _, evaluation = null_run
    limit = float(config.get("null_rig.single_panel_max_abs_spread_t"))
    t_stat = evaluation.deciles.spread_t_stat

    assert np.isfinite(t_stat)
    assert abs(t_stat) < limit, (
        f"null decile spread |t| = {abs(t_stat):.2f} >= {limit} "
        f"({evaluation.deciles.spread_annualised_gross:.2%} annualised over "
        f"{evaluation.deciles.n_periods} periods)"
    )


def test_null_panel_produces_a_real_cross_section(null_run, config):
    """Guards the guard: the null tests above are vacuous on an empty universe."""
    output, evaluation = null_run
    minimum = int(config.get("evaluation.min_names_for_ic"))

    assert evaluation.ic_daily.n_periods > 100, (
        f"only {evaluation.ic_daily.n_periods} scored dates -- the null "
        f"assertions would pass trivially on a near-empty panel"
    )
    assert evaluation.ic_daily.n_names_mean > minimum, (
        f"mean cross-section of {evaluation.ic_daily.n_names_mean:.1f} names is "
        f"at or below the {minimum}-name floor"
    )
    log = output.per_date_log()
    assert (log["top_decile"] > 0).any() and (log["bottom_decile"] > 0).any()


# ---------------------------------------------------------------------------
# CALIBRATION
# ---------------------------------------------------------------------------


def _assert_grand_mean_is_zero(sweep: pd.DataFrame, config) -> None:
    """UNCHANGED from the original rig. This is the contamination detector.

    A lookahead or survivorship bug shows up as a systematically positive mean
    IC across independent null worlds. Self-calibrating: the threshold uses the
    observed dispersion across seeds, so it cannot be loosened by widening a
    constant.
    """
    z_threshold = float(config.get("null_rig.z_threshold"))
    n = len(sweep)

    mean_ic = sweep["mean_ic"].mean()
    standard_error = sweep["mean_ic"].std(ddof=1) / np.sqrt(n)
    assert abs(mean_ic) < z_threshold * standard_error, (
        f"grand mean IC {mean_ic:+.5f} is {abs(mean_ic) / standard_error:.1f} "
        f"standard errors from zero across {n} independent null worlds "
        f"(se = {standard_error:.5f}). A random walk has no cross-sectional "
        f"information; a systematic offset is a pipeline bug."
    )


def _assert_matches_null_reference(sweep: pd.DataFrame, config) -> ConsistencyVerdict:
    """Compare the pipeline's t-distribution against the analytic null reference.

    NOT against a nominal 5%. The pre-registered Bartlett-25 estimator is
    over-dispersed by construction on overlapping 20-day windows, so ~5% was
    never the right expectation and the old gate failed for a reason that had
    nothing to do with APEX. See apex/evaluate/reference.py.

    The reference is built from the null MODEL and never from pipeline output,
    and the comparison is two-sided, so this is a stricter gate than the ceiling
    it replaces -- it now also fails a pipeline whose t-statistics are too tight.
    """
    n_obs = int(sweep["n_periods"].median())
    reference = reference_for(config, n_obs)

    verdict = consistency(
        sweep["t_stat"].to_numpy(),
        reference,
        z_threshold=float(config.get("null_rig.consistency_z_threshold")),
        min_power=float(config.get("null_rig.consistency_min_power")),
    )
    assert verdict.consistent, (
        "the pipeline's null t-statistics do not match the reference "
        "distribution for its own estimator:\n" + verdict.explain()
    )
    return verdict


def test_null_ic_series_has_the_autocorrelation_the_overlap_implies(config):
    """Validates the reference model before anything is judged against it.

    Overlapping 20-day forward windows make the daily IC series an MA(19), whose
    autocorrelation must decay to ~0 by lag 20. If it does not, either the
    forward-return window is not what the protocol specifies, or something is
    leaking across dates -- and the reference comparison below would be void.
    """
    series = null_ic_series(config).to_numpy()
    overlap = int(config.get("horizon.forward_trading_days"))
    reference = reference_for(config, series.size)

    acf = autocorrelation(series, 2 * overlap)

    assert acf[1] > 0.8, (
        f"IC autocorrelation at lag 1 is {acf[1]:+.3f}; overlapping "
        f"{overlap}-day windows share {overlap - 1}/{overlap} of their days and "
        f"must be strongly autocorrelated. A low value means the forward window "
        f"is not overlapping the way protocol section 4 specifies."
    )
    assert abs(acf[overlap]) < 0.2, (
        f"IC autocorrelation at lag {overlap} is {acf[overlap]:+.3f}, but two IC "
        f"observations {overlap} days apart share NO forward days and must be "
        f"uncorrelated under the null. Non-zero here means information is "
        f"crossing between non-overlapping windows."
    )
    assert reference.describes_autocorrelation_of(series), (
        "the MA(overlap) null model does not describe this IC series, so the "
        "reference distribution is not a valid yardstick for it"
    )


def test_newey_west_matches_its_null_reference_fast(config):
    """Runs on every build. Catches gross breakage; see the full sweep for power."""
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds_fast")))
    _assert_grand_mean_is_zero(sweep, config)
    _assert_matches_null_reference(sweep, config)


@pytest.mark.slow
def test_newey_west_matches_its_null_reference_full(config):
    """The merge gate. Unlike the fast sweep, this one must be adequately powered."""
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds")))
    _assert_grand_mean_is_zero(sweep, config)
    verdict = _assert_matches_null_reference(sweep, config)

    assert not verdict.underpowered, (
        f"the merge gate is underpowered and therefore not a gate:\n{verdict.explain()}\n"
        f"raise null_rig.n_seeds until it can detect a unit shift."
    )


def test_the_fast_sweep_declares_itself_underpowered(config):
    """A green fast build must not be mistaken for evidence of correctness.

    Eight seeds cannot distinguish a correctly-sized pipeline from a badly broken
    one. That is an acceptable trade for build speed only while the limitation is
    explicit, so it is asserted rather than left in a comment.
    """
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds_fast")))
    n_obs = int(sweep["n_periods"].median())
    verdict = consistency(
        sweep["t_stat"].to_numpy(),
        reference_for(config, n_obs),
        z_threshold=float(config.get("null_rig.consistency_z_threshold")),
        min_power=float(config.get("null_rig.consistency_min_power")),
    )

    assert verdict.underpowered, (
        "the fast sweep is now adequately powered, which is good news -- but this "
        "assertion encoded the opposite. Delete it and rely on the full sweep's "
        "power check instead of leaving a stale claim in the suite."
    )


@pytest.mark.slow
def test_null_decile_spread_is_centred_on_zero(config):
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds")))
    n = len(sweep)
    mean_spread = sweep["spread_annual"].mean()
    standard_error = sweep["spread_annual"].std(ddof=1) / np.sqrt(n)
    z_threshold = float(config.get("null_rig.z_threshold"))

    assert abs(mean_spread) < z_threshold * standard_error, (
        f"mean annualised decile spread {mean_spread:+.2%} across {n} null "
        f"worlds is {abs(mean_spread) / standard_error:.1f} standard errors "
        f"from zero (se = {standard_error:.2%})"
    )


# ---------------------------------------------------------------------------
# SHUFFLE
# ---------------------------------------------------------------------------


def test_shuffled_score_destroys_ic(run_factory, config):
    """Shuffling the score within each date must collapse a real IC to zero.

    Run against a panel with an INJECTED signal, so there is a large genuine IC
    to destroy. Shuffling a null panel's score would prove nothing -- it would
    move an IC of zero to an IC of zero.
    """
    alpha = float(config.get("positive_control.alpha_levels")[-1])
    output, evaluation = run_factory(11, alpha)

    assert evaluation.ic_daily.t_stat > 5.0, (
        "the shuffle test needs a genuine signal to destroy; the injected "
        f"control only reached t = {evaluation.ic_daily.t_stat:.2f}"
    )

    scores = output.scores.apex_score
    rng = np.random.default_rng(int(config.get("determinism.seed")))
    values = scores.to_numpy(copy=True)
    for row in range(values.shape[0]):
        present = np.flatnonzero(np.isfinite(values[row]))
        if present.size > 1:
            values[row, present] = values[row, rng.permutation(present)]
    shuffled = pd.DataFrame(values, index=scores.index, columns=scores.columns)

    period = config.period("in_sample")
    dates = output.calendar.daily_formation_dates(period["start"], config.get("null_rig.end"))
    result = evaluate_ic(
        shuffled,
        output.forward_returns.excess,
        output.universe.eligible,
        config,
        dates,
        "daily_newey_west",
    )

    limit = float(config.get("null_rig.single_panel_max_abs_t"))
    assert abs(result.t_stat) < limit, (
        f"shuffling the APEX Score left |t| = {abs(result.t_stat):.2f} "
        f"(mean IC {result.mean:+.5f}). The measured IC is not coming from the "
        f"score, so the evaluation is reading something it should not see."
    )
    assert abs(result.mean) < abs(evaluation.ic_daily.mean) / 4.0


@pytest.mark.skip(reason=f"DEFERRED until a real vendor is wired (Stage 4): {DEFERRED_UNTIL_REAL_DATA[0]}")
def test_shuffled_score_on_real_data():
    """Kickoff Stage 2, item 3. Cannot run before Stage 4 supplies real prices.

    Present and skipped rather than absent: pytest is configured with `-ra`, so
    this appears in the summary of every single run. An assertion that quietly
    does not exist is the one that never gets written.
    """
    raise AssertionError("no real-data source is wired yet")


def test_deferred_assertions_are_declared():
    assert DEFERRED_UNTIL_REAL_DATA, "the deferred-assertion register must not be emptied silently"


# ---------------------------------------------------------------------------
# POSITIVE CONTROL
# ---------------------------------------------------------------------------


def test_positive_control_is_recovered_and_scales(run_factory, config):
    """A dead pipeline passes every null test. This is what separates them.

    Asserts three things: the null level is not significant, a real effect IS
    detected, and detection increases monotonically with the injected size.
    """
    alphas = [float(a) for a in config.get("positive_control.alpha_levels")]
    results = [run_factory(7, alpha)[1] for alpha in alphas]

    ics = [r.ic_daily.mean for r in results]
    t_stats = [r.ic_daily.t_stat for r in results]

    assert abs(t_stats[0]) < float(config.get("null_rig.single_panel_max_abs_t")), (
        f"alpha = 0 is the null case and produced |t| = {abs(t_stats[0]):.2f}"
    )
    assert t_stats[-1] > 5.0, (
        f"injected momentum at alpha = {alphas[-1]} was NOT recovered "
        f"(t = {t_stats[-1]:.2f}, IC = {ics[-1]:+.4f}). The pipeline is not "
        f"measuring what it claims to measure -- and would still have passed "
        f"every null assertion above."
    )
    assert ics == sorted(ics), (
        f"IC did not increase monotonically with injected signal size: "
        f"{[round(v, 4) for v in ics]} for alphas {alphas}"
    )
    assert results[-1].deciles.monotonic_top_over_bottom
    assert results[-1].deciles.spread_annualised_gross > results[0].deciles.spread_annualised_gross
