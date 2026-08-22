#!/usr/bin/env python
"""LAYER 0 PRE-FLIGHT GATE -- run before premarket on a commissioning day.

Operator law (2026-08-21): for Monday's L0 PASS, DETECTION is not
enough -- the configuration must be VERIFIED before the session:

    AC POWER + SLEEP PREVENTED + LID/CLAMSHELL PLAN + SENTINEL
    + PROCESS SUPERVISION + DATA-PROGRESSION WATCHDOG

This gate checks everything checkable from userland and REFUSES
(exit 1, verdict NOT_READY) when any requirement fails. It cannot
verify the lid plan -- that line prints as OPERATOR_ATTESTATION_REQUIRED
and the operator's word is the evidence.

    .venv/bin/python scripts/l0_preflight.py

Writes results/commissioning/l0_preflight_<day>.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    checks: dict = {}

    # AC power
    batt = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                          text=True, timeout=5).stdout
    checks["ac_power"] = "AC Power" in batt

    # sleep prevention posture: caffeinate assertion present OR
    # system sleep disabled
    assertions = subprocess.run(["pmset", "-g", "assertions"],
                                capture_output=True, text=True,
                                timeout=5).stdout
    checks["idle_sleep_prevented"] = (
        "PreventUserIdleSystemSleep" in assertions
        and "caffeinate" in assertions)
    custom = subprocess.run(["pmset", "-g"], capture_output=True,
                            text=True, timeout=5).stdout
    checks["disablesleep_set"] = "SleepDisabled		1" in custom or \
        " disablesleep          1" in custom.lower()
    checks["sleep_prevention"] = (checks["idle_sleep_prevented"]
                                  or checks["disablesleep_set"])

    # sentinel alive and fresh
    hb = Path("results/host/host_heartbeat.json")
    fresh = False
    if hb.exists():
        try:
            beat = json.loads(hb.read_text())
            fresh = time.time() - beat.get("epoch", 0) < 60
        except (ValueError, OSError):
            pass
    checks["sentinel_alive"] = fresh

    # data-progression watchdog present in the sentinel source
    checks["data_progression_watchdog"] = (
        "_data_progression_check" in
        Path("scripts/host_sentinel.py").read_text())

    # process supervision: the launchd jobs that matter are loaded
    jobs = subprocess.run(["launchctl", "list"], capture_output=True,
                          text=True, timeout=10).stdout
    for job in ("com.apex.host-sentinel", "com.apex.alpaca-fabric"):
        checks[f"supervised:{job}"] = job in jobs

    # disk + clock
    import os
    st = os.statvfs("/")
    checks["disk_free_gb_ok"] = (st.f_bavail * st.f_frsize / 1e9) >= 3.0
    checks["tz_sane"] = time.strftime("%Z") in ("PDT", "PST", "EDT", "EST")

    checks["lid_clamshell_plan"] = "OPERATOR_ATTESTATION_REQUIRED"

    hard = [k for k, v in checks.items()
            if v is False and k not in ("idle_sleep_prevented",
                                        "disablesleep_set")]
    verdict = "READY" if not hard else "NOT_READY"
    rec = {"kind": "l0_preflight", "at": time.strftime("%Y-%m-%d %H:%M:%S%z"),
           "checks": checks, "failed": hard, "verdict": verdict,
           "decision_power": "NONE"}
    day = time.strftime("%Y-%m-%d")
    out = Path(f"results/commissioning/l0_preflight_{day}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    return 0 if verdict == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
