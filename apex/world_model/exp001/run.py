"""The complete research path, in order, with the boundaries it crosses:

  admitted bars -> causal rows -> sealed forecasts (persisted BEFORE any
  outcome) -> outcomes -> sealed grading -> DM-HAC vs null -> N0 control ->
  economic stage -> attribution record.

Every stage may return a NAMED refusal. A refusal is a completed result.
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
from .registration import (DM_THRESHOLD, EMBARGO_BARS, EXPRESSIONS, HORIZON,
                           HORIZON_STEPS, M0, M1, MIN_SAMPLES,
                           MODELLED_SPREAD_BPS, registration_hash)

STATUS = ("READY", "NO_SIGNAL", "NO_OPPORTUNITY", "INSUFFICIENT_EVIDENCE",
          "INVALID_INPUT", "NOT_ESTIMABLE", "BLOCKED", "NOT_IMPLEMENTED")


def _targets(rows: list) -> list:
    """y_i = log(close[i+H]/close[i]); None where the future is not in the
    session. The outcome becomes KNOWN at bar i+H's close."""
    out = []
    for i, r in enumerate(rows):
        j = i + HORIZON_STEPS
        if j < len(rows):
            out.append((math.log(rows[j]["close"] / r["close"]), rows[j]["t"]))
        else:
            out.append((None, None))
    return out


def _usable(rows, tg):
    return [(r, y, tk) for r, (y, tk) in zip(rows, tg) if r["features"] and y is not None]


def _n0_permute(ys: list, seed: int, block: int = 20) -> list:
    """Destroy state->outcome association; keep block structure."""
    blocks = [ys[i:i + block] for i in range(0, len(ys), block)]
    idx = list(range(len(blocks)))
    random.Random(seed).shuffle(idx)
    out = [y for k in idx for y in blocks[k]]
    return out[:len(ys)]


def _economic(fcs: list, rows_y: list) -> dict:
    """Expression per forecast, after a declared spread; realised on the
    same bars. CASH when no expression clears the cost."""
    half = MODELLED_SPREAD_BPS / 1e4
    rt = 2 * half                                  # entry + exit crossing
    per = []
    for fc, (r, y, _) in zip(fcs, rows_y):
        mu = fc.distribution.expected_return
        sig = fc.distribution.total_uncertainty
        best, ex = 0.0, "CASH"
        if mu - rt > 0 and mu - rt > best:
            best, ex = mu - rt, "LONG_15M"
        if -mu - rt > 0 and -mu - rt > best:
            best, ex = -mu - rt, "SHORT_15M"
        realised = 0.0 if ex == "CASH" else ((y if ex == "LONG_15M" else -y) - rt)
        stop = max(r["features"]["rv_30"], 1e-9)
        per.append({"expression": ex, "expected_after_cost": best,
                    "realised_after_cost": realised, "certified_1R": stop + rt,
                    "cost_fraction_of_1R": rt / (stop + rt)})
    active = [p for p in per if p["expression"] != "CASH"]
    if not active:
        return {"status": "NO_OPPORTUNITY", "why": "no expression clears the modelled spread",
                "n_forecasts": len(per), "n_active": 0, "expressions": sorted(set(EXPRESSIONS))}
    x = [p["realised_after_cost"] for p in active]
    n, m = len(x), sum(x) / len(x)
    lag = HORIZON_STEPS - 1
    g = [sum((x[i] - m) * (x[i + k] - m) for i in range(n - k)) / n for k in range(lag + 1)]
    lrv = g[0] + 2 * sum((1 - k / (lag + 1)) * g[k] for k in range(1, lag + 1))
    se = math.sqrt(max(lrv, 1e-18) / n)
    return {"status": "READY" if (m > 0 and m / se > DM_THRESHOLD) else "NO_OPPORTUNITY",
            "n_forecasts": len(per), "n_active": n, "mean_after_cost": m,
            "se_hac": se, "z_econ": m / se, "spread_bps_roundtrip": 2 * MODELLED_SPREAD_BPS,
            "mean_cost_fraction_of_1R": sum(p["cost_fraction_of_1R"] for p in active) / n,
            "law": "dependence-aware SE (Bartlett, L=H-1); realised on the same bars as the forecast"}


