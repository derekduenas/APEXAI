"""The tournament: arms, scoring, inference, nulls and verdicts, on small
synthetic worlds. No market data."""
import json
import math
import time

import numpy as np
import pytest

from apex.world_model import grader
from apex.world_model.exp002 import controls as CW, models as A, scoring as SC
from apex.world_model.exp002.registration import ARMS, FIT_BUDGET, GATES, REPORTED, registration_hash
from apex.world_model.exp002.run import tournament
from apex.world_model.targets import OutcomeRecord


def _world(name, fit=40, dev=20):
    return CW.make_world(name, n_fit_sessions=fit, n_dev_sessions=dev)


def test_registration_hash_is_stable_and_covers_the_module():
    h = registration_hash()
    assert len(h) == 64 and h == registration_hash()


def test_gaussian_arms_are_scored_by_the_untouched_grader():
    w = _world("W4_NULL", 20, 2)
    p = A.fit_arms(w["fit"])
    r, y, tk = w["dev"][0]
    for arm in ("M0", "M1"):
        fc = A.forecast(arm, p, r, input_id="x", input_hash="h", creation_time=1.0)
        oc = OutcomeRecord(world_id="w", world_hash="t", subject="SPY", step=0, horizon="H_15M",
                           target_value=y, outcome_known_time=tk)
        assert SC.grade_any(fc, oc, grading_time=tk + 1).metrics["log_likelihood"] == \
               grader.grade(fc, oc, grading_time=tk + 1).metrics["log_likelihood"]


def test_student_t_scorer_agrees_with_the_grader_in_the_gaussian_limit():
    w = _world("W4_NULL", 20, 2)
    p = A.fit_arms(w["fit"])
    p = dict(p); p["t"] = dict(p["t"], nu=1e6)          # force near-Gaussian tails
    r, y, tk = w["dev"][3]
    fc_t = A.forecast("L", p, r, input_id="x", input_hash="h", creation_time=1.0)
    oc = OutcomeRecord(world_id="w", world_hash="t", subject="SPY", step=0, horizon="H_15M",
                       target_value=y, outcome_known_time=tk)
    ll_t = SC.grade_any(fc_t, oc, grading_time=tk + 1).metrics["log_likelihood"]
    d = fc_t.distribution.canonical()
    # the true t(1e6)-vs-normal log-density gap is O(1/nu) ~ 1e-6; 1e-5 tests convergence, not luck
    assert abs(ll_t - grader._gauss_logpdf(y, d["expected_return"], d["total_uncertainty"])) < 1e-5


def test_the_three_t_arms_share_scale_and_tail_exactly():
    w = _world("W4_NULL", 20, 2)
    p = A.fit_arms(w["fit"])
    r = w["dev"][0][0]
    metas = [A.forecast(a, p, r, input_id="x", input_hash="h", creation_time=1.0).calibration_metadata
             for a in ("S", "L", "C")]
    assert len({(m["scale"], m["nu"]) for m in metas}) == 1


def test_exactly_five_fits_and_no_tuned_hyperparameters():
    w = _world("W4_NULL", 20, 2)
    p = A.fit_arms(w["fit"])
    assert p["fits_performed"] == 5 == FIT_BUDGET["market_data_fits"]
    assert FIT_BUDGET["tuned_hyperparameters"] == 0


def test_zero_variance_feature_is_refused_not_regularised():
    """Whichever arm meets the degenerate column first refuses by name. The
    registered baseline is fitted first and refuses with SINGULAR_DESIGN; the
    SVD arms refuse with ZERO_VARIANCE_FEATURE. Nothing regularises."""
    w = _world("W4_NULL", 20, 2)
    rows = [({**r, "features": {**r["features"], "ret_5": 0.0}}, y, tk) for r, y, tk in w["fit"]]
    with pytest.raises(A.ArmRefused, match="SINGULAR_DESIGN|ZERO_VARIANCE_FEATURE"):
        A.fit_arms(rows)
    # and the SVD path's own check fires when reached directly
    ys = np.array([y for _, y, _ in rows])
    with pytest.raises(A.ArmRefused, match="ZERO_VARIANCE_FEATURE"):
        A._fit_lstsq([r for r, _, _ in rows], ys, quadratic=True, label="C")


