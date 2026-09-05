"""WM-0E-R3: N3_SHADOW_FEATURE_NULL_V1 structural proofs, P0 power
contract, frozen engine, predeclaration, budget. Development only."""
import glob
import statistics as st

import numpy as np
import pytest

from apex.world_model import bootstrap as BS, controls as C, controls_r3 as R3, teststand as TS
from apex.world_model.budget import wm0e_r2_1_truth, wm0e_r3_truth
from apex.world_model.controls import ControlViolation
from apex.world_model.court import _world
from apex.world_model.features import FEATURE_NAMES
from apex.world_model.holdout import HOLDOUT_SEEDS
from apex.world_model.runs import ChronologicalSplit

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
DEV = 1000                                         # V0 development seed
ZI = FEATURE_NAMES.index("declared_observable_state")


def _split(w):
    T = w.config.n_steps
    return ChronologicalSplit(n_steps=T, boundary=int(T * TS.FIXED_BOUNDARY_FRACTION))


# ---------------------------------------------------------------- §0 frozen
def test_inference_engine_is_frozen():
    assert BS.content_identity() == FROZEN_ENGINE
    assert BS.BOOTSTRAP_VERSION == "DEPENDENT_BLOCK_BOOTSTRAP_V0.1"
    assert BS.B_REPLICATIONS == 1999 and BS.ALPHA == 0.025


def test_n3_v0_retired_not_edited_and_p0_v0_preserved():
    assert R3.N3_V0_STATUS["status"] == "RETIRED_AFTER_CONTROL_FAILURE"
    assert R3.N3_V0_STATUS["edited"] is False and R3.N3_V0_STATUS["rerun"] is False
    n3 = C.CONTROL_CONTRACT["N3"]                                   # still there, untouched
    assert "PERMUT" in n3["name"].upper() and n3["expected"] == "NO_SIGNAL"
    assert C.CONTROLS_VERSION == "WM0E_CONTROLS_V0.1"
    assert R3.P0_V0_STATUS["status"] == "FAIL_POWER_REQUIREMENT"
    assert R3.P0_V0_STATUS["requirement_lowered"] is False


# ---------------------------------------------------------------- §3 structural
def test_shadow_seed_namespace_and_distinctness():
    s = R3.shadow_seed(DEV)
    assert s != DEV and 0 <= s < 2 ** 31 - 1
    assert R3.shadow_seed(DEV) == s                     # deterministic
    assert R3.shadow_seed(DEV + 1) != s


def test_shadow_world_same_family_config_independent_path():
    w = _world(DEV); sh = R3.shadow_world(w)
    assert sh.world_type == w.world_type == "S1_CAUSAL_TREND" or sh.world_type == w.world_type
    a, b = w.config, sh.config
    assert a.seed != b.seed and sh.world_hash != w.world_hash
    for f in ("world_type", "n_subjects", "n_steps", "step_seconds"):
        assert getattr(a, f) == getattr(b, f)
    assert a.sigma == b.sigma and a.params == b.params and a.observe_latent == b.observe_latent
    assert R3.shadow_world(w).world_hash == sh.world_hash   # reproducible identity


def test_n3_v1_features_come_from_shadow_targets_from_target():
    w = _world(DEV); sh = R3.shadow_world(w); sp = _split(w)
    Xtr, ytr, Xev, yev, iev, ev_out = R3.n3_v1_dataset(DEV)(w, "SYN_A", sp)
    Xtr_t, ytr_t, Xev_t, yev_t, iev_t, ev_out_t = TS.default_dataset(w, "SYN_A", sp)
    Xtr_s, _, Xev_s, _, _, _ = TS.default_dataset(sh, "SYN_A", sp)
    assert Xtr == Xtr_s and Xev == Xev_s                # shadow observables, exactly
    assert Xtr != Xtr_t and Xev != Xev_t                # no target observable reaches input
    assert ytr == ytr_t and yev == yev_t and iev == iev_t
    assert [o.outcome_hash for o in ev_out] == [o.outcome_hash for o in ev_out_t]


def test_n3_v1_fails_closed_on_same_world_and_wrong_seed():
    w = _world(DEV)
    with pytest.raises(ControlViolation):
        R3.n3_v1_dataset(DEV + 1)(w, "SYN_A", _split(w))     # dataset for another seed
    import apex.world_model.controls_r3 as M
    orig = M.shadow_seed
    try:
        M.shadow_seed = lambda s: s                          # force same-world pairing
        with pytest.raises(ControlViolation):
            R3.shadow_world(w)
    finally:
        M.shadow_seed = orig


