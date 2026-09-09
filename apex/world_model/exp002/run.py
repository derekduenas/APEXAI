"""EXP-002 tournament runner. Bounded memory by construction: no forecast or
grade object is retained; per-arm log-likelihoods are kept as float arrays.
Forecasts are recomputed for the null pass, which is exact because every arm
is a deterministic function of the row and creation_time is fixed per run."""
from __future__ import annotations

import hashlib
import json
import math
import random
import time

import numpy as np

from apex.world_model import inference
from apex.world_model.targets import OutcomeRecord
from . import models as A, scoring as SC
from .bootstrap import session_stationary_bootstrap
from .registration import (ARMS, BOOT_BLOCK_SESSIONS, BOOT_P_THRESHOLD, BOOT_RESAMPLES,
                           BOOT_SEED, BOOT_SENSITIVITY_SESSIONS, DM_THRESHOLD, EXPERIMENT_ID,
                           GATES, HORIZON, N0, REPORTED, RV_FLOOR, registration_hash)

PAIRS = {**GATES, **REPORTED}
MATCHED_FOR_NULL = (("C", "L"), ("L", "S"), ("M1", "M0"))


def _phi_sf(t: float) -> float:
    return 0.5 * math.erfc(t / math.sqrt(2.0))


def _hac(d: list) -> dict:
    s = inference.dm_hac_statistic(list(d))
    s["verdict"] = "SIGNAL_DETECTED" if (s["mean"] > 0 and s["t"] > DM_THRESHOLD) else "NO_SIGNAL"
    s["p_one_sided"] = _phi_sf(s["t"])
    return s


def _holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def _admit(rows_y: list) -> tuple:
    keep, refused = [], 0
    for r, y, tk in rows_y:
        if r["features"] is None or not (r["features"]["rv_30"] >= RV_FLOOR):
            refused += 1
            continue
        keep.append((r, y, tk))
    return keep, refused


def _block_permute(ys: list, seed: int, block: int) -> list:
    blocks = [ys[i:i + block] for i in range(0, len(ys), block)]
    idx = list(range(len(blocks)))
    random.Random(seed).shuffle(idx)
    return [y for k in idx for y in blocks[k]][:len(ys)]


