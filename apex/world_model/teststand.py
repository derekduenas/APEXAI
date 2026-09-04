"""THE TEST STAND -- run one frozen pipeline over one synthetic world.

    generate world -> chronological purged split -> features (observable
    only) -> targets (through the narrow door) -> fit scaler on TRAIN ->
    fit model on TRAIN -> forecast EVAL -> SEAL forecasts -> resolve
    outcomes -> grade -> preregistered null rule

Identical code path for every world and every model. If the pipeline
behaves differently on S1 than on S0, it is because the WORLD differs,
not because anything was tuned.
"""
from __future__ import annotations

from apex.world_model.features import (FeatureContractViolation,
                                       FrozenScaler, extract_features)
from apex.world_model.forecast import WorldModelForecast
from apex.world_model.grader import aggregate, grade, null_rule
from apex.world_model.models import M0SyntheticBaseline, NullBaseline
from apex.world_model.runs import ChronologicalSplit, ModelRun
from apex.world_model.targets import HORIZON_NOT_AVAILABLE, resolve_target
from apex.world_model.worlds import GeneratorGroundTruth, SyntheticWorld

TESTSTAND_VERSION = "WM0D_TESTSTAND_V0"
FIXED_BOUNDARY_FRACTION = 0.6      # PREDECLARED


class StandViolation(Exception):
    pass


def _reject_truth(obj):
    if isinstance(obj, GeneratorGroundTruth):
        raise StandViolation(
            "a GeneratorGroundTruth object reached the model pipeline. "
            "The answer key does not enter the classroom.")


def build_dataset(world: SyntheticWorld, subject: str, steps: range):
    """X from ObservableState only; y through resolve_target only."""
    states = world.observables[subject]
    X, y, idx, outcomes = [], [], [], []
    for s in steps:
        rec = resolve_target(world, subject, s)
        if rec == HORIZON_NOT_AVAILABLE:
            continue
        X.append(extract_features(states, s))
        y.append(rec.target_value)
        idx.append(s)
        outcomes.append(rec)
    if not X:
        raise StandViolation("empty partition for %s" % subject)
    return X, y, idx, outcomes


def default_dataset(world, subject, split):
    """The untransformed pipeline: features and targets as generated."""
    Xtr, ytr, _, _ = build_dataset(world, subject, split.train_steps)
    Xev, yev, ev_idx, ev_out = build_dataset(world, subject, split.eval_steps)
    return Xtr, ytr, Xev, yev, ev_idx, ev_out


def run_pipeline(world: SyntheticWorld, model, *, subject: str = "SYN_A",
                 code_commit: str = "UNCOMMITTED", seed: int = 0,
                 creation_time: float | None = None,
                 dataset=default_dataset) -> dict:
    """`dataset` is the ONE seam a negative control may use. It replaces
    how (X, y) are assembled; it cannot touch the model, the scaler, the
    forecast contract, the sealing step or the grader. A null that
    needed to change any of those would not be a null."""
    _reject_truth(model)
    T = world.config.n_steps
    split = ChronologicalSplit(n_steps=T, boundary=int(T * FIXED_BOUNDARY_FRACTION))

    Xtr, ytr, Xev, yev, ev_idx, ev_out = dataset(world, subject, split)
    if not Xtr or not Xev:
        raise StandViolation("a dataset builder returned an empty partition")
    if len(Xev) != len(ev_idx) or len(Xev) != len(ev_out):
        raise StandViolation("dataset builder returned misaligned eval arrays")

    scaler = FrozenScaler.fit(Xtr)                 # TRAIN ONLY
    model.fit(scaler.transform(Xtr), ytr)

    ct = creation_time if creation_time is not None else (
        world.config.session_start)
    run = ModelRun(
        run_id="RUN-%s-%s" % (model.model_id, world.world_id),
        model_id=model.model_id, model_family=model.model_family,
        model_version=model.model_version, code_commit=code_commit,
        information_tier="A0_CORE",
        training_world_ids=(world.world_id,),
        evaluation_world_ids=(world.world_id,),
        world_hashes={world.world_id: world.world_hash},
        fixture_classes={world.world_id: world.fixture_class},
        split=split, seed=seed,
        training_configuration={"model": model.model_identity()["configuration"],
                                "scaler": scaler.canonical(),
                                "boundary_fraction": FIXED_BOUNDARY_FRACTION},
        creation_time=ct)

    # ---- forecast, and SEAL before any outcome is looked at
    forecasts, sealed_hashes = [], {}
    for x, s in zip(scaler.transform(Xev), ev_idx):
        inp = world.to_world_model_input(subject, s)
        dist = model.predict_distribution(x)
        f = WorldModelForecast(
            forecast_id="%s:%s:%d" % (run.run_id, subject, s),
            input_id=inp.input_id, input_hash=inp.input_hash,
            model_id=model.model_id, model_version=model.model_version,
            model_family=model.model_family,
            information_tier=inp.information_tier,
            creation_time=inp.known_from, known_from=inp.known_from,
            forecast_horizon=run.forecast_horizon, distribution=dist,
            uncertainty_metadata={"epistemic_aleatoric_split": False})
        forecasts.append(f)
        sealed_hashes[f.forecast_id] = f.forecast_hash

    # ---- only NOW resolve outcomes and grade
    grades = []
    for f, rec in zip(forecasts, ev_out):
        g = grade(f, rec, grading_time=rec.outcome_known_time + 1.0)
        if sealed_hashes[f.forecast_id] != g.forecast_hash_after:
            raise StandViolation("sealed hash mismatch for %s" % f.forecast_id)
        grades.append(g)

    return {"run": run, "scaler": scaler, "forecasts": forecasts,
            "sealed_hashes": sealed_hashes, "grades": grades,
            "aggregate": aggregate(grades), "n_train": len(Xtr),
            "n_eval": len(Xev), "split": split.canonical()}


def control_experiment(world: SyntheticWorld, *, subject: str = "SYN_A",
                       code_commit: str = "UNCOMMITTED") -> dict:
    """M0 vs the null comparator on ONE world, same split, same eval
    outcomes, preregistered rule. This is the whole experiment."""
    m0 = run_pipeline(world, M0SyntheticBaseline(), subject=subject,
                      code_commit=code_commit)
    nl = run_pipeline(world, NullBaseline(), subject=subject,
                      code_commit=code_commit)
    verdict = null_rule(m0["grades"], nl["grades"])
    return {"world_id": world.world_id, "world_type": world.world_type,
            "world_hash": world.world_hash, "m0": m0, "null": nl,
            "verdict": verdict,
            "m0_run_hash": m0["run"].run_hash,
            "null_run_hash": nl["run"].run_hash}
