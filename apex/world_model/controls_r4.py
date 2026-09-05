"""WM-0E-R4 -- P0_POWER_CONTRACT_V2: positive-control EVALUATION-LENGTH
power calibration. DEVELOPMENT ONLY. No acceptance court.

QUESTION
Does the frozen model/court reliably recognise the ORIGINAL planted causal
relationship (S1, mu = 1.0 x P0_V0) when supplied with enough independent
out-of-sample evidence? Only the amount of evaluation evidence varies.

WHY A NESTED DESIGN, AND WHY ONE WORLD PER SEED
The generator keys every PRNG stream on sha256(version | config_hash |
seed | stream) and config_hash includes n_steps. Four worlds with four
n_steps would be four different paths -- the same confound that made
R3's magnitude ladder partly a different-world comparison. So for each
development seed exactly ONE world is generated at the maximum length,
M0 is fitted ONCE on the V0 training interval (warmup 5 .. boundary 720,
701 samples, identical to every prior court), forecasts are produced once
for the whole 1860-sample evaluation path, and the ladder levels are
deterministic nested PREFIXES of that one graded path. Same world, same
training, same fitted model, same transforms, same mu -- only the
evaluation cutoff changes.

THE SPLIT
run_pipeline() builds its own split at boundary 0.6*T; at T_max that
would move the boundary to 1557 and GROW the training sample, which §4
forbids. The dataset seam therefore uses R4_SPLIT (boundary 720, the V0
boundary) and ignores the pipeline's default split. Consequence, stated
plainly: the `split` and `boundary_fraction` fields inside the pipeline's
run record are the default and are NOT what was used; the split actually
used is R4_SPLIT and is persisted in the evidence. No frozen module is
modified to achieve this.

LADDER (mechanical, from the registered V0 evaluation count)
  E0 = usable evaluation observations of the V0 split = 465
  ladder = [1, 2, 3, 4] x E0 = [465, 930, 1395, 1860]
  T_max = boundary + 4*E0 + H = 720 + 1860 + 15 = 2595
  cutoffs (exclusive step index) = 720 + k*E0
"""
from __future__ import annotations

from apex.world_model.canonical import content_hash
from apex.world_model.controls import ControlViolation
from apex.world_model.controls_r3 import N3_DEV_SEEDS, P0_DEV_SEEDS
from apex.world_model.court import N_STEPS, S1_PARAMS, S1_SIGMA, SEED_SET as _V0_SEEDS
from apex.world_model.features import WARMUP_STEPS
from apex.world_model.holdout import HOLDOUT_SEEDS as _CONSUMED, derive_holdout
from apex.world_model.runs import ChronologicalSplit
from apex.world_model.targets import TARGET_HORIZON_STEPS as H
from apex.world_model.teststand import FIXED_BOUNDARY_FRACTION, build_dataset
from apex.world_model.worlds import S1_CAUSAL_TREND, WorldConfig, generate_world

R4_VERSION = "P0_POWER_CONTRACT_V2"
P0_MU_MULTIPLIER = 1.0                                   # the ORIGINAL effect
V0_T = N_STEPS                                           # 1200
V0_BOUNDARY = int(V0_T * FIXED_BOUNDARY_FRACTION)        # 720
E0 = V0_T - H - V0_BOUNDARY                              # 465 usable eval obs
LADDER_MULTIPLIERS = (1, 2, 3, 4)
EVAL_LADDER = tuple(k * E0 for k in LADDER_MULTIPLIERS)  # (465, 930, 1395, 1860)
T_MAX = V0_BOUNDARY + max(EVAL_LADDER) + H               # 2595
CUTOFFS = tuple(V0_BOUNDARY + L for L in EVAL_LADDER)    # exclusive step index
R4_SPLIT = ChronologicalSplit(n_steps=T_MAX, boundary=V0_BOUNDARY)
V0_SPLIT = ChronologicalSplit(n_steps=V0_T, boundary=V0_BOUNDARY)
assert len(R4_SPLIT.train_steps) == len(V0_SPLIT.train_steps) == 701
assert R4_SPLIT.train_steps == V0_SPLIT.train_steps

