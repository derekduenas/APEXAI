"""SYNTHETIC TARGET CONTRACT -- the ONLY door to the answer key.

The target resolver is the single place in the laboratory that reads
generator truth, and it reads exactly one number per (subject, step):
the forward log return at the ONE registered horizon. It does not hand
the caller the path, the latent state, the regime or the MFE/MAE. If a
model wants to know the future, this is the door, and the door is
narrow on purpose.

THE FROZEN TARGET
    horizon   H_15M   (15 synthetic steps)
    y_t       log(p_{t+15} / p_t)
Frozen before any model was run. Not compared against other horizons.

An OutcomeRecord is a separate, sealed object from a forecast. The two
are never merged into one mutable thing: the grader takes both and
compares, and a forecast's hash is checked before and after.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from apex.world_model.canonical import content_hash, strict_float
from apex.world_model.worlds import HORIZON_NOT_AVAILABLE, SyntheticWorld

TARGET_VERSION = "WM0D_SYNTHETIC_TARGET_V0"
TARGET_HORIZON = "H_15M"
TARGET_HORIZON_STEPS = 15
TARGET_DEFINITION = "log(p_{t+15} / p_t), forward log return at H_15M"


class TargetContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class OutcomeRecord:
    """Sealed synthetic outcome. Carries when it became KNOWN, so the
    grader can refuse an outcome that was resolvable before the forecast
    it grades was made."""
    world_id: str
    world_hash: str
    subject: str
    step: int
    horizon: str
    target_value: float
    outcome_known_time: float
    target_version: str = TARGET_VERSION

    def canonical(self) -> dict:
        return {"world_id": self.world_id, "world_hash": self.world_hash,
                "subject": self.subject, "step": self.step,
                "horizon": self.horizon,
                "target_value": float(self.target_value),
                "outcome_known_time": float(self.outcome_known_time),
                "target_version": self.target_version}

    @property
    def outcome_hash(self) -> str:
        return content_hash(self.canonical())


def resolve_target(world: SyntheticWorld, subject: str, step: int):
    """The narrow door. Returns an OutcomeRecord or HORIZON_NOT_AVAILABLE.

    It reads world.forward_truth for ONE horizon and returns ONE number.
    It does NOT return the truth object.
    """
    t = world.forward_truth(subject, step, TARGET_HORIZON)
    if t == HORIZON_NOT_AVAILABLE:
        return HORIZON_NOT_AVAILABLE
    y = math.log1p(strict_float(t["forward_return"], field="forward_return"))
    known = (world.config.session_start
             + (step + TARGET_HORIZON_STEPS) * world.config.step_seconds)
    return OutcomeRecord(world_id=world.world_id, world_hash=world.world_hash,
                         subject=subject, step=step, horizon=TARGET_HORIZON,
                         target_value=y, outcome_known_time=known)
