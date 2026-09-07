"""M0 and M1 for EXP-001B. The estimators are EXP-001's (unchanged, imported);
what changes is the clock the forecast claims: known_from is the bar's
ASSUMED availability (its completion), never its open."""
from __future__ import annotations

import hashlib

from apex.world_model.exp001.models import _dist, fit  # noqa: F401  (reused, unchanged)
from apex.world_model.forecast import WorldModelForecast
from .registration import AVAILABILITY_BASIS, FEATURE_SET_VERSION, HORIZON, M0, M1


def forecast(model: str, params: dict, row: dict, *, input_id: str,
             input_hash: str, creation_time: float) -> WorldModelForecast:
    f = row["features"]
    if f is None:
        raise ValueError("NO_FEATURES: %s" % row["why"])
    if row.get("assumed_available") is None:
        raise ValueError("NO_AVAILABILITY_CLOCK: row carries no assumed_available")
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
        creation_time=creation_time, known_from=row["assumed_available"],
        forecast_horizon=HORIZON, distribution=_dist(mu, sigma),
        calibration_metadata={"sigma_law": M0["sigma"]},
        uncertainty_metadata={"mean_law": M0["mean"] if model == M0["id"] else M1["mean"],
                              "availability_basis": AVAILABILITY_BASIS,
                              "publication_time": "NOT_AVAILABLE",
                              "event_time": row["event_time"], "bar_complete": row["bar_complete"]})