QUALIFICATION = {"min_detection_rate": 0.90, "min_wilson95_lower": 0.80,
                 "min_direction_rate": 0.95,
                 "rule": "after ALL levels ran: the SMALLEST evaluation length "
                         "satisfying all three; none -> FAIL/STOP"}
FUTURE_ACCEPTANCE = {"min_detections": 40, "min_direction": 45, "n": 50,
                     "note": "frozen; NOT run in this brick"}

DEV_NAMESPACE = "WM0E_R4_P0_DEV_V0"
_EXCLUDED = tuple(_V0_SEEDS) + tuple(_CONSUMED) + tuple(N3_DEV_SEEDS) + tuple(P0_DEV_SEEDS)
DEV = derive_holdout(DEV_NAMESPACE, 50, _EXCLUDED)
DEV_SEEDS = tuple(DEV["seeds"])
assert len(DEV_SEEDS) == 50 and not set(DEV_SEEDS) & set(_EXCLUDED)


def r4_world(seed: int):
    """ONE maximum-length world per seed; the ORIGINAL S1 parameters."""
    return generate_world(WorldConfig(world_type=S1_CAUSAL_TREND, seed=seed,
                                      n_subjects=1, n_steps=T_MAX,
                                      sigma=S1_SIGMA, params=dict(S1_PARAMS),
                                      observe_latent=True))


def r4_dataset(world, subject, split_from_pipeline):
    """The seam. Training = the V0 interval; evaluation = the FULL
    1860-sample path. Levels are prefixes taken AFTER grading."""
    if world.config.n_steps != T_MAX:
        raise ControlViolation("R4 dataset requires the T_MAX world (%d), got %d"
                               % (T_MAX, world.config.n_steps))
    Xtr, ytr, itr, _ = build_dataset(world, subject, R4_SPLIT.train_steps)
    Xev, yev, iev, ev_out = build_dataset(world, subject, R4_SPLIT.eval_steps)
    if list(itr) != list(V0_SPLIT.train_steps):
        raise ControlViolation("training interval drifted from the V0 interval")
    if len(Xev) != max(EVAL_LADDER):
        raise ControlViolation("usable evaluation count %d != %d"
                               % (len(Xev), max(EVAL_LADDER)))
    return Xtr, ytr, Xev, yev, iev, ev_out


def training_hash(Xtr, ytr) -> str:
    return content_hash({"X": Xtr, "y": ytr, "n": len(ytr),
                         "steps": [R4_SPLIT.train_steps.start,
                                   R4_SPLIT.train_steps.stop]})


def predeclaration() -> dict:
    return {"version": R4_VERSION, "design": "NESTED prefixes of ONE world per seed; "
            "M0 fit once on the V0 training interval; only the evaluation cutoff varies",
            "mu_multiplier": P0_MU_MULTIPLIER, "s1_params": dict(S1_PARAMS), "sigma": S1_SIGMA,
            "E0": E0, "ladder_multipliers": list(LADDER_MULTIPLIERS),
            "evaluation_ladder": list(EVAL_LADDER), "cutoffs_exclusive": list(CUTOFFS),
            "T_max": T_MAX, "boundary": V0_BOUNDARY, "warmup": WARMUP_STEPS,
            "train_steps": [R4_SPLIT.train_steps.start, R4_SPLIT.train_steps.stop],
            "train_samples": len(R4_SPLIT.train_steps),
            "eval_start": V0_BOUNDARY, "ladder_hash": content_hash(list(EVAL_LADDER)),
            "seeds": {"namespace": DEV_NAMESPACE, "n": 50, "paired_across_levels": True,
                      "hash": DEV["seed_set_hash"], "excluded": "V0 dev 25, consumed V2.1 50, "
                      "R3 N3 dev 100, R3 P0 dev 50", "skipped": DEV["skipped"]},
            "qualification": QUALIFICATION, "future_acceptance": FUTURE_ACCEPTANCE,
            "acceptance_court": "NONE", "new_acceptance_seeds_created": False,
            "pipeline_split_field_disclosure": "run records carry the pipeline default "
            "split (boundary 0.6*T_max = 1557); it is NOT used; R4_SPLIT (boundary 720) is"}


def predeclaration_hash() -> str:
    return content_hash(predeclaration())