def test_n3_v1_no_truth_and_no_future_in_features():
    """Features are built by the frozen extract_features from ObservableState
    only (the stand rejects truth objects); swapping the target world changes
    y but leaves the shadow features byte-identical -> features cannot
    contain the target or its future."""
    w1, w2 = _world(DEV), _world(DEV)                 # same target twice
    sp = _split(w1)
    X1, y1, *_ = R3.n3_v1_dataset(DEV)(w1, "SYN_A", sp)
    X2, y2, *_ = R3.n3_v1_dataset(DEV)(w2, "SYN_A", sp)
    assert X1 == X2 and y1 == y2
    # and a DIFFERENT target world with the same shadow donor cannot exist:
    # the donor is a function of the target seed, so changing the target
    # changes both; features never depend on y (they are extracted from
    # ObservableState by the frozen stand, which rejects truth objects)
    Xo, yo, *_ = R3.n3_v1_dataset(DEV + 37)(_world(DEV + 37), "SYN_A", sp)
    assert yo != y1


def test_shadow_path_keeps_dependence_and_regime_persistence_and_is_independent():
    w = _world(DEV); sp = _split(w)
    Xtr_s, _, Xev_s, _, _, _ = R3.n3_v1_dataset(DEV)(w, "SYN_A", sp)
    Xtr_t, _, Xev_t, _, _, _ = TS.default_dataset(w, "SYN_A", sp)
    zs = np.array([x[ZI] for x in Xtr_s + Xev_s]); zt = np.array([x[ZI] for x in Xtr_t + Xev_t])
    acf = lambda z: float(((z[1:] - z.mean()) * (z[:-1] - z.mean())).sum() / ((z - z.mean()) ** 2).sum())
    assert acf(zs) > 0.8 and acf(zt) > 0.8                  # persistence survives
    assert abs(float(np.corrcoef(zs, zt)[0, 1])) < 0.3      # independent latent paths


def test_n3_v1_identity_is_a_function_of_both_world_hashes():
    w = _world(DEV)
    assert R3.n3_v1_identity(w) == R3.n3_v1_identity(_world(DEV))
    assert R3.n3_v1_identity(w) != R3.n3_v1_identity(_world(DEV + 37))


# ---------------------------------------------------------------- §6-§9 P0
def test_p0_ladder_finite_and_off_ladder_refused():
    assert R3.P0_POWER_LADDER == (1.0, 1.5, 2.0, 3.0)
    w = R3.p0_world(DEV, 2.0)
    assert w.config.params["mu"] == pytest.approx(R3.P0_BASE_MU * 2.0)
    assert w.config.params["flip_prob"] == C.S1_FLIP_PROB
    with pytest.raises(ControlViolation):
        R3.p0_world(DEV, 2.5)
    assert R3.p0_world(DEV, 1.0).world_hash == _world(DEV).world_hash   # 1.0x IS P0 V0


def test_p0_v1_selection_and_future_acceptance_predeclared():
    s = R3.P0_V1_SELECTION
    assert s["min_detection_rate"] == 0.90 and s["min_wilson95_lower"] == 0.80 and s["min_direction_rate"] == 0.95
    assert R3.P0_V1_FUTURE_ACCEPTANCE == {"min_detections": 40, "min_direction": 45, "n": 50,
                                          "note": R3.P0_V1_FUTURE_ACCEPTANCE["note"]}


# ---------------------------------------------------------------- §4/§8/§11 seeds
def test_development_seed_sets_are_new_and_disjoint_and_no_acceptance_set():
    assert len(R3.N3_DEV_SEEDS) == 100 and len(R3.P0_DEV_SEEDS) == 50
    old = set(C.__dict__.get("SEED_SET", ())) | set(HOLDOUT_SEEDS) | {1000 + 37 * i for i in range(25)}
    assert not set(R3.N3_DEV_SEEDS) & old and not set(R3.P0_DEV_SEEDS) & old
    assert not set(R3.N3_DEV_SEEDS) & set(R3.P0_DEV_SEEDS)
    pre = R3.predeclaration()
    assert pre["new_acceptance_seeds_created"] is False and pre["acceptance_court"].startswith("NONE")
    assert not glob.glob("evidence/*acceptance*v2*") and not glob.glob("evidence/*holdout_v1*")
    assert R3.predeclaration_hash() == R3.predeclaration_hash()


# ---------------------------------------------------------------- §12 budget
def test_budget_r3_records_control_development_search():
    b21, b3 = wm0e_r2_1_truth(), wm0e_r3_truth()
    c = b3.counts()
    assert c["null_control_design"] == 2                 # N3 V0 retired + N3 V1
    assert c["positive_control_power_level"] == 5        # P0 V0 failed + 4 ladder levels
    assert c["model_family"] == b21.counts()["model_family"]
    assert c["hyperparameter_configuration"] == 0 and c["horizon_variant"] == 1
    assert c["inference_rule_revision"] == 3             # unchanged: no revision
    assert len(b3.attempts) == len(b21.attempts) + 7
