"""EXP-002 on admitted historical data, through the governed path.

Called by scripts/alpha_exp_real_execute.py with --experiment ALPHA-EXP-002.
It never decides admission: the route that admitted the files supplies the
session loader. It opens fit, development and observed only; evaluation and
reserve are never requested.

Two records are kept apart on purpose:
  scientific_status  the development verdict (selection authority G1 only)
  status             whether the REQUESTED run completed; observed reporting
                     that was requested and did not happen makes the run
                     incomplete even when development produced a verdict."""
from __future__ import annotations

import json
import time
from pathlib import Path

from apex.world_model.exp001b import bars as B
from apex.world_model.exp001b.run import _usable
from . import models as A
from .registration import (DEVELOPMENT_STATUS, EXPERIMENT_ID, FIT_BUDGET, OBSERVED_STATUS,
                           PERIODS, registration_hash)
from .run import _admit, evaluate, reconstruct_forecast_hashes

PERIOD_ROLES = {"fit": PERIODS["fit"], "development": PERIODS["development"],
                "observed": PERIODS["observed"]}
NEVER_OPENED = ("evaluation", "reserve")
TAGS = {"development": "DEVELOPMENT_2019", "observed": "OBSERVED_2020_2021"}
SCIENTIFIC = ("MATCHED_IMPROVEMENT", "NOT_SELECTED", "NOT_SELECTED_INFERENCE_DISAGREEMENT")
ADMISSION_REFUSALS = ("SourceAdmissionRefused", "RealDataRefused")
STATUS = {
    "MATCHED_IMPROVEMENT": "SCIENTIFIC_COMPLETE",
    "NOT_SELECTED": "SCIENTIFIC_COMPLETE",
    "NOT_SELECTED_INFERENCE_DISAGREEMENT": "SCIENTIFIC_COMPLETE",
    "INVALID_NULL_CONTROL": "INVALID_INPUT_OR_FAILURE",
    "INVALID_INPUT": "INVALID_INPUT_OR_FAILURE",
    "INSUFFICIENT_EVIDENCE": "INVALID_INPUT_OR_FAILURE",
    "ADMISSION_REFUSED": "AUTHORIZATION_REFUSED",
    # requested observed reporting did not happen: development evidence is
    # preserved under scientific_status, but the run did not complete
    "INCOMPLETE_OBSERVED_ADMISSION_REFUSED": "AUTHORIZATION_REFUSED",
    "INCOMPLETE_OBSERVED_REPORTING": "INVALID_INPUT_OR_FAILURE",
}


def _rows_for(paths: list, session_loader) -> tuple:
    """Feature/target-usable rows, per session, with refusal counts. Volatility
    admission (RV_FLOOR) is applied afterwards by the SAME `_admit` the
    qualified tournament uses, so a below-floor row is refused for fitting
    exactly as it is refused for scoring."""
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


