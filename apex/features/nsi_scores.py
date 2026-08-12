"""APEX-002 scoring: percentile score and equal-count deciles from NSI.

INDEPENDENT OF APEX-001 BY CONSTRUCTION. This module does not import
`apex.features.composite`, does not call `build_scores` or `assign_deciles`,
and does not touch F1-F4. The arithmetic of equal-count deciles is the same
arithmetic anyone would write; reusing #001's function would put a closed
experiment's scoring machinery inside #002's live path, which the frozen
specification forbids. Duplication here is deliberate and is the cheaper error.

DIRECTION -- the one reading of the frozen text that satisfies every clause
------------------------------------------------------------------------
Section 9 states: "ascending -- lowest NSI (largest net repurchase) = rank 1 =
top decile". Section 13 states the experiment succeeds only if "the mean daily
cross-sectional Spearman IC is positive", and section 2 states "lower net
issuance predicts higher subsequent return".

Those three clauses fix the orientation together:

  * ordinal rank 1 is the LOWEST NSI -- the largest net repurchaser;
  * a positive IC requires `apex_score` to RISE with expected return, so the
    score must DECREASE in NSI: the largest repurchaser scores 100;
  * "top decile" therefore means the BEST decile, which under the 1-worst to
    10-best numbering section 9 inherits ("equal-count, 1..10, existing
    machinery") is decile 10.

Reading "top decile" as the literal number 1 would invert the score, make the
pre-registered IC negative, and contradict section 13's own success criterion.
The orientation implemented here is the only one under which all three clauses
hold simultaneously. It is flagged in the Step 3A report as the single
remaining textual ambiguity: the WORD "top" is unambiguous, the NUMBER is not.

TIE-BREAK (C10)
---------------
`method='first'` resolves ties by position, so position must be made to mean
something. Ranking happens on a `security_id`-sorted view, making the tie-break
deterministic and independent of whatever column order the caller's panel
happened to have.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import ScorePanel

SCORE_MIN = 0.0
SCORE_MAX = 100.0


def nsi_percentile_score(
    nsi: pd.DataFrame, eligible: pd.DataFrame, tie_method: str = "first"
) -> pd.DataFrame:
    """Cross-sectional percentile score in 0-100. Lowest NSI scores highest.

    Eligibility is applied BEFORE ranking, so an ineligible security cannot
    displace an eligible one. Missing NSI stays missing: excluded from the
    cross-section, never filled.
    """
    restricted = nsi.where(eligible)

    order = restricted.columns.sort_values()
    ordered = restricted.reindex(columns=order)

    # Ordinal rank, ascending: rank 1 == lowest NSI == largest repurchase.
    ranks = ordered.rank(axis=1, method=tie_method, ascending=True)
    counts = ordered.notna().sum(axis=1)

    # Invert so the lowest NSI carries the HIGHEST score (section 13 requires a
    # positive IC under the pre-registered direction).
    pct_best = (counts.to_numpy()[:, None] - ranks.to_numpy() + 1.0) / counts.to_numpy()[:, None]

    scores = pd.DataFrame(pct_best * SCORE_MAX, index=ordered.index, columns=ordered.columns)
    return scores.reindex(columns=nsi.columns)


def equal_count_deciles(score: pd.DataFrame, n_deciles: int) -> pd.DataFrame:
    """Equal-count deciles 1 (worst) .. n_deciles (best) from a 0-100 score.

    Independent of #001's `assign_deciles`. Same mechanism, separate code: the
    specification permits the mechanical percentile conversion, not the import.
    """
    scaled = np.ceil(score.to_numpy() / SCORE_MAX * n_deciles)
    clipped = np.clip(scaled, 1, n_deciles)
    out = pd.DataFrame(clipped, index=score.index, columns=score.columns)
    return out.where(score.notna())


def build_nsi_scores(nsi: pd.DataFrame, eligible: pd.DataFrame, config: Config) -> ScorePanel:
    """The APEX-002 ScorePanel. No winsorisation, no z-scoring, no smoothing."""
    tie_method = config.get("evaluation.rank_tie_method")
    n_deciles = int(config.get("evaluation.n_deciles"))

    score = nsi_percentile_score(nsi, eligible, tie_method)
    decile = equal_count_deciles(score, n_deciles)

    return ScorePanel(
        dates=nsi.index,
        securities=nsi.columns,
        # The raw signal is carried through unmodified for the section 9 log.
        category_scores={"nsi": nsi.where(eligible)},
        apex_score=score,
        decile=decile,
    )
