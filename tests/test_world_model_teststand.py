"""WM-0D -- the test stand must refuse to lie in either direction.

Nothing here optimises a metric. The two controls assert only that a
frozen pipeline, run identically on two worlds whose truth is known by
construction, says NOTHING where nothing was planted and SOMETHING
where something was.
"""
import math

import pytest

from apex.world_model.canonical import NumericContractViolation
from apex.world_model.features import (FEATURE_NAMES, WARMUP_STEPS,
                                       FeatureContractViolation, FrozenScaler,
                                       extract_features)
from apex.world_model.forecast import ForecastContractViolation
from apex.world_model.grader import (GRADER_VERSION, NULL_RULE, Z_RULE,
                                     GradingViolation, grade, null_rule)
from apex.world_model.models import (M0SyntheticBaseline,
                                     ModelContractViolation, NullBaseline,
                                     gaussian_distribution)
from apex.world_model.runs import (RUN_AUTHORITY, ChronologicalSplit,
                                   ModelRun, RunContractViolation)
from apex.world_model.targets import (HORIZON_NOT_AVAILABLE, TARGET_HORIZON,
                                      TARGET_HORIZON_STEPS, OutcomeRecord,
                                      resolve_target)
from apex.world_model.teststand import (StandViolation, build_dataset,
                                        control_experiment, run_pipeline)
from apex.world_model.worlds import (S0_NO_SIGNAL_RANDOM_WALK,
                                     S1_CAUSAL_TREND,
                                     S2_CAUSAL_MEAN_REVERSION,
                                     S3_REGIME_TRANSITION_JUMP,
                                     GeneratorGroundTruth, WorldConfig,
                                     generate_world)

SEED = 20260904


def world(wt=S0_NO_SIGNAL_RANDOM_WALK, n_steps=600, seed=SEED, **kw):
    kw.setdefault("observe_latent", True)
    kw.setdefault("n_subjects", 1)
    return generate_world(WorldConfig(world_type=wt, seed=seed,
                                      n_steps=n_steps, **kw))


# ===================================================== the two controls
def test_S0_returns_NO_SIGNAL_under_the_preregistered_rule():
    """Z_RULE was fixed in grader.py before any world was run."""
    assert Z_RULE == 2.0
    r = control_experiment(world(S0_NO_SIGNAL_RANDOM_WALK, n_steps=1200))
    assert r["verdict"]["verdict"] == "NO_SIGNAL", r["verdict"]
    assert r["verdict"]["rule"] == NULL_RULE


def test_S1_positive_control_is_distinguished_from_the_null():
    """Same frozen M0, same lambda, same features, same split. The only
    thing that changed is the WORLD."""
    r = control_experiment(world(S1_CAUSAL_TREND, n_steps=1200, sigma=0.002,
                                 params={"mu": 0.0015, "flip_prob": 0.02}))
    assert r["verdict"]["verdict"] == "SIGNAL_DETECTED", r["verdict"]
    assert r["m0"]["aggregate"]["nll"] < r["null"]["aggregate"]["nll"]


def test_the_controls_used_identical_model_configuration():
    """Proof of no retuning: the M0 configuration hash is the same on
    S0 and S1. Only the fitted parameters may differ."""
    r0 = control_experiment(world(S0_NO_SIGNAL_RANDOM_WALK))
    r1 = control_experiment(world(S1_CAUSAL_TREND, params={"mu": 0.001}))
    c0 = r0["m0"]["run"].content()["training_configuration"]["model"]
    c1 = r1["m0"]["run"].content()["training_configuration"]["model"]
    assert c0 == c1 == {"ridge_lambda": 1.0, "residual": "gaussian",
                        "bias_penalised": False}


