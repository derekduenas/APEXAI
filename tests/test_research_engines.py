"""The reusable research engines: stats, manifest, ML accounting, causal, regime.

Each engine EVALUATES a declared question and is structurally incapable of
searching or selecting. Every test proves both the positive behaviour and that
the refusal (no 'best', no bare causal claim, no fit, no future leak) can fire.
No credit, no model fit, no holdout, no alpha claim.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apex.stats import robustness as R


# === 1. STATISTICAL ROBUSTNESS =============================================

def test_positive_control_bootstrap_ci_excludes_zero():
    pos = R.positive_control_series(500, mean=0.30, seed=1)
    b = R.moving_block_bootstrap_mean(pos, block_size=20, n_resamples=2000, seed=7)
    assert b.ci_low > 0, "a known positive mean was not detected"


def test_negative_control_bootstrap_ci_includes_zero():
    neg = R.negative_control_series(500, seed=1)
    b = R.moving_block_bootstrap_mean(neg, block_size=20, n_resamples=2000, seed=7)
    assert b.ci_low < 0 < b.ci_high, "a mean-zero series was called significant"


def test_positive_control_permutation_rejects_null():
    pos = R.positive_control_series(500, mean=0.30, seed=1)
    p = R.block_sign_permutation(pos, block_size=20, n_permutations=2000, seed=7)
    assert p.p_value_two_sided < 0.05


def test_negative_control_permutation_does_not_reject():
    neg = R.negative_control_series(500, seed=1)
    p = R.block_sign_permutation(neg, block_size=20, n_permutations=2000, seed=7)
    assert p.p_value_two_sided > 0.05


def test_bootstrap_is_deterministic_given_a_seed():
    pos = R.positive_control_series(300, mean=0.1, seed=3)
    a = R.moving_block_bootstrap_mean(pos, block_size=20, n_resamples=1000, seed=9)
    b = R.moving_block_bootstrap_mean(pos, block_size=20, n_resamples=1000, seed=9)
    assert a.as_dict() == b.as_dict()


def test_permutation_p_value_is_never_exactly_zero():
    """+1 smoothing: a permutation p is a proportion over finite draws."""
    pos = R.positive_control_series(500, mean=5.0, seed=1)   # huge signal
    p = R.block_sign_permutation(pos, block_size=20, n_permutations=100, seed=1)
    assert p.p_value_two_sided > 0


def test_counterexample_the_stats_engine_exposes_no_select_best():
    """The control: there is no search/optimise entry point."""
    for banned in ("select_best", "best_block_size", "optimise", "argmax",
                   "search", "tune"):
        assert not hasattr(R, banned), f"robustness exposes {banned}: it can search"


def test_subperiod_reports_all_subperiods_and_ranks_none():
    s = R.positive_control_series(600, mean=0.05, seed=2)
    result = R.subperiod_means(s, scheme="calendar_year")
    assert result.n_subperiods >= 2
    # the object carries per-subperiod means but no 'best'/'strongest' field
    assert "best" not in result.as_dict()
    assert "strongest_subperiod" not in result.as_dict()


def test_counterexample_a_bad_block_size_is_refused():
    s = R.positive_control_series(100, mean=0.1, seed=1)
    with pytest.raises(R.RobustnessError):
        R.moving_block_bootstrap_mean(s, block_size=999, n_resamples=10, seed=1)


def test_multiple_comparison_exposes_the_denominator():
    mc = R.MultipleComparison(n_comparisons=5, family_alpha=0.05)
    assert mc.bonferroni_alpha() == pytest.approx(0.01)
    assert mc.as_dict()["n_comparisons"] == 5


# === 2. RESEARCH MANIFEST ==================================================

def _science(**over):
    base = {
        "experiment_id": "APEX-XXX", "hypothesis_dossier_hash": "d" * 64,
        "dataset_fingerprint": "f" * 64, "feature_signature": "sig",
        "protocol_hash": "p" * 64, "config_hash": "c" * 64,
        "sample_definition": "in_sample 2005-2017", "method": "spearman_ic",
        "seed": 20260807,
    }
    base.update(over)
    return base


def test_manifest_science_id_is_stable_across_presentation_changes():
    from apex.research.manifest import ResearchManifest

    a = ResearchManifest(science=_science(), provenance={"author": "x"},
                         presentation={"title": "First title"})
    b = ResearchManifest(science=_science(), provenance={"author": "x"},
                         presentation={"title": "Totally different title"})
    assert a.same_science_as(b), "a presentation change altered scientific identity"
    assert a.science_id == b.science_id


def test_counterexample_a_science_change_changes_identity():
    from apex.research.manifest import ResearchManifest

    a = ResearchManifest(science=_science(seed=1), provenance={"author": "x"})
    b = ResearchManifest(science=_science(seed=2), provenance={"author": "x"})
    assert a.science_id != b.science_id, "a seed change did not change identity"


def test_provenance_changes_full_id_but_not_science_id():
    from apex.research.manifest import ResearchManifest

    a = ResearchManifest(science=_science(), provenance={"author": "alice"})
    b = ResearchManifest(science=_science(), provenance={"author": "bob"})
    assert a.science_id == b.science_id
    assert a.full_id != b.full_id


def test_counterexample_a_manifest_missing_a_science_key_is_refused():
    from apex.research.manifest import ManifestError, ResearchManifest

    incomplete = _science()
    del incomplete["dataset_fingerprint"]
    with pytest.raises(ManifestError, match="not reconstructible"):
        ResearchManifest(science=incomplete, provenance={})


def test_counterexample_a_freeform_science_field_is_refused():
    from apex.research.manifest import ManifestError, ResearchManifest

    with pytest.raises(ManifestError, match="unknown scientific input"):
        ResearchManifest(science=_science(vibe="good"), provenance={})


# === 3. ML SEARCH ACCOUNTING (no fitting) ==================================

def _spec(**over):
    from apex.ml.search_ledger import ModelSpec
    base = {"model_family": "gbm", "feature_ids": ("prof_gross_profitability",),
            "target": "fwd_excess_20d", "cv_scheme": "purged_walk_forward"}
    base.update(over)
    return ModelSpec(**base)


def test_the_search_denominator_counts_distinct_specs():
    from apex.ml.search_ledger import ModelSearchLedger

    ledger = ModelSearchLedger()
    ledger.consider(_spec(model_family="gbm"))
    ledger.consider(_spec(model_family="random_forest"))
    ledger.consider(_spec(model_family="gbm"))          # duplicate: same comparison
    assert ledger.n_comparisons == 2, "the denominator miscounted distinct specs"


def test_counterexample_a_different_hyperparameter_grid_is_a_new_comparison():
    from apex.ml.search_ledger import ModelSearchLedger

    ledger = ModelSearchLedger()
    ledger.consider(_spec(hyperparameter_grid={"depth": [3]}))
    ledger.consider(_spec(hyperparameter_grid={"depth": [5]}))
    assert ledger.n_comparisons == 2, (
        "changing the hyperparameter grid did not count as a new comparison; "
        "the file-drawer denominator would be understated"
    )


def test_counterexample_select_best_is_refused():
    """A winner cannot be named without a registered, credit-consuming search."""
    from apex.ml.search_ledger import ModelSearchLedger, SearchError

    ledger = ModelSearchLedger()
    ledger.consider(_spec())
    with pytest.raises(SearchError, match="not available"):
        ledger.select_best()


def test_the_ml_package_fits_no_model():
    """The keystone: no fitting library anywhere in apex/ml."""
    import inspect

    from apex.ml import search_ledger
    from apex.audit.execution_path import executable_source

    code = executable_source(inspect.getsource(search_ledger))
    for lib in ("sklearn", "xgboost", "lightgbm", "torch", ".fit("):
        assert lib not in code


# === 4. CAUSAL CLAIM =======================================================

def test_a_descriptive_claim_needs_no_placebo():
    from apex.causal.claim import CausalClaim, DESCRIPTIVE

    c = CausalClaim(treatment="t", outcome="o", confounders=("sector",),
                    rung=DESCRIPTIVE, identification_strategy="placebo",
                    assumptions=(), placebo_passed=False)
    assert c.rung == DESCRIPTIVE


def test_counterexample_a_causal_hypothesis_without_a_placebo_is_refused():
    from apex.causal.claim import CausalClaim, CausalError, HYPOTHESIS

    with pytest.raises(CausalError, match="placebo"):
        CausalClaim(treatment="t", outcome="o", confounders=("sector",),
                    rung=HYPOTHESIS, identification_strategy="placebo",
                    assumptions=("no unobserved confounder",), placebo_passed=False)


def test_counterexample_a_causal_hypothesis_without_assumptions_is_refused():
    from apex.causal.claim import CausalClaim, CausalError, HYPOTHESIS

    with pytest.raises(CausalError, match="assumptions"):
        CausalClaim(treatment="t", outcome="o", confounders=(),
                    rung=HYPOTHESIS, identification_strategy="placebo",
                    assumptions=(), placebo_passed=True)


def test_counterexample_an_unsupported_identification_strategy_is_refused():
    """IV/RDD/DiD are not supported by the data and must not be faked."""
    from apex.causal.claim import CausalClaim, CausalError, HYPOTHESIS

    with pytest.raises(CausalError, match="not supported"):
        CausalClaim(treatment="t", outcome="o", confounders=("x",),
                    rung=HYPOTHESIS, identification_strategy="instrumental_variable",
                    assumptions=("relevance",), placebo_passed=True)


def test_a_well_formed_causal_hypothesis_is_accepted():
    from apex.causal.claim import CausalClaim, HYPOTHESIS

    c = CausalClaim(treatment="low_accruals", outcome="fwd_return",
                    confounders=("sector", "size"), rung=HYPOTHESIS,
                    identification_strategy="neutralised_re_test",
                    assumptions=("sector/size capture the confounding",),
                    placebo_passed=True)
    assert "confirmed" not in c.as_dict()   # no 'confirmed' field can exist


# === 5. REGIME ENGINE ======================================================

def _regime_def(**over):
    from apex.regime.engine import RegimeDefinition
    base = {"name": "vol", "version": "1", "state_variable": "trailing_vol",
            "thresholds": (0.15,), "labels": ("low", "high"), "min_sample": 10,
            "lineage": "VIX tercile"}
    base.update(over)
    return RegimeDefinition(**base)


def _state():
    return pd.Series(np.linspace(0.05, 0.30, 120),
                     index=pd.bdate_range("2010-01-01", periods=120))


def test_regime_assignment_is_deterministic():
    from apex.regime.engine import assign_regime

    a = assign_regime(_state(), _regime_def())
    b = assign_regime(_state(), _regime_def())
    assert a.as_dict() == b.as_dict()


def test_regime_assigns_the_declared_labels():
    from apex.regime.engine import assign_regime

    a = assign_regime(_state(), _regime_def())
    assert set(a.counts) == {"low", "high"}
    assert a.counts["low"] + a.counts["high"] == 120


def test_counterexample_a_future_state_value_is_refused():
    """PIT: a state variable knowable only after T cannot assign T."""
    from apex.regime.engine import RegimeError, assign_regime

    state = _state()
    late = pd.Series(state.index + pd.Timedelta(days=5), index=state.index)  # asof > T
    with pytest.raises(RegimeError, match="future leak"):
        assign_regime(state, _regime_def(), knowable_asof=late)


def test_counterexample_a_mismatched_label_count_is_refused():
    with pytest.raises(Exception):
        _regime_def(labels=("low", "mid", "high"))   # 3 labels, 1 threshold


def test_the_regime_engine_cannot_select_the_best_regime():
    """It evaluates a declared definition; there is no discover-best method."""
    from apex.regime import engine

    for banned in ("best_regime", "select_regime", "optimise", "search"):
        assert not hasattr(engine, banned)
