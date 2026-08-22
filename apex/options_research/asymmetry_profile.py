"""AsymmetryProfile — Doctrine section 1/4/7: every options candidate's
payoff shape, in R-multiples, computed from REAL resolved outcomes
only. Distinguishes VOLATILITY (a wide but BOUNDED payoff range) from
RUIN RISK (an UNDEFINED/unbounded loss) -- a volatile, defined-loss
option is not the same hazard as an unbounded short position, and this
module refuses to conflate them.

Nothing here is fabricated: with zero resolved outcomes, every derived
statistic is None (INSUFFICIENT_SAMPLE), never a guessed number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

RISK_CHARACTERS = ("BOUNDED_VOLATILITY", "UNDEFINED_RUIN_EXPOSURE", "UNKNOWN")

# doctrine section 7: distinguish healthy convexity from a strategy that
# depends on one freak winner.
FRAGILE_TAIL_DEPENDENCE_THRESHOLD = 0.50   # >50% of total edge from top 1%
MIN_SAMPLE_FOR_TAIL_JUDGMENT = 10


class AsymmetryProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class AsymmetryProfile:
    subject: str
    expression_type: str
    risk_character: str              # BOUNDED_VOLATILITY / UNDEFINED_RUIN_EXPOSURE / UNKNOWN
    loss_cap: float | None
    payoff_convexity: str            # CONVEX / LINEAR / CONCAVE / UNKNOWN
    probability_of_total_premium_loss: float | None
    capital_efficiency: float | None
    return_on_risk_capital: float | None
    sample_size: int
    expectancy_r: float | None
    median_r: float | None
    win_rate: float | None
    avg_win_r: float | None
    avg_loss_r: float | None
    payoff_ratio: float | None
    right_tail_contribution: float | None    # share of total expectancy from top 1%
    left_tail_contribution: float | None
    p_r_ge_2: float | None
    p_r_ge_3: float | None
    p_r_ge_5: float | None
    p_r_ge_10: float | None
    tail_dependence_flag: str        # HEALTHY_CONVEXITY / FRAGILE_TAIL_DEPENDENCE / UNKNOWN
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.risk_character not in RISK_CHARACTERS:
            raise AsymmetryProfileError(f"unknown risk_character {self.risk_character!r}")

    def as_record(self) -> dict:
        return {"kind": "asymmetry_profile", **asdict(self)}


def classify_risk_character(*, loss_cap: float | None) -> str:
    """The doctrine's core distinction: RUIN RISK is about an UNDEFINED
    loss, not about payoff variance. A defined loss_cap -- however
    volatile the P&L path within it -- is BOUNDED_VOLATILITY, never
    UNDEFINED_RUIN_EXPOSURE."""
    if loss_cap is None:
        return "UNDEFINED_RUIN_EXPOSURE"
    return "BOUNDED_VOLATILITY"


def _tail_dependence(r_multiples: tuple, right_tail_contribution: float | None) -> str:
    if len(r_multiples) < MIN_SAMPLE_FOR_TAIL_JUDGMENT or right_tail_contribution is None:
        return "UNKNOWN"
    return ("FRAGILE_TAIL_DEPENDENCE" if right_tail_contribution > FRAGILE_TAIL_DEPENDENCE_THRESHOLD
           else "HEALTHY_CONVEXITY")


def build_from_outcomes(*, subject: str, expression_type: str, loss_cap: float | None,
                        payoff_convexity: str, r_multiples: tuple, known_from,
                        capital_efficiency: float | None = None,
                        return_on_risk_capital: float | None = None,
                        probability_of_total_premium_loss: float | None = None
                        ) -> AsymmetryProfile:
    """`r_multiples`: realized R-multiples from resolved
    OptionExpressionOutcome records -- this function computes nothing
    from raw prices itself. An empty tuple yields an honest
    all-statistics-None profile, not fabricated defaults."""
    import pandas as pd
    n = len(r_multiples)
    kf = str(pd.Timestamp(known_from))
    risk_character = classify_risk_character(loss_cap=loss_cap)

    if n == 0:
        return AsymmetryProfile(
            subject=subject, expression_type=expression_type, risk_character=risk_character,
            loss_cap=loss_cap, payoff_convexity=payoff_convexity,
            probability_of_total_premium_loss=probability_of_total_premium_loss,
            capital_efficiency=capital_efficiency, return_on_risk_capital=return_on_risk_capital,
            sample_size=0, expectancy_r=None, median_r=None, win_rate=None, avg_win_r=None,
            avg_loss_r=None, payoff_ratio=None, right_tail_contribution=None,
            left_tail_contribution=None, p_r_ge_2=None, p_r_ge_3=None, p_r_ge_5=None,
            p_r_ge_10=None, tail_dependence_flag="UNKNOWN", known_from=kf)

    sorted_r = sorted(r_multiples)
    wins = [r for r in r_multiples if r > 0]
    losses = [r for r in r_multiples if r <= 0]
    expectancy = sum(r_multiples) / n
    median = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2
    win_rate = len(wins) / n
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    payoff_ratio = (avg_win / abs(avg_loss)) if (avg_win is not None and avg_loss not in (None, 0)) else None

    total_positive = sum(r for r in r_multiples if r > 0)
    total_negative = sum(r for r in r_multiples if r < 0)
    top1_n = max(1, round(n * 0.01))
    top1_sum = sum(sorted_r[-top1_n:])
    right_tail_contribution = (top1_sum / total_positive) if total_positive > 0 else None
    left_tail_contribution = (abs(sum(sorted_r[:top1_n])) / abs(total_negative)) if total_negative < 0 else None

    p_ge = lambda t: sum(1 for r in r_multiples if r >= t) / n  # noqa: E731

    return AsymmetryProfile(
        subject=subject, expression_type=expression_type, risk_character=risk_character,
        loss_cap=loss_cap, payoff_convexity=payoff_convexity,
        probability_of_total_premium_loss=probability_of_total_premium_loss,
        capital_efficiency=capital_efficiency, return_on_risk_capital=return_on_risk_capital,
        sample_size=n, expectancy_r=expectancy, median_r=median, win_rate=win_rate,
        avg_win_r=avg_win, avg_loss_r=avg_loss, payoff_ratio=payoff_ratio,
        right_tail_contribution=right_tail_contribution,
        left_tail_contribution=left_tail_contribution,
        p_r_ge_2=p_ge(2), p_r_ge_3=p_ge(3), p_r_ge_5=p_ge(5), p_r_ge_10=p_ge(10),
        tail_dependence_flag=_tail_dependence(r_multiples, right_tail_contribution),
        known_from=kf)
