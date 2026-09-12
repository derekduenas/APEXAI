"""Read-only telemetry capture for the EXP-004 experiment unit.

The wrapper launches the experiment in a transient systemd unit created with
--collect, so the unit and its accounting disappear the moment it exits. This
watcher therefore RETAINS observations as they arrive: it discovers the unit,
records its invocation identity and cgroup path, and appends raw counters with
sampling times for as long as the unit exists. Anything it could not observe is
reported as unknown rather than reconstructed afterwards.

It reads only: systemctl show, and the unit's cgroup files. It never writes to
the experiment, its output directory, or the unit.

Run: python3 scripts/exp004_run_telemetry.py <out.json> [max_seconds]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SLICE = "wmresearch.slice"
MATCH = "alpha_exp_real_execute.py"
NEEDLE = "ALPHA-EXP-004"
INTERVAL = 1.0


def sh(*a) -> str:
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()


def find_unit() -> str | None:
    out = sh("systemctl", "list-units", "--all", "--no-legend", "--plain", "run-*.service")
    for line in out.splitlines():
        name = line.split()[0] if line.split() else ""
        if not name.startswith("run-"):
            continue
        props = sh("systemctl", "show", name, "-p", "ExecStart", "-p", "Slice")
        if MATCH in props and NEEDLE in props and SLICE in props:
            return name
    return None


def read(p: Path, name: str):
    try:
        return (p / name).read_text().strip()
    except Exception:                                                    # noqa: BLE001
        return None


def main(out_path: str, max_seconds: int = 5400) -> int:
    t0 = time.time()
    rec = {"watcher": "EXP004_RUN_TELEMETRY", "read_only": True, "interval_s": INTERVAL,
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "unit": None, "unit_properties": None, "cgroup": None, "samples": [],
           "unavailable": [], "notes": []}

    unit = None
    while time.time() - t0 < max_seconds and unit is None:
        unit = find_unit()
        if unit is None:
            time.sleep(0.5)
    if unit is None:
        rec["unavailable"].append("unit never observed within the watch window")
        Path(out_path).write_text(json.dumps(rec, indent=1, default=str) + "\n")
        print(json.dumps({"unit": None, "note": "not observed"}))
        return 0

    rec["unit"] = unit
    props = {}
    for k in ("InvocationID", "ExecMainStartTimestamp", "ExecMainPID", "ControlGroup", "Slice",
              "MemoryMax", "TasksMax", "User", "Group", "PrivateNetwork", "ProtectSystem"):
        v = sh("systemctl", "show", unit, "-p", k)
        props[k] = v.split("=", 1)[1] if "=" in v else None
    rec["unit_properties"] = props
    cg = Path("/sys/fs/cgroup") / (props.get("ControlGroup") or "").lstrip("/")
    rec["cgroup"] = {"path": str(cg), "exists_at_discovery": cg.exists()}
    if not cg.exists():
        rec["unavailable"].append("cgroup path not readable at discovery")

    seen_gone = 0
    while time.time() - t0 < max_seconds:
        active = sh("systemctl", "is-active", unit)
        s = {"t": round(time.time() - t0, 2), "utc": time.strftime("%H:%M:%S", time.gmtime()), "active": active}
        if cg.exists():
            s.update({"memory_current": read(cg, "memory.current"),
                      "memory_peak": read(cg, "memory.peak"),
                      "memory_max": read(cg, "memory.max"),
                      "memory_events": read(cg, "memory.events"),
                      "pids_current": read(cg, "pids.current"),
                      "cpu_stat_usage_usec": (read(cg, "cpu.stat") or "").split("\n")[0]})
        else:
            s["cgroup_gone"] = True
        rec["samples"].append(s)
        if active != "active":
            seen_gone += 1
            if seen_gone >= 3:
                break
        time.sleep(INTERVAL)

    live = [s for s in rec["samples"] if s.get("memory_current", "").isdigit()]
    rec["summary"] = {
        "samples_total": len(rec["samples"]),
        "samples_with_counters": len(live),
        "observed_max_memory_current_bytes": max((int(s["memory_current"]) for s in live), default=None),
        "last_observed_memory_peak_bytes": next((int(s["memory_peak"]) for s in reversed(live)
                                                 if s.get("memory_peak", "").isdigit()), None),
        "memory_max_bytes": next((int(s["memory_max"]) for s in live if s.get("memory_max", "").isdigit()), None),
        "last_observed_memory_events": next((s["memory_events"] for s in reversed(live) if s.get("memory_events")), None),
        "first_sample_utc": rec["samples"][0]["utc"] if rec["samples"] else None,
        "last_sample_utc": rec["samples"][-1]["utc"] if rec["samples"] else None,
        "watch_seconds": round(time.time() - t0, 1),
    }
    if not live:
        rec["unavailable"].append("no cgroup counters were ever readable")
    rec["notes"].append("the unit is created with --collect; after exit its accounting is removed, so any counter "
                        "not captured above is UNKNOWN and is not reconstructed")
    Path(out_path).write_text(json.dumps(rec, indent=1, default=str) + "\n")
    print(json.dumps({"unit": unit, "invocation": props.get("InvocationID"),
                      "cgroup": str(cg), **rec["summary"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5400))
