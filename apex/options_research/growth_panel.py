"""Account-growth research panel — Doctrine section 5. For each named
risk tier (0.25%..2.00%, RESEARCH SCENARIOS, never production sizing),
bootstrap-resample the REAL realized R-multiple sequence to estimate
geometric growth, drawdown, and ruin risk under fixed-fractional
sizing. This exists to answer "how fast could this edge compound
without becoming fragile", never to recommend a live risk fraction --
every GrowthScenario hardcodes sizing_authority="NONE".

With zero realized R-multiples (the honest state of Options Research
v1 today, before any prospective outcome has resolved) every scenario
is returned as INSUFFICIENT_SAMPLE with every statistic None -- this
module never substitutes an assumed or synthetic return distribution.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER
from apex.options_research.asymmetric_growth_doctrine import (
    GROWTH_RESEARCH_LABEL, GROWTH_RESEARCH_RISK_TIERS_PCT)

DEFAULT_N_BOOTSTRAP = 500
DEFAULT_SEED = 20260818
RUIN_THRESHOLD_EQUITY_FRACTION = 0.20   # equity falling to <=20% of start = ruin


class GrowthPanelError(RuntimeError):
    pass


@dataclass(frozen=True)
class GrowthScenario:
    risk_pct: float
    sample_size: int
    n_bootstrap_paths: int
    geometric_growth_rate_per_trade: float | None
    maximum_drawdown: float | None
    expected_shortfall: float | None
    risk_of_10pct_drawdown: float | None
    risk_of_20pct_drawdown: float | None
    risk_of_30pct_drawdown: float | None
    risk_of_ruin: float | None
    loss_streak_behavior: int | None       # longest observed losing streak, real sample
    time_to_recovery_trades: float | None
    capital_utilization: float
    label: str
    sizing_authority: str
    known_from: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.label != GROWTH_RESEARCH_LABEL:
            raise GrowthPanelError("a GrowthScenario must carry the research-only label")
        if self.sizing_authority != "NONE":
            raise GrowthPanelError("a GrowthScenario may never carry sizing authority")

    def as_record(self) -> dict:
        return {"kind": "growth_scenario", **asdict(self)}


def _longest_losing_streak(r_multiples: tuple) -> int:
    longest = current = 0
    for r in r_multiples:
        if r < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _simulate_path(r_multiples: tuple, risk_frac: float, rng: random.Random) -> dict:
    equity, peak, max_dd = 1.0, 1.0, 0.0
    in_drawdown_since = None
    recovery_lengths = []
    ruin = False
    for i in range(len(r_multiples)):
        r = rng.choice(r_multiples)
        equity *= max(0.0, 1 + risk_frac * r)
        if equity > peak:
            if in_drawdown_since is not None:
                recovery_lengths.append(i - in_drawdown_since)
                in_drawdown_since = None
            peak = equity
        else:
            if in_drawdown_since is None:
                in_drawdown_since = i
        dd = 1 - (equity / peak) if peak > 0 else 1.0
        max_dd = max(max_dd, dd)
        if equity <= RUIN_THRESHOLD_EQUITY_FRACTION:
            ruin = True
    final_return = equity - 1.0
    return {"final_return": final_return, "max_drawdown": max_dd, "ruin": ruin,
           "recovery_lengths": recovery_lengths}


def simulate_growth_panel(*, r_multiples: tuple, known_from,
                          n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
                          seed: int = DEFAULT_SEED) -> tuple:
    import pandas as pd
    kf = str(pd.Timestamp(known_from))
    n = len(r_multiples)
    out = []
    for pct in GROWTH_RESEARCH_RISK_TIERS_PCT:
        if n == 0:
            out.append(GrowthScenario(
                risk_pct=pct, sample_size=0, n_bootstrap_paths=0,
                geometric_growth_rate_per_trade=None, maximum_drawdown=None,
                expected_shortfall=None, risk_of_10pct_drawdown=None,
                risk_of_20pct_drawdown=None, risk_of_30pct_drawdown=None,
                risk_of_ruin=None, loss_streak_behavior=None,
                time_to_recovery_trades=None, capital_utilization=pct,
                label=GROWTH_RESEARCH_LABEL, sizing_authority="NONE", known_from=kf))
            continue

        rng = random.Random(f"{seed}:{pct}")
        risk_frac = pct / 100.0
        paths = [_simulate_path(r_multiples, risk_frac, rng) for _ in range(n_bootstrap)]
        final_returns = sorted(p["final_return"] for p in paths)
        drawdowns = [p["max_drawdown"] for p in paths]
        worst_5pct_n = max(1, round(n_bootstrap * 0.05))
        expected_shortfall = sum(final_returns[:worst_5pct_n]) / worst_5pct_n
        all_recoveries = [rl for p in paths for rl in p["recovery_lengths"]]

        out.append(GrowthScenario(
            risk_pct=pct, sample_size=n, n_bootstrap_paths=n_bootstrap,
            geometric_growth_rate_per_trade=sum(final_returns) / n_bootstrap / n,
            maximum_drawdown=sum(drawdowns) / n_bootstrap,
            expected_shortfall=expected_shortfall,
            risk_of_10pct_drawdown=sum(1 for d in drawdowns if d >= 0.10) / n_bootstrap,
            risk_of_20pct_drawdown=sum(1 for d in drawdowns if d >= 0.20) / n_bootstrap,
            risk_of_30pct_drawdown=sum(1 for d in drawdowns if d >= 0.30) / n_bootstrap,
            risk_of_ruin=sum(1 for p in paths if p["ruin"]) / n_bootstrap,
            loss_streak_behavior=_longest_losing_streak(r_multiples),
            time_to_recovery_trades=(sum(all_recoveries) / len(all_recoveries)
                                     if all_recoveries else None),
            capital_utilization=pct, label=GROWTH_RESEARCH_LABEL,
            sizing_authority="NONE", known_from=kf))
    return tuple(out)
