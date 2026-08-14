"""APEX-003-H1 execution path: orientation, isolation, PIT. Pre-credit certification.

The one thing that can silently ruin this experiment is DECILE/SCORE ORIENTATION
-- the exact class of bug the APEX-002 erratum documented. Gross profitability is
HIGHER-is-better, so the highest-profitability names must score 100 and sit in
decile 1. Every orientation claim is pinned here with a positive control and a
counterexample against the inverted convention.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from apex.config import load_config
from apex.experiments import apex003

CFG = load_config("experiment", "costs", "synthetic", "sharadar")
REPO = Path(__file__).resolve().parents[1]


def _frames(values):
    dates = pd.DatetimeIndex(["2010-06-01"])
    secs = pd.Index([f"S{i:02d}" for i in range(len(values))], name="security_id")
    gp = pd.DataFrame([values], index=dates, columns=secs)
    elig = pd.DataFrame([[True] * len(values)], index=dates, columns=secs)
    return gp, elig


# --- ORIENTATION: higher profitability is better ---------------------------

def test_highest_profitability_scores_100():
    gp, elig = _frames(list(np.linspace(0.05, 0.45, 10)))
    score = apex003.gp_percentile_score(gp, elig).iloc[0]
    assert score.iloc[-1] == 100.0, "the most profitable name must score 100"
    assert score.is_monotonic_increasing, "score must rise with profitability"


def test_highest_profitability_is_decile_one():
    gp, elig = _frames(list(np.linspace(0.05, 0.45, 100)))
    decile = apex003.gp_deciles(gp, elig, 10).iloc[0]
    assert decile.iloc[-1] == 1.0, "most profitable must be TOP decile (1)"
    assert decile.iloc[0] == 10.0, "least profitable must be bottom decile (10)"


def test_score_and_decile_agree_on_the_best_name():
    gp, elig = _frames(list(np.linspace(0.05, 0.45, 50)))
    score = apex003.gp_percentile_score(gp, elig).iloc[0]
    decile = apex003.gp_deciles(gp, elig, 10).iloc[0]
    assert decile.loc[score.idxmax()] == 1.0, "highest score is not in decile 1"


def test_counterexample_the_nsi_lower_is_better_convention_would_invert():
    """Proof the orientation matters: NSI's lower-is-better scorer would put the
    LEAST profitable name at score 100 -- the APEX-002-erratum failure, here
    demonstrably avoided."""
    gp, elig = _frames(list(np.linspace(0.05, 0.45, 10)))
    from apex.features.nsi_scores import nsi_percentile_score
    wrong = nsi_percentile_score(gp, elig).iloc[0]     # treats LOW as best
    assert wrong.iloc[0] == 100.0, "counterexample inert: nsi scorer not inverted"
    correct = apex003.gp_percentile_score(gp, elig).iloc[0]
    assert correct.iloc[-1] == 100.0
    assert correct.iloc[0] != wrong.iloc[0], "gp and nsi orientations coincide -- bug"


def test_the_score_panel_declares_decile_1_as_top():
    gp, elig = _frames(list(np.linspace(0.05, 0.45, 40)))
    panel = apex003.build_gp_scores(gp, elig, CFG)
    assert panel.top_decile_label == 1


# --- ELIGIBILITY + MISSINGNESS ---------------------------------------------

def test_ineligible_names_are_not_scored():
    gp, elig = _frames([0.1, 0.2, 0.3, 0.4])
    elig.iloc[0, 1] = False
    score = apex003.gp_percentile_score(gp, elig).iloc[0]
    assert pd.isna(score.iloc[1]) and int(score.notna().sum()) == 3


def test_missing_profitability_is_excluded_not_filled():
    gp, elig = _frames([0.1, np.nan, 0.3, 0.4])
    score = apex003.gp_percentile_score(gp, elig).iloc[0]
    assert pd.isna(score.iloc[1]) and int(score.notna().sum()) == 3


def test_column_order_does_not_change_the_ranking():
    gp, elig = _frames([0.2, 0.2, 0.2, 0.2])      # ties
    a = apex003.gp_percentile_score(gp, elig)
    shuf = gp.columns[::-1]
    b = apex003.gp_percentile_score(gp.reindex(columns=shuf),
                                    elig.reindex(columns=shuf)).reindex(columns=gp.columns)
    pd.testing.assert_frame_equal(a, b)


# --- ISOLATION: #003 reaches neither #001 nor #002 scorer ------------------

def test_the_gp_path_reaches_no_other_experiments_scorer():
    from apex.audit.execution_path import certify_experiment
    assert certify_experiment(REPO, "APEX-003") == []


def test_counterexample_the_isolation_audit_flags_a_contaminated_entry():
    from apex.audit import execution_path as ep
    original = ep.EXPERIMENT_ENTRY["APEX-003"]
    try:
        ep.EXPERIMENT_ENTRY["APEX-003"] = "apex.experiments.apex002"  # #002's path
        findings = ep.certify_experiment(REPO, "APEX-003")
    finally:
        ep.EXPERIMENT_ENTRY["APEX-003"] = original
    assert any("nsi_scores" in f for f in findings)
    assert ep.certify_experiment(REPO, "APEX-003") == []


def test_all_three_experiments_are_isolated():
    from apex.audit.execution_path import certify_experiment
    for exp in ("APEX-001", "APEX-002", "APEX-003"):
        assert certify_experiment(REPO, exp) == [], f"{exp} not isolated"
