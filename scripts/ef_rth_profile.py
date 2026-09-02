"""EQUITY_FABRIC_RTH_PROFILE_V0 -- read-only longitudinal profile.

LANE A. Separate evidence regime from PULSE_V1 prebirth commissioning:
observations are NOT pooled, and neither may substitute for the other.

Changes NOTHING about equity-fabric. Samples cgroup + /proc + its own
canonical outputs at a bounded interval and writes one JSONL row per
sample to a scratch path.

Usage:  ef_rth_profile.py [minutes] [interval_s]
Intended run: the full RTH block, 13:30Z -> 20:00Z.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

UNIT = "apex-equity-fabric.service"
CG = Path(f"/sys/fs/cgroup/apex.slice/apex-market.slice/{UNIT}")
BARS = Path("/apex-data/runtime/data/live/alpaca_fabric/bars")
OUT = Path("/apex-data/core/equity_fabric_rth_profile")
OUT.mkdir(parents=True, exist_ok=True)
LEDGER = OUT / f"profile_{datetime.now(timezone.utc):%Y%m%d}.jsonl"

MINUTES = float(sys.argv[1]) if len(sys.argv) > 1 else 400
INTERVAL = float(sys.argv[2]) if len(sys.argv) > 2 else 60


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True,
                          text=True).stdout.strip()


def cg_read(name):
    try:
        return (CG / name).read_text().strip()
    except OSError:
        return None


def cg_stat():
    out = {}
    try:
        for ln in (CG / "memory.stat").read_text().splitlines():
            k, _, v = ln.partition(" ")
            if k in ("anon", "file", "slab", "inactive_anon",
                     "active_anon", "pgfault", "pgmajfault"):
                out[k] = int(v)
    except OSError:
        pass
    return out


def cg_events():
    out = {}
    try:
        for ln in (CG / "memory.events").read_text().splitlines():
            k, _, v = ln.partition(" ")
            out[k] = int(v)
    except OSError:
        pass
    return out


def proc_mem(pid):
    out = {}
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            m = re.match(r"(VmRSS|VmHWM|VmSize|Threads):\s+(\d+)", ln)
            if m:
                out[m.group(1)] = int(m.group(2))
    except OSError:
        pass
    return out


def bars_state():
    """The ECONOMIC JOB: is it still writing, and how big are the
    session files it re-reads every persist cycle?"""
    if not BARS.exists():
        return {"files": 0}
    now = time.time()
    sizes, fresh = [], 0
    for p in BARS.glob("*.json"):
        st = p.stat()
        sizes.append(st.st_size)
        if now - st.st_mtime < 300:
            fresh += 1
    sizes.sort()
    return {
        "files": len(sizes),
        "fresh_5min": fresh,
        "total_bytes": sum(sizes),
        "max_file_bytes": sizes[-1] if sizes else 0,
        "median_file_bytes": sizes[len(sizes) // 2] if sizes else 0,
    }


def io_state(pid):
    out = {}
    try:
        for ln in Path(f"/proc/{pid}/io").read_text().splitlines():
            k, _, v = ln.partition(":")
            if k in ("read_bytes", "write_bytes"):
                out[k] = int(v.strip())
    except OSError:
        pass
    return out


print(f"EQUITY_FABRIC_RTH_PROFILE_V0 -> {LEDGER}")
print(f"  duration {MINUTES} min, interval {INTERVAL}s, READ-ONLY")
deadline = time.time() + MINUTES * 60
n = 0
start_pid = sh(f"systemctl show {UNIT} -p MainPID --value")
print(f"  MainPID at start: {start_pid}")
print(f"  {'utc':>8} {'rss_MB':>8} {'anon_MB':>8} {'cur_MB':>8} "
      f"{'files':>6} {'fresh':>6} {'maxfile_KB':>11} {'evt.max':>8}")

while time.time() < deadline:
    pid = sh(f"systemctl show {UNIT} -p MainPID --value")
    now = datetime.now(timezone.utc)
    row = {
        "kind": "equity_fabric_rth_sample",
        "regime": "EQUITY_FABRIC_RTH_PROFILE_V0",
        "utc": now.isoformat(),
        "unit": UNIT,
        "pid": pid,
        "pid_changed": pid != start_pid,
        "memory_current": int(cg_read("memory.current") or 0),
        "memory_peak": int(cg_read("memory.peak") or 0),
        "memory_max": cg_read("memory.max"),
        "memory_high": cg_read("memory.high"),
        "memory_stat": cg_stat(),
        "memory_events": cg_events(),
        "proc": proc_mem(pid),
        "io": io_state(pid),
        "bars": bars_state(),
        "cpu_usage_usec": (cg_read("cpu.stat") or "").split("\n")[0],
    }
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    n += 1
    st = row["memory_stat"]
    b = row["bars"]
    print(f"  {now:%H:%M:%S} "
          f"{row['proc'].get('VmRSS', 0)/1024:>8.0f} "
          f"{st.get('anon', 0)/1048576:>8.0f} "
          f"{row['memory_current']/1048576:>8.0f} "
          f"{b['files']:>6} {b.get('fresh_5min', 0):>6} "
          f"{b.get('max_file_bytes', 0)/1024:>11.0f} "
          f"{row['memory_events'].get('max', 0):>8}")
    if row["pid_changed"]:
        print(f"    *** PID CHANGED {start_pid} -> {pid} "
              f"(restart/OOM boundary) ***")
        start_pid = pid
    time.sleep(INTERVAL)

print(f"\n  {n} samples -> {LEDGER}")
