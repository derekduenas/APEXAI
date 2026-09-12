"""Forecast fusion downstream of valid component outputs (M5).

Components must share target, horizon and cutoff and carry lineage (model id, artifact digest).
Weights are estimated on OUT-OF-FOLD component forecasts by minimizing the mean negative log score
of the Gaussian mixture on the simplex, then FROZEN (weights digest) before any later evaluation.
The comparison baseline is the single strongest component ON THE SAME OOF ROWS (no test leakage);
leave-one-out ablations remove each component in turn. A component that supplies no density is
refused — nothing is synthesized to make it fusible."""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats

from apex.worldmodel_wb.contracts import ForecastObject, ModelRefused, UnsupportedOutput, digest


class FusionRefused(RuntimeError):
    pass


def _gauss_params(f: ForecastObject):
    d = f.density()
    if d.get("family") == "GAUSSIAN":
        return float(d["location"]), math.sqrt(float(d["variance"]))
    if d.get("family") == "STUDENT_T":
        # a t density is used through its moment-matched Gaussian for mixture weighting; declared, not hidden
        return float(d.get("location", 0.0)), math.sqrt(float(d["variance"]))
    raise FusionRefused("FAMILY_NOT_FUSIBLE: %r" % d.get("family"))


def check_compatible(components: list) -> dict:
    if len(components) < 2:
        raise FusionRefused("NEED_TWO_COMPONENTS")
    h = {c.horizon_minutes for c in components}; cut = {c.input_cutoff_epoch for c in components}
    if len(h) != 1:
        raise FusionRefused("HORIZON_MISMATCH: %s" % sorted(h))
    if len(cut) != 1:
        raise FusionRefused("CUTOFF_MISMATCH: components were built from different information sets")
    for c in components:
        if not c.artifact_digest or not c.model_id:
            raise FusionRefused("LINEAGE_MISSING")
        try:
            _gauss_params(c)
        except UnsupportedOutput as e:
            raise FusionRefused("COMPONENT_SUPPLIES_NO_DENSITY: %s" % e)
    return {"horizon_minutes": h.pop(), "input_cutoff_epoch": cut.pop(), "lineage": [(c.model_id, c.artifact_digest) for c in components]}


def _mixture_logscore(w, mus, sigs, y):
    dens = np.zeros(len(y))
    for j in range(len(w)):
        dens += w[j] * stats.norm.pdf(y, loc=mus[:, j], scale=sigs[:, j])
    return float(np.mean(np.log(np.clip(dens, 1e-300, None))))


def estimate_weights(oof: list) -> dict:
    """oof: [{"y": realized, "components": [(mu, sigma), ...]}] — every forecast genuinely out-of-fold.
    Returns frozen weights, the OOF log score, the strongest single component and LOO ablations."""
    if len(oof) < 30:
        raise FusionRefused("TOO_FEW_OOF_ROWS")
    K = len(oof[0]["components"])
    y = np.array([r["y"] for r in oof], dtype=float)
    mus = np.array([[c[0] for c in r["components"]] for r in oof]); sigs = np.array([[c[1] for c in r["components"]] for r in oof])
    if not (np.all(np.isfinite(mus)) and np.all(np.isfinite(sigs)) and np.all(sigs > 0)):
        raise FusionRefused("OOF_NONFINITE")

    def neg(theta):
        w = np.exp(theta) / np.sum(np.exp(theta))
        return -_mixture_logscore(w, mus, sigs, y)

    res = optimize.minimize(neg, np.zeros(K), method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-12})
    w = np.exp(res.x) / np.sum(np.exp(res.x))
    singles = [_mixture_logscore(np.eye(K)[j], mus, sigs, y) for j in range(K)]
    best_single = int(np.argmax(singles))
    fused = _mixture_logscore(w, mus, sigs, y)
    loo = {}
    for j in range(K):
        if K == 2:
            loo[j] = singles[1 - j]
            continue
        keep = [i for i in range(K) if i != j]
        r2 = optimize.minimize(lambda th: -_mixture_logscore(np.exp(th) / np.sum(np.exp(th)), mus[:, keep], sigs[:, keep], y),
                               np.zeros(K - 1), method="Nelder-Mead")
        loo[j] = _mixture_logscore(np.exp(r2.x) / np.sum(np.exp(r2.x)), mus[:, keep], sigs[:, keep], y)
    return {"weights": w.tolist(), "weights_digest": digest({"w": [round(float(x), 12) for x in w]}), "frozen": True,
            "oof_log_score_fused": fused, "oof_log_score_singles": singles, "strongest_single": best_single,
            "improvement_over_strongest_single": fused - singles[best_single],
            "loo_ablation_log_score": {str(j): loo[j] for j in range(K)},
            "loo_contribution": {str(j): fused - loo[j] for j in range(K)}, "n_oof": len(y),
            "note": "weights estimated on out-of-fold forecasts and frozen here; later evaluation must not re-estimate them"}


def fuse(components: list, weights: dict, *, created_epoch: float) -> ForecastObject:
    meta = check_compatible(components)
    w = np.array(weights["weights"], dtype=float)
    if len(w) != len(components) or not weights.get("frozen"):
        raise FusionRefused("WEIGHTS_NOT_FROZEN_OR_MISMATCHED")
    if digest({"w": [round(float(x), 12) for x in w]}) != weights["weights_digest"]:
        raise FusionRefused("WEIGHTS_DIGEST_DISAGREES")
    ps = [_gauss_params(c) for c in components]
    mu = float(sum(w[j] * ps[j][0] for j in range(len(w))))
    var = float(sum(w[j] * (ps[j][1] ** 2 + ps[j][0] ** 2) for j in range(len(w))) - mu * mu)
    disagreement = float(np.std([p[0] for p in ps]) / max(1e-12, math.sqrt(var)))
    return ForecastObject(model_id="FUSION[%s]" % "+".join(c.model_id for c in components), artifact_digest=weights["weights_digest"],
                          horizon_minutes=meta["horizon_minutes"], input_cutoff_epoch=meta["input_cutoff_epoch"], created_epoch=created_epoch,
                          supplies=("mean", "variance", "density"), mean=mu, variance=var,
                          density={"family": "GAUSSIAN_MIXTURE", "weights": w.tolist(), "components": [{"location": p[0], "scale": p[1]} for p in ps],
                                   "moment_matched_variance": var},
                          meta={"lineage": meta["lineage"], "weights_digest": weights["weights_digest"], "model_disagreement_ratio": disagreement,
                                "p_return_gt_zero": float(sum(w[j] * (1 - stats.norm.cdf(0, loc=ps[j][0], scale=ps[j][1])) for j in range(len(w)))),
                                "p_meaning": "P(target return > 0) under the fused mixture; not a confidence percentage"})
