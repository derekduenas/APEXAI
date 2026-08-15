"""The calibration audit's adversarial distinctions, each proven concrete:

    CALIBRATION != ACCURACY != DISCRIMINATION != PROFITABILITY

plus the identity guards: a rank can never become a probability, an IC can
never become an expected return, and the cost model can never flatter the
economics by direction.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from apex.distribution.estimator import (
    EstimatorError, empirical_conditional, pit_diagnostic,
)
from apex.reality.harness import reliability_resolution


def _rows(probs, outcomes):
    return [{"probability": float(p), "outcome": float(o)}
            for p, o in zip(probs, outcomes)]


# --- discrimination without calibration --------------------------------------

def test_a_well_discriminating_model_can_be_badly_calibrated():
    """Perfect ORDERING, terrible probabilities: says 0.95/0.05 when truth
    is 0.65/0.35. Resolution (discrimination) high, reliability (calibration)
    terrible -- the two must be measured separately or one masquerades as
    the other."""
    rng = np.random.default_rng(4)
    n = 4000
    truth = np.concatenate([np.full(n, 0.65), np.full(n, 0.35)])
    stated = np.concatenate([np.full(n, 0.95), np.full(n, 0.05)])
    outcomes = (rng.random(2 * n) < truth).astype(float)
    d = reliability_resolution(_rows(stated, outcomes))
    assert d["resolution"] > 0.015, "it genuinely discriminates"
    assert d["reliability"] > 0.05, "and it is genuinely miscalibrated"


def test_a_calibrated_model_can_be_useless():
    """Says the base rate to everything: reliability ~0 (honest), resolution
    ~0 (says nothing). Calibration alone confers no usefulness."""
    rng = np.random.default_rng(5)
    outcomes = (rng.random(4000) < 0.53).astype(float)
    d = reliability_resolution(_rows(np.full(4000, 0.53), outcomes))
    assert d["reliability"] < 0.005
    assert d["resolution"] < 0.005


# --- profitability without calibration ---------------------------------------

def test_a_profitable_sample_with_overconfident_intervals_is_caught():
    """Positive realized mean (profitable!) while the stated distribution is
    half as wide as reality: the PIT diagnostic must pile mass in the tails
    far beyond the uniform expectation, whatever the P&L says."""
    rng = np.random.default_rng(6)
    est = empirical_conditional(rng.normal(0.01, 0.03, 2000), 20,
                                signal="s", conditioning={},
                                estimation_window="test")   # narrow view
    realized = rng.normal(0.01, 0.06, 300)                  # wide reality
    assert realized.mean() > 0, "the sample IS profitable"
    diag = pit_diagnostic([(est, r) for r in realized])
    assert diag["tail_mass_frac"] > 0.35, (
        "overconfidence must be visible in the tails regardless of profit")


def test_counterexample_a_matched_distribution_passes_the_same_diagnostic():
    rng = np.random.default_rng(7)
    est = empirical_conditional(rng.normal(0.01, 0.06, 4000), 20,
                                signal="s", conditioning={},
                                estimation_window="test")
    realized = rng.normal(0.01, 0.06, 400)
    diag = pit_diagnostic([(est, r) for r in realized])
    assert 0.10 < diag["tail_mass_frac"] < 0.30, (
        "a matched distribution must read ~uniform, or the diagnostic is "
        "a device that condemns everything")


# --- identity guards ---------------------------------------------------------

def test_a_rank_can_never_become_a_probability_distribution():
    """Feeding percentile ranks (0..100) where returns belong must be
    REFUSED, not histogrammed into a fake pmf."""
    with pytest.raises(EstimatorError, match="not\\s+fractional returns"):
        empirical_conditional(np.linspace(1, 100, 500), 20, signal="rank!",
                              conditioning={}, estimation_window="test")


def test_no_engine_accepts_an_ic_or_rank_as_an_economic_input():
    """Signature scan: the decision chain's entry points take a
    DistributionEstimate, never an ic/rank/score parameter that could be
    silently reinterpreted as expected return."""
    from apex.opportunity.engine import evaluate_opportunity
    from apex.expression.engine import evaluate as expr_evaluate
    for fn in (evaluate_opportunity, expr_evaluate):
        params = set(inspect.signature(fn).parameters)
        for banned in ("ic", "rank", "score", "sharpe", "t_stat"):
            assert banned not in params, (
                f"{fn.__qualname__} accepts {banned!r}: an identity-confusion "
                f"channel into the economics")


def test_cost_sensitivity_is_monotone_the_honest_direction():
    """The machine must never improve economics via cost optimism: net
    return is strictly non-increasing in spread and in turnover."""
    from apex.portfolio.capacity import assess_capacity
    base = dict(target_notional=1e6, addv_usd=4e7, expected_gross_annual=0.10)
    nets = [assess_capacity(**base, relative_spread=s, annual_turnover=1.0
                            ).expected_net_annual for s in (0.001, 0.01, 0.03)]
    assert nets[0] > nets[1] > nets[2]
    nets_t = [assess_capacity(**base, relative_spread=0.005, annual_turnover=t
                              ).expected_net_annual for t in (0.5, 2.0, 6.0)]
    assert nets_t[0] > nets_t[1] > nets_t[2]


def test_uncertainty_tightens_never_loosens():
    """Across the chain, uncertainty raises bars and restricts expression;
    it never relaxes anything. Spot-checked at the opportunity layer (the
    others are covered in their own suites and cited by the audit)."""
    from apex.opportunity.engine import MIN_NET_EDGE_ANNUAL, UNCERTAINTY_MULTIPLIER
    assert UNCERTAINTY_MULTIPLIER > 1.0
    assert MIN_NET_EDGE_ANNUAL * UNCERTAINTY_MULTIPLIER > MIN_NET_EDGE_ANNUAL
