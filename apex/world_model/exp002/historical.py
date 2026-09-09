"""EXP-002 on admitted historical data, through the governed path.

Called by scripts/alpha_exp_real_execute.py with --experiment ALPHA-EXP-002.
It never decides admission: the route that admitted the files supplies the
session loader. It opens fit, development and observed only; evaluation and
reserve are never requested."""
from __future__ import annotations

import time

from apex.world_model.exp001b import bars as B
from apex.world_model.exp001b.run import _usable
from . import models as A
from .registration import (DEVELOPMENT_STATUS, EXPERIMENT_ID, FIT_BUDGET, OBSERVED_STATUS,
                           PERIODS, registration_hash)
from .run import evaluate

PERIOD_ROLES = {"fit": PERIODS["fit"], "development": PERIODS["development"],
                "observed": PERIODS["observed"]}
NEVER_OPENED = ("evaluation", "reserve")
STATUS = {
    "MATCHED_IMPROVEMENT": "SCIENTIFIC_COMPLETE",
    "NOT_SELECTED": "SCIENTIFIC_COMPLETE",
    "NOT_SELECTED_INFERENCE_DISAGREEMENT": "SCIENTIFIC_COMPLETE",
    "INVALID_NULL_CONTROL": "INVALID_INPUT_OR_FAILURE",
    "INVALID_INPUT": "INVALID_INPUT_OR_FAILURE",
    "INSUFFICIENT_EVIDENCE": "INVALID_INPUT_OR_FAILURE",
    "ADMISSION_REFUSED": "AUTHORIZATION_REFUSED",
}


def _rows_for(paths: list, session_loader) -> tuple:
    rows_all, refused = [], {"WARMUP": 0, "MISSING_FEATURE_BARS": 0, "MISSING_TARGET_BAR": 0, "EMBARGO": 0}
    for p in paths:
        s = session_loader(p)
        rows = B.observable_rows(s)
        tg = B.targets(s, rows)
        for r, (y, tk, why) in zip(rows, tg):
            if r["features"] is None:
                refused[r["why"].split(":")[0]] += 1
            elif y is None:
                refused[why.split(":")[0]] += 1
        for r, y, tk in _usable(rows, tg):
            r["session_id"] = s["session_date"]           # whole-session blocks for the bootstrap
            rows_all.append((r, y, tk))
    return rows_all, refused


def run(sessions_by_period: dict, *, ledger_dir, session_loader, seed: int = 7) -> dict:
    t0 = time.time()
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(),
           "period_roles": {k: list(v) for k, v in PERIOD_ROLES.items()},
           "development_status": DEVELOPMENT_STATUS, "observed_status": OBSERVED_STATUS,
           "never_opened": list(NEVER_OPENED), "stages": []}
    forbidden = [k for k in sessions_by_period if k in NEVER_OPENED]
    if forbidden:
        rec.update(status="INVALID_INPUT", why="sealed periods were offered: %s" % forbidden)
        return rec
    for k in ("fit", "development"):
        if not sessions_by_period.get(k):
            rec.update(status="INVALID_INPUT", why="no sessions for required period %r" % k)
            return rec

    def stage(name, **kw):
        rec["stages"].append({"stage": name, **kw})

    try:
        fit_rows, fit_ref = _rows_for(sessions_by_period["fit"], session_loader)
        stage("admission:fit", sessions=len(sessions_by_period["fit"]), usable_rows=len(fit_rows), refused_rows=fit_ref)
    except Exception as e:                                                   # noqa: BLE001
        kind = type(e).__name__
        rec.update(status="ADMISSION_REFUSED" if kind in ("SourceAdmissionRefused", "RealDataRefused") else "INVALID_INPUT",
                   refusal={"kind": kind, "detail": str(e)[:600]})
        return rec

    try:
        params = A.fit_arms(fit_rows)                        # exactly five fits, once
    except (A.ArmRefused, ValueError) as e:
        rec.update(status="INVALID_INPUT", refusal={"kind": type(e).__name__, "detail": str(e)[:400]})
        return rec
    fit_rows = None                                          # dead after the fit
    rec["fit"] = {"params_hash": params["params_hash"], "n_train": params["n_train"],
                  "fits_performed": params["fits_performed"],
                  "budget": FIT_BUDGET["market_data_fits"],
                  "within_budget": params["fits_performed"] <= FIT_BUDGET["market_data_fits"],
                  "t": {k: params["t"][k] for k in ("s", "nu", "iterations", "converged",
                                                    "nu_at_upper_bound", "nu_at_lower_bound")},
                  "base_k": params["base"]["k"], "L": params["L"], "C": params["C"]}
    stage("fit", status="READY", fits_performed=params["fits_performed"])

    try:
        dev_rows, dev_ref = _rows_for(sessions_by_period["development"], session_loader)
        stage("admission:development", sessions=len(sessions_by_period["development"]), usable_rows=len(dev_rows), refused_rows=dev_ref)
    except Exception as e:                                                   # noqa: BLE001
        rec.update(status="ADMISSION_REFUSED", refusal={"kind": type(e).__name__, "detail": str(e)[:600]})
        return rec
    dev = evaluate(params, dev_rows, seed=seed, tag="DEVELOPMENT_2019", ledger_dir=ledger_dir,
                   authority="SELECTION")
    dev_rows = None
    rec["development"] = dev
    stage("development", status=dev["status"], n=dev.get("n_dev"))

    obs_paths = sessions_by_period.get("observed") or []
    if obs_paths:
        try:
            obs_rows, obs_ref = _rows_for(obs_paths, session_loader)
            stage("admission:observed", sessions=len(obs_paths), usable_rows=len(obs_rows), refused_rows=obs_ref)
            obs = evaluate(params, obs_rows, seed=seed, tag="OBSERVED_2020_2021", ledger_dir=ledger_dir,
                           authority="NONE")                  # same fitted params; no fit; no authority
            obs_rows = None
            rec["observed"] = obs
            stage("observed", status=obs["status"], n=obs.get("n_dev"), authority="NONE")
        except Exception as e:                                               # noqa: BLE001
            rec["observed"] = {"status": "NOT_EVALUATED", "error": "%s: %s" % (type(e).__name__, str(e)[:300])}
    rec["status"] = dev["status"]                            # selection follows development only
    rec["fits_performed_total"] = params["fits_performed"]
    rec["economics"] = "NONE (distributional only)"
    rec["evaluation"] = "SEALED: never requested by this run"
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec
