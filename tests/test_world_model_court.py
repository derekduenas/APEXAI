"""WM-0E -- the court must be sealed before it sits, and it must refuse
every way a researcher could quietly help it along."""
import inspect
import math

import pytest

from apex.world_model import court as CT
from apex.world_model import controls as C
from apex.world_model.budget import (CATEGORIES, BudgetViolation,
                                     ResearchBudget, wm0d_truth)
from apex.world_model.canonical import content_hash
from apex.world_model.grader import GradingViolation, grade
from apex.world_model.models import M0SyntheticBaseline
from apex.world_model.targets import OutcomeRecord
from apex.world_model.teststand import default_dataset, run_pipeline
from apex.world_model.worlds import (S1_CAUSAL_TREND, WorldConfig,
                                     _stream_rng, generate_world)


def small_defn(**kw):
    m = M0SyntheticBaseline().model_identity()
    d = dict(court_id="T", code_commit="c",
             model_identity={"model_id": m["model_id"],
                             "model_version": m["model_version"],
                             "configuration": m["configuration"]},
             model_config_hash=content_hash(m["configuration"]),
             creation_time=0.0)
    d.update(kw)
    return CT.CourtDefinition(**d)


def s1(seed=1000, n_steps=400):
    return generate_world(WorldConfig(world_type=S1_CAUSAL_TREND, seed=seed,
                                      n_subjects=1, n_steps=n_steps,
                                      sigma=CT.S1_SIGMA, params=CT.S1_PARAMS,
                                      observe_latent=True))


# ================================================ the court is sealed
def test_court_hash_commits_to_seeds_rule_tolerance_and_model():
    base = small_defn().court_hash
    assert small_defn(seed_set=tuple(list(CT.SEED_SET)[:-1])).court_hash != base, \
        "removing a seed kept the court identity"
    assert small_defn(seed_set=CT.SEED_SET + (9999,)).court_hash != base, \
        "adding a seed kept the court identity"
    assert small_defn(model_config_hash="other").court_hash != base
    assert small_defn(code_commit="other").court_hash != base


def test_decision_rule_and_tolerance_are_inside_the_sealed_definition():
    c = small_defn().canonical()
    assert c["z_rule"] == 2.0 and c["decision_rule_hash"]
    assert c["error_control"]["max_tolerated_false_positives"] == 3
    assert c["positive_control_rule"]["min_detection_rate"] == 0.80
    assert c["seed_set_hash"] == content_hash(list(CT.SEED_SET))
    assert c["authority"] == "SYNTHETIC_RESEARCH_ONLY"
    assert c["number_of_tests"] == 25 * 6


def test_changing_the_rule_would_change_the_sealed_hash():
    c = small_defn().canonical()
    alt = dict(c); alt["z_rule"] = 1.5
    assert content_hash(alt) != content_hash(c)


def test_seed_set_is_predeclared_and_not_cherry_picked():
    assert CT.SEED_SET == tuple(1000 + 37 * i for i in range(25))
    assert len(set(CT.SEED_SET)) == 25


# ==================================== court-level error control maths
def test_binomial_tail_is_correct():
    assert CT.binomial_tail(25, 0.023, 0) == pytest.approx(1.0)
    assert CT.binomial_tail(25, 0.023, 26) == 0.0
    assert CT.binomial_tail(25, 0.023, 4) == pytest.approx(0.0024, abs=3e-4)


def test_error_control_is_stated_with_its_independence_caveat():
    ec = small_defn().error_control()
    assert ec["expected_false_positives"] == pytest.approx(0.575)
    assert ec["court_false_fail_probability_per_control"] < 0.005
    assert "ACROSS seeds only" in ec["independence_assumption"]


def test_court_tolerates_predeclared_false_positives_not_zero():
    cells = [{"verdict": "SIGNAL_DETECTED", "z": 2.5, "mean_loglik_gain": 0.1}] * 3 + \
            [{"verdict": "NO_SIGNAL", "z": 0.1, "mean_loglik_gain": 0.0}] * 22
    j = CT.judge_control(cells, "N0")
    assert j["court_verdict"] == "PASS" and j["false_positives"] == 3
    cells4 = cells + [{"verdict": "SIGNAL_DETECTED", "z": 2.1, "mean_loglik_gain": 0.1}]
    assert CT.judge_control(cells4, "N0")["court_verdict"] == "CONTROL_FAILURE"


def test_run_invalid_makes_a_control_INVALID_not_pass():
    cells = [{"verdict": "RUN_INVALID", "error": "boom"}] + \
            [{"verdict": "NO_SIGNAL", "z": 0.0, "mean_loglik_gain": 0.0}] * 24
    assert CT.judge_control(cells, "N2")["court_verdict"] == "INVALID"


def test_verdict_taxonomy_has_distinct_words_not_one_pass_fail():
    assert len({CT.NO_SIGNAL, CT.SIGNAL_DETECTED, CT.RUN_INVALID}) == 3
    assert len({CT.PASS, CT.CONTROL_FAILURE, CT.INVALID}) == 3


def test_NO_SIGNAL_is_a_value_not_an_exception():
    assert isinstance(CT.NO_SIGNAL, str)
    assert not isinstance(CT.NO_SIGNAL, BaseException)


# ======================================================== the controls
def test_every_control_declares_destroys_preserves_expected():
    for k in ("N0", "N1", "N2", "N3", "N4"):
        c = C.CONTROL_CONTRACT[k]
        assert c["destroys"] and c["preserves"] and c["expected"] == "NO_SIGNAL"
    assert C.CONTROL_CONTRACT["P0"]["expected"] == "SIGNAL_DETECTED"


def test_derangement_has_no_fixed_points_and_refuses_n_below_2():
    rng = _stream_rng("t", "t", 1, "d")
    for n in (2, 3, 7, 25, 100):
        p = C.derangement(n, rng)
        assert sorted(p) == list(range(n))
        assert all(i != j for i, j in enumerate(p)), n
    with pytest.raises(C.ControlViolation, match="no-op"):
        C.derangement(1, rng)


def test_N0_block_derangement_preserves_X_and_breaks_pairing():
    w = s1()
    from apex.world_model.runs import ChronologicalSplit
    sp = ChronologicalSplit(400, 240)
    Xtr, ytr, Xev, yev, ev_idx, ev_out = default_dataset(w, "SYN_A", sp)
    Xtr2, ytr2, Xev2, yev2, ev_idx2, ev_out2 = C.n0_dataset("T", 1)(w, "SYN_A", sp)
    ktr, kev = len(ytr2), len(yev2)
    assert ktr % C.N0_BLOCK_STEPS == 0 and kev % C.N0_BLOCK_STEPS == 0
    assert Xtr2 == Xtr[:ktr] and Xev2 == Xev[:kev], "N0 touched X"
    assert ytr2 != ytr[:ktr] and yev2 != yev[:kev], "N0 left y unchanged (no-op)"
    assert sorted(ytr2) == sorted(ytr[:ktr]), "N0 changed y's multiset"
    assert sorted(yev2) == sorted(yev[:kev]), "N0 changed y's multiset (eval)"
    assert len(ytr) - ktr < C.N0_BLOCK_STEPS, "N0 dropped more than a partial block"
    assert [o.target_value for o in ev_out2] == yev2
    assert [o.outcome_known_time for o in ev_out2] == [o.outcome_known_time for o in ev_out[:kev]]


def test_N1_shift_is_far_beyond_latent_persistence():
    assert C.N1_SHIFT_STEPS == 200
    assert C.N1_RESIDUAL_AUTOCORR < 1e-3, C.N1_RESIDUAL_AUTOCORR


def test_N1_recomputes_the_purge_for_the_displaced_target():
    w = s1(n_steps=1200)
    from apex.world_model.runs import ChronologicalSplit
    sp = ChronologicalSplit(1200, 720)
    Xtr, ytr, Xev, yev, ev_idx, ev_out = C.n1_dataset("T", 1)(w, "SYN_A", sp)
    assert len(Xtr) > 50 and len(Xev) > 50
    # every eval outcome is known AFTER its forecast step
    for s, o in zip(ev_idx, ev_out):
        assert o.outcome_known_time > w.config.session_start + s * w.config.step_seconds


def test_N1_reversed_displacement_is_refused_by_the_grader():
    """Features from the target's FUTURE: the outcome was knowable
    before the forecast, and the grader must say so."""
    w = s1()
    r = run_pipeline(w, M0SyntheticBaseline())
    f = r["forecasts"][-1]
    from apex.world_model.targets import resolve_target
    earlier = resolve_target(w, "SYN_A", 6)          # long before f
    with pytest.raises(GradingViolation, match="could have seen its own answer"):
        grade(f, earlier, grading_time=f.known_from + 1)


def test_N2_features_come_from_a_prng_not_from_truth():
    src = inspect.getsource(C.n2_dataset)
    for banned in ("ground_truth", "full_price_path", "latent", "regime", "y["):
        assert banned not in src, banned
    w = s1()
    from apex.world_model.runs import ChronologicalSplit
    sp = ChronologicalSplit(400, 240)
    _, ytr, _, yev, _, ev_out = default_dataset(w, "SYN_A", sp)
    Xtr2, ytr2, Xev2, yev2, _, ev_out2 = C.n2_dataset("T", 1)(w, "SYN_A", sp)
    assert ytr2 == ytr and yev2 == yev and ev_out2 == ev_out, "N2 touched y"


def test_N3_permutation_does_not_depend_on_y():
    """Same (court, seed) => same permutation regardless of targets."""
    a = C.derangement(50, _stream_rng("T", "N3", 7, "train"))
    b = C.derangement(50, _stream_rng("T", "N3", 7, "train"))
    assert a == b
    src = inspect.getsource(C.n3_dataset)
    assert "ytr" not in src.split("derangement")[1].split("\n")[0]


