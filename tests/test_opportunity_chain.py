"""THE integration proof: the complete decision chain speaks, end to end.

    candidate -> world state -> distribution -> expression -> risk ->
    capacity -> costs -> opportunity -> TRADE

...and eight adversarial candidates each terminate in NO-TRADE through
their own named rejection path. Synthetic and structurally realistic; no
validation/holdout data, no credit, no live wiring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.distribution.estimator import (
    CalibrationStatus, DistributionEstimate, EstimatorError,
    empirical_conditional, mint_calibrated,
)
from apex.expression.engine import OptionQuote
from apex.opportunity.engine import (
    Opportunity, evaluate_opportunity, rank, render_report,
)
from apex.portfolio.risk import PortfolioState
from apex.world.state import classify_online

EXPR_CFG = load_config("expression")


def _world():
    """A synthetic but realistic world: SPY series and its ONLINE state."""
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2020-01-01", periods=1500)
    spy = pd.Series(100 * np.cumprod(1 + rng.normal(4e-4, 0.009, 1500)),
                    index=days)
    return classify_online(spy, days[-1])


def _estimate(mean=0.012, sd=0.06, n=800, seed=1):
    rng = np.random.default_rng(seed)
    return empirical_conditional(
        rng.normal(mean, sd, n), horizon_days=20,
        signal="gp_rank top decile", conditioning={"regime": "CALM_UP"},
        estimation_window="in-sample 2005-2017")


def _portfolio():
    return PortfolioState(nav=100_000.0, positions={}, sector_weights={},
                          heat=0.02, drawdown_budget_left=0.20,
                          sleeve_correlations={"H1-A": 0.3})


def _chain(spot=100.0):
    return (OptionQuote("call", 100, 20, 3.0, 3.2, 0.30, 800, 300),
            OptionQuote("put", 100, 20, 3.0, 3.2, 0.30, 800, 300),
            OptionQuote("call", 105, 20, 1.2, 1.4, 0.31, 500, 200),
            OptionQuote("put", 95, 20, 1.2, 1.4, 0.31, 500, 200))


def _evaluate(name="candidate", **overrides):
    kw = dict(name=name, hypothesis_lineage="dossier 97da989a / APEX-004 line",
              market_state=_world(), signal={"gp_rank_pct": 0.95},
              estimate=_estimate(), chain=_chain(), spot=100.0,
              expression_config=EXPR_CFG, weight=0.03, ann_vol=0.25,
              sector="TECH", portfolio=_portfolio(),
              target_notional=3_000_000.0, addv_usd=40_000_000.0,
              relative_spread=0.002, annual_turnover=0.8)
    kw.update(overrides)
    return evaluate_opportunity(**kw)


# --- the TRADE path ----------------------------------------------------------

def test_the_complete_chain_produces_a_reasoned_trade():
    opp = _evaluate()
    assert opp.decision == "TRADE", opp.reasons
    assert opp.expected_net_annual > 0.02
    assert opp.implementation_cost_annual > 0, "costs must be nonzero and real"
    assert opp.distribution_status == "HISTORICAL_EMPIRICAL"
    assert opp.confidence.startswith("PAPER-GRADE"), (
        "an uncalibrated distribution must not read as calibrated confidence")
    assert opp.capacity_usd > 0 and opp.risk_consumption["heat_added"] > 0
    assert "TRADE" in render_report([opp])


def test_evidence_the_modules_actually_connect():
    """Chain-connection evidence: the state came from apex/world, the pmf
    from apex/distribution, the expression from apex/expression, risk and
    capacity from apex/portfolio -- one object carries all of them."""
    opp = _evaluate()
    assert opp.market_state["regime"] in ("CALM_UP", "CALM_DOWN",
                                          "VOL_UP", "VOL_DOWN")
    assert "methodology" not in opp.signal          # provenance lives on the estimate
    assert opp.expression in ("common_stock",)      # uncalibrated -> stock only
    assert opp.evidence_class == "engineering_measurement"


# --- the eight NO-TRADE paths ------------------------------------------------

def test_no_trade_on_insufficient_net_edge():
    opp = _evaluate(estimate=_estimate(mean=0.0055))  # nets +1.58%
    assert opp.decision == "NO-TRADE"
    assert any("insufficient expected net edge" in r for r in opp.reasons)


def test_no_trade_on_inadequate_calibration_for_live_intent():
    opp = _evaluate(live_intent=True)
    assert opp.decision == "NO-TRADE"
    assert any("inadequate calibration for LIVE intent" in r for r in opp.reasons)


def test_no_trade_on_synthetic_distribution_always():
    est = _estimate()
    synth = DistributionEstimate(
        returns=est.returns, probs=est.probs, horizon_days=20,
        calibration_status=CalibrationStatus.SYNTHETIC,
        provenance=est.provenance, calibration_evidence=None)
    opp = _evaluate(estimate=synth)
    assert opp.decision == "NO-TRADE"
    assert any("SYNTHETIC distributions never trade" in r for r in opp.reasons)


def test_no_trade_on_excessive_risk():
    opp = _evaluate(weight=0.20)
    assert opp.decision == "NO-TRADE"
    assert any("excessive risk" in r for r in opp.reasons)


def test_no_trade_on_insufficient_capacity():
    opp = _evaluate(addv_usd=200_000.0)         # tiny name, big notional
    assert opp.decision == "NO-TRADE"
    assert any("capacity/cost" in r for r in opp.reasons)


def test_no_trade_when_costs_consume_the_edge():
    opp = _evaluate(relative_spread=0.06, annual_turnover=6.0,
                    estimate=_estimate(mean=0.006))
    assert opp.decision == "NO-TRADE"
    assert any("consumes the edge" in r or "insufficient expected net edge" in r
               for r in opp.reasons)


def test_no_trade_when_regime_uncertainty_raises_the_bar():
    state = dict(_world(), uncertain=True)
    borderline = _estimate(mean=0.0065)          # nets +2.84%: above 2%, below 3%
    certain = _evaluate(market_state=dict(state, uncertain=False),
                        estimate=borderline)
    uncertain = _evaluate(market_state=state, estimate=borderline)
    assert certain.decision == "TRADE"
    assert uncertain.decision == "NO-TRADE"
    assert any("raised: world state uncertain" in r for r in uncertain.reasons)


def test_no_trade_on_governance_violation():
    opp = _evaluate(hypothesis_lineage="")
    assert opp.decision == "NO-TRADE"
    assert any("governance violation" in r for r in opp.reasons)


def test_no_trade_on_insufficient_evidence():
    with pytest.raises(EstimatorError, match="too few"):
        _estimate(n=40)                          # the estimator itself refuses
    opp = _evaluate(estimate=None)               # and the engine refuses None
    assert opp.decision == "NO-TRADE"
    assert any("insufficient evidence" in r for r in opp.reasons)


# --- governance boundaries carried through -----------------------------------

def test_options_expression_is_demoted_without_calibration():
    """A crash-or-moon view WANTS a call; without a CALIBRATED distribution
    the engine forces stock and records the demotion."""
    grid = np.linspace(-0.30, 0.34, 65)
    p = (np.exp(-0.5 * ((grid + 0.25) / 0.03) ** 2)
         + 1.3 * np.exp(-0.5 * ((grid - 0.25) / 0.03) ** 2))
    est = DistributionEstimate(
        returns=grid, probs=p / p.sum(), horizon_days=20,
        calibration_status=CalibrationStatus.HISTORICAL_EMPIRICAL,
        provenance={"methodology": "test"}, calibration_evidence=None)
    opp = _evaluate(estimate=est)
    if opp.decision == "TRADE":
        assert opp.expression == "common_stock"
        assert opp.expression_demoted, "the demotion must be recorded"


def test_calibrated_cannot_be_minted_without_reality_evidence(tmp_path):
    import json
    report = tmp_path / "calibration_report.json"
    # SAC1-01: provenance is checked BEFORE sample size -- evidence of
    # unknown origin is not weighed at all. Declare a legal forward class
    # so this test still probes what it was written to probe.
    report.write_text(json.dumps({
        "evidence_class": "EODHD_FORWARD_OBSERVATION",
        "producers": {"gp_rank": {
            "n_effective_dates": 3, "reliability": 0.002}}}))
    with pytest.raises(EstimatorError, match="cannot be hurried"):
        mint_calibrated(_estimate(), report, "gp_rank")
    # SAC1-01: provenance is checked BEFORE sample size -- evidence of
    # unknown origin is not weighed at all. Declare a legal forward class
    # so this test still probes what it was written to probe.
    report.write_text(json.dumps({
        "evidence_class": "EODHD_FORWARD_OBSERVATION",
        "producers": {"gp_rank": {
            "n_effective_dates": 25, "reliability": 0.002}}}))
    upgraded = mint_calibrated(_estimate(), report, "gp_rank")
    assert upgraded.calibration_status is CalibrationStatus.CALIBRATED


# --- ranking is economic, and NO-TRADE is retained ---------------------------

def test_ranking_is_by_net_economics_not_gross():
    """Candidate A: bigger gross, brutal costs. Candidate B: smaller gross,
    cheap to implement. B must outrank A -- gross-chasing is the failure."""
    a = _evaluate("A_big_gross_costly", estimate=_estimate(mean=0.02, seed=2),
                  relative_spread=0.03, annual_turnover=5.0)
    b = _evaluate("B_modest_cheap", estimate=_estimate(mean=0.010, seed=3),
                  relative_spread=0.001, annual_turnover=0.5)
    ranked = rank([a, b])
    assert ranked[0].name == "B_modest_cheap"


def test_the_report_can_say_no_trade_and_keeps_refusals():
    opps = [_evaluate("x", estimate=_estimate(mean=0.001)),
            _evaluate("y", hypothesis_lineage="")]
    text = render_report(opps)
    assert "NO TRADE." in text
    assert "refused:" in text, "refusals must appear, not vanish"
