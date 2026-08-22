"""OptionExpressionScorecard — F O15: the un-optimized outcome vector.
No magic weighted score. Pareto/dominance comparison happens over this
vector, never over a single collapsed number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

SCORECARD_FIELDS = (
    "mean_net_expectancy", "median_net_outcome", "expected_shortfall",
    "maximum_drawdown", "probability_of_loss", "worst_loss",
    "return_on_risk_capital", "capital_required", "spread_fee_drag",
    "latency_sensitivity", "iv_sensitivity", "tail_concentration",
    "option_minus_stock_net", "option_minus_no_trade_net",
)


class ScorecardError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptionExpressionScorecard:
    expression_type: str
    mean_net_expectancy: float | None
    median_net_outcome: float | None
    expected_shortfall: float | None
    maximum_drawdown: float | None
    probability_of_loss: float | None
    worst_loss: float | None
    return_on_risk_capital: float | None
    capital_required: float | None
    spread_fee_drag: float | None
    latency_sensitivity: float | None
    iv_sensitivity: float | None
    tail_concentration: float | None
    option_minus_stock_net: float | None
    option_minus_no_trade_net: float | None
    sample_size: int
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def as_record(self) -> dict:
        return {"kind": "option_expression_scorecard", **asdict(self)}

    def is_dominant_over(self, other: "OptionExpressionScorecard") -> bool | None:
        """Pareto dominance: True only if this scorecard is at least as
        good on EVERY comparable dimension and strictly better on at
        least one. None (UNKNOWN) if too many dimensions are missing on
        either side to judge honestly."""
        better_or_equal_on = 0
        strictly_better_on = 0
        comparable = 0
        # expected_shortfall / maximum_drawdown / worst_loss are stored as
        # NEGATIVE numbers (a loss) -- LESS NEGATIVE (i.e. numerically
        # HIGHER) is better, same direction as the P&L fields, not the
        # opposite. probability_of_loss/spread_fee_drag/latency_sensitivity/
        # iv_sensitivity/tail_concentration/capital_required are magnitudes
        # where smaller is genuinely better.
        higher_is_better = {"mean_net_expectancy": True, "median_net_outcome": True,
                            "return_on_risk_capital": True,
                            "option_minus_stock_net": True,
                            "option_minus_no_trade_net": True,
                            "expected_shortfall": True, "maximum_drawdown": True,
                            "worst_loss": True,
                            "probability_of_loss": False, "spread_fee_drag": False,
                            "latency_sensitivity": False,
                            "iv_sensitivity": False, "tail_concentration": False,
                            "capital_required": False}
        for field, hib in higher_is_better.items():
            a, b = getattr(self, field), getattr(other, field)
            if a is None or b is None:
                continue
            comparable += 1
            ok = (a >= b) if hib else (a <= b)
            strictly = (a > b) if hib else (a < b)
            if ok:
                better_or_equal_on += 1
            if strictly:
                strictly_better_on += 1
        if comparable < 3:
            return None
        return better_or_equal_on == comparable and strictly_better_on >= 1
