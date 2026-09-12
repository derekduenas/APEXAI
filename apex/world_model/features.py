"""OBSERVABLE-ONLY FEATURES and TRAIN-ONLY TRANSFORMS.

THE FEATURE LAW
A feature is built from ObservableState and NOTHING ELSE. The extractor
takes a tuple of ObservableState and returns floats. It cannot take a
world, a truth object, or a path -- the signature does not admit them.
This is how the student is kept away from the answer key at the point
where it would be most convenient to cheat.

THE FROZEN FEATURE SET (one, not "a few to try")
    ret_1        log(p_t / p_{t-1})          lagged, observable
    ret_5        log(p_t / p_{t-5})          lagged, observable
    spread_bps   as generated                planted as NOISE in WM-0C
    volume       as generated                planted as NOISE
    trade_count  as generated                planted as NOISE
    declared_observable_state                the state the WORLD chose
                                             to expose; in S0 it is a
                                             constant 0.0 and carries no
                                             information, which is the
                                             point

TRAIN-ONLY TRANSFORMS
Standardisation is fit on the training partition and FROZEN. The
evaluation partition is transformed with the training mean and scale,
never its own. A constant column (std == 0) is centred and left at
zero: a feature with no variance has no information, and scaling it by
1/0 would manufacture some. That is a statement about variance, not
about missingness -- missing stays None upstream and never reaches
here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from apex.world_model.canonical import NumericContractViolation, strict_float
from apex.world_model.worlds import ObservableState

FEATURE_SET_VERSION = "WM0D_OBSERVABLE_FEATURES_V0"
FEATURE_NAMES = ("ret_1", "ret_5", "spread_bps", "volume", "trade_count",
                 "declared_observable_state")
WARMUP_STEPS = 5           # ret_5 needs five prior observations


class FeatureContractViolation(ValueError):
    pass


def extract_features(states: tuple, step: int) -> list:
    """Features for one step from observable state only.

    Refuses anything that is not an ObservableState so a caller cannot
    hand it a GeneratorGroundTruth 'by accident'.
    """
    if step < WARMUP_STEPS:
        raise FeatureContractViolation(
            "step %d is inside the %d-step warm-up; no lagged return "
            "exists yet and it is NOT filled with zero" % (step, WARMUP_STEPS))
    for o in (states[step], states[step - 1], states[step - 5]):
        if not isinstance(o, ObservableState):
            raise FeatureContractViolation(
                "feature extraction accepts ObservableState only, got %s"
                % type(o).__name__)
    o, o1, o5 = states[step], states[step - 1], states[step - 5]
    lat = o.observable_latent if o.observable_latent is not None else 0.0
    if o.observable_latent is None and any(
            s.observable_latent is not None for s in states):
        raise FeatureContractViolation(
            "observable_latent is None at step %d but present elsewhere; "
            "a partially-missing column is not silently zero-filled" % step)
    row = [math.log(o.price / o1.price), math.log(o.price / o5.price),
           o.spread, o.volume, float(o.trade_count), float(lat)]
    for name, v in zip(FEATURE_NAMES, row):
        strict_float(v, field=name)
    return row


@dataclass(frozen=True)
class FrozenScaler:
    """Parameters estimated on TRAINING data, then immutable."""
    means: tuple
    scales: tuple
    n_fit: int

    @classmethod
    def fit(cls, X: list) -> "FrozenScaler":
        if not X:
            raise FeatureContractViolation("cannot fit a scaler on no rows")
        k = len(X[0])
        means, scales = [], []
        for j in range(k):
            col = [strict_float(r[j], field=FEATURE_NAMES[j]) for r in X]
            m = sum(col) / len(col)
            var = sum((c - m) ** 2 for c in col) / max(1, len(col) - 1)
            s = math.sqrt(var)
            means.append(m)
            scales.append(s if s > 0 else 1.0)   # constant column -> 0
        return cls(means=tuple(means), scales=tuple(scales), n_fit=len(X))

    def transform(self, X: list) -> list:
        return [[(strict_float(r[j], field=FEATURE_NAMES[j]) - self.means[j])
                 / self.scales[j] for j in range(len(self.means))]
                for r in X]

    def canonical(self) -> dict:
        return {"means": list(self.means), "scales": list(self.scales),
                "n_fit": self.n_fit, "feature_set": FEATURE_SET_VERSION}