def tournament(fit_rows_y: list, dev_rows_y: list, *, seed: int = 7, tag: str = "DEV",
               bootstrap_resamples: int = BOOT_RESAMPLES) -> dict:
    t0 = time.time()
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(), "tag": tag,
           "stages": []}
    fit_rows, fit_refused = _admit(fit_rows_y)
    dev_rows, dev_refused = _admit(dev_rows_y)
    rec["admission"] = {"fit_rows": len(fit_rows), "fit_refused_rv_floor": fit_refused,
                        "dev_rows": len(dev_rows), "dev_refused_rv_floor": dev_refused}
    try:
        params = A.fit_arms(fit_rows)
    except (A.ArmRefused, ValueError) as e:
        rec.update(status="INVALID_INPUT", refusal={"kind": type(e).__name__, "detail": str(e)[:400]})
        rec["elapsed_s"] = round(time.time() - t0, 2)
        return rec
    rec["fit"] = {"params_hash": params["params_hash"], "n_train": params["n_train"],
                  "fits_performed": params["fits_performed"],
                  "t": {k: params["t"][k] for k in ("s", "nu", "iterations", "converged",
                                                    "nu_at_upper_bound", "nu_at_lower_bound")},
                  "base_k": params["base"]["k"], "L_rank": params["L"]["rank"], "C_rank": params["C"]["rank"]}

    now = time.time()
    n = len(dev_rows)
    ll = {a: np.empty(n) for a in ARMS}
    pit = {a: np.empty(n) for a in ARMS}
    cov = {a: {"0.05": 0.0, "0.5": 0.0, "0.95": 0.0} for a in ARMS}
    sessions, outcome_hashes = [], []

    def make_pair(r, y, tk):
        iid = "%s|%s|%d" % (tag, r["event_time"], r["i"])
        ih = hashlib.sha256(json.dumps({k: r[k] for k in ("event_time", "features", "close")},
                                       sort_keys=True).encode()).hexdigest()[:16]
        oc = OutcomeRecord(world_id="corpus", world_hash=tag, subject="SPY", step=r["i"],
                           horizon=HORIZON, target_value=y, outcome_known_time=tk)
        return iid, ih, oc

    for i, (r, y, tk) in enumerate(dev_rows):
        iid, ih, oc = make_pair(r, y, tk)
        sessions.append(r.get("session_id", "S?"))
        outcome_hashes.append(oc.outcome_hash)
        for a in ARMS:
            fc = A.forecast(a, params, r, input_id=iid, input_hash=ih, creation_time=now)
            g = SC.grade_any(fc, oc, grading_time=tk + 1.0)
            assert g.outcome_hash == oc.outcome_hash
            ll[a][i] = g.metrics["log_likelihood"]
            pit[a][i] = SC.pit(fc, y)
            for lv, hit in SC.coverage_hits(fc, y).items():
                cov[a][lv] += hit
    rec["stages"].append({"stage": "forecast_and_grade", "rows": n, "arms": list(ARMS)})

    comparisons = {}
    for name, (a, b) in PAIRS.items():
        d = (ll[a] - ll[b]).tolist()
        hac = _hac(d)
        boots = {str(L): session_stationary_bootstrap(d, sessions, expected_block_sessions=L,
                                                       n_resamples=bootstrap_resamples,
                                                       seed=BOOT_SEED, threshold=BOOT_P_THRESHOLD)
                 for L in (BOOT_BLOCK_SESSIONS, *BOOT_SENSITIVITY_SESSIONS)}
        primary_boot = boots[str(BOOT_BLOCK_SESSIONS)]
        hac_pass = hac["verdict"] == "SIGNAL_DETECTED"
        boot_pass = primary_boot["pass"]
        comparisons[name] = {
            "pair": [a, b], "hac": hac, "bootstrap": boots,
            "hac_pass": hac_pass, "boot5_pass": boot_pass,
            "both_pass": hac_pass and boot_pass,
            "inference_disagreement": hac_pass != boot_pass,
            "sensitivity_disagreement": any(boots[str(L)]["pass"] != boot_pass
                                            for L in BOOT_SENSITIVITY_SESSIONS)}
    holm = _holm({k: comparisons[k]["hac"]["p_one_sided"] for k in REPORTED})
    for k in REPORTED:
        comparisons[k]["holm_adjusted_p"] = holm[k]
        comparisons[k]["promotion_authority"] = False
    for k in GATES:
        comparisons[k]["promotion_authority"] = True

    # null: outcomes permuted in blocks; forecasts recomputed identically (not refitted)
    yp = _block_permute([y for _, y, _ in dev_rows], seed, N0["block"])
    null_ll = {a: np.empty(n) for a in ("C", "L", "S", "M1", "M0")}
    for i, ((r, _, tk), y) in enumerate(zip(dev_rows, yp)):
        iid, ih, _ = make_pair(r, y, tk)
        oc = OutcomeRecord(world_id="corpus", world_hash=tag + "|N0", subject="SPY", step=r["i"],
                           horizon=HORIZON, target_value=y, outcome_known_time=tk)
        for a in null_ll:
            fc = A.forecast(a, params, r, input_id=iid, input_hash=ih, creation_time=now)
            null_ll[a][i] = SC.grade_any(fc, oc, grading_time=tk + 1.0).metrics["log_likelihood"]
    null = {}
    for a, b in MATCHED_FOR_NULL:
        h = _hac((null_ll[a] - null_ll[b]).tolist())
        null["%s-%s" % (a, b)] = {"verdict": h["verdict"], "t": h["t"], "mean": h["mean"],
                                  "required": "NO_SIGNAL", "ok": h["verdict"] == "NO_SIGNAL"}
    null["S-M0_reported_only"] = _hac((null_ll["S"] - null_ll["M0"]).tolist())["t"]
    null_ok = all(v["ok"] for k, v in null.items() if isinstance(v, dict))

    calibration = {a: {"pit_mean": float(pit[a].mean()), "pit_sd": float(pit[a].std()),
                       "pit_hist10": np.histogram(pit[a], bins=10, range=(0, 1))[0].tolist(),
                       "coverage": {lv: cov[a][lv] / n for lv in cov[a]},
                       "coverage_nominal": {"0.05": 0.05, "0.5": 0.5, "0.95": 0.95}}
                   for a in ARMS}

    g1 = comparisons["G1"]
    if not null_ok:
        verdict = "INVALID_NULL_CONTROL"
    elif g1["inference_disagreement"]:
        verdict = "NOT_SELECTED_INFERENCE_DISAGREEMENT"
    elif not g1["both_pass"]:
        verdict = "NOT_SELECTED"
    else:
        verdict = "MATCHED_IMPROVEMENT"
    rec.update(status=verdict, matched_improvement=bool(g1["both_pass"]),
               selection_authority="G1 (C-L) only; comparisons against the registered Gaussian "
                                   "models are reported context without selection authority",
               comparisons=comparisons, null_control=null, null_control_ok=null_ok,
               calibration=calibration, n_dev=n,
               economics="NONE (distributional only)")
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec
