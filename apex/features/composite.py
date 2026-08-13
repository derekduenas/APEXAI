"""Composite construction -- protocol section 5, steps 1 to 5.

    1. Winsorise each raw feature cross-sectionally at the 1st and 99th percentiles
    2. Convert to cross-sectional z-scores
    3. Average the z-scores within each category -> four category scores
    4. Equal-weight the four category scores (0.25 each)
    5. Rank cross-sectionally and map to percentile 0-100 = APEX Score

Every cross-sectional operation here sees ONLY the eligible set at T. Feature
values for ineligible securities exist (they were computed from each security's
own full history) but must not influence a percentile, a mean, or a standard
deviation, or an ineligible name silently moves the ranking of an eligible one.

Sign convention (B1): `composite.negate_components` in config lists the
components multiplied by -1 after z-scoring. For Experiment #001 that is both F3
components -- low volatility is hypothesised favourable. The sign lives in
config, not in a buried minus, so it is auditable against the pre-registration.

Noted, implemented as written (CONVENTIONS section 4.3): step 4 equal-weights the
four category AVERAGES without re-standardising them. The variance of a
two-z-score average depends on the correlation between its components, so a
category whose components are highly correlated (F1's two momentum windows)
contributes more variance to the composite than a category whose components are
not. Equal weight is not equal risk weight. Section 5 specifies the former.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import CATEGORY_COMPONENTS, FeaturePanel, ScorePanel


def winsorise(values: pd.DataFrame, lower: float, upper: float) -> pd.DataFrame:
    """Clip cross-sectionally at the given percentiles, row by row."""
    low = values.quantile(lower, axis=1)
    high = values.quantile(upper, axis=1)
    return values.clip(lower=low, upper=high, axis=0)


def zscore(values: pd.DataFrame, ddof: int) -> pd.DataFrame:
    mean = values.mean(axis=1)
    std = values.std(axis=1, ddof=ddof)
    # A zero-dispersion cross-section has no z-score. NaN propagates into the
    # completeness mask and the security is excluded, rather than being handed a
    # fabricated 0.0.
    return values.sub(mean, axis=0).div(std.where(std > 0), axis=0)


def percentile_rank(values: pd.DataFrame, tie_method: str, score_max: float) -> pd.DataFrame:
    """Cross-sectional percentile rank mapped to 0-`score_max`.

    C10: ties resolved by `method='first'`. Because the security axis is sorted
    by security_id, 'first' breaks ties deterministically on security_id -- the
    same secondary sort C10 specifies, obtained without a separate shuffle.
    """
    return values.rank(axis=1, method=tie_method, pct=True) * score_max


def assign_deciles(rank_pct: pd.DataFrame, n_deciles: int, score_max: float) -> pd.DataFrame:
    """Equal-count deciles, 1 (worst) to `n_deciles` (best)."""
    scaled = rank_pct / score_max * n_deciles
    deciles = np.ceil(scaled.to_numpy())
    deciles = np.clip(deciles, 1, n_deciles)
    out = pd.DataFrame(deciles, index=rank_pct.index, columns=rank_pct.columns)
    return out.where(rank_pct.notna())


def build_scores(
    features: FeaturePanel, eligible: pd.DataFrame, config: Config
) -> ScorePanel:
    lower = float(config.get("composite.winsorize_lower"))
    upper = float(config.get("composite.winsorize_upper"))
    ddof = int(config.get("composite.z_ddof"))
    negate = set(config.get("composite.negate_components"))
    weights = config.section("composite.category_weights")
    score_max = float(config.get("composite.score_max"))
    n_deciles = int(config.get("evaluation.n_deciles"))
    tie_method = config.get("evaluation.rank_tie_method")

    total_weight = sum(float(w) for w in weights.values())
    if not np.isclose(total_weight, 1.0):
        raise ValueError(
            f"composite.category_weights sum to {total_weight}, not 1.0 -- "
            "section 5 pre-registers equal 0.25 weights"
        )

    z_scores: dict[str, pd.DataFrame] = {}
    for name, frame in features.components.items():
        restricted = frame.where(eligible)
        clipped = winsorise(restricted, lower, upper)
        z = zscore(clipped, ddof)
        z_scores[name] = -z if name in negate else z

    category_scores: dict[str, pd.DataFrame] = {}
    for category, components in CATEGORY_COMPONENTS.items():
        stacked = [z_scores[c] for c in components]
        category_scores[category] = sum(stacked) / len(stacked)

    composite = None
    for category, frame in category_scores.items():
        contribution = frame * float(weights[category])
        composite = contribution if composite is None else composite + contribution

    composite = composite.where(eligible)
    apex_score = percentile_rank(composite, tie_method, score_max)
    decile = assign_deciles(apex_score, n_deciles, score_max)

    return ScorePanel(
        # APEX-001: assign_deciles maps the best name to `n_deciles`.
        top_decile_label=n_deciles,
        dates=features.dates,
        securities=features.securities,
        category_scores=category_scores,
        apex_score=apex_score,
        decile=decile,
    )
