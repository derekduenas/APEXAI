"""Which end of the ranking is the long leg? A registered convention.

`evaluate_deciles` hardcoded `per_period[n_deciles] - per_period[1]` --
APEX-001's 10-is-best. APEX-002 ruled decile 1 = top (section 9), so every
decile figure in its recorded validation artifact is sign-inverted relative to
the intended long-top/short-bottom reading. See APEX-002-ERRATUM-001.

The verdict was unaffected -- section 13 is IC-based and the IC used the
correctly-oriented continuous score -- but the spread, its t-statistic,
`monotonic_top_over_bottom` and the whole section 9 attribution inherited the
wrong end. Fixed here for every future experiment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.evaluate.deciles import evaluate_deciles

CFG = load_config("experiment", "costs", "synthetic", "sharadar")
N = 10


def _fixture(n_dates: int = 40):
    """A monotone panel: decile 1 earns least, decile 10 earns most.

    Deliberately the WRONG way round for #002, so an orientation error shows
    up as a sign rather than as a small numeric drift.
    """
    dates = pd.bdate_range("2021-01-01", periods=n_dates)
    secs = pd.Index([f"S{i:03d}" for i in range(N)], name="security_id")

    decile = pd.DataFrame(
        np.tile(np.arange(1, N + 1), (n_dates, 1)), index=dates, columns=secs
    ).astype(float)
    returns = pd.DataFrame(
        np.tile(np.arange(1, N + 1) * 0.001, (n_dates, 1)), index=dates, columns=secs
    )
    eligible = pd.DataFrame(True, index=dates, columns=secs)
    return decile, returns, eligible, dates


def test_top_label_1_and_top_label_10_give_opposite_spreads():
    decile, returns, eligible, dates = _fixture()

    as_002 = evaluate_deciles(decile, returns, eligible, CFG, dates, 1)
    as_001 = evaluate_deciles(decile, returns, eligible, CFG, dates, N)

    assert as_002.spread_mean_per_period == pytest.approx(
        -as_001.spread_mean_per_period
    )
    assert as_002.spread_mean_per_period < 0 < as_001.spread_mean_per_period


def test_counterexample_the_inherited_convention_reproduces_the_old_behaviour():
    """#001 is closed; its numbers must not move.

    With top_decile_label = n_deciles the evaluator must compute exactly what
    the hardcoded version did: per_period[n] - per_period[1].
    """
    decile, returns, eligible, dates = _fixture()

    result = evaluate_deciles(decile, returns, eligible, CFG, dates, N)

    expected = (returns.iloc[0].iloc[N - 1] - returns.iloc[0].iloc[0])
    assert result.spread_mean_per_period == pytest.approx(expected)
    assert result.monotonic_top_over_bottom is True


def test_under_the_002_convention_this_fixture_is_not_monotone_top_over_bottom():
    """The same data, read the other way round, reverses the monotonicity flag.

    A flag that could not flip would be reporting the fixture, not the
    convention.
    """
    decile, returns, eligible, dates = _fixture()

    as_002 = evaluate_deciles(decile, returns, eligible, CFG, dates, 1)
    as_001 = evaluate_deciles(decile, returns, eligible, CFG, dates, N)

    assert as_002.monotonic_top_over_bottom is False
    assert as_001.monotonic_top_over_bottom is True


def test_each_scorer_states_its_own_convention():
    """The label lives with the code that assigns it, not in configuration.

    Configuration was tried and rejected: it is a second source of truth, and
    the null rig -- which scores with #001's composite -- disagreed with it
    immediately.
    """
    import inspect

    from apex.features import composite, nsi_scores

    assert "top_decile_label=n_deciles" in inspect.getsource(composite.build_scores)
    assert "top_decile_label=1" in inspect.getsource(nsi_scores.build_nsi_scores)


def test_counterexample_a_panel_cannot_omit_its_convention():
    """A ScorePanel with no stated orientation must be refused, not defaulted."""
    from apex.contracts import ContractViolation, ScorePanel

    dates = pd.bdate_range("2021-01-01", periods=2)
    secs = pd.Index(["A", "B"], name="security_id")
    dec = pd.DataFrame([[1.0, 10.0], [1.0, 10.0]], index=dates, columns=secs)
    score = pd.DataFrame([[100.0, 1.0], [100.0, 1.0]], index=dates, columns=secs)

    with pytest.raises(ContractViolation, match="top_decile_label"):
        ScorePanel(dates=dates, securities=secs, category_scores={},
                   apex_score=score, decile=dec)          # no label given


def test_counterexample_a_nonsense_label_is_refused():
    """The top portfolio is one END of the ranking. A middle decile is not a
    convention, it is a mistake, and defaulting past it is how the original
    assumption survived."""
    decile, returns, eligible, dates = _fixture()

    with pytest.raises(ValueError, match="must be 1 or 10"):
        evaluate_deciles(decile, returns, eligible, CFG, dates, 5)


def test_the_recorded_apex_002_artifact_is_sign_inverted_as_documented():
    """Pins the erratum against the immutable artifact.

    The recorded spread equals decile10 - decile1. Under #002's convention the
    long-short leg is decile1 - decile10, so the recorded figure is its
    negation. This test documents the discrepancy; it does not repair it, and
    the artifact is never rewritten.
    """
    import json
    from pathlib import Path

    artifact = Path(__file__).resolve().parents[1] / "results/validation_APEX-002.json"
    if not artifact.exists():                       # pragma: no cover
        pytest.skip("validation artifact not present")

    deciles = json.loads(artifact.read_text())["raw"]["deciles_gross"]
    by_decile = {int(k): v for k, v in deciles["mean_by_decile"].items()}

    recorded = deciles["spread_mean_per_period"]
    as_recorded = by_decile[10] - by_decile[1]
    intended = by_decile[1] - by_decile[10]

    assert recorded == pytest.approx(as_recorded), (
        "the artifact no longer matches decile10 - decile1; re-check the erratum"
    )
    assert intended == pytest.approx(-recorded)
    assert recorded > 0 > intended, (
        "the sign inversion the erratum describes is not present"
    )
