"""APEX-002 scoring and deciles: orientation, equal-count, tie determinism.

Every guard here is load-bearing on the DIRECTION of the experiment. An
inverted score would produce a clean-looking run with the sign of the
pre-registered hypothesis reversed, and no shape check would notice.
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from apex.audit.execution_path import executable_source
from apex.config import load_config
from apex.features import nsi_scores

CFG = load_config("experiment", "costs", "synthetic", "sharadar")


def _frames(values, eligible=None):
    dates = pd.DatetimeIndex(["2021-06-01"])
    secs = pd.Index([f"S{i:02d}" for i in range(len(values))], name="security_id")
    nsi = pd.DataFrame([values], index=dates, columns=secs)
    elig = pd.DataFrame(
        [[True] * len(values)] if eligible is None else [eligible],
        index=dates, columns=secs,
    )
    return nsi, elig


# --- DIRECTION --------------------------------------------------------------

def test_the_largest_repurchaser_scores_highest():
    """Section 13 requires a POSITIVE IC under the pre-registered direction.

    Lower NSI is hypothesised to predict higher return, so the score must fall
    as NSI rises. If this inverts, the experiment tests the opposite of what
    was registered while still producing a well-formed number.
    """
    nsi, elig = _frames([-0.50, -0.10, 0.00, 0.10, 0.50])

    score = nsi_scores.nsi_percentile_score(nsi, elig).iloc[0]

    assert score.iloc[0] == 100.0, "the largest net repurchaser must score 100"
    assert score.is_monotonic_decreasing, "score must fall as NSI rises"


def test_counterexample_an_inverted_score_is_detected():
    """Prove the direction check can fail.

    An ascending percentile -- the natural thing to write, and what
    `nsi.rank_ascending` returns -- gives the largest repurchaser the LOWEST
    score. The assertion above must reject it.
    """
    nsi, elig = _frames([-0.50, -0.10, 0.00, 0.10, 0.50])
    inverted = nsi.where(elig).rank(axis=1, method="first", pct=True) * 100.0

    assert inverted.iloc[0].iloc[0] != 100.0
    assert inverted.iloc[0].is_monotonic_increasing, (
        "the counterexample is inert: it is not actually inverted"
    )


def test_the_largest_repurchaser_lands_in_decile_one():
    """Section 9, ruled 2026-08-11: rank 1 = TOP decile = decile 1.

    The opposite of #001's numbering. Inheriting #001's convention here would
    silently relabel every reported bucket.
    """
    values = list(np.linspace(-0.5, 0.5, 100))
    nsi, elig = _frames(values)

    decile = nsi_scores.equal_count_deciles(nsi, elig, 10).iloc[0]

    assert decile.iloc[0] == 1.0, "largest repurchaser must be in the TOP decile (1)"
    assert decile.iloc[-1] == 10.0, "largest issuer must be in the bottom decile (10)"


def test_the_score_and_the_decile_point_in_opposite_directions_deliberately():
    """The resolution, pinned so it cannot be 'tidied' into agreement.

    Score 100 and decile 1 both mean 'largest net repurchaser'. Section 13's
    IC reads the SCORE; section 9's wording governs the LABEL. A future editor
    aligning the two numerically would break one of them.
    """
    values = list(np.linspace(-0.5, 0.5, 50))
    nsi, elig = _frames(values)

    score = nsi_scores.nsi_percentile_score(nsi, elig).iloc[0]
    decile = nsi_scores.equal_count_deciles(nsi, elig, 10).iloc[0]

    best = score.idxmax()
    assert decile.loc[best] == 1.0, "the highest-scoring name is not in decile 1"
    assert decile.loc[score.idxmin()] == 10.0


def test_counterexample_the_apex_001_numbering_would_be_detected():
    """Prove the decile orientation check can fail.

    #001's `assign_deciles` maps the best name to decile 10. If #002 adopted
    it, the top decile would be mislabelled on every date.
    """
    values = list(np.linspace(-0.5, 0.5, 100))
    nsi, elig = _frames(values)

    score = nsi_scores.nsi_percentile_score(nsi, elig)
    apex001_style = np.ceil(score.to_numpy() / 100.0 * 10).clip(1, 10)

    assert apex001_style[0][0] == 10.0, "the counterexample is inert"
    correct = nsi_scores.equal_count_deciles(nsi, elig, 10).to_numpy()
    assert correct[0][0] == 1.0
    assert not np.array_equal(correct, apex001_style), (
        "#001's numbering and #002's are indistinguishable; the guard is inert"
    )


# --- EQUAL COUNT ------------------------------------------------------------

def test_deciles_are_equal_count():
    values = list(np.linspace(-1.0, 1.0, 200))
    nsi, elig = _frames(values)

    decile = nsi_scores.equal_count_deciles(nsi, elig, 10).iloc[0]

    counts = decile.value_counts()
    assert set(counts.index) == set(float(d) for d in range(1, 11))
    assert counts.nunique() == 1, f"deciles are not equal-count: {dict(counts)}"
    assert counts.iloc[0] == 20


def test_counterexample_value_bucketing_is_not_equal_count():
    """Prove the equal-count check can fail.

    Cutting on VALUE rather than RANK is the classic mistake: with a skewed
    signal it produces wildly unequal buckets. NSI is skewed (B1: p50 +0.0024,
    max +4.59), so this is a live hazard, not a hypothetical one.
    """
    values = [-0.5] * 90 + list(np.linspace(0.0, 4.5, 10))
    nsi, _ = _frames(values)

    by_value = pd.cut(nsi.iloc[0], bins=10, labels=False) + 1

    assert by_value.value_counts().nunique() > 1, "the counterexample is inert"
    assert int(by_value.value_counts().max()) >= 90, (
        "value bucketing should pile most names into one bucket"
    )


# --- TIES (C10) -------------------------------------------------------------

def test_ties_break_deterministically_on_security_id():
    nsi, elig = _frames([0.0, 0.0, 0.0, 0.0])

    score = nsi_scores.nsi_percentile_score(nsi, elig).iloc[0]

    assert score.is_monotonic_decreasing
    assert score.loc["S00"] > score.loc["S03"], (
        "the earlier security_id must win the tie"
    )


def test_counterexample_column_order_cannot_change_the_tie_break():
    """The violation: `method='first'` resolves ties by POSITION.

    If ranking ran on the caller's column order rather than a sorted view, the
    same data in a different column order would produce different scores. The
    experiment's output would depend on how the panel happened to be built.
    """
    nsi, elig = _frames([0.0, 0.0, 0.0, 0.0])
    shuffled = nsi.columns[::-1]

    normal = nsi_scores.nsi_percentile_score(nsi, elig)
    reordered = nsi_scores.nsi_percentile_score(
        nsi.reindex(columns=shuffled), elig.reindex(columns=shuffled)
    )

    pd.testing.assert_series_equal(
        normal.iloc[0].sort_index(), reordered.iloc[0].sort_index()
    )
    # and prove the counterexample is not inert: raw pandas DOES flip.
    raw_a = nsi.rank(axis=1, method="first").iloc[0]
    raw_b = nsi.reindex(columns=shuffled).rank(axis=1, method="first").iloc[0]
    assert raw_a.loc["S00"] != raw_b.loc["S00"], (
        "the counterexample is inert: raw ranking did not depend on order"
    )


# --- ELIGIBILITY AND MISSINGNESS -------------------------------------------

def test_ineligible_securities_are_never_scored():
    nsi, elig = _frames([-0.5, -0.1, 0.0, 0.1], eligible=[True, False, True, True])

    score = nsi_scores.nsi_percentile_score(nsi, elig).iloc[0]

    assert pd.isna(score.loc["S01"])
    assert int(score.notna().sum()) == 3


def test_counterexample_an_ineligible_security_would_displace_an_eligible_one():
    """Prove eligibility-before-ranking matters numerically.

    Ranking first and masking afterwards leaves the ineligible name occupying a
    rank slot, shifting every name below it. The scores differ.
    """
    nsi, elig = _frames([-0.5, -0.4, -0.3, -0.2])
    partial = pd.DataFrame([[True, False, True, True]],
                           index=nsi.index, columns=nsi.columns)

    correct = nsi_scores.nsi_percentile_score(nsi, partial).iloc[0]
    wrong = (nsi.rank(axis=1, method="first", ascending=True)
             .rdiv(1).where(partial).iloc[0])

    assert correct.notna().sum() == 3
    assert not np.allclose(
        correct.dropna().to_numpy(), wrong.dropna().to_numpy() * 100.0
    ), "rank-then-mask produced the same answer; the counterexample is inert"


def test_missing_nsi_is_excluded_never_filled():
    nsi, elig = _frames([-0.5, np.nan, 0.0, 0.5])

    score = nsi_scores.nsi_percentile_score(nsi, elig).iloc[0]
    decile = nsi_scores.equal_count_deciles(nsi, elig, 10).iloc[0]

    assert pd.isna(score.loc["S01"]) and pd.isna(decile.loc["S01"])
    assert int(score.notna().sum()) == 3, "a missing NSI was filled"


# --- NO TRANSFORMATION ------------------------------------------------------

def test_the_scoring_module_applies_no_transformation():
    code = executable_source(inspect.getsource(nsi_scores))

    for banned in ("winsor", "zscore", "z_score", "ewm(", "rolling(", "fillna("):
        assert banned not in code, f"{banned!r} is executed in nsi_scores"

    # np.clip appears exactly once, and only to bound the decile INDEX to 1..n.
    # Clipping the signal itself is forbidden; clipping a bucket number is the
    # decile mechanism. The distinction is the whole point, so it is pinned.
    assert code.count("np.clip") == 1
    assert "np.clip(scaled,1,n_deciles)" in "".join(code.split())


def test_the_scoring_module_never_reaches_apex_001():
    """Scans EXECUTABLE code: the module's own docstring names `build_scores`
    and `assign_deciles` precisely to say it does not call them."""
    code = executable_source(inspect.getsource(nsi_scores))

    for banned in ("build_scores", "assign_deciles", "f1_momentum", "f2_trend",
                   "f3_volatility", "f4_relative_strength", "APEX-001"):
        assert banned not in code, f"nsi_scores references {banned}"


def test_counterexample_the_isolation_scan_detects_an_injected_import():
    """Prove the scan can fail rather than merely reporting clean."""
    real = executable_source(inspect.getsource(nsi_scores))
    assert "assign_deciles" not in real

    mutated = executable_source(
        "from apex.features.composite import assign_deciles\n"
        + inspect.getsource(nsi_scores)
    )

    assert "assign_deciles" in mutated, "the isolation scan is inert"


def test_counterexample_the_transformation_scan_detects_an_injected_winsor():
    real = inspect.getsource(nsi_scores)
    mutated = real + "\n\ndef _injected(x):\n    return x.clip(0, 1)\n"

    code = executable_source(mutated)
    assert code.count("np.clip") == 1 and ".clip(" in code, (
        "an injected clip was not visible to the scan"
    )


def test_score_stays_inside_the_scorepanel_contract():
    values = list(np.linspace(-1, 1, 50))
    nsi, elig = _frames(values)

    score = nsi_scores.nsi_percentile_score(nsi, elig)

    assert score.stack().min() > 0.0 and score.stack().max() <= 100.0


def test_build_nsi_scores_produces_a_valid_score_panel():
    values = list(np.linspace(-1, 1, 40))
    nsi, elig = _frames(values)

    panel = nsi_scores.build_nsi_scores(nsi, elig, CFG)

    assert set(panel.category_scores) == {"nsi"}
    assert panel.decile.stack().between(1, 10).all()
    assert panel.apex_score.stack().between(0, 100).all()


@pytest.mark.parametrize("n", [31, 47, 100, 233])
def test_deciles_are_balanced_for_awkward_counts(n):
    """Equal-count cannot be exact when n is not divisible by 10; it must still
    be BALANCED -- no bucket may differ from another by more than one name."""
    nsi, elig = _frames(list(np.linspace(-1, 1, n)))

    decile = nsi_scores.equal_count_deciles(nsi, elig, 10).iloc[0]

    counts = decile.value_counts()
    assert counts.max() - counts.min() <= 1, f"n={n} unbalanced: {dict(counts)}"
