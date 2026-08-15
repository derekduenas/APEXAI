"""Risk engine v1: DECLARED constraints with a first-class REJECT.

Limits are constraints, never hidden alpha selectors: nothing here reads a
return forecast, ranks candidates, or optimises weights. It answers one
question -- can the portfolio afford this position -- and refuses with named
reasons when it cannot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EVIDENCE_CLASS = "engineering_measurement"

# DECLARED limits. Changing one is a dated decision, not a convenience.
MAX_POSITION_WEIGHT = 0.05          # of portfolio NAV
MAX_SECTOR_WEIGHT = 0.25
MAX_PORTFOLIO_HEAT = 0.15           # sum(|w| * ann_vol) across the book
MAX_CORR_TO_EXISTING = 0.80         # candidate vs any existing sleeve
MAX_DRAWDOWN_BUDGET_USE = 0.25      # candidate worst-case loss vs remaining budget
DEFINED_RISK_ONLY = True            # options: no naked shorts, ever


@dataclass(frozen=True)
class PortfolioState:
    nav: float
    positions: dict                  # name -> weight
    sector_weights: dict             # sector -> weight
    heat: float                      # current sum(|w| * vol)
    drawdown_budget_left: float      # fraction of NAV we may still lose
    sleeve_correlations: dict        # sleeve -> corr of candidate to it


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reasons: tuple                   # empty when accepted
    risk_consumption: dict
    evidence_class: str = field(default=EVIDENCE_CLASS)


def assess_risk(*, weight: float, ann_vol: float, sector: str,
                worst_case_loss_frac: float, is_defined_risk: bool,
                portfolio: PortfolioState) -> RiskDecision:
    """Constraints only. REJECT is a first-class, fully-reasoned outcome."""
    reasons = []
    if weight > MAX_POSITION_WEIGHT:
        reasons.append(f"position weight {weight:.3f} > {MAX_POSITION_WEIGHT}")
    sec_after = portfolio.sector_weights.get(sector, 0.0) + weight
    if sec_after > MAX_SECTOR_WEIGHT:
        reasons.append(f"sector {sector} would reach {sec_after:.2f} "
                       f"> {MAX_SECTOR_WEIGHT}")
    heat_after = portfolio.heat + abs(weight) * ann_vol
    if heat_after > MAX_PORTFOLIO_HEAT:
        reasons.append(f"portfolio heat would reach {heat_after:.3f} "
                       f"> {MAX_PORTFOLIO_HEAT}")
    worst = abs(weight) * worst_case_loss_frac
    if portfolio.drawdown_budget_left <= 0 or \
            worst > MAX_DRAWDOWN_BUDGET_USE * portfolio.drawdown_budget_left:
        reasons.append(f"worst-case loss {worst:.4f} of NAV exceeds "
                       f"{MAX_DRAWDOWN_BUDGET_USE:.0%} of the remaining "
                       f"drawdown budget {portfolio.drawdown_budget_left:.3f}")
    hi_corr = {k: c for k, c in portfolio.sleeve_correlations.items()
               if abs(c) > MAX_CORR_TO_EXISTING}
    if hi_corr:
        reasons.append(f"correlation to existing sleeve(s) {hi_corr} "
                       f"> {MAX_CORR_TO_EXISTING}")
    if DEFINED_RISK_ONLY and not is_defined_risk:
        reasons.append("undefined-risk expression refused, without exception")

    return RiskDecision(
        accepted=not reasons, reasons=tuple(reasons),
        risk_consumption={
            "weight": weight, "heat_added": round(abs(weight) * ann_vol, 5),
            "heat_after": round(heat_after, 5),
            "worst_case_nav_loss": round(worst, 5),
            "sector_after": round(sec_after, 4),
        })
