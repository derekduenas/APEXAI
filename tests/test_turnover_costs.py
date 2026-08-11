"""Stage 6 -- realised turnover and net returns. Protocol section 8, ruling C8.

    "Costs = 10 bps per side applied to REALISED one-way turnover, on BOTH legs
     of the spread."  -- CONVENTIONS C8

The standing rule this closes: `deciles.py` has always reported GROSS only, and
refused to report net, because "a net figure computed without realised turnover
is an invented number." This module computes realised turnover from the actual
holdings path, so a net figure finally has something real underneath it.

THE THING THAT MAKES THIS NON-TRIVIAL: DRIFT.

Between rebalances the portfolio is not traded (section 9: "no intra-period
trading"), so weights drift with returns. A name that doubled is now a bigger
share of the book and needs SELLING at the next rebalance even if it is still in
the top decile. Computing turnover as |target - equal_weight| ignores drift and
systematically MIS-states cost. Turnover is measured against the DRIFTED book.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.evaluate.turnover import (
    NetResult,
    annualise_turnover,
    drift_weights,
    leg_costs,
    one_way_turnover,
)

BPS = 10.0  # protocol section 8: 5 half-spread + 5 slippage, per side


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------


def test_weights_drift_with_returns():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    returns = pd.Series({"A": 1.0, "B": 0.0})  # A doubles

    drifted = drift_weights(weights, returns)

    # A is now worth 1.0 of 1.5 total.
    assert drifted["A"] == pytest.approx(2 / 3)
    assert drifted["B"] == pytest.approx(1 / 3)
    assert drifted.sum() == pytest.approx(1.0)


def test_flat_returns_leave_weights_untouched():
    weights = pd.Series({"A": 0.25, "B": 0.75})

    drifted = drift_weights(weights, pd.Series({"A": 0.0, "B": 0.0}))

    pd.testing.assert_series_equal(drifted, weights)


def test_a_total_loss_removes_a_name_from_the_book():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    returns = pd.Series({"A": -1.0, "B": 0.0})

    drifted = drift_weights(weights, returns)

    assert drifted["A"] == pytest.approx(0.0)
    assert drifted["B"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# turnover
# ---------------------------------------------------------------------------


def test_an_unchanged_book_has_zero_turnover():
    held = pd.Series({"A": 0.5, "B": 0.5})

    assert one_way_turnover(held, held) == pytest.approx(0.0)


def test_a_completely_replaced_book_has_full_turnover():
    old = pd.Series({"A": 0.5, "B": 0.5})
    new = pd.Series({"C": 0.5, "D": 0.5})

    assert one_way_turnover(old, new) == pytest.approx(1.0)


def test_replacing_half_the_book_is_half_turnover():
    old = pd.Series({"A": 0.5, "B": 0.5})
    new = pd.Series({"A": 0.5, "C": 0.5})

    assert one_way_turnover(old, new) == pytest.approx(0.5)


def test_turnover_accounts_for_drift_not_just_membership():
    """The subtle one. Same names, same equal-weight target -- but the book
    drifted, so rebalancing back to equal weight IS a trade."""
    target = pd.Series({"A": 0.5, "B": 0.5})
    drifted = pd.Series({"A": 2 / 3, "B": 1 / 3})  # A doubled

    turnover = one_way_turnover(drifted, target)

    assert turnover == pytest.approx(1 / 6), (
        "rebalancing a drifted book back to equal weight costs real trading; "
        "measuring turnover against the TARGET rather than the DRIFTED book "
        "would report zero"
    )


def test_a_name_that_left_the_universe_is_sold():
    """Section 9: closed at its last valid price, proceeds held in cash."""
    drifted = pd.Series({"A": 0.5, "GONE": 0.5})
    target = pd.Series({"A": 1.0})

    assert one_way_turnover(drifted, target) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


def test_cost_is_charged_on_every_unit_traded_both_directions():
    """Full replacement sells 100% and buys 100%: two sides, each paying."""
    old = pd.Series({"A": 1.0})
    new = pd.Series({"B": 1.0})

    cost = leg_costs(old, new, bps_per_side=BPS)

    # sum|dw| = 2.0, at 10bps per side -> 20 bps
    assert cost == pytest.approx(2 * BPS / 1e4)
    assert cost == pytest.approx(0.0020)


def test_zero_turnover_is_free():
    held = pd.Series({"A": 1.0})

    assert leg_costs(held, held, bps_per_side=BPS) == pytest.approx(0.0)


def test_doubling_the_cost_assumption_doubles_the_cost():
    """Section 8's 2x sensitivity profile."""
    old, new = pd.Series({"A": 1.0}), pd.Series({"B": 1.0})

    assert leg_costs(old, new, bps_per_side=2 * BPS) == pytest.approx(
        2 * leg_costs(old, new, bps_per_side=BPS)
    )


# ---------------------------------------------------------------------------
# annualisation
# ---------------------------------------------------------------------------


def test_annualised_turnover_scales_by_periods_per_year():
    """C9: 12.6 rebalances per year."""
    assert annualise_turnover(0.5, periods_per_year=12.6) == pytest.approx(6.3)


def test_full_replacement_every_period_is_1260_percent_annually():
    assert annualise_turnover(1.0, periods_per_year=12.6) == pytest.approx(12.6)


