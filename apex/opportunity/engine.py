"""Evaluate, decide, rank. Every rejection path is named and tested.

DECLARED decision constants (changing one is a dated decision):
  MIN_NET_EDGE_ANNUAL      the same 2% bar the viability gates declared
  UNCERTAINTY_MULTIPLIER   an uncertain world state raises the bar, never
                           lowers it
  RISK_PENALTY             ranking penalises heat consumption; the score is
                           net-of-everything economics, not IC and not gross

GOVERNANCE BOUNDARIES CARRIED THROUGH:
  * a candidate without hypothesis lineage is refused (nothing untraceable
    is decidable);
  * SYNTHETIC distributions never produce a TRADE;
  * an OPTIONS expression requires a CALIBRATED distribution -- with less,
    the expression is forced back to common stock and the demotion recorded;
  * live_intent with an uncalibrated distribution is NO-TRADE: paper-grade
    decisions are marked as such and cannot quietly become live ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apex.distribution.estimator import (
    CalibrationStatus, DistributionEstimate, EstimatorError,
)
from apex.expression.engine import ExpressionInput, evaluate as evaluate_expression
from apex.portfolio.capacity import assess_capacity
from apex.portfolio.risk import PortfolioState, assess_risk

EVIDENCE_CLASS = "engineering_measurement"

MIN_NET_EDGE_ANNUAL = 0.02
UNCERTAINTY_MULTIPLIER = 1.5
RISK_PENALTY = 0.5
PERIODS_PER_YEAR = 252 / 20


@dataclass(frozen=True)
class Opportunity:
    name: str
    decision: str                    # "TRADE" | "NO-TRADE"
    reasons: tuple                   # why NO-TRADE, or empty
    hypothesis_lineage: str
    market_state: dict
    signal: dict
    distribution_status: str
    expression: str
    expression_demoted: bool         # options wanted, calibration lacking
    expected_gross_annual: float
    implementation_cost_annual: float
    expected_net_annual: float
    risk_consumption: dict
    capacity_usd: float
    confidence: str                  # "CALIBRATED" | "PAPER-GRADE (...)"
    governance_status: str
    economic_score: float
    evidence_class: str = field(default=EVIDENCE_CLASS)


def _no_trade(name, reasons, lineage="", state=None, signal=None,
              status="", governance="refused") -> Opportunity:
    return Opportunity(
        name=name, decision="NO-TRADE", reasons=tuple(reasons),
        hypothesis_lineage=lineage, market_state=state or {},
        signal=signal or {}, distribution_status=status, expression="none",
        expression_demoted=False, expected_gross_annual=0.0,
        implementation_cost_annual=0.0, expected_net_annual=0.0,
        risk_consumption={}, capacity_usd=0.0, confidence="n/a",
        governance_status=governance, economic_score=float("-inf"))


def evaluate_opportunity(*, name: str, hypothesis_lineage: str,
                         market_state: dict, signal: dict,
                         estimate: DistributionEstimate | None,
                         chain: tuple, spot: float, expression_config,
                         weight: float, ann_vol: float, sector: str,
                         portfolio: PortfolioState,
                         target_notional: float, addv_usd: float,
                         relative_spread: float, annual_turnover: float,
                         live_intent: bool = False) -> Opportunity:
    # 1. governance: nothing untraceable is decidable
    if not hypothesis_lineage:
        return _no_trade(name, ["governance violation: no hypothesis lineage; "
                                "an untraceable claim cannot be decided"])
    if estimate is None:
        return _no_trade(name, ["insufficient evidence: no admissible "
                                "distribution estimate"], hypothesis_lineage)

    status = estimate.calibration_status
    if status is CalibrationStatus.SYNTHETIC:
        return _no_trade(name, ["inadequate calibration: SYNTHETIC "
                                "distributions never trade"],
                         hypothesis_lineage, market_state, signal, status.value)
    if live_intent and status is not CalibrationStatus.CALIBRATED:
        return _no_trade(name, [f"inadequate calibration for LIVE intent: "
                                f"{status.value}; paper-grade only"],
                         hypothesis_lineage, market_state, signal, status.value)

    # 2. expression -- options demand calibration; stock does not
    report = evaluate_expression(
        ExpressionInput(horizon_days=estimate.horizon_days,
                        returns=estimate.returns, probs=estimate.probs,
                        distribution_source=estimate.expression_source(),
                        chain=chain, spot=spot),
        expression_config)
    expression, demoted = report.selection, False
    if expression != "common_stock" and status is not CalibrationStatus.CALIBRATED:
        expression, demoted = "common_stock", True

    # 3. risk -- constraints, never selectors
    worst_case = abs(float(estimate.returns.min()))
    risk = assess_risk(weight=weight, ann_vol=ann_vol, sector=sector,
                       worst_case_loss_frac=worst_case,
                       is_defined_risk=True, portfolio=portfolio)
    if not risk.accepted:
        return _no_trade(name, [f"excessive risk: {r}" for r in risk.reasons],
                         hypothesis_lineage, market_state, signal, status.value)

    # 4. capacity and implementation -- costs flow INTO the economics
    gross_annual = estimate.expected_return() * PERIODS_PER_YEAR
    cap = assess_capacity(target_notional=target_notional, addv_usd=addv_usd,
                          relative_spread=relative_spread,
                          annual_turnover=annual_turnover,
                          expected_gross_annual=gross_annual)
    if not cap.tradeable:
        return _no_trade(name, [f"capacity/cost: {r}" for r in cap.reasons],
                         hypothesis_lineage, market_state, signal, status.value)

    # 5. the bar -- raised, never lowered, when the world state is uncertain
    bar = MIN_NET_EDGE_ANNUAL
    if market_state.get("uncertain", False):
        bar *= UNCERTAINTY_MULTIPLIER
    if cap.expected_net_annual < bar:
        return _no_trade(
            name, [f"insufficient expected net edge: {cap.expected_net_annual:+.2%}"
                   f" < bar {bar:.2%}"
                   + (" (raised: world state uncertain)"
                      if market_state.get("uncertain") else "")],
            hypothesis_lineage, market_state, signal, status.value)

    score = cap.expected_net_annual - RISK_PENALTY * risk.risk_consumption["heat_added"]
    confidence = ("CALIBRATED" if status is CalibrationStatus.CALIBRATED
                  else f"PAPER-GRADE ({status.value})")
    return Opportunity(
        name=name, decision="TRADE", reasons=(),
        hypothesis_lineage=hypothesis_lineage, market_state=dict(market_state),
        signal=dict(signal), distribution_status=status.value,
        expression=expression, expression_demoted=demoted,
        expected_gross_annual=round(gross_annual, 5),
        implementation_cost_annual=round(gross_annual - cap.expected_net_annual, 5),
        expected_net_annual=cap.expected_net_annual,
        risk_consumption=risk.risk_consumption,
        capacity_usd=cap.capacity_usd, confidence=confidence,
        governance_status="paper-grade" if demoted or
                          status is not CalibrationStatus.CALIBRATED else "clean",
        economic_score=round(score, 5))


def rank(opportunities) -> list:
    """Economic score only: net-of-everything minus a risk-heat penalty.
    NO-TRADEs sink to the bottom and are RETAINED -- the report shows what
    was refused and why, or the ranking is a survivor gallery."""
    return sorted(opportunities, key=lambda o: o.economic_score, reverse=True)


def render_report(opportunities) -> str:
    lines = ["APEX OPPORTUNITY REPORT", "=" * 60]
    ranked = rank(opportunities)
    trades = [o for o in ranked if o.decision == "TRADE"]
    if not trades:
        lines.append("")
        lines.append("NO TRADE. Nothing cleared the bar; the reasons follow.")
    for i, o in enumerate(ranked, 1):
        lines += ["", f"#{i}  {o.name}  --  {o.decision}"]
        if o.decision == "TRADE":
            lines += [
                f"    lineage:     {o.hypothesis_lineage}",
                f"    state:       {o.market_state.get('regime', '?')}"
                f"{' (uncertain)' if o.market_state.get('uncertain') else ''}",
                f"    expression:  {o.expression}"
                f"{' (demoted from options: uncalibrated)' if o.expression_demoted else ''}",
                f"    gross:       {o.expected_gross_annual:+.2%}/yr",
                f"    impl. cost:  {o.implementation_cost_annual:.2%}/yr",
                f"    NET:         {o.expected_net_annual:+.2%}/yr",
                f"    risk:        heat +{o.risk_consumption.get('heat_added', 0):.4f}",
                f"    capacity:    ${o.capacity_usd:,.0f}",
                f"    confidence:  {o.confidence}",
                f"    governance:  {o.governance_status}",
            ]
        else:
            for r in o.reasons:
                lines.append(f"    refused: {r}")
    return "\n".join(lines)
