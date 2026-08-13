"""APEX-002 scoring: percentile score and equal-count deciles from NSI.

INDEPENDENT OF APEX-001 BY CONSTRUCTION. This module does not import
`apex.features.composite`, does not call `build_scores` or `assign_deciles`,
and does not touch F1-F4. The arithmetic of equal-count deciles is the same
arithmetic anyone would write; reusing #001's function would put a closed
experiment's scoring machinery inside #002's live path, which the frozen
specification forbids. Duplication here is deliberate and is the cheaper error.

DIRECTION -- ruled 2026-08-11, after inspecting what section 13 actually binds
-----------------------------------------------------------------------------
Three concepts were conflated here and are now kept separate:

  1. ECONOMIC ORDERING -- lower NSI is better. Section 2.
  2. RANK -- lowest NSI is rank 1. Section 9.
  3. DECILE LABEL -- section 9 says rank 1 is the TOP DECILE, and top decile
     is DECILE 1. The protocol's explicit wording governs; #001's numbering
     (1 worst .. 10 best) does not carry over merely because it exists.

  lowest NSI -> rank 1 -> decile 1 (top) -> highest score -> expected +IC

The apparent conflict with section 13's "mean IC positive" dissolves on
inspection: `apex.evaluate.ic.cross_sectional_ic` correlates forward returns
against the CONTINUOUS score, re-ranking it internally, and never reads the
decile label (`grep decile apex/evaluate/ic.py` returns nothing). Section 13
therefore constrains the SCORE's orientation only. The decile label is a
downstream reporting artifact and is free to follow section 9 literally. No
protocol amendment is required, and none was made.

So the two are oriented independently and deliberately:

  * `nsi_percentile_score` -- 100 for the LOWEST NSI. This is the IC variable;
    its orientation is what makes the pre-registered relationship positive.
  * `equal_count_deciles` -- 1 for the LOWEST NSI. This is the label; it
    follows section 9's words.

They point in opposite numeric directions ON PURPOSE. That is not an
inconsistency, it is the resolution: score orientation serves the statistical
test, decile numbering serves the protocol's language.

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


def _ascending_ordinal_rank(
    nsi: pd.DataFrame, eligible: pd.DataFrame, tie_method: str
) -> tuple[pd.DataFrame, pd.Series]:
    """THE ranking. Rank 1 = lowest NSI = largest net repurchaser.

    One definition, shared by the score and the decile label, so the two can
    never drift apart. Computing them from separate rankings is how a score and
    a label end up disagreeing about which security is best.

    Eligibility is applied BEFORE ranking, so an ineligible security cannot
    occupy a rank slot and displace an eligible one. Missing NSI stays missing.

    `method='first'` resolves ties by POSITION, so position is made to mean
    something: ranking runs on a `security_id`-sorted view (C10), making the
    tie-break independent of the caller's column order.
    """
    restricted = nsi.where(eligible)
    ordered = restricted.reindex(columns=restricted.columns.sort_values())

    ranks = ordered.rank(axis=1, method=tie_method, ascending=True)
    counts = ordered.notna().sum(axis=1)
    return ranks.reindex(columns=nsi.columns), counts


def nsi_percentile_score(
    nsi: pd.DataFrame, eligible: pd.DataFrame, tie_method: str = "first"
) -> pd.DataFrame:
    """Cross-sectional score in 0-100. LOWEST NSI scores HIGHEST.

    This is the variable section 13's IC is computed against. Its orientation
    encodes the pre-registered direction: lower issuance predicts higher
    return, so the largest repurchaser must carry the largest score for the
    expected IC to be positive.
    """
    ranks, counts = _ascending_ordinal_rank(nsi, eligible, tie_method)

    n = counts.to_numpy()[:, None]
    pct_best = (n - ranks.to_numpy() + 1.0) / n

    return pd.DataFrame(pct_best * SCORE_MAX, index=nsi.index, columns=nsi.columns)


def equal_count_deciles(
    nsi: pd.DataFrame,
    eligible: pd.DataFrame,
    n_deciles: int,
    tie_method: str = "first",
) -> pd.DataFrame:
    """Equal-count deciles. DECILE 1 IS THE TOP DECILE (section 9).

    Derived from the ascending NSI rank directly, not from the score, so the
    label states section 9's ordering without a sign flip in between:

        decile 1  = lowest NSI  = largest net repurchasers = TOP
        decile 10 = highest NSI = largest net issuers      = BOTTOM

    This is the opposite numbering from APEX-001, where 10 is best. #002 does
    not inherit that convention; it follows its own protocol's words.

    Independent of #001's `assign_deciles`. Same arithmetic, separate code: the
    specification permits the mechanical percentile conversion, not the import.
    """
    ranks, counts = _ascending_ordinal_rank(nsi, eligible, tie_method)

    n = counts.to_numpy()[:, None]
    with np.errstate(invalid="ignore"):
        scaled = np.ceil(ranks.to_numpy() / n * n_deciles)
    bounded = np.clip(scaled, 1, n_deciles)

    out = pd.DataFrame(bounded, index=nsi.index, columns=nsi.columns)
    return out.where(ranks.notna())


def build_nsi_scores(nsi: pd.DataFrame, eligible: pd.DataFrame, config: Config) -> ScorePanel:
    """The APEX-002 ScorePanel. No winsorisation, no z-scoring, no smoothing."""
    tie_method = config.get("evaluation.rank_tie_method")
    n_deciles = int(config.get("evaluation.n_deciles"))

    score = nsi_percentile_score(nsi, eligible, tie_method)
    decile = equal_count_deciles(nsi, eligible, n_deciles, tie_method)

    return ScorePanel(
        # APEX-002 section 9, ruled 2026-08-11: decile 1 is the TOP decile.
        top_decile_label=1,
        dates=nsi.index,
        securities=nsi.columns,
        # The raw signal is carried through unmodified for the section 9 log.
        category_scores={"nsi": nsi.where(eligible)},
        apex_score=score,
        decile=decile,
    )
