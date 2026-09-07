"""ALPHA-EXP-001B research path:

  admitted sessions -> rows with explicit clocks -> sealed forecasts
  (persisted BEFORE outcomes, known_from = assumed availability) -> outcomes
  (known at the target bar's completion) -> sealed grading -> DM-HAC vs null
  -> N0 control.  VALIDATION IS DISTRIBUTIONAL ONLY.
  EVALUATION (only when separately unsealed) adds the economic stage under
  the registered NEXT_BAR_OPEN execution convention. No certification is
  produced here; a diagnostic normalisation is named as such.

Every stage may return a NAMED status. A status is a completed result.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.world_model import grader, inference
from apex.world_model.targets import OutcomeRecord
from . import bars as B, models as M
from .registration import (DM_THRESHOLD, EXECUTION_MODEL, EXPRESSIONS, HAC_LAG, HORIZON,
                           M0, M1, MIN_SAMPLES, MODELLED_SPREAD_BPS, EXPERIMENT_ID,
                           RISK_CERTIFICATION, registration_hash)

# Process-level meaning of each terminal status (the command maps these):
STATUS = {
    "READY": "SCIENTIFIC_COMPLETE", "NO_OPPORTUNITY": "SCIENTIFIC_COMPLETE",
    "NO_SIGNAL": "SCIENTIFIC_COMPLETE", "EVALUATION_NO_SIGNAL": "SCIENTIFIC_COMPLETE",
    "SEALED_EVALUATION_PENDING": "EVALUATION_SEALED",
    "ADMISSION_REFUSED": "AUTHORIZATION_REFUSED",
    "INVALID_INPUT": "INVALID_INPUT_OR_FAILURE", "INSUFFICIENT_EVIDENCE": "INVALID_INPUT_OR_FAILURE",
}


def _usable(rows, tg):
    return [(r, y, tk) for r, (y, tk, _) in zip(rows, tg) if r["features"] and y is not None]


def _n0_permute(ys: list, seed: int, block: int = 20) -> list:
    blocks = [ys[i:i + block] for i in range(0, len(ys), block)]
    idx = list(range(len(blocks)))
    random.Random(seed).shuffle(idx)
    return [y for k in idx for y in blocks[k]][:len(ys)]


def _hac_se(x: list, lag: int) -> float:
    n, m = len(x), sum(x) / len(x)
    g = [sum((x[i] - m) * (x[i + k] - m) for i in range(n - k)) / n for k in range(lag + 1)]
    lrv = g[0] + 2 * sum((1 - k / (lag + 1)) * g[k] for k in range(1, lag + 1))
    return math.sqrt(max(lrv, 1e-18) / n)


def economic_evaluation(fcs: list, rows_y: list, sessions_by_row: list) -> dict:
    """EVALUATION ONLY. Expression per forecast after the modelled spread,
    REALISED under the registered execution convention: entry at the next
    bar's open, exit at the open of the bar after the target bar."""
    half = MODELLED_SPREAD_BPS / 1e4
    rt = 2 * half
    per, not_exec = [], 0
    for fc, (r, y, _), sess in zip(fcs, rows_y, sessions_by_row):
        mu = fc.distribution.expected_return
        best, ex = 0.0, "CASH"
        if mu - rt > 0 and mu - rt > best:
            best, ex = mu - rt, "LONG_15M"
        if -mu - rt > 0 and -mu - rt > best:
            best, ex = -mu - rt, "SHORT_15M"
        legs = B.execution_legs(sess, r) if ex != "CASH" else {"executable": True}
        if ex != "CASH" and not legs["executable"]:
            not_exec += 1
            per.append({"expression": ex, "expected_after_cost": best, "executable": False,
                        "why": legs["why"]}); continue
        realised = 0.0
        if ex != "CASH":
            leg_ret = math.log(legs["exit_open"] / legs["entry_open"])
            realised = (leg_ret if ex == "LONG_15M" else -leg_ret) - rt
        per.append({"expression": ex, "expected_after_cost": best, "executable": True,
                    "realised_after_cost": realised,
                    "stop_distance_rv30_diagnostic": r["features"]["rv_30"],
                    "certified_1R": None, "certification": "NOT_CERTIFIED",
                    "execution": None if ex == "CASH" else
                    {"entry_time": legs["entry_time"], "exit_time": legs["exit_time"],
                     "decision_time": legs["decision_time"], "model": EXECUTION_MODEL}})
    active = [p for p in per if p["expression"] != "CASH" and p["executable"]]
    base = {"stage": "EVALUATION_ONLY", "execution_model": EXECUTION_MODEL,
            "n_forecasts": len(per), "n_active": len(active), "n_not_executable": not_exec,
            "spread_bps_roundtrip": 2 * MODELLED_SPREAD_BPS,
            "certification": RISK_CERTIFICATION, "expressions": sorted(set(EXPRESSIONS))}
    if not active:
        return {"status": "NO_OPPORTUNITY", "why": "no executable expression clears the modelled spread", **base}
    x = [p["realised_after_cost"] for p in active]
    m = sum(x) / len(x)
    se = _hac_se(x, HAC_LAG)
    return {"status": "READY" if (m > 0 and m / se > DM_THRESHOLD) else "NO_OPPORTUNITY",
            "mean_after_cost": m, "se_hac": se, "z_econ": m / se,
            "law": "dependence-aware SE (Bartlett, L=H-1); realised under NEXT_BAR_OPEN legs", **base}


