"""ACCELERATED CLOCK + CHAOS TEST — prove orchestration before the open.

Do not wait for Wednesday to discover a scheduling error. This drives
the orchestrator through a compressed exchange day (and a half-day,
and a holiday), kills things on purpose, and checks that the machine
recovers the way the laws say it must.

It touches no market logic and places no orders. It is a test of
whether APEX SHOWS UP.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.ops.orchestrator import (ArmCheck, default_roster,   # noqa: E402
                                   evaluate_arm, missed_start_verdict,
                                   phase_at, reconcile_expected,
                                   session_bounds)
from apex.ops.outbox import (Cursor, consume, consumer_health,  # noqa: E402
                             emit)
from apex.ops.release_gate import build_manifest, preopen_gate  # noqa: E402


def U(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def run() -> dict:
    results, failures = [], []

    def check(name, ok, detail=""):
        results.append({"check": name, "ok": bool(ok),
                        "detail": detail})
        if not ok:
            failures.append(name)

    specs = default_roster("cloud")

    # ---------- 1. accelerated normal day
    session = "2026-08-26"
    b = session_bounds(session)
    walk = []
    t = b["open_utc"] - timedelta(hours=2)
    while t < b["close_utc"] + timedelta(hours=2):
        walk.append((t, phase_at(t, session)["phase"]))
        t += timedelta(minutes=5)
    phases = [p for _t, p in walk]
    ordered = []
    for p in phases:
        if not ordered or ordered[-1] != p:
            ordered.append(p)
    check("accelerated day walks IDLE->PREOPEN->ARMED->RTH->POST->IDLE",
          ordered == ["IDLE", "PREOPEN", "SESSION_ARMED", "RTH",
                      "POST_CLOSE", "IDLE"], str(ordered))
    check("SESSION_ARMED occurs before the open",
          any(p == "SESSION_ARMED" and tt < b["open_utc"]
              for tt, p in walk), "armed strictly pre-open")

    # ---------- 2. half-day closes early
    hb = session_bounds("2026-11-27")
    fb = session_bounds("2026-11-30")
    check("half-day closes earlier than a full day",
          hb["close_utc"].hour < fb["close_utc"].hour,
          f"{hb['close_utc']} vs {fb['close_utc']}")
    check("half-day RTH has ended by the full-day close",
          phase_at(fb["close_utc"].replace(day=27, month=11),
                   "2026-11-27")["phase"] != "RTH",
          "no paper trading into a closed market")

    # ---------- 3. holiday never arms
    hol = [phase_at(U(f"2026-11-26T{h:02d}:00:00"), "2026-11-26")
           ["phase"] for h in range(24)]
    check("holiday never launches paper trading",
          set(hol) == {"IDLE"}, str(set(hol)))

    # ---------- 4. first-work sentinel
    grace = missed_start_verdict(
        service="options-paper", phase="RTH",
        expected_lifecycle="EXPECTED_RUNNING", first_work_seen=False,
        seconds_since_phase_start=60, deadline_s=600,
        recovery_attempts=[], dependency_states={}, release="test")
    fired = missed_start_verdict(
        service="options-paper", phase="RTH",
        expected_lifecycle="EXPECTED_RUNNING", first_work_seen=False,
        seconds_since_phase_start=700, deadline_s=600,
        recovery_attempts=[{"outcome": "FAILED"}],
        dependency_states={"theta-terminal": "MISSING"},
        release="test")
    check("first-work sentinel waits its grace",
          grace["verdict"] == "WITHIN_GRACE", grace["verdict"])
    check("first-work sentinel escalates SESSION_MISSED_START",
          fired["verdict"] == "SESSION_MISSED_START"
          and fired["severity"] == "CRITICAL", fired["verdict"])

    # ---------- 5. CHAOS: kill options-paper mid-session
    obs = {s.name: True for s in specs}
    obs["options-paper"] = False
    rec = reconcile_expected(phase="RTH", specs=specs,
                             observed_running=obs)
    check("killing options-paper in RTH raises CRITICAL",
          rec["verdict"] == "CRITICAL"
          and "options-paper" in rec["missing"], str(rec["missing"]))
    obs["options-paper"] = True
    rec2 = reconcile_expected(phase="RTH", specs=specs,
                              observed_running=obs)
    check("bounded recovery returns the roster to OK",
          rec2["verdict"] == "OK", rec2["verdict"])

    # ---------- 6. CHAOS: a service running when it should be idle
    idle_obs = {s.name: False for s in specs}
    idle_obs["options-paper"] = True
    rec3 = reconcile_expected(phase="IDLE", specs=specs,
                              observed_running=idle_obs)
    check("a service running while EXPECTED_IDLE is CRITICAL",
          "options-paper" in rec3["unexpectedly_running"],
          str(rec3["unexpectedly_running"]))

    # ---------- 7. CHAOS: EdgeForge outage then catch-up
    tmp = Path(tempfile.mkdtemp())
    ob = tmp / "outbox.jsonl"
    cur = Cursor(path=tmp / "cursor.json", consumer="edgeforge")
    for i in range(30):
        emit(ob, kind="boundary_map", session=session,
             payload={"i": i}, source="v1.geometry", known_from="t")
    seen = []
    consume(ob, cur, lambda r: seen.append(r["payload"]["i"]) or 1)
    for i in range(30, 95):                     # 30-minute "outage"
        emit(ob, kind="boundary_map", session=session,
             payload={"i": i}, source="v1.geometry", known_from="t")
    stalled = consumer_health(ob, cur, session_active=True)
    check("a stalled consumer during a session is CRITICAL",
          stalled["state"] == "EDGEFORGE_CONSUMER_STALLED",
          f"lag {stalled['consumer_lag']}")
    drain = consume(ob, cur, lambda r: seen.append(r["payload"]["i"])
                    or 1)
    check("EdgeForge catches up after a simulated outage",
          drain["records_processed"] == 65, str(drain[
              "records_processed"]))
    check("no observation skipped or duplicated after catch-up",
          seen == list(range(95)), f"{len(seen)} records")

    # ---------- 8. CHAOS: crash between read and commit -> redelivery
    tmp2 = Path(tempfile.mkdtemp())
    ob2 = tmp2 / "o.jsonl"
    cur2 = Cursor(path=tmp2 / "c.json", consumer="edgeforge")
    for i in range(6):
        emit(ob2, kind="k", session=session, payload={"i": i},
             source="v1", known_from="t")

    def crash(r):
        if r["payload"]["i"] == 3:
            raise RuntimeError("simulated consumer crash")
        return 1

    d1 = consume(ob2, cur2, crash)
    d2 = consume(ob2, cur2, lambda r: 1)
    check("a crashed record is redelivered, never skipped",
          d1["records_processed"] == 3 and d2["records_processed"] == 3,
          f"{d1['records_processed']}+{d2['records_processed']}")

    # ---------- 9. release/dev separation
    rel = tmp / "9f9868b1c"
    rel.mkdir(parents=True, exist_ok=True)
    (rel / "RELEASE_MANIFEST.json").write_text(json.dumps(
        build_manifest(release_sha="9f9868b1c", suite_result="PASS",
                       suite_passed=2922, suite_artifact_hash="h",
                       environment_fingerprint="e",
                       approved_by="operator")))
    g = preopen_gate(active_release_path=rel,
                     canonical_shas=("9f9868b1c",),
                     dev_tree_dirty=True, dev_head_sha="dirty123")
    check("a dirty dev tree does NOT block the preopen gate",
          g["verdict"] == "GATE_PASS", g["verdict"])
    g2 = preopen_gate(active_release_path=tmp / "missing",
                      canonical_shas=(), dev_tree_dirty=False)
    check("a release without a manifest DOES block",
          g2["verdict"] == "GATE_BLOCKED", str(g2["blocking"]))

    # ---------- 10. arming refuses on a failed dependency
    arm = evaluate_arm(session=session, now_utc=b["open_utc"] -
                       timedelta(minutes=3), checks=[
        ArmCheck("theta-terminal alive", False, "not started"),
        ArmCheck("dev tree clean", False, "dirty", required=False)])
    check("arming refuses when a required dependency is down",
          arm["verdict"] == "ARM_REFUSED"
          and arm["non_blocking_failures"] == ["dev tree clean"],
          str(arm["blocking"]))

    return {"kind": "apex_clock_chaos_test",
            "checks": results,
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "failures": failures,
            "verdict": "PASS" if not failures else "FAIL"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = run()
    if a.json:
        print(json.dumps(r, indent=1, default=str))
    else:
        for c in r["checks"]:
            print(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['check']}"
                  f"{'  -- ' + c['detail'] if c['detail'] else ''}")
        print(f"\nverdict: {r['verdict']}  "
              f"({r['passed']}/{len(r['checks'])})")
    return 0 if r["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