@pytest.mark.parametrize("wt,params", [
    (S2_CAUSAL_MEAN_REVERSION, {"theta": 0.05}),
    (S3_REGIME_TRANSITION_JUMP, {"lambda_stress": 0.1, "jump_size": 0.01}),
])
def test_S2_S3_smoke_compatibility_only(wt, params):
    """Contract compatibility, NOT a result. M0 is a linear baseline and
    is not redesigned because these worlds are nonlinear."""
    r = control_experiment(world(wt, params=params))
    assert r["verdict"]["verdict"] in ("NO_SIGNAL", "SIGNAL_DETECTED")
    assert r["m0"]["aggregate"]["n"] > 0


# ============================================== MODEL_RUN_V0 contract
def test_model_run_contract_is_valid_and_hashable():
    r = run_pipeline(world(), M0SyntheticBaseline())
    run = r["run"]
    s = run.sealed()
    assert s["authority"] == RUN_AUTHORITY == "SYNTHETIC_RESEARCH_ONLY"
    assert s["TRADING_AUTHORITY"] == "NONE"
    assert s["run_hash"] and s["configuration_hash"]
    assert s["forecast_horizon"] == TARGET_HORIZON == "H_15M"
    for k in ("training_world_ids", "evaluation_world_ids", "world_hashes",
              "feature_set_version", "target_definition", "split", "seed"):
        assert k in s


def test_run_identity_is_deterministic():
    a = run_pipeline(world(), M0SyntheticBaseline())["run"].run_hash
    b = run_pipeline(world(), M0SyntheticBaseline())["run"].run_hash
    assert a == b


def test_run_identity_excludes_creation_time():
    a = run_pipeline(world(), M0SyntheticBaseline(), creation_time=1.0)
    b = run_pipeline(world(), M0SyntheticBaseline(), creation_time=2.0)
    assert a["run"].run_hash == b["run"].run_hash


def test_forecasts_are_reproducible_within_stated_tolerance():
    """Byte identity is NOT claimed for floating point; a relative
    tolerance of 1e-9 on distribution parameters is."""
    a = run_pipeline(world(), M0SyntheticBaseline())["forecasts"]
    b = run_pipeline(world(), M0SyntheticBaseline())["forecasts"]
    assert len(a) == len(b)
    for fa, fb in zip(a, b):
        da, db = fa.distribution.canonical(), fb.distribution.canonical()
        assert math.isclose(da["expected_return"], db["expected_return"],
                            rel_tol=1e-9, abs_tol=1e-12)
        assert math.isclose(da["total_uncertainty"], db["total_uncertainty"],
                            rel_tol=1e-9)
        assert fa.forecast_hash == fb.forecast_hash


def test_run_refuses_real_market_provenance():
    w = world()
    with pytest.raises(RunContractViolation, match="Real-market provenance"):
        ModelRun(run_id="r", model_id="m", model_family="f",
                 model_version="1", code_commit="c", information_tier="A0_CORE",
                 training_world_ids=(w.world_id,),
                 evaluation_world_ids=(w.world_id,),
                 world_hashes={w.world_id: w.world_hash},
                 fixture_classes={w.world_id: "REAL_HISTORICAL_LABEL"},
                 split=ChronologicalSplit(600, 360), seed=0,
                 training_configuration={}, creation_time=1.0)


def test_run_refuses_non_synthetic_world_id():
    with pytest.raises(RunContractViolation, match="not a generated"):
        ModelRun(run_id="r", model_id="m", model_family="f",
                 model_version="1", code_commit="c", information_tier="A0_CORE",
                 training_world_ids=("SPY_2026-09-03",),
                 evaluation_world_ids=("SPY_2026-09-03",),
                 world_hashes={"SPY_2026-09-03": "x"},
                 fixture_classes={"SPY_2026-09-03": "SYNTHETIC_FIXTURE"},
                 split=ChronologicalSplit(600, 360), seed=0,
                 training_configuration={}, creation_time=1.0)


