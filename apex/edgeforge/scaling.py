"""SCALING — WHY_SMALL_WINS 2.0 and the Capital Evolution Simulator.

Phases 15-17.

WHY_SMALL_WINS 2.0 (15) turns "we're small so we're nimble" from a
comforting slogan into a tested proposition. The test is mechanical:
push notional up and watch what the market does to the edge. If the
edge survives at institutional size, it is not ours -- it is everyone's,
and better-resourced participants will have found it first.

CAPITAL EVOLUTION (16) simulates account paths, and its single most
important refusal is IID. Trades cluster: by regime, by underlying, by
factor, by session. An IID simulator produces a beautiful smooth
compounding curve and understates drawdown badly -- precisely the error
that ruins small accounts that believed their own backtest.

NO BLIND KELLY (17). Kelly assumes the edge is known. Ours is
estimated, and estimation error in the numerator becomes leverage in
the position. A fractional-Kelly reference is reported alongside the
estimation error that should shrink it, never as a sizing instruction.

decision_power: NONE_RESEARCH. Sizes nothing. Authorizes nothing.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

SCALE_VERDICTS = ("SMALL_ACCOUNT_ADVANTAGE", "NEUTRAL_SCALE",
                  "INSTITUTIONAL_ADVANTAGE", "UNKNOWN")

RESEARCH_SCALES = (5_000, 10_000, 25_000, 50_000, 100_000, 250_000,
                   500_000, 1_000_000)


class ScalingViolation(RuntimeError):
    pass


# ==================================================== PHASE 15

def scale_response(*, base_edge_per_unit: float, touch_liquidity: float,
                   spread: float, unit_notional: float,
                   sizes: tuple = RESEARCH_SCALES,
                   impact_coefficient: float = 0.5,
                   signal_half_life_min: float | str = NOT_ESTIMABLE
                   ) -> dict:
    """Push notional up and measure what the market takes back.

    Impact is modelled as a square-root-of-participation cost -- a
    conventional, deliberately crude proxy. It is labelled a PROXY
    because a precise impact model we have not validated would be a
    false precision worse than a rough one honestly named."""
    if touch_liquidity <= 0 or unit_notional <= 0:
        raise ScalingViolation("liquidity and unit notional must be > 0")
    rows = []
    for acct in sizes:
        deploy = acct * 0.10                     # research convention
        units = deploy / unit_notional
        participation = units / touch_liquidity
        impact = impact_coefficient * spread * math.sqrt(
            max(participation, 0.0))
        net = base_edge_per_unit - impact
        rows.append({
            "account": acct, "deployed": round(deploy, 2),
            "units": round(units, 3),
            "participation_of_touch": round(participation, 4),
            "impact_cost_per_unit_PROXY": round(impact, 6),
            "net_edge_per_unit": round(net, 6),
            "edge_retained_fraction": (round(net / base_edge_per_unit, 4)
                                       if base_edge_per_unit else
                                       NOT_ESTIMABLE)})

    small = rows[0]["net_edge_per_unit"]
    large = rows[-1]["net_edge_per_unit"]
    if base_edge_per_unit <= 0:
        verdict = "UNKNOWN"
        why = "no positive base edge to scale"
    elif large <= 0 < small:
        verdict = "SMALL_ADVANTAGE_INDICATED"
        why = (f"the edge survives at ${sizes[0]:,} and is gone by "
               f"${sizes[-1]:,}: capacity is the moat")
    elif large / base_edge_per_unit > 0.9:
        verdict = "INSTITUTIONAL_ADVANTAGE"
        why = ("the edge barely decays with size, so it is not ours -- "
               "better-resourced participants have no reason to have "
               "missed it")
    else:
        verdict = "NEUTRAL_SCALE"
        why = "partial decay; no decisive capacity advantage"

    return {"kind": "scale_response", "rows": rows,
            "verdict": verdict, "why": why,
            "signal_half_life_min": signal_half_life_min,
            "impact_model": "sqrt-participation PROXY, unvalidated",
            "law": "smallness is not automatically an advantage; an "
                   "edge that survives at institutional size is not "
                   "ours",
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 16

@dataclass
class CapitalPathResult:
    scale: float
    ending_equity_median: float
    geometric_growth_median: float
    max_drawdown_median: float
    max_drawdown_p95: float
    drawdown_duration_median: int
    risk_of_ruin: float
    time_under_water_fraction: float
    capital_utilization: float
    n_paths: int

    def as_record(self) -> dict:
        return asdict(self)


def simulate_capital_paths(*, r_multiples: list, risk_fraction: float,
                           trades_per_path: int, n_paths: int,
                           starting_equity: float, seed: int = 0,
                           cluster_len: int = 5,
                           ruin_fraction: float = 0.5) -> dict:
    """Account paths with CLUSTERED outcomes, never IID.

    Blocks of consecutive historical R-multiples are resampled so that
    losing streaks survive into the simulation. IID resampling breaks
    exactly the dependence that produces the drawdowns which actually
    end small accounts."""
    from apex.edgeforge.world_foundry import _Rng
    if not r_multiples:
        raise ScalingViolation("no R-multiples: nothing to simulate")
    if cluster_len < 2:
        raise ScalingViolation(
            "IID resampling destroys loss clustering and will "
            "understate drawdown; use blocks")
    rng = _Rng(seed)
    n = len(r_multiples)
    endings, mdds, dds, ruins, uw = [], [], [], 0, []

    for _ in range(n_paths):
        eq, peak, dd_run, worst, under = starting_equity, starting_equity, 0, 0.0, 0
        seq = []
        while len(seq) < trades_per_path:
            i = rng.randint(0, max(n - cluster_len, 0))
            seq.extend(r_multiples[i:i + cluster_len])
        for r in seq[:trades_per_path]:
            eq *= (1.0 + risk_fraction * r)
            if eq <= starting_equity * ruin_fraction:
                ruins += 1
                break
            if eq > peak:
                peak, dd_run = eq, 0
            else:
                dd_run += 1
                under += 1
                worst = max(worst, (peak - eq) / peak)
        endings.append(eq)
        mdds.append(worst)
        dds.append(dd_run)
        uw.append(under / max(trades_per_path, 1))

    srt = sorted(mdds)
    return {"kind": "capital_path_simulation",
            "starting_equity": starting_equity,
            "risk_fraction": risk_fraction,
            "trades_per_path": trades_per_path, "n_paths": n_paths,
            "cluster_len": cluster_len,
            "ending_equity_median": round(statistics.median(endings), 2),
            "ending_equity_p10": round(sorted(endings)[len(endings)//10], 2),
            "ending_equity_p90": round(
                sorted(endings)[min(len(endings)-1, 9*len(endings)//10)], 2),
            "geometric_growth_median": round(
                statistics.median(endings) / starting_equity - 1.0, 4),
            "max_drawdown_median": round(statistics.median(mdds), 4),
            "max_drawdown_p95": round(
                srt[min(len(srt) - 1, int(0.95 * len(srt)))], 4),
            "drawdown_duration_median": int(statistics.median(dds)),
            "risk_of_ruin": round(ruins / n_paths, 4),
            "ruin_definition": f"equity <= {ruin_fraction:.0%} of start",
            "time_under_water_fraction": round(
                statistics.median(uw), 4),
            "dependence_law": "outcomes are resampled in BLOCKS; IID "
                              "resampling breaks loss clustering and "
                              "understates the drawdowns that actually "
                              "end small accounts",
            "not_a_forecast": "a distribution over resampled histories, "
                              "not a prediction of our account",
            "decision_power": "NONE_RESEARCH"}


def kelly_reference(*, win_rate: float, win_loss_ratio: float,
                    estimation_error: float | str = NOT_ESTIMABLE
                    ) -> dict:
    """A reference number, wrapped in the reason not to trust it."""
    if not (0 < win_rate < 1) or win_loss_ratio <= 0:
        return {"kind": "kelly_reference", "verdict": NOT_ESTIMABLE}
    f = win_rate - (1 - win_rate) / win_loss_ratio
    return {"kind": "kelly_reference",
            "full_kelly_fraction": round(f, 4),
            "half_kelly": round(f / 2, 4),
            "quarter_kelly": round(f / 4, 4),
            "estimation_error_on_edge": estimation_error,
            "warning": ("Kelly assumes the edge is KNOWN. Ours is "
                        "estimated, and estimation error in the "
                        "numerator becomes leverage in the position. "
                        "Full Kelly on an overestimated edge is a ruin "
                        "machine"),
            "is_a_sizing_instruction": False,
            "decision_power": "NONE_RESEARCH"}


# ==================================================== PHASE 17

def capital_accelerant_research(*, tail_asymmetry, loss_bound,
                                capital_efficiency, holding_period,
                                execution, mechanism, capacity,
                                uncertainty, correlation) -> dict:
    """Dimensions preserved separately. No magic score."""
    dims = {"tail_asymmetry": tail_asymmetry, "loss_bound": loss_bound,
            "capital_efficiency": capital_efficiency,
            "holding_period": holding_period, "execution": execution,
            "mechanism": mechanism, "capacity": capacity,
            "uncertainty": uncertainty, "correlation": correlation}
    unknown = [k for k, v in dims.items() if v in
               (NOT_ESTIMABLE, None, "UNKNOWN")]
    return {"kind": "capital_accelerant_research",
            "dimensions": dims,
            "dimensions_unknown": unknown,
            "question": ("does this offer sufficiently asymmetric "
                         "payoff per dollar at risk to materially move "
                         "a small account WITHOUT unacceptable ruin "
                         "contribution?"),
            "answerable": not unknown,
            "verdict": ("CANDIDATE_ASSESSABLE" if not unknown
                        else "INSUFFICIENT_EVIDENCE"),
            "grants_capital_authority": False,
            "law": "no magic score; a scored answer would be a learned "
                   "threshold nobody has earned",
            "decision_power": "NONE_RESEARCH"}
