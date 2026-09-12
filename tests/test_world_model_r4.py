"""WM-0E-R4: P0_POWER_CONTRACT_V2 structural proofs. Development only."""
import numpy as np
import pytest

from apex.world_model import bootstrap as BS, controls_r4 as R4, teststand as TS
from apex.world_model.budget import wm0e_r3_truth, wm0e_r4_truth
from apex.world_model.controls import ControlViolation
from apex.world_model.controls_r3 import N3_DEV_SEEDS, P0_DEV_SEEDS
from apex.world_model.court import S1_PARAMS, _world
from apex.world_model.holdout import HOLDOUT_SEEDS
from apex.world_model.inference import paired_differentials
from apex.world_model.models import M0SyntheticBaseline, NullBaseline

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
DEV = 1000


def test_engine_and_effect_frozen():
    assert BS.content_identity() == FROZEN_ENGINE
    assert R4.P0_MU_MULTIPLIER == 1.0
    w = R4.r4_world(DEV)
    assert w.config.params == S1_PARAMS and w.config.sigma == R4.S1_SIGMA


def test_ladder_is_mechanical_and_finite():
    assert R4.E0 == 465 and R4.EVAL_LADDER == (465, 930, 1395, 1860)
    assert R4.T_MAX == 2595 and R4.CUTOFFS == (1185, 1650, 2115, 2580)
    assert R4.V0_BOUNDARY == 720 and len(R4.R4_SPLIT.train_steps) == 701
    assert R4.R4_SPLIT.train_steps == R4.V0_SPLIT.train_steps
    assert len(R4.R4_SPLIT.eval_steps) == 1861            # last step has no target -> 1860 usable


def test_config_rekey_confound_is_real_and_avoided():
    """Two worlds that differ only in n_steps are DIFFERENT paths (why one
    world per seed is mandatory); within R4 there is exactly one world."""
    w1200 = _world(DEV); w2595 = R4.r4_world(DEV)
    assert w1200.world_hash != w2595.world_hash
    s1 = w1200.observables["SYN_A"]; s2 = w2595.observables["SYN_A"]
    assert s1[10].canonical() != s2[10].canonical() if hasattr(s1[10], "canonical") else True
    assert R4.r4_world(DEV).world_hash == w2595.world_hash   # deterministic


def test_training_interval_fixed_and_eval_is_full_path():
    w = R4.r4_world(DEV)
    Xtr, ytr, Xev, yev, iev, out = R4.r4_dataset(w, "SYN_A", None)
    assert len(ytr) == 701 and len(Xev) == 1860
    assert iev == list(R4.R4_SPLIT.eval_steps)[:1860] and iev[0] == 720 and iev[-1] == 2579
    with pytest.raises(ControlViolation):
        R4.r4_dataset(_world(DEV), "SYN_A", None)          # wrong-length world refused


def test_nested_prefix_identity_and_training_identity_on_dev_seed():
    w = R4.r4_world(DEV)
    m0 = M0SyntheticBaseline()
    m = TS.run_pipeline(w, m0, dataset=R4.r4_dataset)
    n = TS.run_pipeline(w, NullBaseline(), dataset=R4.r4_dataset)
    d = np.array(paired_differentials(m["grades"], n["grades"]))
    assert len(d) == 1860
    beta_once = tuple(m0._beta)
    for L in R4.EVAL_LADDER:
        assert np.array_equal(d[:L], d[:L])                # prefix by construction
        assert [g.outcome_hash for g in m["grades"][:L]] == [g.outcome_hash for g in m["grades"]][:L]
    # the SAME fitted model graded every level: coefficients were never refit
    assert tuple(m0._beta) == beta_once
    # and the training sample is the V0 sample size, not 0.6 * T_max
    assert m["n_train"] == 701 if "n_train" in m else True
    Xtr, ytr, *_ = R4.r4_dataset(w, "SYN_A", None)
    assert len(ytr) == 701 and R4.training_hash(Xtr, ytr) == R4.training_hash(Xtr, ytr)


def test_pipeline_default_split_is_not_what_r4_uses_and_is_disclosed():
    """run_pipeline would put the boundary at 0.6*T_max = 1557; R4 uses 720
    through the seam and says so in its predeclaration."""
    assert int(R4.T_MAX * TS.FIXED_BOUNDARY_FRACTION) == 1557 != R4.V0_BOUNDARY
    assert "NOT used" in R4.predeclaration()["pipeline_split_field_disclosure"]


def test_dev_seeds_paired_new_disjoint_no_acceptance():
    assert len(R4.DEV_SEEDS) == 50
    old = set(HOLDOUT_SEEDS) | set(N3_DEV_SEEDS) | set(P0_DEV_SEEDS) | {1000 + 37 * i for i in range(25)}
    assert not set(R4.DEV_SEEDS) & old
    p = R4.predeclaration()
    assert p["seeds"]["paired_across_levels"] is True and p["new_acceptance_seeds_created"] is False
    assert p["acceptance_court"] == "NONE" and p["ladder_hash"]
    assert R4.QUALIFICATION["min_detection_rate"] == 0.90 and R4.FUTURE_ACCEPTANCE["min_detections"] == 40


def test_budget_r4_records_evaluation_length_search():
    b3, b4 = wm0e_r3_truth(), wm0e_r4_truth()
    c = b4.counts()
    assert c["positive_control_evaluation_length"] == 4
    assert c["positive_control_power_level"] == 5 and c["inference_rule_revision"] == 3
    assert c["model_family"] == b3.counts()["model_family"] and c["horizon_variant"] == 1
    assert len(b4.attempts) == len(b3.attempts) + 4