def test_run_refuses_wrong_authority():
    w = world()
    with pytest.raises(RunContractViolation, match="authority"):
        ModelRun(run_id="r", model_id="m", model_family="f",
                 model_version="1", code_commit="c", information_tier="A0_CORE",
                 training_world_ids=(w.world_id,), evaluation_world_ids=(w.world_id,),
                 world_hashes={w.world_id: w.world_hash},
                 fixture_classes={w.world_id: "SYNTHETIC_FIXTURE"},
                 split=ChronologicalSplit(600, 360), seed=0,
                 training_configuration={}, creation_time=1.0,
                 authority="LIVE_TRADING")


# ====================================== observable-only feature access
def test_feature_extraction_accepts_only_observable_state():
    w = world()
    truth = w.ground_truth()
    with pytest.raises(FeatureContractViolation, match="ObservableState only"):
        extract_features((truth,) * 10, 6)


def test_model_fit_has_no_parameter_for_a_world_or_truth():
    import inspect
    for cls in (M0SyntheticBaseline, NullBaseline):
        sig = inspect.signature(cls.fit)
        assert set(sig.parameters) == {"self", "X", "y"}, cls


def test_pipeline_refuses_a_truth_object_as_the_model():
    with pytest.raises(StandViolation, match="answer key"):
        run_pipeline(world(), world().ground_truth())


def test_target_resolver_returns_one_number_not_the_truth_object():
    w = world()
    rec = resolve_target(w, "SYN_A", 10)
    assert isinstance(rec, OutcomeRecord)
    assert not isinstance(rec, GeneratorGroundTruth)
    for banned in ("latent_path", "regime_path", "full_price_path",
                   "jump_steps", "shared_factor"):
        assert not hasattr(rec, banned)


def test_frozen_features_exclude_future_and_latent_truth_vocabulary():
    for n in FEATURE_NAMES:
        low = n.lower()
        for tok in ("future", "forward", "mfe", "mae", "regime", "truth",
                    "label", "outcome"):
            assert tok not in low, n


def test_features_do_not_zero_fill_the_warmup():
    w = world()
    with pytest.raises(FeatureContractViolation, match="NOT filled with zero"):
        extract_features(w.observables["SYN_A"], WARMUP_STEPS - 1)


# ============================================ chronological split + purge
def test_split_is_chronological_and_purged():
    s = ChronologicalSplit(n_steps=600, boundary=360)
    tr, pu, ev = s.train_steps, s.purged_steps, s.eval_steps
    assert max(tr) + TARGET_HORIZON_STEPS <= 360, (
        "a training label reads an evaluation-period price")
    assert min(ev) == 360
    assert list(pu) == list(range(360 - TARGET_HORIZON_STEPS + 1, 360))
    assert max(tr) < min(pu) < min(ev)
    assert max(ev) + TARGET_HORIZON_STEPS <= 600


def test_no_training_target_depends_on_evaluation_prices():
    """The mathematical statement, checked on the actual dataset."""
    w = world(n_steps=600)
    s = ChronologicalSplit(600, 360)
    _, _, tr_idx, _ = build_dataset(w, "SYN_A", s.train_steps)
    assert all(t + TARGET_HORIZON_STEPS <= 360 for t in tr_idx)


def test_bad_split_refused():
    with pytest.raises(RunContractViolation, match="no purged training"):
        ChronologicalSplit(n_steps=100, boundary=18)
    with pytest.raises(RunContractViolation, match="no evaluation interval"):
        ChronologicalSplit(n_steps=100, boundary=90)


def test_empty_partition_refused():
    w = world(n_steps=60)
    with pytest.raises(StandViolation, match="empty partition"):
        build_dataset(w, "SYN_A", range(50, 50))


# ================================================ train-only transforms
def test_scaler_is_fit_on_train_and_frozen():
    Xtr = [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]]
    sc = FrozenScaler.fit(Xtr)
    assert sc.n_fit == 3
    assert sc.means == (2.0, 20.0)


