"""WM-0E-R5.1: N0_SHADOW_TARGET_NULL_V1 structural proofs; N1 exact-E1860
geometry; seeds; frozen engine; budget."""
import numpy as np
import pytest

from apex.world_model import bootstrap as BS, controls as C, controls_r4 as R4, controls_r51 as R, teststand as TS
from apex.world_model.budget import wm0e_r5_truth, wm0e_r51_truth
from apex.world_model.controls import ControlViolation
from apex.world_model.controls_r3 import N3_DEV_SEEDS, P0_DEV_SEEDS
from apex.world_model.controls_r5 import R5_DEV_SEEDS
from apex.world_model.features import FEATURE_NAMES
from apex.world_model.holdout import HOLDOUT_SEEDS
from apex.world_model.models import NullBaseline

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
DEV = 1000
ZI = FEATURE_NAMES.index("declared_observable_state")


def test_engine_frozen_n0v0_preserved():
    assert BS.content_identity() == FROZEN_ENGINE
    assert R.N0_V0_STATUS["status"] == "FAILED_E1860" and R.N0_V0_STATUS["edited"] is False
    assert R.N0_V0_STATUS["mechanism_classification"] == "SUSPECTED_NULL_DESIGN_GAP"
    assert C.CONTROL_CONTRACT["N0"]["name"] == "BLOCK_DERANGED_TARGETS"      # untouched


# ---------------------------------------------------------------- N0 V1 (§2-§4)
def test_target_world_independent_same_family_fail_closed():
    a = R4.r4_world(DEV); b = R.target_world(a)
    assert b.config.seed == R.target_seed(DEV) != DEV and b.world_hash != a.world_hash
    for f in ("world_type", "n_subjects", "n_steps", "step_seconds"):
        assert getattr(a.config, f) == getattr(b.config, f)
    assert a.config.params == b.config.params and a.config.sigma == b.config.sigma
    import apex.world_model.controls_r51 as M
    orig = M.target_seed
    try:
        M.target_seed = lambda s: s
        with pytest.raises(ControlViolation):
            R.target_world(a)
    finally:
        M.target_seed = orig


def test_n0_v1_features_from_A_targets_from_B_no_permutation():
    a = R4.r4_world(DEV); b = R.target_world(a)
    Xtr, ytr, Xev, yev, iev, out = R.n0_v1_dataset(DEV)(a, "SYN_A", R4.R4_SPLIT)
    Xtr_a, ytr_a, Xev_a, yev_a, iev_a, _ = TS.default_dataset(a, "SYN_A", R4.R4_SPLIT)
    Xtr_b, ytr_b, Xev_b, yev_b, iev_b, out_b = TS.default_dataset(b, "SYN_A", R4.R4_SPLIT)
    assert Xtr == Xtr_a and Xev == Xev_a                     # features: A, in order
    assert ytr == ytr_b and yev == yev_b and iev == iev_b    # targets: B, in order (no derangement)
    assert ytr != ytr_a and yev != yev_a                     # A's targets never reach the model
    assert [o.outcome_hash for o in out] == [o.outcome_hash for o in out_b]
    assert len(ytr) == 701 and len(yev) == 1860
    with pytest.raises(ControlViolation):
        R.n0_v1_dataset(DEV + 1)(a, "SYN_A", R4.R4_SPLIT)


def test_n0_v1_runs_through_pipeline_with_executed_split_and_identity():
    a = R4.r4_world(DEV)
    m = TS.run_pipeline(a, NullBaseline(), dataset=R.n0_v1_dataset(DEV), split=R4.R4_SPLIT)
    assert m["n_eval"] == 1860 and m["n_train"] == 701 and m["executed_split"]["boundary"] == 720
    i1 = R.n0_v1_identity(a); assert i1 == R.n0_v1_identity(R4.r4_world(DEV)) and i1 != R.n0_v1_identity(R4.r4_world(DEV + 37))


def test_n0_v1_both_processes_structured_and_independent():
    a = R4.r4_world(DEV); b = R.target_world(a)
    Xa, _, Xea, _, *_ = TS.default_dataset(a, "SYN_A", R4.R4_SPLIT)
    Xb, yb, Xeb, yeb, *_ = TS.default_dataset(b, "SYN_A", R4.R4_SPLIT)
    za = np.array([x[ZI] for x in Xa + Xea]); zb = np.array([x[ZI] for x in Xb + Xeb])
    acf = lambda z: float(((z[1:] - z.mean()) * (z[:-1] - z.mean())).sum() / ((z - z.mean()) ** 2).sum())
    assert acf(za) > 0.8 and acf(zb) > 0.8
    y = np.array(yb + yeb); assert acf(y) > 0.5                 # 15-step overlap: targets keep dependence
    assert abs(float(np.corrcoef(za, zb)[0, 1])) < 0.3


# ---------------------------------------------------------------- N1 E1860 (§9-§12)
def test_n1_transformation_unchanged_and_geometry_exact():
    assert R.N1_SHIFT == 200 and C.N1_SHIFT_STEPS == 200
    assert R.T_N1 == 2795 and R.N1_SPLIT.boundary == 720 and R.N1_EXPECTED_TRAIN == 501
    w = R.n1_world(DEV)
    assert w.config.n_steps == 2795 and w.config.params == R4.r4_world(DEV).config.params
    m = TS.run_pipeline(w, NullBaseline(), dataset=R.n1_e1860_dataset(DEV), split=R.N1_SPLIT)
    assert m["n_eval"] == 1860 and m["n_train"] == 501
    assert m["executed_split"]["usable_evaluation_count"] == 1860 and m["executed_split"]["boundary"] == 720
    with pytest.raises(ControlViolation):                          # wrong-length world refused
        R.n1_e1860_dataset(DEV)(R4.r4_world(DEV), "SYN_A", R4.R4_SPLIT)


def test_n1_e1860_is_the_frozen_construction():
    import hashlib, inspect
    p = R.predeclaration()
    assert p["N1_E1860"]["transformation_sha256"] == hashlib.sha256(inspect.getsource(C.n1_dataset).encode()).hexdigest()
    assert p["N1_E1860"]["displacement"] == 200 and p["N1_E1860"]["final_usable_evaluation"] == 1860


# ---------------------------------------------------------------- seeds / budget
def test_dev_seeds_fresh_disjoint_paired_target_seeds():
    assert len(R.DEV_SEEDS) == 100 and len(set(R.N0_V1_TARGET_SEEDS)) == 100
    old = set(HOLDOUT_SEEDS) | set(N3_DEV_SEEDS) | set(P0_DEV_SEEDS) | set(R4.DEV_SEEDS) | set(R5_DEV_SEEDS) | {1000 + 37 * i for i in range(25)}
    assert not set(R.DEV_SEEDS) & old and not set(R.N0_V1_TARGET_SEEDS) & set(R.DEV_SEEDS)
    p = R.predeclaration()
    assert p["new_acceptance_seeds_created"] is False and p["acceptance_court"] == "NONE"
    assert R.predeclaration_hash() == R.predeclaration_hash()


def test_budget_r51():
    b5, b51 = wm0e_r5_truth(), wm0e_r51_truth()
    c = b51.counts()
    assert c["null_control_design"] == 3 and c["null_control_validation"] == 7
    assert c["inference_rule_revision"] == 3 and c["model_family"] == b5.counts()["model_family"]
    assert len(b51.attempts) == len(b5.attempts) + 3
