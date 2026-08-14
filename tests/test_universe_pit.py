"""Point-in-time universe construction -- protocol section 3.

The two properties that silently destroy an equity cross-sectional study, both
asserted here against hand-built panels rather than trusted:

  SURVIVORSHIP  A security that was later delisted must be eligible for every
                date on which it actually traded. Section 3: "A universe
                constructed from a current list of tickers is invalid and must
                not be used, even provisionally."

  LEVEL FILTERS The $5 close and $1B market-cap tests are LEVEL quantities and
                must use as-of-date UNADJUSTED prices (CONVENTIONS section 4.4).
                Cumulative split and dividend factors cancel in a ratio but not
                in a level, so applying a modern adjustment factor to a
                historical level test is lookahead. The tests below are built so
                that using the adjusted series gives the WRONG answer -- they
                fail if the two are ever confused.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.universe import build_universe
from tests.conftest import hand_panel, patched

DATES = pd.bdate_range("2020-01-01", periods=12)


@pytest.fixture(scope="module")
def base():
    """Thresholds a twelve-row panel can actually reach."""
    return patched(
        load_config("experiment", "costs", "synthetic"),
        {
            "universe.min_history_trading_days": 3,
            "universe.prior_bars_window": 5,
            "universe.min_bars_in_prior_252": 3,
            "universe.addv_window_days": 3,
        },
    )


def _eligible(panel, config) -> pd.DataFrame:
    return build_universe(panel, config).eligible


# ---------------------------------------------------------------------------
# LEVEL FILTERS -- adjusted vs unadjusted
# ---------------------------------------------------------------------------


def test_market_cap_uses_unadjusted_price_not_adjusted(base):
    """A name above $1B on as-of-date prices stays in, whatever the adjustment.

    Constructed so the answer differs: a later 2-for-1 split halves the whole
    adjusted history, and judging $1B on that halved series would wrongly
    exclude a company that was genuinely a $1.5B company at the time.
    """
    panel = hand_panel(
        DATES,
        close_adj={"S1": [5.0] * 12},        # post-split-adjusted
        close_unadj={"S1": [10.0] * 12},     # as it printed
        shares_out={"S1": [150e6] * 12},
    )

    eligible = _eligible(panel, base)

    assert eligible["S1"].iloc[-1], (
        "as-of-date market cap is 10 x 150m = $1.5B and clears the $1B filter; "
        "the adjusted series would give $0.75B and wrongly exclude it. The "
        "filter is reading the adjusted price -- a lookahead violation on a "
        "level quantity (CONVENTIONS section 4.4)."
    )


def test_close_filter_uses_unadjusted_price_not_adjusted(base):
    panel = hand_panel(
        DATES,
        close_adj={"S1": [3.0] * 12},     # below $5 after adjustment
        close_unadj={"S1": [6.0] * 12},   # above $5 as it printed
    )

    assert _eligible(panel, base)["S1"].iloc[-1], (
        "the security traded at $6 and clears the $5 filter; only the "
        "retrospectively adjusted series puts it below"
    )


def test_a_genuine_sub_dollar_stock_is_excluded(base):
    """Specificity: the filter must still bite when the real price is low."""
    panel = hand_panel(DATES, close_adj={"S1": [4.0] * 12})

    assert not _eligible(panel, base)["S1"].iloc[-1]


def test_market_cap_below_a_billion_is_excluded(base):
    panel = hand_panel(
        DATES, close_adj={"S1": [10.0] * 12}, shares_out={"S1": [50e6] * 12}
    )

    assert not _eligible(panel, base)["S1"].iloc[-1], "10 x 50m = $500m is below $1B"


# ---------------------------------------------------------------------------
# SURVIVORSHIP
# ---------------------------------------------------------------------------


def test_a_later_delisted_security_is_eligible_while_it_traded(base):
    """The single most important property in the whole universe module."""
    prices = [50.0] * 8 + [np.nan] * 4
    panel = hand_panel(
        DATES,
        close_adj={"S1": prices},
        meta={"S1": {"delist_date": DATES[8], "delist_reason": "bankruptcy"}},
    )

    eligible = _eligible(panel, base)

    assert eligible["S1"].iloc[7], (
        "a security that went bankrupt later was excluded from dates on which it "
        "actually traded. This is survivorship bias, and it inflates every "
        "backtested return the pipeline will ever produce."
    )
    assert not eligible["S1"].iloc[8], "it must not be eligible after it stopped trading"


def test_a_security_is_not_eligible_before_it_lists(base):
    prices = [np.nan] * 5 + [50.0] * 7
    panel = hand_panel(DATES, close_adj={"S1": prices})

    eligible = _eligible(panel, base)

    assert not eligible["S1"].iloc[0]
    assert not eligible["S1"].iloc[4]


def test_history_counts_bars_actually_present_not_calendar_days(base):
    """"300 days since listing" is not "300 days of trading history".

    A name that listed long ago but halted through most of it does not satisfy
    section 3's history requirement.
    """
    sparse = [50.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 50.0, 50.0, np.nan, np.nan]
    dense = [50.0] * 12
    panel = hand_panel(DATES, close_adj={"SPARSE": sparse, "DENSE": dense})

    config = patched(base, {"universe.min_history_trading_days": 5})
    eligible = _eligible(panel, config)

    assert eligible["DENSE"].iloc[9]
    assert not eligible["SPARSE"].iloc[9], (
        "SPARSE has traded only 3 bars in 10 calendar days; counting calendar "
        "days rather than bars would wrongly admit it"
    )


# ---------------------------------------------------------------------------
# ATTRIBUTE AND LIQUIDITY FILTERS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("security_type", ["etf", "reit", "adr", "spac", "preferred", "warrant"])
def test_non_common_security_types_are_excluded(base, security_type):
    panel = hand_panel(
        DATES,
        close_adj={"S1": [50.0] * 12},
        meta={"S1": {"security_type": security_type}},
    )

    assert not _eligible(panel, base)["S1"].any(), f"{security_type} must be excluded"


def test_off_exchange_listings_are_excluded(base):
    panel = hand_panel(
        DATES, close_adj={"S1": [50.0] * 12}, meta={"S1": {"exchange": "OTC"}}
    )

    assert not _eligible(panel, base)["S1"].any()


@pytest.mark.parametrize("exchange", ["NYSE", "NASDAQ", "NYSEAMERICAN"])
def test_the_three_permitted_exchanges_are_admitted(base, exchange):
    panel = hand_panel(
        DATES, close_adj={"S1": [50.0] * 12}, meta={"S1": {"exchange": exchange}}
    )

    assert _eligible(panel, base)["S1"].iloc[-1]


def test_illiquid_names_are_excluded_on_dollar_volume(base):
    """$10m ADDV, measured on price x volume over the trailing window."""
    panel = hand_panel(
        DATES,
        close_adj={"LIQUID": [50.0] * 12, "THIN": [50.0] * 12},
        volume={"LIQUID": [1e6] * 12, "THIN": [1e4] * 12},
    )

    eligible = _eligible(panel, base)

    assert eligible["LIQUID"].iloc[-1], "50 x 1m = $50m/day"
    assert not eligible["THIN"].iloc[-1], "50 x 10k = $500k/day is below $10m"


# ---------------------------------------------------------------------------
# THE SECTION 9 LOG
# ---------------------------------------------------------------------------


def test_the_per_date_log_attributes_every_exclusion(base):
    """Section 9: "count excluded by each filter", from the same object that decided."""
    panel = hand_panel(
        DATES,
        close_adj={"GOOD": [50.0] * 12, "CHEAP": [2.0] * 12, "SMALL": [50.0] * 12},
        shares_out={"GOOD": [1e9] * 12, "CHEAP": [1e9] * 12, "SMALL": [1e6] * 12},
    )

    counts = build_universe(panel, base).counts()
    last = counts.iloc[-1]

    assert last["eligible"] == 1
    assert last["excluded_close"] >= 1
    assert last["excluded_market_cap"] >= 1
    assert last["tradable"] == 3


def test_every_declared_filter_appears_in_the_log(base):
    """A filter that runs but is never counted could shrink the universe unseen."""
    from apex.contracts import FILTER_NAMES

    panel = hand_panel(DATES, close_adj={"S1": [50.0] * 12})
    counts = build_universe(panel, base).counts()

    for name in FILTER_NAMES:
        assert f"excluded_{name}" in counts.columns, f"filter '{name}' is not reported"


def test_exclusion_reason_is_a_single_deterministic_label(base):
    """C10: per-filter counts may overlap; the reason label must not be ambiguous."""
    panel = hand_panel(
        DATES,
        close_adj={"BOTH": [2.0] * 12},   # fails close AND market cap
        shares_out={"BOTH": [1e6] * 12},
    )

    reason = build_universe(panel, base).exclusion_reason["BOTH"].iloc[-1]

    assert reason == "close", (
        f"reason_priority lists close before market_cap, so a security failing "
        f"both must be labelled 'close'; got '{reason}'"
    )


# ---------------------------------------------------------------------------
# PIT ESTABLISHMENT -- the user's hard rule, 2026-08-09
# ---------------------------------------------------------------------------


def test_a_security_date_without_pit_market_cap_is_excluded(base):
    """"If a security-date cannot be established PIT, it is excluded."

    Never filled with today's shares, today's market cap, a current ticker
    mapping, or a later-revised fundamental.
    """
    shares = [1e9] * 6 + [np.nan] * 6
    panel = hand_panel(DATES, close_adj={"S1": [50.0] * 12}, shares_out={"S1": shares})

    eligible = _eligible(panel, base)

    assert eligible["S1"].iloc[5], "shares outstanding are known here"
    assert not eligible["S1"].iloc[8], (
        "shares outstanding are unknown at this date, so PIT market cap cannot "
        "be established and the security-date must be excluded"
    )


def test_unknown_market_cap_is_reported_separately_from_small_market_cap(base):
    """"...and the exclusion is reported."

    "We know it was a $400m company" and "we do not know what it was worth" are
    different facts. Collapsing them into one bucket hides how much of the
    universe was lost to missing PIT data -- which is exactly the number needed
    to judge whether the dual-vendor join is working.
    """
    panel = hand_panel(
        DATES,
        close_adj={"SMALL": [50.0] * 12, "UNKNOWN": [50.0] * 12},
        shares_out={"SMALL": [1e6] * 12, "UNKNOWN": [np.nan] * 12},
    )

    counts = build_universe(panel, base).counts()
    reasons = build_universe(panel, base).exclusion_reason

    assert reasons["SMALL"].iloc[-1] == "market_cap"
    assert reasons["UNKNOWN"].iloc[-1] == "pit_market_cap", (
        "a security whose shares outstanding are unavailable is being reported "
        "as 'too small', which is a different claim and an untrue one"
    )
    assert counts["excluded_pit_market_cap"].iloc[-1] == 1
    assert counts["excluded_market_cap"].iloc[-1] == 1


def test_pit_availability_does_not_rescue_a_genuinely_small_company(base):
    """Specificity: the new filter must not become a way around the $1B rule."""
    panel = hand_panel(
        DATES, close_adj={"S1": [50.0] * 12}, shares_out={"S1": [1e6] * 12}
    )

    assert not _eligible(panel, base)["S1"].iloc[-1]


def test_eligibility_is_boolean_and_covers_every_date(base):
    panel = hand_panel(DATES, close_adj={"S1": [50.0] * 12})
    snapshot = build_universe(panel, base)

    assert snapshot.eligible.dtypes.eq(bool).all()
    assert snapshot.eligible.index.equals(pd.DatetimeIndex(DATES))


# ---------------------------------------------------------------------------
# THE OPTIONAL MARKET-CAP CEILING (APEX-004 small-cap universe)
# ---------------------------------------------------------------------------


def test_absent_ceiling_key_changes_nothing(base):
    """The closed experiments' configs carry no ceiling; a mega-cap must stay
    eligible under them, bit-for-bit. If this fails, APEX-001/002/003 stopped
    being reproducible."""
    panel = hand_panel(
        DATES, close_adj={"S1": [100.0] * 12}, shares_out={"S1": [5e9] * 12}
    )
    assert _eligible(panel, base)["S1"].iloc[-1], "$500B name must remain eligible"


def test_counterexample_the_ceiling_excludes_a_large_cap(base):
    """The new key must be able to do the one thing it exists to do."""
    capped = patched(base, {"universe.max_market_cap_usd": 2e9})
    panel = hand_panel(
        DATES,
        close_adj={"BIG": [100.0] * 12, "SML": [100.0] * 12},
        shares_out={"BIG": [5e9] * 12, "SML": [20e6] * 12},
    )
    # BIG: 100 x 5e9  = $500B -> above ceiling, excluded
    # SML: 100 x 20e6 = $2B   -> AT the ceiling, excluded (strict <)
    eligible = _eligible(panel, capped)
    assert not eligible["BIG"].iloc[-1]
    assert not eligible["SML"].iloc[-1], "ceiling is exclusive: mcap < ceiling"


def test_a_name_between_floor_and_ceiling_is_eligible(base):
    capped = patched(base, {"universe.max_market_cap_usd": 2e9})
    panel = hand_panel(
        DATES, close_adj={"MID": [100.0] * 12}, shares_out={"MID": [15e6] * 12}
    )
    assert _eligible(panel, capped)["MID"].iloc[-1], "$1.5B sits inside [1B, 2B)"


def test_unknowable_market_cap_still_fails_pit_not_the_ceiling(base):
    """The PIT rule outranks the size rule in both directions: unknown market
    cap is excluded as UNKNOWABLE, never as too big or too small."""
    capped = patched(base, {"universe.max_market_cap_usd": 2e9})
    panel = hand_panel(DATES, close_adj={"S1": [100.0] * 12})  # no shares_out
    snapshot = build_universe(panel, capped)
    assert not snapshot.eligible["S1"].iloc[-1]
