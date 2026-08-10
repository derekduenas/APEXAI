"""Feature unit tests against hand-computed values on small fixtures.

Every expected number here was worked out by hand and is written into the test
as an arithmetic expression, not as a constant copied from a previous run. A
golden value captured from the implementation tests only that the code still
does what it did last week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.features.composite import (
    assign_deciles,
    percentile_rank,
    winsorise,
    zscore,
)
from apex.features.f1_momentum import skip_adjusted_return, universe_mean
from apex.features.f2_trend import simple_moving_average
from apex.features.f3_volatility import realised_volatility, true_range, wilder_atr
from apex.features.f4_relative_strength import market_relative, sector_relative
from tests.conftest import tiny_frame


# ---------------------------------------------------------------------------
# F1
# ---------------------------------------------------------------------------


def test_skip_adjusted_return_uses_the_right_two_endpoints():
    """window=3, skip=2 at t must read close[t-2] and close[t-5]."""
    closes = tiny_frame(np.arange(10.0, 20.0).reshape(-1, 1))
    result = skip_adjusted_return(closes, window=3, skip=2)

    # t = 9: end = close[7] = 17, start = close[4] = 14
    assert result.iloc[9, 0] == pytest.approx(17.0 / 14.0 - 1.0)
    # t = 4: end = close[2] = 12, start = close[-1] does not exist
    assert np.isnan(result.iloc[4, 0])


def test_skip_adjusted_return_survives_a_gap_between_the_endpoints():
    """A halt strictly inside the window must not make the return uncomputable.

    F1 is a two-point return. Section 9's exclusion rule should fire on a genuinely
    absent input, not on any gap anywhere in the lookback.
    """
    values = np.arange(10.0, 20.0).reshape(-1, 1)
    values[6, 0] = np.nan
    result = skip_adjusted_return(tiny_frame(values), window=3, skip=2)
    assert result.iloc[9, 0] == pytest.approx(17.0 / 14.0 - 1.0)


def test_universe_mean_ignores_ineligible_securities():
    values = tiny_frame([[1.0, 2.0, 300.0]])
    eligible = tiny_frame([[1.0, 1.0, 0.0]]).astype(bool)
    assert universe_mean(values, eligible).iloc[0] == pytest.approx(1.5)


def test_universe_excess_is_inert_after_zscoring():
    """The finding recorded in `f1_momentum`, asserted mechanically.

    Subtracting a cross-sectional constant leaves winsorisation and z-scoring
    unchanged, so F1's universe-excess step and F4b's S&P-500 step cannot move
    the APEX Score. Locking this in a test keeps it a documented property of the
    pre-registered specification rather than something rediscovered later and
    mistaken for a bug.
    """
    raw = tiny_frame([[0.05, -0.02, 0.11, 0.03, -0.07, 0.20, 0.01, -0.15]])
    eligible = tiny_frame(np.ones((1, 8))).astype(bool)

    benchmark = universe_mean(raw, eligible)
    excess = raw.sub(benchmark, axis=0)

    z_raw = zscore(winsorise(raw, 0.01, 0.99), ddof=1)
    z_excess = zscore(winsorise(excess, 0.01, 0.99), ddof=1)

    pd.testing.assert_frame_equal(z_raw, z_excess)


def test_f4_market_relative_is_identical_to_f1_after_zscoring():
    """The sharper consequence: F4b reduces to exactly F1b's z-score."""
    raw = tiny_frame([[0.05, -0.02, 0.11, 0.03, -0.07, 0.20, 0.01, -0.15]])
    eligible = tiny_frame(np.ones((1, 8))).astype(bool)
    benchmark_return = pd.Series([0.04], index=raw.index)

    f1b = raw.sub(universe_mean(raw, eligible), axis=0)
    f4b = market_relative(raw, benchmark_return)

    z_f1b = zscore(winsorise(f1b, 0.01, 0.99), ddof=1)
    z_f4b = zscore(winsorise(f4b, 0.01, 0.99), ddof=1)

    pd.testing.assert_frame_equal(z_f1b, z_f4b)


# ---------------------------------------------------------------------------
# F2
# ---------------------------------------------------------------------------


