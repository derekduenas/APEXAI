"""Forward returns, the timing firewall, and delisting conventions.

Protocol section 4 fixes the timing exactly:

    features computed from data through the close of day T
    portfolio formed at the close of day T+1
    forward return measured close T+1 -> close T+21

An off-by-one here is invisible in every summary statistic and changes the
answer completely: measuring T -> T+20 instead of T+1 -> T+21 lets the score
"see" the first day's move, which is where a large share of any apparent
short-horizon edge would come from.

Delisting (section 3, ruling B4, Shumway 1997):

    performance-related, or not affirmatively identifiable as M&A or voluntary:
        R = (P_last / P_entry) x 0.70 - 1
    merger, acquisition or voluntary:
        R = (P_last / P_entry) - 1

The -30% is applied to the TERMINAL VALUE on top of the realised partial-period
return, not as the total window return. B4 selects that reading explicitly, and
the difference is large for a name that had already halved before it failed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.returns import (
    DELIST_MERGER,
    DELIST_PERFORMANCE,
    HELD,
    compute_forward_returns,
)
from tests.conftest import hand_panel, patched

DATES = pd.bdate_range("2020-01-01", periods=12)


@pytest.fixture(scope="module")
def real():
    return load_config("experiment", "costs", "synthetic")


@pytest.fixture(scope="module")
def short(real):
    """lag 1, horizon 3 -- the same mechanism, hand-computable on a 12-row panel."""
    return patched(real, {"horizon.forward_trading_days": 3})


def _all_eligible(panel) -> pd.DataFrame:
    return pd.DataFrame(True, index=panel.dates, columns=panel.securities)


# ---------------------------------------------------------------------------
# the protocol's actual numbers
# ---------------------------------------------------------------------------


def test_the_configured_timing_is_the_protocol_timing(real):
    """Guards the constants themselves; every other test here patches them."""
    assert int(real.get("horizon.signal_to_formation_lag")) == 1, "form at T+1"
    assert int(real.get("horizon.forward_trading_days")) == 20, "hold to T+21"


# ---------------------------------------------------------------------------
# TIMING
# ---------------------------------------------------------------------------


def test_forward_return_runs_from_the_formation_close_to_the_exit_close(short):
    """R(T) = close[T+4]/close[T+1] - 1 for lag 1, horizon 3."""
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0]
    panel = hand_panel(DATES, close_adj={"S1": prices})

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    # signal date index 0 -> entry at index 1 (11.0), exit at index 4 (14.0)
    assert forward.raw["S1"].iloc[0] == pytest.approx(14.0 / 11.0 - 1.0)
    # signal date index 5 -> entry at index 6 (16.0), exit at index 9 (19.0)
    assert forward.raw["S1"].iloc[5] == pytest.approx(19.0 / 16.0 - 1.0)


def test_the_return_is_indexed_by_signal_date_not_formation_date(short):
    """So it joins the score panel without an off-by-one.

    Prices are strictly monotone and distinct, so every (entry, exit) pair gives
    a different return and a one-row shift is actually detectable. A flat or
    step-shaped path would make neighbouring rows agree and the test would pass
    whether or not the frame were shifted.
    """
    prices = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0]
    panel = hand_panel(DATES, close_adj={"S1": prices})

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    signal_2 = 16.0 / 13.0 - 1.0  # entry index 3, exit index 6
    signal_3 = 17.0 / 14.0 - 1.0  # entry index 4, exit index 7

    assert forward.raw["S1"].iloc[2] == pytest.approx(signal_2)
    assert forward.raw["S1"].iloc[3] == pytest.approx(signal_3)
    assert forward.raw["S1"].iloc[3] != pytest.approx(signal_2), (
        "row 3 carries signal-date-2's window, so the frame is indexed by "
        "FORMATION date and every score/return join is off by one"
    )


def test_the_entry_price_is_not_the_signal_day_close(short):
    """The T -> T+20 off-by-one, isolated.

    The panel jumps +50% between T and T+1. A return measured from the SIGNAL
    close would capture that jump; the protocol's T+1 entry must not.
    """
    prices = [10.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0]
    panel = hand_panel(DATES, close_adj={"S1": prices})

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.raw["S1"].iloc[0] == pytest.approx(0.0), (
        "entry is the T+1 close of 15.0 and exit is 15.0, so the return is zero. "
        "A non-zero value means the entry used the signal-day close of 10.0 and "
        "the pipeline is capturing a move it could never have traded."
    )


def test_a_truncated_forward_window_is_nan_not_short(short):
    """Better a missing observation than a 2-day return reported as a 3-day one."""
    panel = hand_panel(DATES, close_adj={"S1": [10.0] * 12})

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.raw["S1"].iloc[-4:].isna().all()


# ---------------------------------------------------------------------------
# DELISTING
# ---------------------------------------------------------------------------


def test_performance_delisting_applies_the_shumway_haircut_to_terminal_value(short):
    """B4 reading (b): R = (P_last / P_entry) x 0.70 - 1."""
    prices = [100.0, 100.0, 80.0, 60.0] + [np.nan] * 8
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[4], "delist_reason": "bankruptcy"}},
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    # signal 0 -> entry index 1 (100.0), last traded 60.0, delisted before exit
    assert forward.raw["S1"].iloc[0] == pytest.approx((60.0 / 100.0) * 0.70 - 1.0)
    assert forward.raw["S1"].iloc[0] == pytest.approx(-0.58)
    assert forward.exit_reason["S1"].iloc[0] == DELIST_PERFORMANCE


def test_the_haircut_is_not_applied_to_the_whole_window_return(short):
    """Distinguishes B4 reading (b) from reading (a), which would give -0.70.

    Reading (a) -- treating -30% as the total window return -- would report the
    same number no matter how far the stock had already fallen, discarding the
    realised loss entirely.
    """
    prices = [100.0, 100.0, 80.0, 60.0] + [np.nan] * 8
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[4], "delist_reason": "bankruptcy"}},
    )

    value = compute_forward_returns(panel, _all_eligible(panel), short).raw["S1"].iloc[0]

    assert value != pytest.approx(-0.30)
    assert value != pytest.approx(-0.70)


def test_a_merger_uses_the_final_traded_price_with_no_haircut(short):
    prices = [100.0, 100.0, 120.0, 130.0] + [np.nan] * 8
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[4], "delist_reason": "merger"}},
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.raw["S1"].iloc[0] == pytest.approx(130.0 / 100.0 - 1.0)
    assert forward.exit_reason["S1"].iloc[0] == DELIST_MERGER


@pytest.mark.parametrize("reason", [None, "", "unknown", "nan"])
def test_an_unidentifiable_delisting_is_treated_as_performance_related(short, reason):
    """CONVENTIONS section 1's pre-registered fallback, in the conservative direction."""
    prices = [100.0, 100.0, 90.0, 90.0] + [np.nan] * 8
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[4], "delist_reason": reason}},
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.raw["S1"].iloc[0] == pytest.approx((90.0 / 100.0) * 0.70 - 1.0)
    assert forward.exit_reason["S1"].iloc[0] == DELIST_PERFORMANCE


