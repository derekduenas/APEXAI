#!/usr/bin/env python3
"""STRATEGIC-INTEGRATION-002 PRE-ADMISSION REPAIR -- reproduce the reviewer's
findings against the ACTUAL functions at the base commit, with disposable
fixtures only. Each finding ends REPRODUCED or REFUTED with the measured
evidence. Nothing here reads a real corpus row.

Run from a checkout of 566600dca8632cd5e3831ef20304c29ae725bb0a:
    PYTHONPATH=. python scripts/si002_reproduce_findings.py <out.json>
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.world_model import sources
from apex.world_model.exp001 import bars as B, models as M, run as R
from apex.world_model.exp001.registration import (EXPERIMENT_ID, PERIODS, SESSION_UTC,
                                                  EXECUTION_MODEL, registration_hash)
from apex.world_model.real_data import boundary, loader, manifest

REPO = Path(__file__).resolve().parents[1]
HEAD = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                      text=True).stdout.strip()
ATTR = {"exp001": "7f26e938f (ALPHA-EXP-001 first commit)",
        "si002": "566600dca (STRATEGIC-INTEGRATION-002)"}
findings = []


def rec(n, title, reproduced, evidence, introduced):
    findings.append({"finding": n, "title": title,
                     "status": "REPRODUCED" if reproduced else "REFUTED",
                     "evidence": evidence, "introduced_in": introduced})


def session_doc(day, *, start_utc="13:30", n=390, seed=1, signal=0.0, gap_after=None, gap_minutes=0):
    rng = random.Random(seed)
    t = datetime.fromisoformat("%sT%s:00+00:00" % (day, start_utc))
    px, bars, last, minute = 400.0, [], 0.0, 0
    for i in range(n):
        if gap_after is not None and i == gap_after:
            minute += gap_minutes
        r = signal * last + rng.gauss(0, 3e-4); last = r
        o = px * math.exp(rng.gauss(0, 5e-5))      # open != prior close, as in real prints
        px = px * math.exp(r)
        bars.append({"event_time_utc": (t + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "open": o, "high": max(o, px) * 1.0001, "low": min(o, px) * 0.9999,
                     "close": px, "volume": 1000})
        minute += 1
    return {"source": "alpaca_sip_raw_1m", "bars": bars}


def lab_root(tmp, docs: dict):
    root = tmp / "lab"; root.mkdir(parents=True)
    fx = {}
    for name, doc in docs.items():
        p = root / name; p.write_text(json.dumps(doc))
        fx[name] = {"source_class": "SYNTHETIC_FIXTURE", "sha256": sources.sha256_of(p), "generator": "repro"}
    (root / "_PROVENANCE.json").write_text(json.dumps({"fixtures": fx}))
    return root


AVAIL = {"event_time": {"kind": "PER_ROW", "latest": "2021-12-31"},
         "receipt_time": {"kind": "BULK", "at": "2026-08-29"},
         "publication_time": {"kind": "NOT_AVAILABLE"}, "revision_time": {"kind": "NOT_AVAILABLE"},
         "corporate_actions": "RAW_UNADJUSTED_EXPLICIT", "restricted_use": "HISTORICAL_RESEARCH_ONLY"}


def real_grant(tmp, docs: dict, *, code_commit):
    ds = tmp / "dataset" / "bars"; ds.mkdir(parents=True)
    for name, doc in docs.items():
        (ds / name).write_text(json.dumps(doc))
    man = manifest.build(ds, dataset_id="fixture/etf", source_families=["alpaca_sip_raw_1m"], availability=AVAIL)
    mpath = tmp / "manifest.json"; msha = manifest.write(man, mpath)
    key = tmp / "key"; key.write_bytes(os.urandom(32).hex().encode())
    aroot = tmp / "admissions"; aroot.mkdir()
    body = {"contract": boundary.REAL_DATA_CONTRACT, "decision": "ADMIT",
            "dataset": {"dataset_id": "fixture/etf", "root": str(ds), "manifest_path": str(mpath), "manifest_sha256": msha},
            "scope": {"source_families": ["alpaca_sip_raw_1m"], "fields": ["event_time_utc", "open", "high", "low", "close", "volume"],
                      "universe": ["SPY"], "temporal_range": {"start": "2016-01-04", "end": "2021-12-31"}},
            "availability": AVAIL,
            "purpose": {"research_purpose": "repro", "experiment_id": EXPERIMENT_ID, "registration_hash": registration_hash()},
            "code": {"commit": code_commit},
            "output": {"root": str(tmp / "out"), "authority_classification": "RESEARCH_HISTORICAL"},
            "provenance": {"decided_by": "repro-reviewer", "decided_utc": "2026-09-07T20:00:00Z", "review_reference": "R"}}
    doc = {**body, "binding": boundary.binding_for(body, key.read_bytes().strip())}
    p = aroot / "d.json"; p.write_text(json.dumps(doc))
    return p, key, aroot, ds


def main(out):
    tmp = Path(tempfile.mkdtemp(prefix="si002_repro_"))

    # ---- F1: loader known_from not honored by the forecast -------------
    p, key, aroot, ds = real_grant(tmp / "f1", {"SPY_2019-06-03.json": session_doc("2019-06-03", seed=1)},
                                   code_commit="ab" * 20)
    g = boundary.verify_decision(p, key_path=key, admission_root=aroot, permitted_roots=(tmp / "f1" / "dataset",),
                                 code_commit="ab" * 20)
    s = loader.load_session(ds / "SPY_2019-06-03.json", grant=g, symbol="SPY", session_date="2019-06-03")
    rows = B.observable_rows(s)
    params = {"k": 1.0, "a": 0.0, "b1": 0.0, "b5": 0.0, "n_train": 0, "params_hash": "x"}
    r = rows[40]
    fc = M.forecast(M.M0["id"], params, r, input_id="i", input_hash="h", creation_time=0.0)
    rec(1, "loader known_from is not honored by the forecast",
        fc.known_from == r["t"] and r["known_from"] == r["t"] + 60 and fc.known_from != r["known_from"],
        {"row_t_bar_open": r["t"], "loader_known_from": r["known_from"], "forecast_known_from": fc.known_from,
         "forecast_claims_availability_seconds_before_bar_complete": r["known_from"] - fc.known_from},
        ATTR["exp001"] + "; the loader convention was added in " + ATTR["si002"] + " and not threaded through")

    # ---- F2: outcome availability uses the target bar's OPEN clock ------
    tg = R._targets(rows)
    i = 40; j = i + 15
    y, tk = tg[i]
    rec(2, "outcome availability uses the wrong bar clock",
        tk == rows[j]["t"] and tk != rows[j]["t"] + 60,
        {"target_bar_open": rows[j]["t"], "outcome_known_time_used": tk, "target_bar_complete": rows[j]["t"] + 60,
         "note": "grader accepts because forecast.known_from is also the OPEN clock; both are early by one bar"},
        ATTR["exp001"])

    # ---- F3: fixed UTC session window vs winter session and early close -
    winter = session_doc("2019-01-15", start_utc="13:00", n=480, seed=2)   # 08:00-16:00 ET = 13:00-21:00Z
    early = session_doc("2019-11-29", start_utc="13:30", n=390, seed=3)    # early close 13:00 ET = 18:00Z; bars run to 20:00Z
    root = lab_root(tmp / "f3", {"SPY_2019-01-15.json": winter, "SPY_2019-11-29.json": early})
    sw = B.load_session(root / "SPY_2019-01-15.json", declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    se = B.load_session(root / "SPY_2019-11-29.json", declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    w_first = datetime.fromtimestamp(sw["rows"][0]["t"], timezone.utc).strftime("%H:%MZ")
    w_last = datetime.fromtimestamp(sw["rows"][-1]["t"], timezone.utc).strftime("%H:%MZ")
    e_last = datetime.fromtimestamp(se["rows"][-1]["t"], timezone.utc).strftime("%H:%MZ")
    rec(3, "fixed UTC session filtering mishandles winter sessions and early closes",
        w_first == "13:30Z" and w_last == "19:59Z" and e_last == "19:59Z",
        {"registration_SESSION_UTC": list(SESSION_UTC),
         "winter_2019-01-15": {"rows_kept": len(sw["rows"]), "first_kept": w_first, "last_kept": w_last,
                               "premarket_bars_included_08:30-09:30ET": 60, "regular_bars_dropped_15:00-16:00ET": 60},
         "early_close_2019-11-29": {"rows_kept": len(se["rows"]), "last_kept": e_last,
                                    "post_close_bars_included_13:00-15:00ET": 120}},
        ATTR["exp001"])

    # ---- F4: missing minutes change a row-count horizon's elapsed time --
    gap = session_doc("2019-06-04", seed=4, gap_after=100, gap_minutes=10)
    root = lab_root(tmp / "f4", {"SPY_2019-06-04.json": gap})
    sg = B.load_session(root / "SPY_2019-06-04.json", declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    rg = B.observable_rows(sg); tgg = R._targets(rg)
    i = 90; j = i + 15
    elapsed = (rg[j]["t"] - rg[i]["t"]) / 60
    rec(4, "missing minutes change a row-count horizon's elapsed duration",
        elapsed == 25.0,
        {"gap_minutes_inserted": 10, "row_i": i, "row_j": j, "elapsed_minutes_between_rows": elapsed,
         "registered_horizon_minutes": 15, "target_returned_for_row_i": tgg[i][0] is not None},
        ATTR["exp001"])

    # ---- F5: validation invokes economics (evaluation-only registration) -
    docs = {"SPY_%s.json" % d: session_doc(d, seed=k, signal=0.9)
            for k, d in enumerate(["2019-06-03", "2019-06-04", "2020-06-01", "2020-06-02"])}
    root = lab_root(tmp / "f5", docs)
    rr = R.run({"train": [str(root / "SPY_2019-06-03.json"), str(root / "SPY_2019-06-04.json")],
                "validation": [str(root / "SPY_2020-06-01.json"), str(root / "SPY_2020-06-02.json")],
                "evaluation": []}, ledger_dir=tmp / "f5" / "led", declared_class="SYNTHETIC_FIXTURE", fixture_root=root)
    val = rr.get("validation") or {}
    src = (REPO / "apex/world_model/exp001/run.py").read_text()
    rec(5, "validation invokes economics despite the evaluation-only registration",
        "economic" in val and "economic\": _economic(f1, rows_y)" in src.replace("'", '"'),
        {"run_status": rr["status"], "validation_keys": sorted(val.keys()),
         "validation_economic_status": val.get("economic", {}).get("status"),
         "registration_ECONOMIC_TEST": "On EVALUATION only, after the statistical stage"},
        ATTR["exp001"])

    # ---- F6: economics realised on close-to-close target, not next-bar open
    ys = R._targets(rows)
    i = 60
    y_close, _ = ys[i]
    nbo = math.log(rows[i + 16]["open"] / rows[i + 1]["open"])
    rec(6, "economic execution differs from the registered next-bar-open convention",
        "y if ex ==" in src and abs(y_close - nbo) > 0 and EXECUTION_MODEL.startswith("NEXT_BAR_OPEN"),
        {"registration_EXECUTION_MODEL": EXECUTION_MODEL,
         "implementation": "realised = (y if LONG else -y) - roundtrip, y = log(close[i+15]/close[i])",
         "row": i, "close_to_close": y_close, "next_bar_open_to_open": nbo, "difference": y_close - nbo},
        ATTR["exp001"])

    # ---- F7: certified_1R is a formula, not a certificate ---------------
    tree = ast.parse(src)
    imports = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    rec(7, "certified_1R is not certified maximum loss",
        '"certified_1R": stop + rt' in src and not any("risk_certificate" in m for m in imports),
        {"label_in_run.py": '"certified_1R": stop + rt  (stop = rv_30)',
         "risk_certificate_imported_by_run.py": any("risk_certificate" in m for m in imports),
         "law": "certification only by apex.organism.risk_certificate.certify; a stop is not a certified max loss"},
        ATTR["exp001"])

    # ---- F8: dirty source retains the accepted HEAD identity ------------
    target = REPO / "apex/world_model/exp001/models.py"
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"\n# DIRTY\n")
        dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", str(target)],
                               capture_output=True, text=True).stdout.strip()
        p, key, aroot, ds = real_grant(tmp / "f8", {"SPY_2019-06-03.json": session_doc("2019-06-03")}, code_commit=HEAD)
        ok = False
        try:
            g8 = boundary.verify_decision(p, key_path=key, admission_root=aroot,
                                          permitted_roots=(tmp / "f8" / "dataset",))   # real HEAD, no override
            ok = g8.code_commit == HEAD
        except boundary.RealDataRefused as e:
            ok = False; err = str(e)
    finally:
        target.write_bytes(original)
    rec(8, "dirty source can retain the accepted HEAD identity",
        ok and bool(dirty),
        {"git_status_while_dirty": dirty, "verify_decision_result": "GRANT with code_commit == HEAD" if ok else err},
        ATTR["si002"])

    # ---- F9: invalid experiment result -> process exit 0 ----------------
    import importlib.util
    spec = importlib.util.spec_from_file_location("x", REPO / "scripts/exp001_real_execute.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    p, key, aroot, ds = real_grant(tmp / "f9", {"SPY_2019-06-03.json": session_doc("2019-06-03")}, code_commit="cd" * 20)
    boundary.ADMISSION_ROOT = aroot; boundary.ADMISSION_KEY_PATH = key
    boundary.PERMITTED_HISTORICAL_ROOTS = (str(tmp / "f9" / "dataset"),)
    boundary.checkout_commit = lambda root=None: "cd" * 20
    mod.R.run = lambda *a, **k: {"experiment": EXPERIMENT_ID, "status": "INVALID_INPUT", "why": "forced"}
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc9 = mod.main(["--decision", str(p), "--execute", "--output-name", "r9"])
    rec(9, "an invalid experiment result can produce process exit 0", rc9 == 0,
        {"run_status_forced": "INVALID_INPUT", "process_exit_code": rc9}, ATTR["si002"])

    # ---- F10: reusing an output directory mixes or overwrites evidence --
    g10 = boundary.verify_decision(p, key_path=key, admission_root=aroot,
                                   permitted_roots=(tmp / "f9" / "dataset",), code_commit="cd" * 20)
    out1 = boundary.open_output(g10, "same")
    stamp1 = (out1 / "_AUTHORITY.json").read_bytes(); m1 = (out1 / "_AUTHORITY.json").stat().st_mtime_ns
    led = out1 / "forecasts_validation.jsonl"; led.write_text('{"kind":"prior_run"}\n')
    out2 = boundary.open_output(g10, "same")
    m2 = (out2 / "_AUTHORITY.json").stat().st_mtime_ns
    rec(10, "reusing an output directory mixes or overwrites evidence",
        out1 == out2 and m2 >= m1 and led.exists() and (out2 / "_AUTHORITY.json").read_bytes() == stamp1,
        {"second_open_output_same_dir": out1 == out2, "authority_stamp_rewritten": m2 > m1,
         "prior_forecast_ledger_still_present_for_append": led.exists(),
         "run_ledger_mode": "chain_append appends; result json is overwritten"}, ATTR["si002"])

    result = {"base_commit": HEAD, "produced_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "fixtures": "disposable, synthetic, under tempdir; no real corpus row read",
              "findings": findings,
              "summary": {"reproduced": sum(f["status"] == "REPRODUCED" for f in findings),
                          "refuted": sum(f["status"] == "REFUTED" for f in findings)}}
    Path(out).write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({f["finding"]: f["status"] for f in findings}))
    print(json.dumps(result["summary"]))


if __name__ == "__main__":
    main(sys.argv[1])
