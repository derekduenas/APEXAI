"""The five arms. M0 and M1 are the registered EXP-001B estimators, imported
unchanged. S, L and C share one (s*, nu*) estimated from linear-mean residuals."""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from apex.world_model.exp001b import models as M01
from apex.world_model.exp001b.registration import AVAILABILITY_BASIS, FEATURE_SET_VERSION, HORIZON, M0, M1
from apex.world_model.forecast import PredictiveDistribution, WorldModelForecast
from . import studentt as T
from .registration import ARMS, NU_BOUNDS

QS = ("0.05", "0.25", "0.5", "0.75", "0.95")
RCOND = 1e-12


class ArmRefused(ValueError):
    """An arm could not be fitted under the declared rules. Named, never silent."""


def _basis(f: dict, quadratic: bool) -> list:
    r1, r5 = f["ret_1"], f["ret_5"]
    cols = [r1, r5]
    if quadratic:
        cols += [r1 * r1, r5 * r5, r1 * r5]
    return cols


def _fit_lstsq(rows: list, ys: np.ndarray, *, quadratic: bool, label: str) -> dict:
    X = np.array([_basis(r["features"], quadratic) for r in rows], dtype=float)
    mean, sd = X.mean(axis=0), X.std(axis=0)
    if np.any(sd <= 0) or not np.all(np.isfinite(sd)):
        raise ArmRefused("ZERO_VARIANCE_FEATURE: %s basis column has no fit-split variance" % label)
    Z = np.column_stack([np.ones(len(rows)), (X - mean) / sd])
    beta, _, rank, _ = np.linalg.lstsq(Z, ys, rcond=RCOND)
    if rank < Z.shape[1]:
        raise ArmRefused("RANK_DEFICIENT: %s design rank %d < %d at rcond=%g" % (label, rank, Z.shape[1], RCOND))
    if not np.all(np.isfinite(beta)):
        raise ArmRefused("NONFINITE_COEFFICIENTS: %s" % label)
    return {"beta": beta.tolist(), "mean": mean.tolist(), "sd": sd.tolist(),
            "quadratic": quadratic, "rank": int(rank), "solver": "numpy.linalg.lstsq(SVD)", "rcond": RCOND}


def _mean_of(spec: dict, f: dict) -> float:
    x = np.array(_basis(f, spec["quadratic"]), dtype=float)
    z = (x - np.array(spec["mean"])) / np.array(spec["sd"])
    b = np.array(spec["beta"])
    return float(b[0] + z @ b[1:])


def fit_arms(rows_y: list) -> dict:
    """rows_y: [(row, y, tk)] on the FIT split only. Exactly five fits."""
    rows = [r for r, _, _ in rows_y]
    ys = np.array([y for _, y, _ in rows_y], dtype=float)
    try:
        base = M01.fit(rows, ys.tolist())                 # registered M0/M1, untouched
    except ValueError as e:
        # the registered estimator's own refusal, surfaced under the same
        # named-refusal contract so no arm can fail silently or differently
        raise ArmRefused("REGISTERED_BASELINE_REFUSED: %s" % e) from e
    lin = _fit_lstsq(rows, ys, quadratic=False, label="L")
    quad = _fit_lstsq(rows, ys, quadratic=True, label="C")
    mu_L = np.array([_mean_of(lin, r["features"]) for r in rows])
    rv = np.array([r["features"]["rv_30"] for r in rows], dtype=float)
    z = (ys - mu_L) / rv
    t = T.fit_scale_nu(z)
    if t["nu_at_lower_bound"]:
        raise ArmRefused("NU_AT_LOWER_BOUND: nu*=%.4f at the declared lower bound %.1f; "
                         "refused by model-domain policy, not because the variance is undefined"
                         % (t["nu"], NU_BOUNDS[0]))
    params = {"base": base, "L": lin, "C": quad, "t": t, "n_train": len(rows_y),
              "fits_performed": 5}
    params["params_hash"] = hashlib.sha256(
        json.dumps({k: v for k, v in params.items() if k != "params_hash"},
                   sort_keys=True, default=float).encode()).hexdigest()[:16]
    return params


_TQ_CACHE: dict = {}


def _standard_quantiles(nu: float) -> dict:
    """t quantiles at scale 1, mean 0, computed ONCE per fitted nu. A forecast's
    quantiles are mu + scale * these; recomputing the bisection per row was the
    whole of the runtime."""
    key = round(nu, 12)
    if key not in _TQ_CACHE:
        _TQ_CACHE[key] = {s: T.ppf(float(s), 0.0, 1.0, nu) for s in QS}
    return _TQ_CACHE[key]


def _t_dist(mu: float, scale: float, nu: float) -> PredictiveDistribution:
    tq = _standard_quantiles(nu)
    q = {s: mu + scale * tq[s] for s in QS}
    p_up = 1.0 - T.cdf(0.0, mu, scale, nu)
    sd = T.implied_sd(scale, nu)
    return PredictiveDistribution(
        expected_return=mu, median_return=mu, quantiles=q,
        prob_return_gt_zero=p_up, prob_return_lt_zero=1.0 - p_up,
        predictive_intervals={"0.90": [q["0.05"], q["0.95"]]},
        total_uncertainty=sd, aleatoric_uncertainty=sd, epistemic_uncertainty=0.0)


def forecast(arm: str, params: dict, row: dict, *, input_id: str, input_hash: str,
             creation_time: float) -> WorldModelForecast:
    if arm not in ARMS:
        raise ValueError("UNKNOWN_ARM: %s" % arm)
    if arm == "M0":
        return M01.forecast(M0["id"], params["base"], row, input_id=input_id,
                            input_hash=input_hash, creation_time=creation_time)
    if arm == "M1":
        return M01.forecast(M1["id"], params["base"], row, input_id=input_id,
                            input_hash=input_hash, creation_time=creation_time)
    f = row["features"]
    if f is None:
        raise ValueError("NO_FEATURES")
    if row.get("assumed_available") is None:
        raise ValueError("NO_AVAILABILITY_CLOCK")
    mu = 0.0 if arm == "S" else _mean_of(params["L"] if arm == "L" else params["C"], f)
    s, nu = params["t"]["s"], params["t"]["nu"]
    scale = f["rv_30"] * s
    if not (scale > 0):
        raise ValueError("ZERO_SCALE: rv_30=%r" % f["rv_30"])
    fid = hashlib.sha256(("%s|%s|%s" % (arm, input_id, params["params_hash"])).encode()).hexdigest()[:24]
    return WorldModelForecast(
        forecast_id=fid, input_id=input_id, input_hash=input_hash,
        model_id="EXP002_%s" % arm, model_version=params["params_hash"],
        model_family="STUDENT_T", information_tier=FEATURE_SET_VERSION,
        creation_time=creation_time, known_from=row["assumed_available"],
        forecast_horizon=HORIZON, distribution=_t_dist(mu, scale, nu),
        calibration_metadata={"family": "STUDENT_T", "scale": scale, "nu": nu,
                              "sd": T.implied_sd(scale, nu), "shared_reference": "linear-mean residuals"},
        uncertainty_metadata={"arm": arm, "availability_basis": AVAILABILITY_BASIS,
                              "publication_time": "NOT_AVAILABLE",
                              "event_time": row["event_time"], "bar_complete": row["bar_complete"]})
