"""Track 2: long/short construction and the attribution ladder (v3.1 §3).

DESIGN-LAYER ONLY. Every result object carries, as a FIELD:

    evidence_class = "engineering_measurement"

and `results_table()` refuses any row without it. An in-sample construction
number must never sit next to a registered t-statistic and inherit its
authority; the tag travels with the data, like the reality harness's
PRELIMINARY stamp.

THE LADDER (same signal, same dates, in-sample; marginal delta per rung):

  0  long-only top decile, GROSS -- the frozen §13 measuring stick, computed
     here for reference and NEVER modified
  1  long-only, net of realized costs
  2  long/short, unconstrained beta, net
  3  long/short, beta-neutral (ex-ante), net
  4  rung 3 + sector-neutral
  5  rung 4 + borrow carry and hard-to-borrow exclusions

DECLARED CONVENTIONS (fixed here, not searched):
  * Long book sums to +0.5 and short book to -0.5 (gross 1.0), so every rung
    is per-dollar-of-capital comparable with the long-only rungs.
  * Beta: per-name, trailing 252 daily returns against the panel benchmark,
    PIT through the formation date. Ex-ante neutralisation scales the SHORT
    book by s = 0.5*beta_long/beta_short, CAPPED to [0.25, 1.0]; cap hits
    are reported, not hidden. Realized beta is regressed afterwards and its
    divergence from ex-ante is a RESULT.
  * Costs on REALIZED turnover only: round-trip 20bp and 40bp cases.
  * BORROW (ASSUMPTION, v1.0 §37 -- no PIT borrow dataset exists on disk):
    a name is shortable only if formation-date 60d ADDV >= $2M and
    unadjusted close >= $5; excluded names are counted and reported. Borrow
    carry: 100bp/yr on short notional. Conservative proxy, never EVIDENCE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

EVIDENCE_CLASS = "engineering_measurement"

LONG_GROSS, SHORT_GROSS = 0.5, 0.5
BETA_WINDOW = 252
SHORT_SCALE_CAP = (0.25, 1.0)
BORROW_MIN_ADDV = 2e6
BORROW_MIN_CLOSE = 5.0
BORROW_CARRY_ANNUAL = 0.01
COST_CASES_RT = (0.0020, 0.0040)          # round-trip, applied to realized turnover


class UntaggedResult(ValueError):
    """A design-layer result tried to travel without its evidence class."""


@dataclass(frozen=True)
class RungResult:
    rung: int
    label: str
    ann_return_gross: float
    ann_return_net_20bp: float
    ann_return_net_40bp: float
    sharpe_gross: float
    sharpe_net_20bp: float
    ann_vol: float
    max_drawdown: float
    turnover_per_rebalance: float
    realized_beta: float
    ex_ante_beta_mean: float
    beta_cap_hits: int
    names_long_median: int
    names_short_median: int
    borrow_excluded_total: int
    n_periods: int
    evidence_class: str = field(default=EVIDENCE_CLASS)

    def as_row(self) -> dict:
        row = {k: getattr(self, k) for k in self.__dataclass_fields__}
        if row.get("evidence_class") != EVIDENCE_CLASS:
            raise UntaggedResult("rung result lost its evidence_class")
        return row


def results_table(rows: list[dict]) -> list[dict]:
    """THE serialization gate: refuses any row without the tag."""
    for r in rows:
        if r.get("evidence_class") != EVIDENCE_CLASS:
            raise UntaggedResult(
                "a design-layer result reached the results table without "
                "evidence_class='engineering_measurement'. In-sample "
                "construction numbers are not evidence of edge.")
    return rows


def name_betas(close: pd.DataFrame, benchmark: pd.Series, date, window=BETA_WINDOW):
    """Per-name beta from trailing daily returns, PIT through `date`."""
    px = close.loc[:date].tail(window + 1)
    r = px.pct_change().dropna(how="all")
    b = benchmark.loc[:date].tail(window + 1).pct_change().dropna()
    r, b = r.align(b, join="inner", axis=0)
    var = float(b.var())
    if var == 0 or len(b) < 60:
        return pd.Series(1.0, index=close.columns)
    return r.apply(lambda col: col.cov(b) / var).fillna(1.0)


def _ew(names, total):
    return pd.Series(total / len(names), index=pd.Index(names)) if len(names) else \
        pd.Series(dtype=float)


def build_weights(rung: int, decile_row: pd.Series, sector: pd.Series,
                  betas: pd.Series, shortable: pd.Series) -> tuple[pd.Series, dict]:
    """Target weights for one rung on one formation date. Deterministic."""
    diag = {"beta_cap_hit": 0, "borrow_excluded": 0}
    top = sorted(decile_row[decile_row == 1].index)
    bot = sorted(decile_row[decile_row == 10].index)

    if rung in (0, 1):
        return _ew(top, 1.0), diag

    if rung == 5:
        ok = [s for s in bot if bool(shortable.get(s, False))]
        diag["borrow_excluded"] = len(bot) - len(ok)
        bot = ok

    if rung == 4 or rung == 5:
        # sector-neutral: short book mirrors the long book's sector weights,
        # sector by sector; a sector with no shortable bottom names drops out
        # of the short book and is reported via the weight shortfall.
        longs = _ew(top, LONG_GROSS)
        shorts = pd.Series(dtype=float)
        for sec, sec_w in longs.groupby(sector.reindex(longs.index)).sum().items():
            sec_bot = [s for s in bot if sector.get(s) == sec]
            shorts = pd.concat([shorts, _ew(sec_bot, -float(sec_w))])
    else:
        longs, shorts = _ew(top, LONG_GROSS), _ew(bot, -SHORT_GROSS)

    if rung >= 3 and len(shorts):
        bl = float((longs * betas.reindex(longs.index).fillna(1.0)).sum())
        bs = float((-shorts * betas.reindex(shorts.index).fillna(1.0)).sum())
        s = bl / bs if bs > 0 else 1.0
        capped = min(max(s, SHORT_SCALE_CAP[0]), SHORT_SCALE_CAP[1])
        if capped != s:
            diag["beta_cap_hit"] = 1
        shorts = shorts * capped

    return pd.concat([longs, shorts]), diag


def run_rung(rung: int, label: str, grid, decile, sector, panel,
             addv: pd.DataFrame, shortable_override=None) -> RungResult:
    """`shortable_override(date, default_mask) -> mask` exists for SCRUTINY of
    the borrow proxy (e.g. random exclusion at a matched rate) -- never for
    production construction. It can only shrink or reshape the short book."""
    close, bench = panel.close_adj, panel.benchmark_tr
    prev_w = None
    rets, turns, nl, ns, exa_betas = [], [], [], [], []
    cap_hits = borrow_excl = 0

    for i, d in enumerate(grid[:-1]):
        decile_row = decile.loc[d].dropna()
        book = decile_row[(decile_row == 1) | (decile_row == 10)].index
        betas = (name_betas(close[book], bench, d) if rung >= 3
                 else pd.Series(dtype=float))
        shortable = ((addv.loc[d] >= BORROW_MIN_ADDV)
                     & (panel.close_unadj.loc[d] >= BORROW_MIN_CLOSE))
        if shortable_override is not None:
            shortable = shortable_override(d, shortable)
        w, diag = build_weights(rung, decile_row, sector, betas, shortable)
        cap_hits += diag["beta_cap_hit"]
        borrow_excl += diag["borrow_excluded"]
        if prev_w is not None:
            both = w.index.union(prev_w.index)
            turns.append(float((w.reindex(both, fill_value=0)
                                - prev_w.reindex(both, fill_value=0)).abs().sum() / 2))
        prev_w = w
        nl.append(int((w > 0).sum()))
        ns.append(int((w < 0).sum()))
        if rung >= 3 and len(w):
            exa_betas.append(float((w * betas.reindex(w.index).fillna(1.0)).sum()))

        d1 = grid[i + 1]
        pr = (close.loc[d1].reindex(w.index) / close.loc[d].reindex(w.index) - 1)
        r = float((w * pr.fillna(0.0)).sum())
        if rung == 5:
            short_notional = float(-w[w < 0].sum())
            r -= BORROW_CARRY_ANNUAL * short_notional * 20 / 252
        rets.append(r)

    rets = pd.Series(rets, index=grid[:-1])
    ppy = 252 / 20
    turn = float(np.mean(turns)) if turns else 0.0
    # benchmark FORWARD returns labeled at the FORMATION date, matching the
    # portfolio series phase-for-phase. The first version labeled the
    # benchmark at period END, a one-period misalignment that reported a
    # long-only small-cap book at beta 0.04 -- an impossible number that a
    # sanity check caught before anything was recorded.
    bg = bench.reindex(grid)
    bench_r = (bg.shift(-1) / bg - 1).iloc[:-1]
    aligned = rets.align(bench_r, join="inner")
    realized_beta = (float(np.cov(aligned[0], aligned[1])[0, 1]
                           / np.var(aligned[1]))
                     if len(aligned[0]) > 10 and float(np.var(aligned[1])) > 0
                     else float("nan"))

    def ann(r):
        return float(r.mean() * ppy)

    def sharpe(r):
        return float(r.mean() / r.std() * np.sqrt(ppy)) if r.std() > 0 else 0.0

    cost20 = turn * COST_CASES_RT[0] * ppy
    cost40 = turn * COST_CASES_RT[1] * ppy
    equity = (1 + rets).cumprod()
    mdd = float((equity / equity.cummax() - 1).min())
    net20 = rets - turn * COST_CASES_RT[0]

    return RungResult(
        rung=rung, label=label,
        ann_return_gross=round(ann(rets), 6),
        ann_return_net_20bp=round(ann(rets) - cost20, 6),
        ann_return_net_40bp=round(ann(rets) - cost40, 6),
        sharpe_gross=round(sharpe(rets), 4),
        sharpe_net_20bp=round(sharpe(net20), 4),
        ann_vol=round(float(rets.std() * np.sqrt(ppy)), 6),
        max_drawdown=round(mdd, 6),
        turnover_per_rebalance=round(turn, 4),
        realized_beta=round(realized_beta, 4),
        ex_ante_beta_mean=round(float(np.mean(exa_betas)), 4) if exa_betas else float("nan"),
        beta_cap_hits=cap_hits,
        names_long_median=int(np.median(nl)) if nl else 0,
        names_short_median=int(np.median(ns)) if ns else 0,
        borrow_excluded_total=borrow_excl,
        n_periods=len(rets),
    )


LADDER = (
    (0, "long-only top decile, GROSS (frozen measuring stick)"),
    (1, "long-only, net of realized costs"),
    (2, "long/short, unconstrained beta, net"),
    (3, "long/short, beta-neutral, net"),
    (4, "rung 3 + sector-neutral"),
    (5, "rung 4 + borrow carry and HTB exclusions"),
)


def run_ladder(grid, decile, sector, panel, addv) -> list[RungResult]:
    return [run_rung(r, label, grid, decile, sector, panel, addv)
            for r, label in LADDER]
