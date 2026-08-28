"""THE RISK KERNEL — the survival instinct. It sits BELOW the arena.

Capital Arena decides which opportunity deserves the next paper
dollar. This kernel decides whether the book can AFFORD it, and the
arena cannot override a kernel refusal -- allocation intelligence and
survival constraints are different organs on purpose. The same
philosophy as apex/portfolio/risk.py ("limits are constraints, never
hidden alpha selectors; a first-class REJECT with named reasons"),
restated here in the declared-1R terms the paper book actually uses
rather than that module's factor-portfolio weights.

Limits are PREDECLARED, dollar-denominated, and not tuned in this
project or from any observed outcome. Provenance: sized against the
incumbent evidence -- observed declared_1R has run 301..335 and the
shadow budget law fixed 300 -- and then set conservatively. Changing
one is a dated, operator-approved decision.

decision_power: STRUCTURAL_VETO_ONLY -- the kernel can only say no.
"""
from __future__ import annotations

THRESHOLD_SET = "ORGANISM_PAPER_V1"

STARTING_PAPER_CAPITAL = 10_000.0
MAX_RISK_PER_TRADE = 500.0        # covers every incumbent declared_1R
MAX_AGGREGATE_OPEN_RISK = 1_500.0  # three concurrent full-size stakes
MAX_SAME_UNDERLYING_RISK = 600.0
MAX_SAME_FAMILY_RISK = 1_000.0    # one beta family is one bet
SESSION_DRAWDOWN_HALT = 1_000.0   # -10 percent of start = stop funding

LIMITS = {"max_risk_per_trade": MAX_RISK_PER_TRADE,
          "max_aggregate_open_risk": MAX_AGGREGATE_OPEN_RISK,
          "max_same_underlying_risk": MAX_SAME_UNDERLYING_RISK,
          "max_same_family_risk": MAX_SAME_FAMILY_RISK,
          "session_drawdown_halt": SESSION_DRAWDOWN_HALT}


def check(*, declared_risk: float, symbol: str, beta_family: str,
          open_risk: float, same_underlying_risk: float,
          same_family_risk: float, session_realized_pnl: float,
          available_capital: float) -> dict:
    """One candidate against every survival constraint. Every refusal
    names its limit; the arena cannot argue with any of them."""
    refusals = []

    if declared_risk > MAX_RISK_PER_TRADE:
        refusals.append(f"declared_risk {declared_risk:.2f} exceeds "
                        f"max_risk_per_trade {MAX_RISK_PER_TRADE:.2f}")
    if open_risk + declared_risk > MAX_AGGREGATE_OPEN_RISK:
        refusals.append(f"aggregate open risk would reach "
                        f"{open_risk + declared_risk:.2f} > "
                        f"{MAX_AGGREGATE_OPEN_RISK:.2f}")
    if same_underlying_risk + declared_risk > MAX_SAME_UNDERLYING_RISK:
        refusals.append(f"{symbol} risk would reach "
                        f"{same_underlying_risk + declared_risk:.2f} > "
                        f"{MAX_SAME_UNDERLYING_RISK:.2f}")
    if beta_family != "UNKNOWN" and \
            same_family_risk + declared_risk > MAX_SAME_FAMILY_RISK:
        refusals.append(f"{beta_family} family risk would reach "
                        f"{same_family_risk + declared_risk:.2f} > "
                        f"{MAX_SAME_FAMILY_RISK:.2f}")
    if session_realized_pnl <= -SESSION_DRAWDOWN_HALT:
        refusals.append(f"session drawdown "
                        f"{session_realized_pnl:.2f} has breached the "
                        f"halt {-SESSION_DRAWDOWN_HALT:.2f}: no new "
                        f"funding this session")
    if declared_risk > available_capital:
        refusals.append(f"declared_risk {declared_risk:.2f} exceeds "
                        f"available capital {available_capital:.2f}")

    return {"kind": "risk_kernel_check",
            "threshold_set": THRESHOLD_SET,
            "approved": not refusals,
            "refusals": refusals,
            "law": "the kernel only says no; allocation intelligence "
                   "lives above it and cannot override it",
            "decision_power": "STRUCTURAL_VETO_ONLY"}
