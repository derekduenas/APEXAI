"""WM-0E-R5 -- full negative-control DEVELOPMENT validation at E=1860.

Every negative control runs under the exact geometry selected for
P0_CAUSAL_TREND_POWERED_V2: one T_MAX=2595 world per target seed, training
boundary 720 (n_train 701), H_15M, 1860 usable evaluation observations,
frozen court (DEPENDENT_BLOCK_BOOTSTRAP_V0.1). The controls themselves are
the frozen constructions: N0/N1/N2 from controls.py V0.1, N3 =
N3_SHADOW_FEATURE_NULL_V1 from controls_r3, N4 = RandomRanker. Nothing is
redesigned. N3 V0 stays retired. P0 is NOT rerun.

The split is passed EXPLICITLY to run_pipeline (WM-META-001) so the run
artifact binds to the executed split; no seam trickery.
"""
from __future__ import annotations

from apex.world_model import controls as C
from apex.world_model.canonical import content_hash
from apex.world_model.controls import ControlViolation
from apex.world_model.controls_r3 import N3_DEV_SEEDS, N3_V1, P0_DEV_SEEDS, n3_v1_dataset
from apex.world_model.controls_r4 import DEV_SEEDS as R4_SEEDS, EVAL_LADDER, R4_SPLIT, T_MAX, V0_BOUNDARY, r4_world
from apex.world_model.court import SEED_SET as _V0_SEEDS
from apex.world_model.holdout import HOLDOUT_SEEDS as _CONSUMED, derive_holdout
from apex.world_model.teststand import default_dataset

R5_VERSION = "WM0E_R5_NEGATIVE_CONTROLS_E1860_V1"
E_SELECTED = max(EVAL_LADDER)                   # 1860
R5_MAX_FP = 5                                    # per control, per 100
R5_CONTROLS = ("N0", "N1", "N2", "N3_SHADOW_V1", "N4")
COURT_ID = "R5_E1860"                            # keys control PRNGs; not a court

DEV_NAMESPACE = "WM0E_R5_NEG_DEV_V0"
_EXCLUDED = (tuple(_V0_SEEDS) + tuple(_CONSUMED) + tuple(N3_DEV_SEEDS)
             + tuple(P0_DEV_SEEDS) + tuple(R4_SEEDS))
R5_DEV = derive_holdout(DEV_NAMESPACE, 100, _EXCLUDED)
R5_DEV_SEEDS = tuple(R5_DEV["seeds"])
assert len(R5_DEV_SEEDS) == 100 and not set(R5_DEV_SEEDS) & set(_EXCLUDED)


def r5_dataset(control: str, seed: int):
    """The frozen construction for `control`, unchanged; geometry comes from
    the split run_pipeline passes in (R4_SPLIT)."""
    if control == "N0":
        return C.n0_dataset(COURT_ID, seed)
    if control == "N1":
        return C.n1_dataset(COURT_ID, seed)
    if control == "N2":
        return C.n2_dataset(COURT_ID, seed)
    if control == "N3_SHADOW_V1":
        return n3_v1_dataset(seed)
    if control == "N4":
        return default_dataset
    raise ControlViolation("unknown R5 control %r" % control)


def r5_model(control: str, seed: int):
    from apex.world_model.models import M0SyntheticBaseline
    return C.RandomRanker(COURT_ID, seed) if control == "N4" else M0SyntheticBaseline()


EXPECTED_USABLE = {"N0": 1860, "N1": 1860 - C.N1_SHIFT_STEPS, "N2": 1860,
                   "N3_SHADOW_V1": 1860, "N4": 1860}
EXPECTED_TRAIN = {"N0": 700, "N1": 701 - C.N1_SHIFT_STEPS, "N2": 701,
                  "N3_SHADOW_V1": 701, "N4": 701}
# N0: block-derangement truncates to whole 20-step blocks (1860 = 93 blocks
# exactly; 701 -> 700). N1: X_t is paired with y_{t+200}, so 200 pairs at
# each window end have no partner. Both are the FROZEN constructions'
# declared behaviour, recorded here so nobody mistakes them for drift.


def predeclaration() -> dict:
    return {"version": R5_VERSION, "purpose": "DEVELOPMENT validation of every "
            "negative control at the selected evaluation length; no acceptance court",
            "geometry": {"T_max": T_MAX, "boundary": V0_BOUNDARY, "n_train": 701,
                         "usable_eval": E_SELECTED, "split": R4_SPLIT.canonical(),
                         "expected_usable_by_control": EXPECTED_USABLE,
                         "expected_train_by_control": EXPECTED_TRAIN},
            "controls": {"N0": C.CONTROL_CONTRACT["N0"], "N1": C.CONTROL_CONTRACT["N1"],
                         "N2": C.CONTROL_CONTRACT["N2"], "N3_SHADOW_V1": N3_V1 + " (controls_r3, unchanged)",
                         "N4": C.CONTROL_CONTRACT["N4"], "N3_V0": "RETIRED, not run"},
            "requirement_per_control": "false detections <= %d / 100" % R5_MAX_FP,
            "alpha": 0.025, "seeds": {"namespace": DEV_NAMESPACE, "n": 100,
                                       "hash": R5_DEV["seed_set_hash"], "skipped": R5_DEV["skipped"],
                                       "shared_by_all_controls": True,
                                       "excluded": "V0 dev 25, consumed V2.1 50, R3 N3 100, R3 P0 50, R4 50"},
            "P0": "P0_CAUSAL_TREND_POWERED_V2 carried forward; NOT rerun",
            "pooled": "descriptive only; controls share seeds; no pooled rescue",
            "new_acceptance_seeds_created": False, "acceptance_court": "NONE",
            "WM_META_001": "run_pipeline(split=R4_SPLIT); run artifact binds the EXECUTED split"}


def predeclaration_hash() -> str:
    return content_hash(predeclaration())