def run(sessions_by_period: dict, *, ledger_dir, declared_class: str,
        fixture_root=None, seed: int = 7, evaluation_unsealed: bool = False) -> dict:
    """sessions_by_period: {"train": [paths], "validation": [paths], "evaluation": [paths]}.
    Returns a status record. Raises nothing on refusal: refusals are results."""
    t0 = time.time()
    led = Path(ledger_dir); led.mkdir(parents=True, exist_ok=True)
    rec = {"experiment": "ALPHA-EXP-001", "registration_hash": registration_hash(),
           "declared_class": declared_class, "stages": []}

    def stage(name, **kw):
        rec["stages"].append({"stage": name, **kw})

    # 1. admission + rows, per period, in order; the boundary decides
    data = {}
    try:
        for period in ("train", "validation", "evaluation"):
            if period == "evaluation" and not evaluation_unsealed:
                stage("evaluation", status="BLOCKED", why="SEALED: evaluation is not opened "
                      "until validation passes and the registration is frozen")
                continue
            rows_all = []
            for p in sessions_by_period.get(period, []):
                s = B.load_session(p, declared_class=declared_class, fixture_root=fixture_root)
                rows = B.observable_rows(s)
                tg = _targets(rows)
                # EMBARGO: drop the last EMBARGO_BARS targets of each session so no
                # target's future crosses into the next session's state
                tg = [(y, tk) if i + HORIZON_STEPS + EMBARGO_BARS <= len(rows) else (None, None)
                      for i, (y, tk) in enumerate(tg)]
                rows_all.extend(_usable(rows, tg))
            data[period] = rows_all
            stage("admission:" + period, status="READY", sessions=len(sessions_by_period.get(period, [])),
                  usable_rows=len(rows_all))
    except (B.BarsRefused, Exception) as e:                 # noqa: BLE001
        kind = type(e).__name__
        rec.update(status="BLOCKED" if kind == "SourceAdmissionRefused" else "INVALID_INPUT",
                   refusal={"kind": kind, "detail": str(e)[:600]})
        stage("admission", status=rec["status"], refusal=kind)
        rec["elapsed_s"] = round(time.time() - t0, 2)
        return rec

    # 2. fit on TRAIN only
    tr = data["train"]
    if len(tr) < MIN_SAMPLES:
        rec.update(status="INSUFFICIENT_EVIDENCE",
                   why="train has %d usable rows, need >= %d" % (len(tr), MIN_SAMPLES))
        return rec
    try:
        params = M.fit([r for r, _, _ in tr], [y for _, y, _ in tr])
    except ValueError as e:
        rec.update(status="INVALID_INPUT", why=str(e)); return rec
    stage("fit", status="READY", **{k: params[k] for k in ("n_train", "params_hash")})

    # 3. VALIDATION: seal forecasts BEFORE outcomes, then grade, then DM-HAC, then N0
    def evaluate(period: str, rows_y: list, tag: str) -> dict:
        if len(rows_y) < MIN_SAMPLES:
            return {"status": "INSUFFICIENT_EVIDENCE", "n": len(rows_y), "need": MIN_SAMPLES}
        now = time.time()
        f0, f1, sealed = [], [], []
        for r, y, tk in rows_y:
            iid = "%s|%s|%d" % (tag, r["t"], r["i"])
            ih = hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest()[:16]
            a = M.forecast(M0["id"], params, r, input_id=iid, input_hash=ih, creation_time=now)
            b = M.forecast(M1["id"], params, r, input_id=iid, input_hash=ih, creation_time=now)
            f0.append(a); f1.append(b)
            sealed.append(chain_append(led / ("forecasts_%s.jsonl" % period),
                                       {"kind": "sealed_forecast", "period": period,
                                        "m0": a.sealed(), "m1": b.sealed()})["entry_hash"])
        # outcomes are attached AFTER sealing, never merged
        g0, g1 = [], []
        for a, b, (r, y, tk) in zip(f0, f1, rows_y):
            oc = OutcomeRecord(world_id="corpus", world_hash=tag, subject="SPY",
                               step=r["i"], horizon=HORIZON, target_value=y,
                               outcome_known_time=tk)
            g0.append(grader.grade(a, oc, grading_time=tk + 1.0))
            g1.append(grader.grade(b, oc, grading_time=tk + 1.0))
        dm = inference.dm_hac_rule(g1, g0)
        # N0: permute outcomes across blocks, re-grade M1, must be NO_SIGNAL
        ys = [y for _, y, _ in rows_y]
        yp = _n0_permute(ys, seed)
        g1n, g0n = [], []
        for a, b, (r, _, tk), y in zip(f0, f1, rows_y, yp):
            oc = OutcomeRecord(world_id="corpus", world_hash=tag + "|N0", subject="SPY",
                               step=r["i"], horizon=HORIZON, target_value=y,
                               outcome_known_time=tk)
            g0n.append(grader.grade(a, oc, grading_time=tk + 1.0))
            g1n.append(grader.grade(b, oc, grading_time=tk + 1.0))
        n0 = inference.dm_hac_rule(g1n, g0n)
        for k in ("forecasts_%s.jsonl" % period,):
            chain_append(led / "outcomes.jsonl", {"kind": "outcomes_attached", "period": period,
                                                  "n": len(rows_y), "forecast_ledger": k,
                                                  "first_sealed": sealed[0], "last_sealed": sealed[-1]})
        return {"status": "READY", "n": len(rows_y), "dm": dm, "n0": n0,
                "n0_is_no_signal": n0.get("verdict") == "NO_SIGNAL",
                "economic": _economic(f1, rows_y)}

    val = evaluate("validation", data["validation"], "VAL")
    stage("validation", **{k: v for k, v in val.items() if k != "economic"})
    if val["status"] != "READY":
        rec.update(status=val["status"], validation=val); return rec
    if not val["n0_is_no_signal"]:
        rec.update(status="INVALID_INPUT", why="N0 null did NOT return NO_SIGNAL: harness broken",
                   validation=val); return rec
    if val["dm"].get("verdict") != "SIGNAL_DETECTED":
        rec.update(status="NO_SIGNAL", validation=val,
                   why="DM-HAC on validation did not exceed %.1f; evaluation stays sealed" % DM_THRESHOLD)
        rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    rec["validation"] = val
    if not evaluation_unsealed:
        rec.update(status="BLOCKED", why="validation SIGNAL_DETECTED; evaluation remains SEALED "
                   "until the registration is frozen and unsealing is authorized")
        rec["elapsed_s"] = round(time.time() - t0, 2); return rec
    ev = evaluate("evaluation", data["evaluation"], "EVAL")
    rec["evaluation"] = ev
    rec["status"] = (ev["economic"]["status"] if ev["status"] == "READY"
                     and ev["dm"].get("verdict") == "SIGNAL_DETECTED" else
                     ("NO_SIGNAL" if ev["status"] == "READY" else ev["status"]))
    rec["elapsed_s"] = round(time.time() - t0, 2)
    chain_append(led / "attribution.jsonl", {"kind": "exp001_result", "status": rec["status"],
                                             "registration_hash": rec["registration_hash"]})
    return rec
