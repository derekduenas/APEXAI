"""Cost model -- protocol section 8, ruling C8.

SCOPE, AND WHAT IS DELIBERATELY ABSENT.

What exists today is the cost SURFACE: the per-side basis-point figures, the 1x
and 2x profiles, and the arithmetic that turns them into a round-trip charge.
That is what this file tests.

What does NOT exist is the turnover simulation that would turn those figures
into a NET decile spread -- the section 9 portfolio rule (hold the top decile,
rebalance every 20 trading days, close names that leave the universe at their
last valid price, hold the proceeds in cash). `apex/evaluate/deciles.py` reports
GROSS only, and says why: reporting a net figure before that machinery exists
means inventing a turnover number, and the cost hurdle sits too close to the
pass threshold for an invented number to be harmless.

That gap is registered below so it appears in every `-ra` summary rather than
being discovered later as a missing feature.

WHY THE HURDLE IS SO HIGH (CONVENTIONS section 4.1, recorded before results):
20 bps round trip at full turnover every 20 trading days is ~2.5% annualised per
leg. The decile spread carries TWO legs, so ~5% at 1x and ~10% at 2x. Section 10
demands a net spread >= 4% at 1x, which means roughly 9% GROSS -- and ~12% gross
to survive the 2x fragility check. For a four-factor price composite that is a
demanding bar, and it was acknowledged before any result existed.
"""

from __future__ import annotations

import pytest

from apex.config import ConfigError, load_config

# Stage 6 shipped 2026-08-11 (apex/evaluate/turnover.py, tests/test_turnover_costs.py):
# realised one-way turnover on both legs, and annualised turnover, are now
# computed from the simulated holdings path rather than deferred.
DEFERRED_UNTIL_STAGE_6 = [
    "after-tax figures at the 35% short-term rate (section 8)",
]


@pytest.fixture(scope="module")
def config():
    return load_config("experiment", "costs", "synthetic")


# ---------------------------------------------------------------------------
# the pre-registered figures
# ---------------------------------------------------------------------------


def test_the_base_profile_is_ten_basis_points_per_side(config):
    """Section 8: $0 commission + 5 bps half-spread + 5 bps slippage."""
    assert config.cost_bps_per_side("1x") == pytest.approx(10.0)


def test_the_base_profile_is_twenty_basis_points_round_trip(config):
    assert 2 * config.cost_bps_per_side("1x") == pytest.approx(20.0)


def test_the_sensitivity_profile_is_exactly_double(config):
    """Section 8: 'all headline results are also reported at 2x cost'."""
    assert config.cost_bps_per_side("2x") == pytest.approx(
        2 * config.cost_bps_per_side("1x")
    )
    assert 2 * config.cost_bps_per_side("2x") == pytest.approx(40.0)


def test_commission_is_zero_but_remains_a_parameter(config):
    """So the sensitivity surface can move it without touching code."""
    assert config.cost_profile("1x")["commission_bps"] == 0.0


def test_the_default_profile_is_the_one_bps_profile(config):
    assert config.cost_bps_per_side() == config.cost_bps_per_side("1x")


def test_the_short_term_tax_rate_is_recorded_for_context(config):
    """Section 8: reported, never a pass/fail input."""
    assert config.get("tax.short_term_rate") == pytest.approx(0.35)


# ---------------------------------------------------------------------------
# the cost model cannot be silently incomplete
# ---------------------------------------------------------------------------


def test_a_profile_missing_a_component_is_rejected_not_defaulted(config):
    """A missing slippage figure must not silently become zero."""
    from tests.conftest import patched

    broken = patched(config, {"profiles.1x": {"commission_bps": 0.0, "half_spread_bps": 5.0}})

    with pytest.raises(ConfigError) as excinfo:
        broken.cost_bps_per_side("1x")
    assert "slippage_bps" in str(excinfo.value)


def test_an_unknown_profile_raises(config):
    with pytest.raises(ConfigError):
        config.cost_bps_per_side("free_lunch")


def test_costs_live_in_config_not_in_code():
    """Section 30: no magic numbers. A hardcoded 5.0 would escape Config.hash
    and a cost assumption could change without changing the run's fingerprint.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "apex" / "evaluate" / "deciles.py").read_text()

    for forbidden in ("0.0005", "0.001", "5.0 /", "bps = 5", "bps = 10"):
        assert forbidden not in source, f"cost constant '{forbidden}' hardcoded in deciles.py"


# ---------------------------------------------------------------------------
# the gross/net boundary
# ---------------------------------------------------------------------------


def test_decile_results_are_labelled_gross(config):
    """Nothing may present a gross number as though costs had been applied."""
    from apex.evaluate.deciles import DecileResult

    fields = DecileResult.__dataclass_fields__
    assert "spread_annualised_gross" in fields
    assert not any(
        name.endswith("_net") for name in fields
    ), (
        "a *_net field exists on DecileResult, but the turnover simulation that "
        "would justify it is Stage 6 and is not built. A net figure computed "
        "without realised turnover is an invented number."
    )


def test_the_stage_6_gap_is_declared():
    """Registered rather than absent, so `-ra` surfaces it on every run."""
    assert DEFERRED_UNTIL_STAGE_6


def test_net_spread_applies_costs_to_realised_turnover_on_both_legs(config):
    """C8, no longer deferred -- Stage 6 shipped.

    Kept here (rather than only in test_turnover_costs.py) because this file is
    the register of what the cost model owes the protocol, and this line is the
    one that was outstanding longest.
    """
    import pandas as pd

    from apex.evaluate.turnover import net_decile_result

    dates = pd.DatetimeIndex(["2020-01-31", "2020-02-28"])
    securities = pd.Index(["A", "B"], name="security_id")
    top = pd.DataFrame([[True, False], [False, True]], index=dates, columns=securities)
    returns = pd.DataFrame(0.0, index=dates, columns=securities)

    result = net_decile_result(
        top, ~top,
        returns,
        bps_per_side=config.cost_bps_per_side("1x"),
        periods_per_year=float(config.get("evaluation.periods_per_year")),
    )

    assert result.long_cost_per_period > 0 and result.short_cost_per_period > 0
    assert result.net_spread_per_period < result.gross_spread_per_period
    assert "No turnover was assumed" in result.as_dict()["basis"]