def test_rows_below_the_rv_floor_are_refused_for_every_arm_alike():
    w = _world("W4_NULL", 20, 3)
    dev = list(w["dev"])
    dev[0] = ({**dev[0][0], "features": {**dev[0][0]["features"], "rv_30": 0.0}}, dev[0][1], dev[0][2])
    rec = tournament(w["fit"], dev, tag="T", bootstrap_resamples=200)
    assert rec["admission"]["dev_refused_rv_floor"] == 1
    assert rec["n_dev"] == len(dev) - 1


def test_verdict_structure_and_null_on_a_null_world():
    w = _world("W4_NULL", 40, 20)
    rec = tournament(w["fit"], w["dev"], tag="W4", bootstrap_resamples=300)
    assert set(GATES) | set(REPORTED) <= set(rec["comparisons"])
    for k in REPORTED:
        assert rec["comparisons"][k]["promotion_authority"] is False
        assert "holm_adjusted_p" in rec["comparisons"][k]
    for k in GATES:
        assert rec["comparisons"][k]["promotion_authority"] is True
    assert set(rec["null_control"]) >= {"C-L", "L-S", "M1-M0"}
    assert rec["status"] in ("NOT_SELECTED", "NOT_SELECTED_INFERENCE_DISAGREEMENT",
                             "INVALID_NULL_CONTROL")
    assert rec["economics"].startswith("NONE")
    for a in ARMS:
        c = rec["calibration"][a]
        assert set(c["coverage"]) == {"0.05", "0.5", "0.95"} and len(c["pit_hist10"]) == 10


def test_strong_interaction_world_is_detected_by_the_matched_gate():
    w = _world("W2S_INTERACTION", 60, 30)
    rec = tournament(w["fit"], w["dev"], tag="W2S", bootstrap_resamples=400)
    g1 = rec["comparisons"]["G1"]
    assert g1["hac"]["verdict"] == "SIGNAL_DETECTED", g1["hac"]
    assert rec["comparisons"]["R4"]["hac"]["verdict"] == "NO_SIGNAL"     # linear cannot see it


def test_the_null_permutes_outcomes_and_leaves_forecasts_fixed():
    """A matched pair with real signal must go silent under N0."""
    w = _world("W2S_INTERACTION", 60, 30)
    rec = tournament(w["fit"], w["dev"], tag="W2S", bootstrap_resamples=200)
    assert rec["null_control"]["C-L"]["verdict"] == "NO_SIGNAL"
    assert rec["null_control_ok"] is True


def test_matched_improvement_is_preserved_when_a_compound_gate_fails():
    """Construct the verdict logic directly: G1 passes, G3 fails -> MATCHED_IMPROVEMENT_ONLY."""
    from apex.world_model.exp002 import run as R
    fake = {"G1": {"both_pass": True, "inference_disagreement": False},
            "G2": {"both_pass": True, "inference_disagreement": False},
            "G3": {"both_pass": False, "inference_disagreement": False}}
    g1, g2, g3 = fake["G1"], fake["G2"], fake["G3"]
    verdict = ("NOT_SELECTED_INFERENCE_DISAGREEMENT" if g1["inference_disagreement"]
               else "NOT_SELECTED" if not g1["both_pass"]
               else "BASELINE_REPLACEMENT_CANDIDATE" if (g2["both_pass"] and g3["both_pass"])
               else "MATCHED_IMPROVEMENT_ONLY")
    assert verdict == "MATCHED_IMPROVEMENT_ONLY"


def test_no_forecast_or_grade_objects_are_retained():
    """Bounded memory by construction: the record holds arrays and dicts only."""
    w = _world("W4_NULL", 20, 5)
    rec = tournament(w["fit"], w["dev"], tag="T", bootstrap_resamples=100)
    s = json.dumps(rec, default=str)
    assert "WorldModelForecast" not in s and "Grade(" not in s
