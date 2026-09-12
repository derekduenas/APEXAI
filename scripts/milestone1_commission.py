"""MILESTONE 1 -- commissioning observer, run AFTER the symlink swap.

Judges completed work, not process state. Anchors on the FIRST start that
loaded the new release; everything before it belongs to the broken release.
Reads only the unit's own signals and the journal; never the shared slice
counter. Ends with the full-prefix ledger verification. Explicit verdict.
"""
import json, os, re, subprocess, sys, time
from datetime import datetime, timezone

REC = "73fc712d355032e0a66b41675ba114491b04799d"
EV = "/apex-data/tmp/m1_deploy"
UNIT = "apex-orchestrator.service"
CG = "/sys/fs/cgroup/apex.slice/apex-market.slice/apex-orchestrator.service"
LEDGER = "/apex-data/core/ops/orchestrator.jsonl"
HB = "/apex-data/core/heartbeats/orchestrator.json"
OBSERVE_S = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
SAMPLE_S = 60


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def unit():
    _, out = sh("systemctl", "show", UNIT, "-p",
                "NRestarts,Result,ActiveState,SubState,ExecMainStartTimestamp,"
                "ExecMainStatus,ExecMainPID")
    return dict(l.split("=", 1) for l in out.splitlines() if "=" in l)


def heartbeat():
    try:
        d = json.load(open(HB))
        return {"last_work_utc": d.get("last_work_utc"), "work_completed": d.get("work_completed"),
                "release_path": d.get("release_path"), "pid": d.get("pid")}
    except Exception as e:                                   # noqa: BLE001
        return {"error": type(e).__name__}


def oom_lines_since(t_iso):
    _, out = sh("sudo", "-n", "journalctl", "-u", UNIT, "--since", t_iso, "--no-pager", "-o", "cat")
    return sum(1 for l in out.splitlines() if "Failed with result" in l or "OOM" in l)


def unit_peak_mib():
    try:
        return round(int(open(CG + "/memory.peak").read()) / 1048576, 1)
    except OSError:
        return None                                          # between restarts


def newest_record():
    size = os.path.getsize(LEDGER)
    with open(LEDGER, "rb") as fh:
        fh.seek(max(0, size - 262144))
        lines = [l for l in fh.read().decode("utf-8", "replace").splitlines() if l.strip()]
    r = json.loads(lines[-1])
    incs = r.get("incidents", [])
    outs = sorted({a.get("outcome") for a in r.get("actions", [])})
    hist = max((len(i.get("recovery_attempts", [])) for i in incs), default=0)
    return {"at": r.get("at"), "bytes": len(json.dumps(r, sort_keys=True)),
            "incidents": len(incs), "max_history_entries": hist,
            "action_outcomes": outs, "maintenance": list((r.get("maintenance") or {}).keys()),
            "ledger_size": size}


# ---------------------------------------------------------------- anchor
swap_line = open(EV + "/swap.txt").read().strip()
swap_utc = swap_line.split()[-1]
print("swap:", swap_line, flush=True)
if REC not in swap_line:
    print("ABORT: current does not point at the candidate"); sys.exit(10)
pre = dict(l.split("=", 1) for l in open(EV + "/pre_deploy_unit.txt").read().splitlines() if "=" in l)
print("pre-deploy unit:", pre, flush=True)

t_anchor = None
for _ in range(20):                                           # up to ~2 min for the next restart
    u = unit()
    hb = heartbeat()
    if hb.get("release_path") and REC in str(hb["release_path"]):
        t_anchor = u.get("ExecMainStartTimestamp"); N0 = int(u["NRestarts"]); break
    if u.get("ActiveState") == "active" and int(u.get("NRestarts", 0)) > int(pre.get("NRestarts", 0)):
        t_anchor = u.get("ExecMainStartTimestamp"); N0 = int(u["NRestarts"]); break
    time.sleep(6)
if not t_anchor:
    print("ABORT: no start of the new release observed within 2 minutes")
    json.dump({"verdict": "FAIL", "why": "no anchor"}, open(EV + "/commission.json", "w"), indent=1); sys.exit(11)
print("ANCHOR T0=%s N0=%d" % (t_anchor, N0), flush=True)
# systemd timestamps are 'Day YYYY-MM-DD HH:MM:SS UTC'; journal wants ISO
m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", t_anchor)
t0_iso = "%s %s UTC" % (m.group(1), m.group(2))