def test_simple_moving_average_requires_a_complete_window():
    closes = tiny_frame(np.array([[1.0], [2.0], [3.0], [np.nan], [5.0]]))
    sma = simple_moving_average(closes, window=3)

    assert np.isnan(sma.iloc[1, 0])
    assert sma.iloc[2, 0] == pytest.approx(2.0)
    assert np.isnan(sma.iloc[3, 0]), "a gap inside an SMA window must not be skipped over"
    assert np.isnan(sma.iloc[4, 0])


def test_fraction_above_sma_preserves_nan_rather_than_counting_it_as_below():
    """`close > sma` is False when either side is NaN. That must not count."""
    close = tiny_frame(np.array([[10.0], [np.nan], [12.0]]))
    sma = tiny_frame(np.array([[9.0], [9.0], [13.0]]))
    above = (close > sma).where(close.notna() & sma.notna())

    assert above.iloc[0, 0] == 1.0
    assert np.isnan(above.iloc[1, 0]), "a halted day was silently recorded as below the SMA"
    assert above.iloc[2, 0] == 0.0


# ---------------------------------------------------------------------------
# F3
# ---------------------------------------------------------------------------


def test_wilder_atr_matches_the_hand_computed_recursion():
    """period=3, TR = 1,2,3,4,5.

        ATR[2] = (1 + 2 + 3) / 3            = 2
        ATR[3] = (2 * 2 + 4) / 3            = 8/3
        ATR[4] = (8/3 * 2 + 5) / 3          = 10.333.../3
    """
    tr = tiny_frame(np.array([[1.0], [2.0], [3.0], [4.0], [5.0]]))
    atr = wilder_atr(tr, period=3)

    assert np.isnan(atr.iloc[0, 0]) and np.isnan(atr.iloc[1, 0])
    assert atr.iloc[2, 0] == pytest.approx(2.0)
    assert atr.iloc[3, 0] == pytest.approx((2.0 * 2 + 4.0) / 3.0)
    assert atr.iloc[4, 0] == pytest.approx(((2.0 * 2 + 4.0) / 3.0 * 2 + 5.0) / 3.0)


def test_wilder_atr_carries_state_across_a_gap_without_being_poisoned():
    tr = tiny_frame(np.array([[1.0], [2.0], [3.0], [np.nan], [5.0]]))
    atr = wilder_atr(tr, period=3)

    assert atr.iloc[2, 0] == pytest.approx(2.0)
    assert np.isnan(atr.iloc[3, 0]), "the halted date itself must be NaN"
    assert atr.iloc[4, 0] == pytest.approx((2.0 * 2 + 5.0) / 3.0), (
        "the recursion must resume from its retained state, not restart or stay NaN"
    )


def test_true_range_takes_the_max_of_the_three_candidates():
    high = tiny_frame(np.array([[10.0], [12.0]]))
    low = tiny_frame(np.array([[9.0], [8.0]]))
    close = tiny_frame(np.array([[9.5], [11.0]]))

    tr = true_range(high, low, close)
    # t=1: high-low = 4, |high-prev| = |12-9.5| = 2.5, |low-prev| = |8-9.5| = 1.5
    assert tr.iloc[1, 0] == pytest.approx(4.0)


def test_realised_volatility_is_log_return_std_with_ddof_one():
    closes = tiny_frame(np.array([[100.0], [110.0], [99.0], [108.9]]))
    vol = realised_volatility(closes, window=3, ddof=1)

    log_returns = np.diff(np.log(closes.to_numpy().ravel()))
    assert vol.iloc[3, 0] == pytest.approx(np.std(log_returns, ddof=1))


def test_volatility_ratio_annualisation_cancels():
    """C5 declines to annualise because the ratio is scale-free. Confirm it."""
    walk = np.random.default_rng(3).normal(0, 0.02, (60, 1))
    closes = tiny_frame(np.exp(np.cumsum(walk, axis=0)))
    short = realised_volatility(closes, 5, 1)
    long = realised_volatility(closes, 20, 1)

    plain = (short / long).iloc[-1, 0]
    annualised = ((short * np.sqrt(252)) / (long * np.sqrt(252))).iloc[-1, 0]
    assert plain == pytest.approx(annualised)


# ---------------------------------------------------------------------------
# F4
# ---------------------------------------------------------------------------