def test_N3_preserves_X_marginals_and_y():
    w = s1()
    from apex.world_model.runs import ChronologicalSplit
    sp = ChronologicalSplit(400, 240)
    Xtr, ytr, Xev, yev, _, _ = default_dataset(w, "SYN_A", sp)
    Xtr2, ytr2, Xev2, yev2, _, _ = C.n3_dataset("T", 1)(w, "SYN_A", sp)
    assert sorted(map(tuple, Xtr2)) == sorted(map(tuple, Xtr))
    assert Xtr2 != Xtr and ytr2 == ytr and yev2 == yev


def test_N4_random_ranker_cannot_see_outcome_or_features():
    sig = inspect.signature(C.RandomRanker.predict_distribution)
    assert set(sig.parameters) == {"self", "x"}
    rr = C.RandomRanker("T", 1).fit([[1.0], [2.0], [3.0], [4.0]], [0.1, -0.1, 0.2, -0.2])
    d1 = rr.predict_distribution([0.0]).canonical()
    d2 = rr.predict_distribution([0.0]).canonical()
    assert d1["expected_return"] != d2["expected_return"], "not random"
    assert rr.capabilities()["uses_features"] is False


# ============================================== frozen M0, one config
def test_M0_configuration_is_byte_identical_to_WM0D():
    cfg = M0SyntheticBaseline().model_identity()["configuration"]
    assert cfg == {"ridge_lambda": 1.0, "residual": "gaussian", "bias_penalised": False}
    assert content_hash(cfg) == "b6aec556e20cf6617cf7797cb0ef0d84" + content_hash(cfg)[32:]


def test_run_control_on_a_small_world_returns_a_named_verdict(monkeypatch):
    monkeypatch.setattr(CT, "N_STEPS", 400)
    d = small_defn()
    for ctl in ("N0", "N2", "N3", "N4", "P0"):
        cell = CT.run_control(d, ctl, 1000)
        assert cell["verdict"] in (CT.NO_SIGNAL, CT.SIGNAL_DETECTED, CT.RUN_INVALID)
        assert cell["control"] == ctl and cell["seed"] == 1000


def test_run_control_refuses_a_drifted_M0(monkeypatch):
    monkeypatch.setattr(CT, "N_STEPS", 400)
    d = small_defn(model_identity={"model_id": "M0", "model_version": "0.1.0",
                                   "configuration": {"ridge_lambda": 99.0}})
    cell = CT.run_control(d, "N0", 1000)
    assert cell["verdict"] == CT.RUN_INVALID and "drifted" in cell["error"]


# ========================================================= the budget
def test_budget_records_wm0d_truth_including_smoke_observations():
    b = wm0d_truth()
    c = b.counts()
    assert c["model_family"] == 2 and c["compatibility_observation"] == 2
    assert c["hyperparameter_configuration"] == 0
    assert c["horizon_variant"] == 1 and c["feature_family_variant"] == 1
    s = b.burden_statement()
    assert s["configurations_tried"] == 0
    assert s["compatibility_observations_not_credited"] == 2


def test_budget_is_immutable_and_hashes_every_attempt():
    b = ResearchBudget()
    b2 = b.register("model_family", "X")
    assert b.attempts == () and len(b2.attempts) == 1
    assert b.budget_hash != b2.budget_hash


def test_budget_refuses_hidden_duplicate_and_unknown_category():
    b = ResearchBudget().register("model_family", "X")
    with pytest.raises(BudgetViolation, match="duplicate"):
        b.register("model_family", "X")
    with pytest.raises(BudgetViolation, match="unknown"):
        b.register("vibes", "X")
    with pytest.raises(BudgetViolation, match="identity"):
        b.register("model_family", "")


def test_budget_categories_cover_the_directive():
    for k in ("model_family", "hyperparameter_configuration",
              "feature_family_variant", "horizon_variant", "target_variant",
              "sampling_variant", "calibration_variant", "ablation_variant"):
        assert k in CATEGORIES


# ===================================================== firewalls
def test_real_data_firewall_still_active_under_WM0E():
    from apex.world_model import admit
    from apex.world_model.sources import SourceAdmissionRefused
    with pytest.raises(SourceAdmissionRefused, match="REAL_EVIDENCE_PATH"):
        admit("/apex-data/core/btc/window_outcomes.jsonl", declared_class="SYNTHETIC_FIXTURE")


def test_court_modules_import_no_production_apex_and_no_broker():
    import ast, pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    placement = ("place_order", "place_equity_order", "place_option_order",
                 "submit_order", "execute_order", "send_order")
    for f in pkg.glob("*.py"):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            mod = None
            if isinstance(n, ast.ImportFrom): mod = n.module or ""
            elif isinstance(n, ast.Import): mod = n.names[0].name
            if mod and mod.startswith("apex"):
                assert mod.startswith("apex.world_model"), (f.name, mod)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert n.name not in placement, f.name


def test_no_economic_vocabulary_in_court_modules():
    import pathlib
    import apex.world_model as wm
    pkg = pathlib.Path(wm.__file__).parent
    for f in ("court.py", "controls.py", "budget.py"):
        src = (pkg / f).read_text().lower()
        for bad in ("sharpe", "pnl", "p&l", "win_rate", "kelly", "position_size", "alpha_"):
            assert bad not in src, (f, bad)