def _admitted_rows_for(paths: list, session_loader) -> tuple:
    usable, refused = _rows_for(paths, session_loader)
    admitted, rv_refused = _admit(usable)
    refused = {**refused, "RV_FLOOR": rv_refused}
    return admitted, refused, len(usable)


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
        fit_rows, fit_ref, fit_usable = _admitted_rows_for(sessions_by_period["fit"], session_loader)
        stage("admission:fit", sessions=len(sessions_by_period["fit"]), usable_rows=fit_usable,
              admitted_rows=len(fit_rows), refused_rows=fit_ref,
              rule="apex.world_model.exp002.run._admit (RV_FLOOR), the qualified tournament's admission")
    except Exception as e:                                                   # noqa: BLE001
        kind = type(e).__name__
        rec.update(status="ADMISSION_REFUSED" if kind in ADMISSION_REFUSALS else "INVALID_INPUT",
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
                  "base_k": params["base"]["k"], "L": params["L"], "C": params["C"],
                  # the EXACT fitted object every forecast was built from; a
                  # recorded forecast hash is reconstructible from this and the row
                  "params": json.loads(json.dumps(params, default=float))}
    stage("fit", status="READY", fits_performed=params["fits_performed"])

    try:
        dev_rows, dev_ref, dev_usable = _admitted_rows_for(sessions_by_period["development"], session_loader)
        stage("admission:development", sessions=len(sessions_by_period["development"]),
              usable_rows=dev_usable, admitted_rows=len(dev_rows), refused_rows=dev_ref)
    except Exception as e:                                                   # noqa: BLE001
        rec.update(status="ADMISSION_REFUSED", refusal={"kind": type(e).__name__, "detail": str(e)[:600]})
        return rec
    dev = evaluate(params, dev_rows, seed=seed, tag=TAGS["development"], ledger_dir=ledger_dir,
                   authority="SELECTION")
    dev_rows = None
    rec["development"] = dev
    rec["scientific_status"] = dev["status"]                 # selection follows development only
    stage("development", status=dev["status"], n=dev.get("n_dev"))

    obs_paths = sessions_by_period.get("observed") or []
    execution = {"observed_requested": bool(obs_paths), "observed_outcome": None, "failure": None}
    if obs_paths:
        try:
            obs_rows, obs_ref, obs_usable = _admitted_rows_for(obs_paths, session_loader)
            stage("admission:observed", sessions=len(obs_paths), usable_rows=obs_usable,
                  admitted_rows=len(obs_rows), refused_rows=obs_ref)
        except Exception as e:                                               # noqa: BLE001
            kind = type(e).__name__
            execution["failure"] = {"class": "ADMISSION_REFUSED" if kind in ADMISSION_REFUSALS else "EXCEPTION",
                                    "at": "admission:observed", "kind": kind, "detail": str(e)[:600]}
        else:
            try:
                obs = evaluate(params, obs_rows, seed=seed, tag=TAGS["observed"], ledger_dir=ledger_dir,
                               authority="NONE")              # same fitted params; no fit; no authority
                obs_rows = None
                rec["observed"] = obs
                stage("observed", status=obs["status"], n=obs.get("n_dev"), authority="NONE")
                if obs["status"] not in SCIENTIFIC:
                    execution["failure"] = {"class": "INVALID_RESULT", "at": "observed",
                                            "kind": obs["status"], "detail": obs.get("why", "")}
            except Exception as e:                                           # noqa: BLE001
                execution["failure"] = {"class": "EXCEPTION", "at": "observed",
                                        "kind": type(e).__name__, "detail": str(e)[:600]}
        if execution["failure"] is None:
            execution["observed_outcome"] = "REPORTED_WITHOUT_SELECTION_AUTHORITY"
        else:
            execution["observed_outcome"] = "NOT_REPORTED"
            rec.setdefault("observed", {})["status"] = "NOT_EVALUATED"
            rec["observed"]["failure"] = execution["failure"]
    execution["complete"] = execution["failure"] is None
    rec["execution"] = execution
    if execution["complete"]:
        rec["status"] = dev["status"]
    else:
        f = execution["failure"]
        rec["status"] = ("INCOMPLETE_OBSERVED_ADMISSION_REFUSED" if f["class"] == "ADMISSION_REFUSED"
                         else "INCOMPLETE_OBSERVED_REPORTING")
        rec["why"] = ("requested observed reporting did not happen (%s at %s: %s); the development "
                      "verdict %s is preserved under scientific_status but the run is not complete"
                      % (f["class"], f["at"], f["kind"], dev["status"]))
    rec["fits_performed_total"] = params["fits_performed"]
    rec["economics"] = "NONE (distributional only)"
    rec["evaluation"] = "SEALED: never requested by this run"
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec


def reconstruct(result: dict, sessions_by_period: dict, *, session_loader, ledger_dir,
                params: dict | None = None) -> dict:
    """Rebuild every recorded forecast hash from the SAVED artifacts (the sealed
    result's exact fitted params and per-period forecast creation time) plus
    freshly admitted rows, and compare against the sealed forecast-hash ledger.
    `params` overrides the saved object only for negative controls."""
    params = params if params is not None else (result.get("fit") or {}).get("params")
    # required periods are derived from the SAVED execution record, never from
    # what happens to be present: development always; observed if requested
    required = ["development"]
    if (result.get("execution") or {}).get("observed_requested"):
        required.append("observed")
    out = {"params_hash": params["params_hash"] if params else None, "required_periods": required,
           "verified_periods": [], "missing": [], "periods": {},
           "verifies": {"forecast_contents": "each admitted row's per-arm forecast hash, looked up by (event_time, i)",
                        "ledger_ordering": "reported separately as ledger_ordering_matches; not part of all_match",
                        "chain_integrity": "NOT VERIFIED here (entry/prev hash chain is not checked)"}}
    if params is None:
        out["missing"].append("fit.params")
    for period in required:
        tag = TAGS[period]
        per = result.get(period) or {}
        ledger = Path(ledger_dir) / ("forecast_hashes_%s.jsonl" % tag)
        absent = [k for k, ok in (("forecast_creation_time", "forecast_creation_time" in per),
                                  ("ledger", ledger.exists()), ("sessions", bool(sessions_by_period.get(period))))
                  if not ok]
        if params is None or absent:
            out["periods"][period] = {"status": "NOT_VERIFIED", "missing": absent}
            out["missing"].extend("%s.%s" % (period, a) for a in absent)
            continue
        rows, _, _ = _admitted_rows_for(sessions_by_period[period], session_loader)
        rep = reconstruct_forecast_hashes(params, rows, tag=tag, creation_time=per["forecast_creation_time"],
                                          ledger_path=ledger)
        rep["status"] = "VERIFIED" if rep["all_match"] else "MISMATCH"
        out["periods"][period] = rep
        if rep["all_match"]:
            out["verified_periods"].append(period)
    out["all_match"] = bool(required) and out["verified_periods"] == required
    out["ledger_ordering_matches"] = all(out["periods"][p].get("ledger_order_matches_admitted") is True
                                         for p in required) if out["all_match"] else False
    out["status"] = "VERIFIED" if out["all_match"] else "NOT_VERIFIED"
    return out
