"""Hunter ML engine v1 — the complete training/evaluation pipeline, whose
FIRST production act is to refuse.

Model lifecycle (a separate axis from distribution provenance, per the
existing calibration architecture): UNTRAINED -> EXPLORATORY_MODEL ->
FORWARD_EVALUATING -> PAPER_GRADE -> CALIBRATED, with DEGRADED / RETIRED.
No state is skippable and none is reachable without the evidence the
frozen criteria demand.

Feature contract: ONLY legitimate as-of state (ChartState,
RelativeStrengthState, market state, playbook, time of day) — extracted
via the SAME frozen analog schema so features cannot silently drift from
what the retrieval engine considers "state". No post-outcome feature can
enter: the dataset builder takes features exclusively from DECISION
records and labels exclusively from REALIZATION records, and refuses any
feature name matching a realized-outcome field.

Training discipline: interpretable family only in v1 (L2-regularized
logistic via IRLS, deterministic, no library dependency), one declared
spec registered in the existing ModelSearchLedger — the denominator is
every fit attempted, not every fit kept. Overlapping-horizon labels are
never treated as independent: N_effective (session-day cells) gates
training, not row count.

INSUFFICIENT_FORWARD_DATA is the expected Monday answer and it is a
correct, successful output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from apex.analog.engine import ANALOG_FEATURE_SCHEMA_V1, feature_vector
from apex.hunter.contracts import HORIZONS_MINUTES

ML_ENGINE_VERSION = "hunter_ml_v1"
MIN_EFFECTIVE_TO_TRAIN = 40          # sessions-x-playbook cells (frozen)
# outcome-field tokens; note realized_vol_ann is as-of-T state, NOT an
# outcome — the guard targets realization-record fields specifically
FORBIDDEN_FEATURE_TOKENS = ("ret_", "mae_", "mfe_", "target_before",
                            "stop_before", "closing_return")

LIFECYCLE = ("UNTRAINED", "EXPLORATORY_MODEL", "FORWARD_EVALUATING",
             "PAPER_GRADE", "CALIBRATED", "DEGRADED", "RETIRED")


class MLContractViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class HunterDataset:
    horizon_minutes: int
    X: object                        # (n, f) ndarray from the frozen schema
    y: object                        # (n,) {0,1} = ret_h > 0
    session_dates: tuple
    playbook_ids: tuple
    n_raw: int
    n_effective: int
    feature_names: tuple
    provenance: dict


@dataclass(frozen=True)
class HunterModel:
    status: str                      # lifecycle state
    horizon_minutes: int
    coef: tuple | None
    intercept: float | None
    n_raw: int
    n_effective: int
    reasons: tuple
    provenance: dict
    engine_version: str = field(default=ML_ENGINE_VERSION)

    def predict_p_positive(self, record: dict) -> dict:
        """Typed refusal is a first-class output."""
        if self.status in ("UNTRAINED", "RETIRED", "DEGRADED"):
            return {"status": self.status, "p_positive": None,
                    "reasons": list(self.reasons)}
        v, missing = feature_vector(record)
        if not np.all(np.isfinite(v)):
            return {"status": self.status, "p_positive": None,
                    "reasons": [f"missing features: {missing}"]}
        z = float(np.dot(np.array(self.coef), v) + self.intercept)
        return {"status": self.status,
                "p_positive": round(float(1 / (1 + np.exp(-z))), 4),
                "reasons": []}


def build_dataset(decisions: list, realizations_by_id: dict,
                  horizon_minutes: int, *, evidence_class=None
                  ) -> HunterDataset:
    """Features from DECISION records only; labels from REALIZATIONS only.
    Playbook candidates only (baselines are a scoreboard concern).

    LAB-08: `evidence_class` is REQUIRED and verified against every row.
    The forward_eligibility filter below is NOT a class barrier -- the
    replay lab deliberately stamps its records FORWARD_ELIGIBLE as a
    declared counterfactual, so exploratory rows sail straight through it.
    A model trained on laboratory tape while believing itself forward-
    trained is the exact confusion the evidence law exists to prevent.
    """
    from apex.hunter.evidence import require_declared_class
    if evidence_class is None:
        raise MLContractViolation(
            "build_dataset requires an explicit evidence_class: a training "
            "set whose provenance is assumed is not a training set.")
    require_declared_class(decisions, evidence_class,
                           where="ml.build_dataset")
    if horizon_minutes not in HORIZONS_MINUTES:
        raise MLContractViolation(f"undeclared horizon {horizon_minutes}")
    names = tuple(n for n, _, _ in ANALOG_FEATURE_SCHEMA_V1)
    for n in names:
        if any(tok in n for tok in FORBIDDEN_FEATURE_TOKENS):
            raise MLContractViolation(
                f"feature {n!r} smells of a realized outcome; refused")
    X, y, dates, pids = [], [], [], []
    for d in decisions:
        if d.get("playbook_id", "").startswith("BASELINE-"):
            continue
        if d.get("forward_eligibility") != "FORWARD_ELIGIBLE":
            continue
        o = realizations_by_id.get(d.get("decision_id"))
        if not o or o.get(f"ret_{horizon_minutes}m") is None:
            continue
        v, missing = feature_vector(d)
        if missing:
            continue          # F-05: a missing feature is excluded, never
        X.append(v)           # coerced to a scaled-zero "typical" value
        y.append(1.0 if o[f"ret_{horizon_minutes}m"] > 0 else 0.0)
        dates.append(d["session_date"])
        pids.append(d["playbook_id"])
    cells = {(dt, p) for dt, p in zip(dates, pids)}
    n_eff = min(len(cells), len(set(dates)))
    return HunterDataset(
        horizon_minutes=horizon_minutes,
        X=np.array(X) if X else np.zeros((0, len(names))),
        y=np.array(y), session_dates=tuple(dates),
        playbook_ids=tuple(pids), n_raw=len(y), n_effective=n_eff,
        feature_names=names,
        provenance={"engine": ML_ENGINE_VERSION,
                    "schema": "ANALOG_FEATURE_SCHEMA_V1",
                    "label": f"ret_{horizon_minutes}m > 0"})


def train(dataset: HunterDataset, *, ridge: float = 1.0,
          seed: int = 0) -> HunterModel:
    """Deterministic L2 logistic (IRLS). REFUSES below the frozen
    effective-sample bar — building the socket is this function's whole
    Monday job; filling it is the market's."""
    del seed                                     # deterministic anyway
    base = {"horizon_minutes": dataset.horizon_minutes,
            "n_raw": dataset.n_raw, "n_effective": dataset.n_effective,
            "provenance": dataset.provenance}
    if dataset.n_effective < MIN_EFFECTIVE_TO_TRAIN:
        return HunterModel(
            status="UNTRAINED", coef=None, intercept=None,
            reasons=(f"INSUFFICIENT_FORWARD_DATA: n_effective "
                     f"{dataset.n_effective} < {MIN_EFFECTIVE_TO_TRAIN}; "
                     f"refusing to train a production model on air",),
            **base)
    X = np.column_stack([np.ones(len(dataset.y)), dataset.X])
    w = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w))
        grad = X.T @ (dataset.y - p) - ridge * np.r_[0.0, w[1:]]
        s = np.clip(p * (1 - p), 1e-6, None)
        H = (X.T * s) @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, grad)
        w = w + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return HunterModel(status="EXPLORATORY_MODEL",
                       coef=tuple(round(float(c), 6) for c in w[1:]),
                       intercept=round(float(w[0]), 6),
                       reasons=("exploratory only: forward evaluation and "
                                "calibration gates remain ahead",), **base)
