"""MODEL_RUN_V0 and the CHRONOLOGICAL SPLIT.

THE SPLIT, STATED MATHEMATICALLY
Let T be the number of steps, H = 15 the target horizon, B the boundary
step, and W = 5 the feature warm-up.

    TRAIN   t in [W, B - H]        target y_t depends on p_{t+H} <= p_B
    PURGE   t in (B - H, B)        DISCARDED
    EVAL    t in [B, T - H]        target y_t depends on p_{t+H} <= p_T

Every training target is a function of prices at or before p_B, and
every evaluation feature is a function of prices at or after p_{B-5}
(lagged returns). The purge exists because a training sample at
t = B - 1 has a target that reads p_{B+14}: fourteen evaluation-period
prices, leaked into the fit through the label. Without the purge that
leak is silent and the evaluation is worthless.

No shuffling. Ever. A random split of a time series lets the model see
the neighbourhood of every evaluation point during training, which is
not what "out of sample" means for anything that evolves in time.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field

from apex.world_model.canonical import content_hash, strict_float
from apex.world_model.features import FEATURE_SET_VERSION, WARMUP_STEPS
from apex.world_model.targets import (TARGET_DEFINITION, TARGET_HORIZON,
                                      TARGET_HORIZON_STEPS, TARGET_VERSION)
from apex.world_model.worlds import NULL_FIXTURE, SYNTHETIC_FIXTURE

RUN_SCHEMA_VERSION = "MODEL_RUN_V0"
SPLIT_VERSION = "WM0D_CHRONOLOGICAL_PURGED_SPLIT_V0"
RUN_AUTHORITY = "SYNTHETIC_RESEARCH_ONLY"
PERMITTED_FIXTURE_CLASSES = frozenset({SYNTHETIC_FIXTURE, NULL_FIXTURE})


class RunContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class ChronologicalSplit:
    n_steps: int
    boundary: int
    horizon_steps: int = TARGET_HORIZON_STEPS
    warmup_steps: int = WARMUP_STEPS

    def __post_init__(self):
        T, B, H, W = (self.n_steps, self.boundary, self.horizon_steps,
                      self.warmup_steps)
        if not (W < B - H):
            raise RunContractViolation(
                "boundary %d leaves no purged training interval: need "
                "warmup(%d) < boundary - horizon(%d)" % (B, W, B - H))
        if not (B <= T - H):
            raise RunContractViolation(
                "boundary %d leaves no evaluation interval: need "
                "boundary <= n_steps - horizon = %d" % (B, T - H))

    @property
    def train_steps(self) -> range:
        return range(self.warmup_steps, self.boundary - self.horizon_steps + 1)

    @property
    def purged_steps(self) -> range:
        return range(self.boundary - self.horizon_steps + 1, self.boundary)

    @property
    def eval_steps(self) -> range:
        return range(self.boundary, self.n_steps - self.horizon_steps + 1)

    def canonical(self) -> dict:
        return {"split_version": SPLIT_VERSION, "n_steps": self.n_steps,
                "boundary": self.boundary, "horizon_steps": self.horizon_steps,
                "warmup_steps": self.warmup_steps,
                "train": [self.train_steps.start, self.train_steps.stop - 1],
                "purged": [self.purged_steps.start, self.purged_steps.stop - 1]
                          if len(self.purged_steps) else None,
                "eval": [self.eval_steps.start, self.eval_steps.stop - 1],
                "law": "every training target reads prices <= p_boundary; "
                       "the purge removes training samples whose label "
                       "would read evaluation-period prices"}


@dataclass(frozen=True)
class ModelRun:
    run_id: str
    model_id: str
    model_family: str
    model_version: str
    code_commit: str
    information_tier: str
    training_world_ids: tuple
    evaluation_world_ids: tuple
    world_hashes: dict
    fixture_classes: dict            # world_id -> fixture class
    split: ChronologicalSplit
    seed: int
    training_configuration: dict
    creation_time: float
    feature_set_version: str = FEATURE_SET_VERSION
    target_version: str = TARGET_VERSION
    target_definition: str = TARGET_DEFINITION
    forecast_horizon: str = TARGET_HORIZON
    run_schema_version: str = RUN_SCHEMA_VERSION
    authority: str = RUN_AUTHORITY

    def __post_init__(self):
        if self.authority != RUN_AUTHORITY:
            raise RunContractViolation(
                "run authority must be %s, got %r" % (RUN_AUTHORITY,
                                                     self.authority))
        for wid in set(self.training_world_ids) | set(self.evaluation_world_ids):
            fc = self.fixture_classes.get(wid)
            if fc not in PERMITTED_FIXTURE_CLASSES:
                raise RunContractViolation(
                    "world %r has fixture class %r; a research run may "
                    "reference SYNTHETIC_FIXTURE or NULL_FIXTURE worlds "
                    "only. Real-market provenance is refused." % (wid, fc))
            if wid not in self.world_hashes:
                raise RunContractViolation(
                    "world %r has no recorded hash" % wid)
            if not str(wid).startswith("W-"):
                raise RunContractViolation(
                    "world id %r is not a generated synthetic world id" % wid)
        strict_float(self.creation_time, field="creation_time")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise RunContractViolation("seed must be an int")

    def content(self) -> dict:
        return {"run_schema_version": self.run_schema_version,
                "model_id": self.model_id, "model_family": self.model_family,
                "model_version": self.model_version,
                "code_commit": self.code_commit,
                "information_tier": self.information_tier,
                "training_world_ids": list(self.training_world_ids),
                "evaluation_world_ids": list(self.evaluation_world_ids),
                "world_hashes": dict(self.world_hashes),
                "fixture_classes": dict(self.fixture_classes),
                "feature_set_version": self.feature_set_version,
                "target_version": self.target_version,
                "target_definition": self.target_definition,
                "forecast_horizon": self.forecast_horizon,
                "split": self.split.canonical(), "seed": self.seed,
                "training_configuration": dict(self.training_configuration),
                "configuration_hash": content_hash(
                    dict(self.training_configuration)),
                "authority": self.authority}

    @property
    def run_hash(self) -> str:
        """CONTENT identity: creation_time excluded, same law as forecasts."""
        return content_hash(self.content())

    def sealed(self) -> dict:
        d = self.content()
        d["run_id"] = self.run_id
        d["creation_time"] = float(self.creation_time)
        d["run_hash"] = self.run_hash
        d["TRADING_AUTHORITY"] = "NONE"
        d["CAPITAL_AUTHORITY"] = "NONE"
        d["ORDER_AUTHORITY"] = "NONE"
        return d