def test_a_surviving_security_is_never_haircut(short):
    panel = hand_panel(DATES, close_adj={"S1": [10.0, 11.0, 12.0, 13.0, 14.0] + [15.0] * 7})

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.exit_reason["S1"].iloc[0] == HELD


def test_no_return_can_fall_below_minus_one_hundred_percent(short):
    """Contract-enforced: a long position cannot lose more than its capital."""
    prices = [100.0, 100.0, 0.01, 0.01] + [np.nan] * 8
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[4], "delist_reason": "bankruptcy"}},
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)
    values = forward.raw.to_numpy()

    assert np.nanmin(values) >= -1.0


# ---------------------------------------------------------------------------
# EXCESS RETURN
# ---------------------------------------------------------------------------


def test_excess_return_subtracts_the_eligible_universe_median(short):
    """Section 2 / C11: the median, over the post-filter eligible universe at T."""
    panel = hand_panel(
        DATES,
        close_adj={
            "A": [10.0, 10.0, 10.0, 10.0, 11.0] + [11.0] * 7,   # +10%
            "B": [10.0, 10.0, 10.0, 10.0, 12.0] + [12.0] * 7,   # +20%
            "C": [10.0, 10.0, 10.0, 10.0, 13.0] + [13.0] * 7,   # +30%
        },
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)

    assert forward.raw["B"].iloc[0] == pytest.approx(0.20)
    assert forward.excess["B"].iloc[0] == pytest.approx(0.0), "B is the median"
    assert forward.excess["A"].iloc[0] == pytest.approx(-0.10)
    assert forward.excess["C"].iloc[0] == pytest.approx(0.10)


def test_the_median_ignores_ineligible_securities(short):
    """An ineligible name must not move the benchmark for eligible ones."""
    panel = hand_panel(
        DATES,
        close_adj={
            "A": [10.0, 10.0, 10.0, 10.0, 11.0] + [11.0] * 7,
            "B": [10.0, 10.0, 10.0, 10.0, 12.0] + [12.0] * 7,
            "JUNK": [10.0, 10.0, 10.0, 10.0, 90.0] + [90.0] * 7,
        },
    )
    eligible = _all_eligible(panel)
    eligible["JUNK"] = False

    forward = compute_forward_returns(panel, eligible, short)

    # Median over {A: +10%, B: +20%} is +15%.
    assert forward.excess["A"].iloc[0] == pytest.approx(0.10 - 0.15)
    assert forward.excess["B"].iloc[0] == pytest.approx(0.20 - 0.15)


def test_excess_return_preserves_the_ranking_of_raw_return(short):
    """Section 2's technical note: subtracting a cross-sectional constant cannot
    change the ordering, so IC and decile spread are numerically identical on
    raw or excess returns. Asserted so the claim cannot quietly stop being true.
    """
    rng = np.random.default_rng(0)
    panel = hand_panel(
        DATES,
        close_adj={
            f"S{i}": [10.0, 10.0, 10.0, 10.0, 10.0 * (1 + rng.uniform(-0.3, 0.3))] + [10.0] * 7
            for i in range(8)
        },
    )

    forward = compute_forward_returns(panel, _all_eligible(panel), short)
    raw = forward.raw.iloc[0]
    excess = forward.excess.iloc[0]

    assert list(raw.rank()) == list(excess.rank())