# ---------------------------------------------------------------- observe
samples, t_start = [], time.time()
while time.time() - t_start < OBSERVE_S:
    u = unit(); hb = heartbeat()
    s = {"t": datetime.now(timezone.utc).strftime("%H:%M:%SZ"),
         "NRestarts": int(u.get("NRestarts", -1)), "Result": u.get("Result"),
         "ActiveState": u.get("ActiveState"), "oom_lines_since_T0": oom_lines_since(t0_iso),
         "last_work_utc": hb.get("last_work_utc"), "work_completed": hb.get("work_completed"),
         "unit_peak_mib": unit_peak_mib()}
    try:
        s["newest"] = newest_record()
    except Exception as e:                                   # noqa: BLE001
        s["newest"] = {"error": type(e).__name__}
    samples.append(s)
    print("  %(t)s NRestarts=%(NRestarts)d Result=%(Result)s %(ActiveState)s oom=%(oom_lines_since_T0)d "
          "work=%(work_completed)s last=%(last_work_utc)s peak=%(unit_peak_mib)s MiB" % s, flush=True)
    time.sleep(SAMPLE_S)

# ---------------------------------------------------------------- judge
first, last = samples[0], samples[-1]
wc = [s["work_completed"] for s in samples if isinstance(s.get("work_completed"), int)]
lw = [s["last_work_utc"] for s in samples if s.get("last_work_utc")]
peaks = [s["unit_peak_mib"] for s in samples if s.get("unit_peak_mib")]
newest = [s["newest"] for s in samples if "bytes" in s.get("newest", {})]
checks = {
    "restart_counter_static": last["NRestarts"] == N0,
    "no_oom_kill_since_T0": last["oom_lines_since_T0"] == 0,
    "result_not_oom_kill": last["Result"] != "oom-kill",
    "heartbeat_advanced": len(set(lw)) >= max(3, OBSERVE_S // 240),
    "work_completed_climbed": len(wc) >= 2 and wc[-1] - wc[0] >= max(3, OBSERVE_S // 240),
    "unit_peak_under_cap": bool(peaks) and max(peaks) < 480.0,
    "unit_peak_max_mib": max(peaks) if peaks else None,
    "ledger_growing": bool(newest) and newest[-1]["ledger_size"] > 438867453,
    "newest_record_bounded": bool(newest) and newest[-1]["bytes"] < 20000 and newest[-1]["max_history_entries"] <= 7,
    "no_STARTED_outcome": all("STARTED" not in (n.get("action_outcomes") or []) for n in newest),
}
# ---------------------------------------------------------------- ledger prefixes
prefix = []
for line in open(EV + "/pre_deploy_ledger_prefixes.txt"):
    L, N, H = line.split()
    _, now = sh("bash", "-c", "head -c %s %s | sha256sum | cut -d' ' -f1" % (N, L))
    sz = os.path.getsize(L)
    prefix.append({"ledger": L, "recorded_len": int(N), "size_now": sz,
                   "prefix_identical": now == H, "did_not_shrink": sz >= int(N)})
checks["all_ledger_prefixes_identical"] = all(p["prefix_identical"] and p["did_not_shrink"] for p in prefix)

verdict = "PASS" if all(v for k, v in checks.items() if isinstance(v, bool)) else "FAIL"
doc = {"kind": "milestone1_commissioning", "candidate": REC, "swap": swap_line,
       "anchor": {"T0": t_anchor, "N0": N0}, "observe_s": OBSERVE_S, "samples": samples,
       "checks": checks, "ledger_prefixes": prefix, "verdict": verdict,
       "law": "judged on completed work and the unit's own counters; the shared slice counter is never used"}
json.dump(doc, open(EV + "/commission.json", "w"), indent=1)
print("\nCOMMISSIONING VERDICT:", verdict)
for k, v in checks.items():
    print("  %-34s %s" % (k, v))
for p in prefix:
    print("  %-70s prefix_identical=%s size %d -> %d" % (p["ledger"].split("/core/")[-1], p["prefix_identical"], p["recorded_len"], p["size_now"]))
sys.exit(0 if verdict == "PASS" else 12)