def run(sessions_by_period: dict, *, ledger_dir, session_loader, seed: int = 7,
        evaluation_unsealed: bool = False) -> dict:
    """sessions_by_period: {"train": [paths], "validation": [paths], "evaluation": [paths]}.
    session_loader: callable(path) -> session (the route that ADMITTED the file
    supplies it; run() never decides admission). Refusals are results."""
    t0 = time.time()
    led = Path(ledger_dir)
    if not led.is_dir():
        raise FileNotFoundError("ledger_dir must be an existing run directory: %s" % led)
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(), "stages": [],
           "validation_is_distributional_only": True}

    def stage(name, **kw):
        rec["stages"].append({"stage": name, **kw})

    data, sess_of = {}, {}
    try:
        for period in ("train", "validation", "evaluation"):
            if period == "evaluation" and not evaluation_unsealed:
                stage("evaluation", status="SEALED", why="not opened by this run"); continue
            rows_all, sessions = [], []
            refused_rows = {"WARMUP": 0, "MISSING_FEATURE_BARS": 0, "MISSING_TARGET_BAR": 0, "EMBARGO": 0}
            for p in sessions_by_period.get(period, []):
                s = session_loader(p)
                rows = B.observable_rows(s)
                tg = B.targets(s, rows)
                for r, (y, tk, why) in zip(rows, tg):
                    if r["features"] is None:
                        refused_rows[r["why"].split(":")[0]] += 1
                    elif y is None:
                        refused_rows[why.split(":")[0]] += 1
                us = _usable(rows, tg)
                rows_all.extend(us); sessions.extend([s] * len(us))
            data[period], sess_of[period] = rows_all, sessions
            stage("admission:" + period, status="READY", sessions=len(sessions_by_period.get(period, [])),
                  usable_rows=len(rows_all), refused_rows=refused_rows)
    except Exception as e:                                                  # noqa: BLE001
        kind = type(e).__name__
        rec.update(status="ADMISSION_REFUSED" if kind in ("SourceAdmissionRefused", "RealDataRefused")
                   else "INVALID_INPUT", refusal={"kind": kind, "detail": str(e)[:600]})
        stage("admission", status=rec["status"], refusal=kind)
        rec["elapsed_s"] = round(time.time() - t0, 2)
        return rec

    tr = data["train"]
    if len(tr) < MIN_SAMPLES:
        rec.update(status="INSUFFICIENT_EVIDENCE", why="train has %d usable rows, need >= %d" % (len(tr), MIN_SAMPLES))
        return rec
    try:
        params = M.fit([r for r, _, _ in tr], [y for _, y, _ in tr])
    except ValueError as e:
        rec.update(status="INVALID_INPUT", why=str(e)); return rec
    stage("fit", status="READY", **{k: params[k] for k in ("n_train", "params_hash")})

    def evaluate(period: str, rows_y: list, tag: str) -> dict:
        if len(rows_y) < MIN_SAMPLES:
            return {"status": "INSUFFICIENT_EVIDENCE", "n": len(rows_y), "need": MIN_SAMPLES}
        now = time.time()
        f0, f1, sealed = [], [], []
        for r, y, tk in rows_y:
            iid = "%s|%s|%d" % (tag, r["event_time"], r["i"])
            ih = hashlib.sha256(json.dumps({k: r[k] for k in ("event_time", "features", "close")},
                                           sort_keys=True).encode()).hexdigest()[:16]
            a = M.forecast(M0["id"], params, r, input_id=iid, input_hash=ih, creation_time=now)
            b = M.forecast(M1["id"], params, r, input_id=iid, input_hash=ih, creation_time=now)
            f0.append(a); f1.append(b)
            sealed.append(chain_append(led / ("forecasts_%s.jsonl" % period),
                                       {"kind": "sealed_forecast", "period": period,
                                        "m0": a.sealed(), "m1": b.sealed()})["entry_hash"])
        g0, g1 = [], []
        for a, b, (r, y, tk) in zip(f0, f1, rows_y):
            oc = OutcomeRecord(world_id="corpus", world_hash=tag, subject="SPY", step=r["i"],
                               horizon=HORIZON, target_value=y, outcome_known_time=tk)
            g0.append(grader.grade(a, oc, grading_time=tk + 1.0))
            g1.append(grader.grade(b, oc, grading_time=tk + 1.0))
        dm = inference.dm_hac_rule(g1, g0)
        ys = [y for _, y, _ in rows_y]
        yp = _n0_permute(ys, seed)
        g0n, g1n = [], []
        for a, b, (r, _, tk), y in zip(f0, f1, rows_y, yp):
            oc = OutcomeRecord(world_id="corpus", world_hash=tag + "|N0", subject="SPY", step=r["i"],
                               horizon=HORIZON, target_value=y, outcome_known_time=tk)
            g0n.append(grader.grade(a, oc, grading_time=tk + 1.0))
            g1n.append(grader.grade(b, oc, grading_time=tk + 1.0))
        n0 = inference.dm_hac_rule(g1n, g0n)
        chain_append(led / "outcomes.jsonl", {"kind": "outcomes_attached", "period": period, "n": len(rows_y),
                                              "outcome_clock": "target bar_complete",
                                              "first_sealed": sealed[0], "last_sealed": sealed[-1]})
        return {"status": "READY", "n": len(rows_y), "dm": dm, "n0": n0,
                "n0_is_no_signal": n0.get("verdict") == "NO_SIGNAL", "_f1": f1}

    def public(d):
        return {k: v for k, v in d.items() if not k.startswith("_")}

    val = evaluate("validation", data["validation"], "VAL")
    stage("validation", **public(val))
    rec["validation"] = public(val)
    if val["status"] != "READY":
        rec.update(status=val["status"]); rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    if not val["n0_is_no_signal"]:
        rec.update(status="INVALID_INPUT", why="N0 null did NOT return NO_SIGNAL: harness broken")
        rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    if val["dm"].get("verdict") != "SIGNAL_DETECTED":
        rec.update(status="NO_SIGNAL", why="DM-HAC on validation did not exceed %.1f; evaluation stays sealed"
                   % DM_THRESHOLD)
        rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    if not evaluation_unsealed:
        rec.update(status="SEALED_EVALUATION_PENDING",
                   why="validation SIGNAL_DETECTED; evaluation remains SEALED until separately authorized")
        rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    ev = evaluate("evaluation", data["evaluation"], "EVAL")
    rec["evaluation"] = public(ev)
    if ev["status"] != "READY":
        rec["status"] = ev["status"]
    elif ev["dm"].get("verdict") != "SIGNAL_DETECTED":
        rec["status"] = "EVALUATION_NO_SIGNAL"
    else:
        # economics are computed ONLY here, on the sealed period, once, from
        # the SAME sealed M1 forecasts that were graded
        econ = economic_evaluation(ev["_f1"], data["evaluation"], sess_of["evaluation"])
        rec["evaluation"]["economic"] = econ
        rec["status"] = econ["status"]
    rec["elapsed_s"] = round(time.time() - t0, 2)
    chain_append(led / "attribution.jsonl", {"kind": "exp001b_result", "status": rec["status"],
                                             "registration_hash": rec["registration_hash"]})
    return rec
