"""WM-0E-R5.1 -- N0_SHADOW_TARGET_NULL_V1 + N1_TIME_DESTRUCTION_E1860_V1.
DEVELOPMENT ONLY. Engine, M0, geometry (boundary 720, n_train 701 for the
un-displaced controls, H_15M, E=1860) and the executed-split contract are
frozen. N0 V0 is FAILED_E1860 and untouched. N2/N3-V1/N4/P0 not rerun.

N0_SHADOW_TARGET_NULL_V1
  FEATURE WORLD A = the development-seed world (all observable features).
  TARGET WORLD B  = an independently generated world of the SAME declared
                    family/config class, seed = sha256(WM0E_R51_N0_TARGET_V1
                    | feature_seed); supplies EVERY training and evaluation
                    target/outcome. Training and evaluation are X_A -> y_B.
  No permutation, no block derangement, no row shuffle: both processes keep
  their own temporal dependence, regime persistence and marginal evolution;
  there is no feature->target linkage because the worlds share nothing
  (no latent state, no regime, no factor, no ground truth). Fail-closed on
  same-world pairing. Identity commits BOTH world hashes.
  STATED PLAINLY: this is the role-reversed twin of N3_SHADOW_FEATURE_NULL_V1
  (there: shadow features, target targets; here: target features, shadow
  targets), under an independent namespace. They are the same two-world
  construction and are not two independent nulls.

N1_TIME_DESTRUCTION_E1860_V1
  The FROZEN n1_dataset (X_t paired with y_{t+200}; purge recomputed) is
  executed on a longer upstream path so that AFTER the unchanged 200-step
  displacement exactly 1860 usable evaluation pairs remain:
    T_N1 = boundary + E + shift + H = 720 + 1860 + 200 + 15 = 2795
  Boundary stays 720. The construction, shift and semantics are untouched;
  only the path length changes. Its training set is 501 pairs by the same
  frozen purge (t + 200 + 15 <= 720) -- declared, not drift.
  WM-N1-GEOMETRY-001: the R5 result (5/100 at 1660) is retained as valid
  development evidence and does NOT close N1_E1860; this does.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace as _replace

from apex.world_model import controls as C
from apex.world_model.canonical import content_hash
from apex.world_model.controls import ControlViolation
from apex.world_model.controls_r3 import N3_DEV_SEEDS, P0_DEV_SEEDS
from apex.world_model.controls_r4 import DEV_SEEDS as R4_SEEDS, R4_SPLIT, T_MAX, V0_BOUNDARY, r4_world
from apex.world_model.controls_r5 import R5_DEV_SEEDS
from apex.world_model.court import SEED_SET as _V0_SEEDS
from apex.world_model.holdout import HOLDOUT_SEEDS as _CONSUMED, derive_holdout
from apex.world_model.runs import ChronologicalSplit
from apex.world_model.targets import TARGET_HORIZON_STEPS as H
from apex.world_model.teststand import build_dataset
from apex.world_model.worlds import generate_world

R51_VERSION = "WM0E_R51_N0V1_N1E1860_V1"
E = 1860
MAX_FP = 5
COURT_ID = "R51_E1860"
SEED_MODULUS = 2 ** 31 - 1

N0_V0_STATUS = {"control": "N0_BLOCK_NULL_V0", "status": "FAILED_E1860", "observed": "6/100 (max 5)",
                "mechanism_classification": "SUSPECTED_NULL_DESIGN_GAP",
                "note": "window-preserving label derangement may leave marginal/regime "
                        "interactions capable of generating finite-sample signed offsets; "
                        "the failure is proven, the mechanism is diagnostic interpretation",
                "edited": False, "rerun": False}

# ---------------------------------------------------------------- N0 V1
N0_V1 = "N0_SHADOW_TARGET_NULL_V1"
N0_TARGET_NAMESPACE = "WM0E_R51_N0_TARGET_V1"


def target_seed(feature_seed: int) -> int:
    h = hashlib.sha256(("%s|%d" % (N0_TARGET_NAMESPACE, feature_seed)).encode()).digest()
    s = int.from_bytes(h[:8], "big") % SEED_MODULUS
    if s == feature_seed:
        raise ControlViolation("target seed collided with feature seed %d" % feature_seed)
    return s


def target_world(feature_world):
    """World B: same family/config class as A, independent seed -> independent
    latent path, regimes, factor and ground truth. Fails closed on identity."""
    cfg = feature_world.config
    b = generate_world(_replace(cfg, seed=target_seed(cfg.seed)))
    if b.world_hash == feature_world.world_hash or b.config.seed == cfg.seed:
        raise ControlViolation("target world is the feature world")
    if b.world_type != feature_world.world_type or b.config.n_steps != cfg.n_steps:
        raise ControlViolation("target world family/geometry differs from feature world")
    return b


def n0_v1_dataset(feature_seed: int):
    """X from A (the world run_pipeline receives), y/outcomes from B, same
    split and subject, whole run. Nothing is permuted."""
    def build(world_a, subject, split):
        if world_a.config.seed != feature_seed:
            raise ControlViolation("N0 V1 dataset for feature seed %d, got %d"
                                   % (feature_seed, world_a.config.seed))
        b = target_world(world_a)
        Xtr, _, itr_a, _ = build_dataset(world_a, subject, split.train_steps)
        Xev, _, iev_a, _ = build_dataset(world_a, subject, split.eval_steps)
        _, ytr, itr_b, _ = build_dataset(b, subject, split.train_steps)
        _, yev, iev_b, ev_out = build_dataset(b, subject, split.eval_steps)
        if itr_a != itr_b or iev_a != iev_b:
            raise ControlViolation("feature and target step indices diverge")
        return Xtr, ytr, Xev, yev, iev_b, ev_out
    return build


def n0_v1_identity(feature_world) -> str:
    b = target_world(feature_world)
    return content_hash({"control": N0_V1, "namespace": N0_TARGET_NAMESPACE,
                         "feature_world_hash": feature_world.world_hash,
                         "target_world_hash": b.world_hash})


N0_V1_CONTRACT = {"name": N0_V1, "replaces": "N0_BLOCK_NULL_V0 (FAILED_E1860; not edited)",
                  "construction": "X_A -> y_B for training AND evaluation; A = feature world "
                                  "(dev seed), B = independent same-family world (namespace-derived)",
                  "destroys": "any feature->target linkage (worlds share nothing)",
                  "preserves": "feature temporal dependence/regime persistence/marginal evolution; "
                               "target temporal dependence/regime persistence/marginal evolution",
                  "no_permutation": True, "twin_of": "N3_SHADOW_FEATURE_NULL_V1 (roles reversed)",
                  "expected": "NO_SIGNAL"}

# ---------------------------------------------------------------- N1 E1860
N1_E1860 = "N1_TIME_DESTRUCTION_E1860_V1"
N1_SHIFT = C.N1_SHIFT_STEPS                                  # 200, unchanged
T_N1 = V0_BOUNDARY + E + N1_SHIFT + H                        # 2795
N1_SPLIT = ChronologicalSplit(n_steps=T_N1, boundary=V0_BOUNDARY)
N1_EXPECTED_TRAIN = len(range(5, V0_BOUNDARY - H - N1_SHIFT + 1))   # 501, frozen purge


def n1_world(seed: int):
    """Same original S1 parameters; only n_steps grows so the frozen
    displacement leaves E usable evaluation pairs."""
    base = r4_world(seed).config
    return generate_world(_replace(base, n_steps=T_N1))


def n1_e1860_dataset(seed: int):
    inner = C.n1_dataset(COURT_ID, seed)                      # the FROZEN transformation
    def build(world, subject, split):
        if world.config.n_steps != T_N1 or split.n_steps != T_N1 or split.boundary != V0_BOUNDARY:
            raise ControlViolation("N1 E1860 requires T=%d, boundary %d" % (T_N1, V0_BOUNDARY))
        Xtr, ytr, Xev, yev, iev, ev_out = inner(world, subject, split)
        if len(Xev) != E:
            raise ControlViolation("N1 E1860 usable evaluation %d != %d" % (len(Xev), E))
        return Xtr, ytr, Xev, yev, iev, ev_out
    return build


N1_E1860_CONTRACT = {"name": N1_E1860, "transformation": "controls.n1_dataset UNCHANGED "
                     "(FORWARD_TIME_DISPLACEMENT, shift %d, purge recomputed)" % N1_SHIFT,
                     "transformation_sha256": None,           # filled by predeclaration()
                     "displacement": N1_SHIFT, "T": T_N1, "boundary": V0_BOUNDARY,
                     "source_evaluation_steps": len(N1_SPLIT.eval_steps),
                     "final_usable_evaluation": E, "train_pairs": N1_EXPECTED_TRAIN,
                     "run_invalid_if_usable_differs": True, "expected": "NO_SIGNAL"}

# ---------------------------------------------------------------- dev seeds
DEV_NAMESPACE = "WM0E_R51_DEV_V0"
_EXCLUDED = (tuple(_V0_SEEDS) + tuple(_CONSUMED) + tuple(N3_DEV_SEEDS) + tuple(P0_DEV_SEEDS)
             + tuple(R4_SEEDS) + tuple(R5_DEV_SEEDS))
DEV = derive_holdout(DEV_NAMESPACE, 100, _EXCLUDED)
DEV_SEEDS = tuple(DEV["seeds"])
assert len(DEV_SEEDS) == 100 and not set(DEV_SEEDS) & set(_EXCLUDED)
N0_V1_TARGET_SEEDS = tuple(target_seed(s) for s in DEV_SEEDS)
assert not set(N0_V1_TARGET_SEEDS) & set(DEV_SEEDS) and len(set(N0_V1_TARGET_SEEDS)) == 100


def predeclaration() -> dict:
    import inspect
    n1c = dict(N1_E1860_CONTRACT)
    n1c["transformation_sha256"] = hashlib.sha256(inspect.getsource(C.n1_dataset).encode()).hexdigest()
    return {"version": R51_VERSION, "N0_V0": N0_V0_STATUS, "N0_V1": N0_V1_CONTRACT,
            "N0_V1_geometry": {"T": T_MAX, "boundary": V0_BOUNDARY, "n_train": 701, "usable_eval": E,
                               "split": R4_SPLIT.canonical()},
            "N0_V1_pairing": {"feature_seeds": "DEV_SEEDS (namespace %s)" % DEV_NAMESPACE,
                              "target_seeds": "sha256(%s|feature_seed)[:8] mod 2^31-1" % N0_TARGET_NAMESPACE,
                              "feature_seed_hash": DEV["seed_set_hash"],
                              "target_seed_hash": content_hash(list(N0_V1_TARGET_SEEDS))},
            "WM_N1_GEOMETRY_001": {"R5_result": "5/100 at 1660 usable (retained; does not close N1_E1860)",
                                   "closure": N1_E1860},
            "N1_E1860": n1c, "N1_split": N1_SPLIT.canonical(),
            "seeds": {"namespace": DEV_NAMESPACE, "n": 100, "hash": DEV["seed_set_hash"],
                      "skipped": DEV["skipped"], "shared_by_N0V1_and_N1": True,
                      "excluded": "V0 dev 25, consumed V2.1 50, R3 N3 100, R3 P0 50, R4 50, R5 100"},
            "requirement": "each control <= %d/100 false detections at alpha 0.025" % MAX_FP,
            "carried_forward_not_rerun": ["N2_E1860 PASS", "N3_SHADOW_V1_E1860 PASS", "N4_E1860 PASS",
                                          "P0_POWERED_V2_E1860 PASS"],
            "new_acceptance_seeds_created": False, "acceptance_court": "NONE"}


def predeclaration_hash() -> str:
    return content_hash(predeclaration())
