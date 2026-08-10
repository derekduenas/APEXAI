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
from tests.conftest import null_sweep

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


def _assert_calibrated(sweep: pd.DataFrame, config) -> None:
    z_threshold = float(config.get("null_rig.z_threshold"))
    max_dispersion = float(config.get("null_rig.max_tstat_dispersion"))
    max_rejection = float(config.get("null_rig.max_rejection_rate"))

    n = len(sweep)
    mean_ic = sweep["mean_ic"].mean()
    standard_error = sweep["mean_ic"].std(ddof=1) / np.sqrt(n)

    assert abs(mean_ic) < z_threshold * standard_error, (
        f"grand mean IC {mean_ic:+.5f} is {abs(mean_ic) / standard_error:.1f} "
        f"standard errors from zero across {n} independent null worlds "
        f"(se = {standard_error:.5f}). A random walk has no cross-sectional "
        f"information; a systematic offset is a pipeline bug."
    )

    mean_t = sweep["t_stat"].mean()
    assert abs(mean_t) * np.sqrt(n) < z_threshold, (
        f"mean Newey-West t-statistic {mean_t:+.3f} across {n} null worlds is "
        f"{abs(mean_t) * np.sqrt(n):.1f} standard errors from zero"
    )

    dispersion = sweep["t_stat"].std(ddof=1)
    assert dispersion < max_dispersion, (
        f"t-statistics have standard deviation {dispersion:.2f}, not ~1.0. "
        f"Over-dispersion means the Newey-West lag-{config.get('evaluation.newey_west_lag')} "
        f"correction is under-correcting for the overlapping 20-day windows, so "
        f"every significance figure this pipeline reports is overstated."
    )

    rejection_rate = float((sweep["t_stat"].abs() > 1.96).mean())
    assert rejection_rate <= max_rejection, (
        f"{rejection_rate:.0%} of null worlds rejected at |t| > 1.96 against ~5% "
        f"expected. The test is not correctly sized."
    )


def test_newey_west_is_calibrated_fast(config):
    """Runs on every build. The full sweep below runs before every merge."""
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds_fast")))
    _assert_calibrated(sweep, config)


@pytest.mark.slow
def test_newey_west_is_calibrated_full(config):
    sweep = null_sweep(config, int(config.get("null_rig.n_seeds")))
    _assert_calibrated(sweep, config)


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