def test_evaluation_shift_cannot_alter_training_normalisation():
    """LEAKAGE TEST: shift the evaluation distribution by +1000 and prove
    the frozen training parameters are untouched and applied verbatim."""
    Xtr = [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0], [4.0, 4.0]]
    sc = FrozenScaler.fit(Xtr)
    before = sc.canonical()
    Xev_shifted = [[1001.0, 1001.0], [1002.0, 1002.0]]
    out = sc.transform(Xev_shifted)
    assert sc.canonical() == before, "evaluation data altered the scaler"
    # transformed with TRAINING mean 2.5, TRAINING scale, not its own
    assert out[0][0] == pytest.approx((1001.0 - 2.5) / sc.scales[0])


def test_constant_column_is_centred_not_divided_by_zero():
    sc = FrozenScaler.fit([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
    assert sc.scales[0] == 1.0
    assert sc.transform([[5.0, 2.0]])[0][0] == 0.0


# ================================================== probabilistic output
def test_M0_emits_a_full_distribution_not_a_direction():
    r = run_pipeline(world(), M0SyntheticBaseline())
    d = r["forecasts"][0].distribution.canonical()
    for k in ("expected_return", "median_return", "quantiles",
              "prob_return_gt_zero", "predictive_intervals",
              "total_uncertainty"):
        assert d[k] is not None, k
    assert set(d["quantiles"]) == {"0.05", "0.25", "0.5", "0.75", "0.95"}


def test_M0_declares_it_cannot_split_epistemic_from_aleatoric():
    r = run_pipeline(world(), M0SyntheticBaseline())
    d = r["forecasts"][0].distribution.canonical()
    assert d["epistemic_uncertainty"] is None
    assert d["aleatoric_uncertainty"] is None
    assert M0SyntheticBaseline().capabilities()["epistemic_aleatoric_split"] is False


def test_null_comparator_emits_a_valid_forecast_and_ignores_features():
    nl = NullBaseline().fit([[1.0], [2.0], [3.0], [4.0]], [0.1, -0.1, 0.2, -0.2])
    a = nl.predict_distribution([0.0]).canonical()
    b = nl.predict_distribution([999.0]).canonical()
    assert a == b, "the null used a feature"
    assert a["quantiles"] and a["predictive_intervals"]


def test_gaussian_distribution_refuses_bad_sigma():
    with pytest.raises(ModelContractViolation):
        gaussian_distribution(0.0, 0.0)
    with pytest.raises(ModelContractViolation):
        gaussian_distribution(0.0, -1.0)


# ================================================= forecast immutability
def test_every_evaluation_forecast_is_sealed_before_truth_and_unchanged_after():
    r = run_pipeline(world(), M0SyntheticBaseline())
    for f, g in zip(r["forecasts"], r["grades"]):
        assert r["sealed_hashes"][f.forecast_id] == g.forecast_hash_before
        assert g.forecast_hash_before == g.forecast_hash_after
        assert g.forecast_hash_after == f.forecast_hash


def test_grader_refuses_an_outcome_knowable_before_the_forecast():
    r = run_pipeline(world(), M0SyntheticBaseline())
    f = r["forecasts"][0]
    early = OutcomeRecord(world_id="W-x", world_hash="h", subject="SYN_A",
                          step=0, horizon="H_15M", target_value=0.0,
                          outcome_known_time=f.known_from - 1.0)
    with pytest.raises(GradingViolation, match="could have seen its own answer"):
        grade(f, early, grading_time=f.known_from + 1)


def test_post_outcome_tampering_is_detected():
    """A forecast whose distribution is swapped after sealing produces a
    different hash and therefore no longer matches the sealed record."""
    r = run_pipeline(world(), M0SyntheticBaseline())
    f = r["forecasts"][0]
    sealed = r["sealed_hashes"][f.forecast_id]
    from apex.world_model.forecast import WorldModelForecast
    tampered = WorldModelForecast(
        forecast_id=f.forecast_id, input_id=f.input_id, input_hash=f.input_hash,
        model_id=f.model_id, model_version=f.model_version,
        model_family=f.model_family, information_tier=f.information_tier,
        creation_time=f.creation_time, known_from=f.known_from,
        forecast_horizon=f.forecast_horizon,
        distribution=gaussian_distribution(0.5, 0.001))   # "predicted" the answer
    assert tampered.forecast_hash != sealed, "tampering went undetected"


def test_grade_records_forecast_and_outcome_as_separate_identities():
    r = run_pipeline(world(), M0SyntheticBaseline())
    g = r["grades"][0]
    assert g.forecast_hash_before != g.outcome_hash
    assert g.grader_version == GRADER_VERSION
    assert g.grade_hash


# ======================================================= failure modes
def test_nan_in_training_refused():
    with pytest.raises(NumericContractViolation):
        M0SyntheticBaseline().fit([[float("nan")], [1.0], [2.0], [3.0]],
                                  [0.0, 0.1, 0.2, 0.3])


def test_inf_target_refused():
    with pytest.raises(NumericContractViolation):
        NullBaseline().fit([[1.0], [2.0], [3.0]], [0.0, float("inf"), 0.2])


def test_degenerate_fit_refused():
    with pytest.raises(ModelContractViolation, match="degenerate"):
        M0SyntheticBaseline().fit([[1.0, 2.0]], [0.1])


def test_zero_variance_target_refused_by_null():
    with pytest.raises(ModelContractViolation, match="zero variance"):
        NullBaseline().fit([[1.0], [2.0], [3.0]], [0.5, 0.5, 0.5])


def test_predict_before_fit_refused():
    with pytest.raises(ModelContractViolation, match="before fit"):
        M0SyntheticBaseline().predict_distribution([0.0])


def test_null_rule_refuses_unpaired_or_mismatched_outcomes():
    r0 = run_pipeline(world(seed=1), M0SyntheticBaseline())
    r1 = run_pipeline(world(seed=2), NullBaseline())
    with pytest.raises(GradingViolation, match="DIFFERENT outcomes"):
        null_rule(r0["grades"], r1["grades"])


# ============================================ diagnostics, not objectives
def test_aggregate_metrics_present_and_sane():
    r = run_pipeline(world(), M0SyntheticBaseline())
    a = r["aggregate"]
    for k in ("n", "nll", "mean_residual", "rmse", "mae", "coverage_0.9",
              "pinball", "brier", "log_loss"):
        assert k in a, k
    assert 0.0 <= a["coverage_0.9"] <= 1.0
    assert 0.0 <= a["brier"] <= 1.0


def test_no_economic_vocabulary_in_the_test_stand():
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    for f in ("teststand.py", "grader.py", "models.py", "runs.py"):
        src = (pkg / f).read_text().lower()
        for bad in ("sharpe", "pnl", "p&l", "win_rate", "win rate",
                    "kelly", "position_size", "transaction cost",
                    "alpha"):
            assert bad not in src, "%s mentions %s" % (f, bad)


# =========================================================== authority
def test_test_stand_modules_import_no_production_apex_and_no_broker():
    import ast
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    placement = ("place_order", "place_equity_order", "place_option_order",
                 "submit_order", "execute_order", "send_order")
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            mod = None
            if isinstance(n, ast.ImportFrom):
                mod = n.module or ""
            elif isinstance(n, ast.Import):
                mod = n.names[0].name
            if mod and mod.startswith("apex"):
                assert mod.startswith("apex.world_model"), (f.name, mod)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert n.name not in placement, f.name


def test_real_data_firewall_still_active_under_WM0D():
    from apex.world_model import admit
    from apex.world_model.sources import SourceAdmissionRefused
    with pytest.raises(SourceAdmissionRefused, match="REAL_EVIDENCE_PATH"):
        admit("/apex-data/core/btc/window_outcomes.jsonl",
              declared_class="SYNTHETIC_FIXTURE")