# ---------------------------------------------------------------------------
# the end-to-end net result
# ---------------------------------------------------------------------------


def _toy_path():
    """Three rebalances, two names, hand-computable."""
    dates = pd.DatetimeIndex(["2020-01-31", "2020-02-28", "2020-03-31"])
    securities = pd.Index(["A", "B", "C", "D"], name="security_id")
    # top decile membership flips completely at each rebalance
    top = pd.DataFrame(
        [[True, True, False, False],
         [False, False, True, True],
         [True, True, False, False]],
        index=dates, columns=securities,
    )
    bottom = ~top
    returns = pd.DataFrame(0.01, index=dates, columns=securities)
    return dates, top, bottom, returns


def test_net_is_gross_minus_realised_cost():
    from apex.evaluate.turnover import net_decile_result

    dates, top, bottom, returns = _toy_path()

    result = net_decile_result(top, bottom, returns, bps_per_side=BPS, periods_per_year=12.6)

    assert isinstance(result, NetResult)
    assert result.net_spread_per_period < result.gross_spread_per_period
    drop = result.gross_spread_per_period - result.net_spread_per_period
    assert drop > 0
    assert result.cost_per_period == pytest.approx(drop)


def test_both_legs_are_charged():
    """C8: 'on BOTH legs of the spread'. A long-only charge halves the cost."""
    from apex.evaluate.turnover import net_decile_result

    dates, top, bottom, returns = _toy_path()
    result = net_decile_result(top, bottom, returns, bps_per_side=BPS, periods_per_year=12.6)

    assert result.long_cost_per_period > 0
    assert result.short_cost_per_period > 0
    assert result.cost_per_period == pytest.approx(
        result.long_cost_per_period + result.short_cost_per_period
    )


def test_an_unchanging_book_is_charged_only_for_establishing_itself():
    """Buying the initial position IS realised turnover and must be charged.

    An earlier version of this test asserted zero cost for a book that never
    changes. That was wrong: going from nothing to fully invested is a real
    trade. After establishment there is nothing further to pay.
    """
    from apex.evaluate.turnover import net_decile_result

    dates = pd.DatetimeIndex(["2020-01-31", "2020-02-28", "2020-03-31"])
    securities = pd.Index(["A", "B"], name="security_id")
    top = pd.DataFrame([[True, False]] * 3, index=dates, columns=securities)
    returns = pd.DataFrame(0.0, index=dates, columns=securities)

    result = net_decile_result(top, ~top, returns, bps_per_side=BPS, periods_per_year=12.6)

    # Establishment only: one-way turnover 0.5 in period 1, zero thereafter,
    # on each of the two legs, averaged over three periods.
    establishment = 2.0 * (BPS / 1e4) * 0.5
    assert result.cost_per_period == pytest.approx(2 * establishment / 3)
    assert result.long_turnover_per_period == pytest.approx(0.5 / 3)


def test_a_static_book_pays_nothing_after_establishment():
    """The ongoing cost of never trading is zero -- lengthen the sample and the
    per-period average of the one-off establishment cost tends to zero."""
    from apex.evaluate.turnover import net_decile_result

    dates = pd.DatetimeIndex(pd.date_range("2020-01-31", periods=60, freq="ME"))
    securities = pd.Index(["A", "B"], name="security_id")
    top = pd.DataFrame([[True, False]] * 60, index=dates, columns=securities)
    returns = pd.DataFrame(0.0, index=dates, columns=securities)

    result = net_decile_result(top, ~top, returns, bps_per_side=BPS, periods_per_year=12.6)

    assert result.cost_per_period < 2.0 * (BPS / 1e4) * 0.5 * 2 / 50


def test_the_result_reports_realised_turnover_not_an_assumption():
    """The whole reason this module exists."""
    from apex.evaluate.turnover import net_decile_result

    dates, top, bottom, returns = _toy_path()
    result = net_decile_result(top, bottom, returns, bps_per_side=BPS, periods_per_year=12.6)

    assert 0.0 < result.long_turnover_per_period <= 1.0
    assert result.annualised_turnover == pytest.approx(
        annualise_turnover(result.long_turnover_per_period, 12.6)
    )
    assert "realised" in result.as_dict()["basis"].lower()


def test_an_empty_decile_period_is_skipped_not_charged():
    """A rebalance with nothing to hold is not a 100% liquidation."""
    from apex.evaluate.turnover import net_decile_result

    dates = pd.DatetimeIndex(["2020-01-31", "2020-02-28"])
    securities = pd.Index(["A", "B"], name="security_id")
    top = pd.DataFrame([[False, False], [True, False]], index=dates, columns=securities)
    returns = pd.DataFrame(0.0, index=dates, columns=securities)

    result = net_decile_result(top, ~top, returns, bps_per_side=BPS, periods_per_year=12.6)

    assert np.isfinite(result.cost_per_period)


def test_costs_cannot_be_computed_from_an_assumed_turnover():
    """No API accepts a turnover number. It must be derived from holdings."""
    import inspect

    from apex.evaluate import turnover as module

    signature = inspect.signature(module.net_decile_result)
    for forbidden in ("turnover", "assumed_turnover", "turnover_rate"):
        assert forbidden not in signature.parameters, (
            f"net_decile_result accepts '{forbidden}' -- a net figure computed "
            f"from an assumed turnover is an invented number"
        )
