"""M0 and M1. Fitted on TRAIN rows only; the fit returns frozen parameters
and a forecaster that emits the laboratory's WorldModelForecast."""
from __future__ import annotations

import hashlib
import json
import math
from statistics import NormalDist

from apex.world_model.forecast import PredictiveDistribution, WorldModelForecast
from .registration import FEATURE_SET_VERSION, HORIZON, M0, M1

QS = ("0.05", "0.25", "0.5", "0.75", "0.95")
_N = NormalDist()


def _ols2(xs1, xs5, ys):
    """a + b1*x1 + b5*x5 by normal equations; refuses a singular design."""
    n = len(ys)
    X = [[1.0, a, b] for a, b in zip(xs1, xs5)]
    XtX = [[sum(X[i][r] * X[i][c] for i in range(n)) for c in range(3)] for r in range(3)]
    Xty = [sum(X[i][r] * ys[i] for i in range(n)) for r in range(3)]
    # 3x3 solve by Gaussian elimination
    A = [row[:] + [Xty[r]] for r, row in enumerate(XtX)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(A[r][c]))
        if abs(A[piv][c]) < 1e-18:
            raise ValueError("SINGULAR_DESIGN")
        A[c], A[piv] = A[piv], A[c]
        for r in range(3):
            if r != c:
                f = A[r][c] / A[c][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
    return [A[r][3] / A[r][r] for r in range(3)]


def fit(train_rows: list, targets: list) -> dict:
    """train_rows: observable rows with features; targets: aligned y."""
    pairs = [(r["features"], y) for r, y in zip(train_rows, targets) if r["features"]]
    if len(pairs) < 100:
        raise ValueError("INSUFFICIENT_TRAIN: %d usable rows" % len(pairs))
    rv = [f["rv_30"] for f, _ in pairs]
    ys = [y for _, y in pairs]
    k = (sum(abs(y) for y in ys) / len(ys)) / (sum(rv) / len(rv))
    a, b1, b5 = _ols2([f["ret_1"] for f, _ in pairs], [f["ret_5"] for f, _ in pairs], ys)
    params = {"k": k, "a": a, "b1": b1, "b5": b5, "n_train": len(pairs)}
    for v in params.values():
        if not math.isfinite(v):
            raise ValueError("NONFINITE_PARAM")
    params["params_hash"] = hashlib.sha256(
        json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    return params


def _dist(mu: float, sigma: float) -> PredictiveDistribution:
    q = {s: mu + sigma * _N.inv_cdf(float(s)) for s in QS}
    p_up = 1.0 - _N.cdf(-mu / sigma)
    return PredictiveDistribution(
        expected_return=mu, median_return=mu, quantiles=q,
        prob_return_gt_zero=p_up, prob_return_lt_zero=1.0 - p_up,
        predictive_intervals={"0.90": [q["0.05"], q["0.95"]]},
        total_uncertainty=sigma, aleatoric_uncertainty=sigma, epistemic_uncertainty=0.0)


def forecast(model: str, params: dict, row: dict, *, input_id: str,
             input_hash: str, creation_time: float) -> WorldModelForecast:
    f = row["features"]
    if f is None:
        raise ValueError("NO_FEATURES: %s" % row["why"])
    sigma = max(params["k"] * f["rv_30"], 1e-9)
    if model == M0["id"]:
        mu = 0.0
    elif model == M1["id"]:
        mu = params["a"] + params["b1"] * f["ret_1"] + params["b5"] * f["ret_5"]
    else:
        raise ValueError("UNKNOWN_MODEL: %s" % model)
    fid = hashlib.sha256(("%s|%s|%s" % (model, input_id, params["params_hash"])).encode()).hexdigest()[:24]
    return WorldModelForecast(
        forecast_id=fid, input_id=input_id, input_hash=input_hash,
        model_id=model, model_version=params["params_hash"],
        model_family="GAUSSIAN", information_tier=FEATURE_SET_VERSION,
        creation_time=creation_time, known_from=row["t"],
        forecast_horizon=HORIZON, distribution=_dist(mu, sigma),
        calibration_metadata={"sigma_law": M0["sigma"]},
        uncertainty_metadata={"mean_law": M0["mean"] if model == M0["id"] else M1["mean"]})
