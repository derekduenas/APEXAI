"""Protocol section 9 attribution -- required with every result.

    "This exists to answer one specific question: did APEX find a cross-sectional
     signal, or did it find 'own semiconductors during 2023-2025'? Both are
     informative; they are not the same discovery."

Four outputs, all mandatory:

  1. Return contribution by sector
  2. Contribution of the top 5 individual winners
  3. Contribution of the top 5 individual losers
  4. The result recomputed with the single largest-contributing sector excluded

Item 4 follows ruling B6: a FULL RE-RANK. The sector is removed from the
universe at each formation date and winsorisation, z-scoring, category scores,
ranking and deciles are all recomputed from scratch. Stripping names out of the
P&L while holding the original ranking fixed is the weaker test and is not what
section 9 asks for -- under a full re-rank the remaining securities genuinely
compete against a different cross-section, which is the counterfactual that
matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from apex.config import Config
from apex.evaluate.deciles import evaluate_deciles
from apex.features.composite import build_scores


@dataclass(frozen=True)
class Attribution:
    by_sector: pd.Series
    top_winners: pd.DataFrame
    top_losers: pd.DataFrame
    largest_sector: str
    spread_with_all_sectors: float
    spread_excluding_largest: float
    share_from_largest_sector: float

    def render(self) -> str:
        return (
            "  contribution by sector (annualised spread points):\n"
            + self.by_sector.round(5).to_string()
            + "\n\n  top 5 winners:\n"
            + self.top_winners.round(5).to_string(index=False)
            + "\n\n  top 5 losers:\n"
            + self.top_losers.round(5).to_string(index=False)
            + f"\n\n  largest contributing sector : {self.largest_sector}"
            + f"\n  spread, all sectors         : {self.spread_with_all_sectors:+.4%}"
            + f"\n  spread, that sector removed : {self.spread_excluding_largest:+.4%}"
            + (
                f"\n  share of spread from it     : {self.share_from_largest_sector:.1%}"
                if self.share_from_largest_sector == self.share_from_largest_sector
                else "\n  share of spread from it     : n/a (baseline spread is not "
                "positive, so there is no spread to apportion)"
            )
            + (
                "\n\n  NOTE: section 10 routes >60% from one sector to INCONCLUSIVE."
                if self.share_from_largest_sector == self.share_from_largest_sector
                and self.share_from_largest_sector > 0.60
                else ""
            )
        )

    def as_dict(self) -> dict:
        return {
            "by_sector": {k: float(v) for k, v in self.by_sector.items()},
            "top_winners": self.top_winners.to_dict("records"),
            "top_losers": self.top_losers.to_dict("records"),
            "largest_sector": self.largest_sector,
            "spread_with_all_sectors": self.spread_with_all_sectors,
            "spread_excluding_largest": self.spread_excluding_largest,
            "share_from_largest_sector": self.share_from_largest_sector,
        }


def _contributions(output, config: Config, grid) -> pd.Series:
    """Mean per-period contribution of each security to the top-decile leg."""
    n = int(config.get("evaluation.n_deciles"))
    deciles = output.scores.decile.loc[grid]
    returns = output.forward_returns.excess.loc[grid]

    in_top = deciles == n
    weights = in_top.div(in_top.sum(axis=1).replace(0, pd.NA), axis=0)
    return (weights * returns).sum(axis=0) / len(grid)


def attribute(output, config: Config, start, end) -> Attribution:
    grid = output.calendar.grid_formation_dates(start, end)
    contribution = _contributions(output, config, grid)

    meta = output.panel.meta
    sectors = meta["sector"]
    tickers = meta["ticker"]

    by_sector = contribution.groupby(sectors).sum().sort_values(ascending=False)

    ranked = contribution.sort_values(ascending=False)
    winners = pd.DataFrame(
        {
            "ticker": [tickers.get(s, s) for s in ranked.head(5).index],
            "sector": [sectors.get(s, "") for s in ranked.head(5).index],
            "contribution": ranked.head(5).to_numpy(),
        }
    )
    losers = pd.DataFrame(
        {
            "ticker": [tickers.get(s, s) for s in ranked.tail(5).index],
            "sector": [sectors.get(s, "") for s in ranked.tail(5).index],
            "contribution": ranked.tail(5).to_numpy(),
        }
    )

    baseline = evaluate_deciles(
        output.scores.decile, output.forward_returns.excess, output.universe.eligible,
        config, grid,
    )

    # B6: FULL re-rank with the sector removed, not a P&L subtraction.
    largest = str(by_sector.index[0]) if len(by_sector) else ""
    excluded = output.universe.eligible.copy()
    if largest:
        members = sectors[sectors == largest].index
        excluded[excluded.columns.intersection(members)] = False

    rescored = build_scores(output.features, excluded, config)
    without = evaluate_deciles(
        rescored.decile, output.forward_returns.excess, excluded, config, grid
    )

    full = float(baseline.spread_annualised_gross)
    rest = float(without.spread_annualised_gross)

    # "Share of the spread from one sector" is only meaningful when there IS a
    # positive spread to apportion. With a zero or negative baseline the ratio
    # is arithmetic noise -- it flips sign, exceeds 100%, and reads as a finding.
    # Section 10 uses this number as a >60% gate, so a nonsense value here would
    # be actively misleading. Report NaN and say why instead.
    share = (full - rest) / full if (full == full and full > 0) else float("nan")

    return Attribution(
        by_sector=by_sector,
        top_winners=winners,
        top_losers=losers,
        largest_sector=largest,
        spread_with_all_sectors=float(full),
        spread_excluding_largest=float(rest),
        share_from_largest_sector=float(share),
    )