def test_sector_relative_excludes_self_from_its_own_benchmark():
    values = tiny_frame([[1.0, 2.0, 3.0, 4.0]])
    eligible = tiny_frame(np.ones((1, 4))).astype(bool)
    sectors = pd.Series(["A"] * 4, index=values.columns)

    result = sector_relative(values, eligible, sectors, min_names=4, exclude_self=True)

    # security 0: benchmark = mean(2, 3, 4) = 3 -> 1 - 3 = -2
    assert result.iloc[0, 0] == pytest.approx(-2.0)
    # security 3: benchmark = mean(1, 2, 3) = 2 -> 4 - 2 = +2
    assert result.iloc[0, 3] == pytest.approx(2.0)


def test_sector_relative_requires_the_minimum_member_count():
    values = tiny_frame([[1.0, 2.0, 3.0]])
    eligible = tiny_frame(np.ones((1, 3))).astype(bool)
    sectors = pd.Series(["A"] * 3, index=values.columns)

    result = sector_relative(values, eligible, sectors, min_names=10, exclude_self=True)
    assert result.isna().all().all(), "C2 requires >=10 eligible names in the sector"


def test_sector_benchmark_uses_only_eligible_members():
    values = tiny_frame([[1.0, 2.0, 3.0, 999.0]])
    eligible = tiny_frame([[1.0, 1.0, 1.0, 0.0]]).astype(bool)
    sectors = pd.Series(["A"] * 4, index=values.columns)

    result = sector_relative(values, eligible, sectors, min_names=3, exclude_self=True)

    # security 0's benchmark is mean(2, 3) = 2.5; the ineligible 999 is excluded
    assert result.iloc[0, 0] == pytest.approx(1.0 - 2.5)
    # the ineligible security still gets a value: benchmark = mean(1, 2, 3) = 2
    assert result.iloc[0, 3] == pytest.approx(999.0 - 2.0)


# ---------------------------------------------------------------------------
# composite
# ---------------------------------------------------------------------------


def test_winsorise_clips_at_the_interpolated_percentiles():
    """[1, 2, 3, 4, 100] at 1%/99%.

    pandas uses linear interpolation: the 1st percentile sits at position
    0.01 * 4 = 0.04 -> 1 + 0.04 * (2 - 1) = 1.04; the 99th at position 3.96 ->
    4 + 0.96 * (100 - 4) = 96.16.
    """
    values = tiny_frame([[1.0, 2.0, 3.0, 4.0, 100.0]])
    clipped = winsorise(values, 0.01, 0.99)

    assert clipped.iloc[0, 0] == pytest.approx(1.04)
    assert clipped.iloc[0, 4] == pytest.approx(96.16)
    assert clipped.iloc[0, 2] == pytest.approx(3.0)


def test_zscore_is_cross_sectional_with_ddof_one():
    values = tiny_frame([[1.0, 2.0, 3.0]])
    z = zscore(values, ddof=1)
    assert list(z.iloc[0]) == pytest.approx([-1.0, 0.0, 1.0])


def test_zscore_of_a_flat_cross_section_is_nan_not_zero():
    """A fabricated 0.0 would put a security in the middle decile on no evidence."""
    z = zscore(tiny_frame([[5.0, 5.0, 5.0]]), ddof=1)
    assert z.isna().all().all()


def test_percentile_rank_and_deciles_are_equal_count():
    values = tiny_frame([np.arange(100.0)])
    rank = percentile_rank(values, "first", 100.0)
    decile = assign_deciles(rank, 10, 100.0)

    assert rank.iloc[0].min() == pytest.approx(1.0)
    assert rank.iloc[0].max() == pytest.approx(100.0)
    counts = decile.iloc[0].value_counts()
    assert set(counts.index) == set(range(1, 11))
    assert counts.nunique() == 1, "deciles must be equal-count"
    assert decile.iloc[0, 0] == 1 and decile.iloc[0, 99] == 10


def test_decile_assignment_ignores_ineligible_securities():
    values = tiny_frame([[1.0, np.nan, 3.0]])
    decile = assign_deciles(percentile_rank(values, "first", 100.0), 10, 100.0)
    assert np.isnan(decile.iloc[0, 1])
