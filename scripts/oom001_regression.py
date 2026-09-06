"""REGRESSION-OOM-001: the full bounded, sharded regression.

ONE fresh contained process per test module. Unit MemoryMax=1400M inside
wmresearch.slice -- the existing contract; nothing here raises either cap.
Every shard's pytest exit status is captured explicitly, so no failure can be
reported as a success. Collection and execution identities are recorded per
shard and reconciled at the end.
"""
import json, os, re, subprocess, sys, time
os.chdir("/opt/apex-repo")

PLAN = json.load(open("/tmp/oom001_plan.json"))
OUT = "/tmp/oom001_regression.json"
SLICE_EV = "/sys/fs/cgroup/wmresearch.slice/memory.events"
COUNT = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed|deselected|warning)")
KEY = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "errors": "ERROR",
       "skipped": "SKIP", "xfailed": "XFAIL", "xpassed": "XPASS"}


def slice_oom():
    for line in open(SLICE_EV):
        if line.startswith("oom_kill "):
            return int(line.split()[1])
    return -1


def collect(mod):
    """Collected identities, before execution -- cheap, uncontained, no side effects."""
    r = subprocess.run(["/opt/apex/shared/venv/bin/python", "-m", "pytest", mod,
                        "--collect-only", "-q", "-p", "no:cacheprovider"],
                       capture_output=True, text=True, env={**os.environ,
                       "PYTHONPATH": "/opt/apex-repo", "HOME": "/home/apex"})
    ids = [l.strip() for l in r.stdout.splitlines() if l.startswith(mod + "::")]
    return ids, r.returncode


shards, t_start = [], time.time()
oom_start = slice_oom()
print("commit %s | %d shards | slice oom_kill at start %d"
      % (PLAN["commit"], PLAN["shards"], oom_start), flush=True)

for i, mod in enumerate(PLAN["modules"], 1):
    ids, crc = collect(mod)
    log = "/tmp/oom001_shards/%03d.txt" % i
    os.makedirs("/tmp/oom001_shards", exist_ok=True)
    rc = subprocess.run(["/tmp/oom001_shard.sh", mod, log]).returncode
    txt = open(log).read()

    def tag(name, cast=str):
        m = re.search(r"__%s__=(\S+)" % name, txt)
        return cast(m.group(1)) if m else None

    counts = {}
    tail = txt.strip().splitlines()
    for line in tail[-14:]:
        if " passed" in line or " failed" in line or " error" in line or " skipped" in line:
            for n, w in COUNT.findall(line):
                if w in KEY:
                    counts[KEY[w]] = counts.get(KEY[w], 0) + int(n)
    executed = sum(counts.get(k, 0) for k in ("PASS", "FAIL", "ERROR", "SKIP", "XFAIL", "XPASS"))
    peak = tag("PEAK_BYTES")
    rec = {"n": i, "module": mod, "rc": rc, "collect_rc": crc,
           "collected": len(ids), "collected_ids": ids, "executed": executed,
           "counts": counts,
           "peak_mib": round(int(peak) / 1048576, 1) if peak and peak.isdigit() else None,
           "unit_oom_kill": tag("UNIT_OOM"),
           "slice_oom_before": tag("SLICE_OOM_BEFORE", int),
           "slice_oom_after": tag("SLICE_OOM_AFTER", int),
           "seconds": round(float(tag("SECONDS") or 0), 1),
           "skipped_reasons": [l.strip() for l in txt.splitlines() if l.startswith("SKIPPED")]}
    rec["accounted"] = (rec["collected"] == executed)
    rec["oomed"] = (rec["unit_oom_kill"] not in ("0", None)
                    or (rec["slice_oom_after"] or 0) > (rec["slice_oom_before"] or 0))
    shards.append(rec)
    flag = "" if (rc == 0 and rec["accounted"] and not rec["oomed"]) else "   <<< PROBLEM"
    print("[%3d/%3d] rc=%d %-52s collected=%-3d executed=%-3d peak=%sMiB %ss%s"
          % (i, PLAN["shards"], rc, mod.replace("tests/", ""), rec["collected"], executed,
             rec["peak_mib"], rec["seconds"], flag), flush=True)

oom_end = slice_oom()
tot = {}
for s in shards:
    for k, v in s["counts"].items():
        tot[k] = tot.get(k, 0) + v
problems = [s["module"] + "(rc=%d)" % s["rc"] for s in shards
            if s["rc"] != 0 or not s["accounted"] or s["oomed"]]
doc = {"kind": "oom001_bounded_regression", "version": "OOM001_SHARDED_REGRESSION_V1",
       "law": PLAN["law"], "commit": PLAN["commit"],
       "tree": subprocess.run(["git", "rev-parse", "HEAD^{tree}"], capture_output=True,
                              text=True).stdout.strip(),
       "shards": len(shards), "totals": tot,
       "collected_total": sum(s["collected"] for s in shards),
       "executed_total": sum(s["executed"] for s in shards),
       "slice_oom_kill_before": oom_start, "slice_oom_kill_after": oom_end,
       "problem_shards": problems,
       "all_skips": sorted({r for s in shards for r in s["skipped_reasons"]}),
       "elapsed_s": round(time.time() - t_start, 1),
       "shard_detail": shards,
       "previous_run": PLAN["previous_run"]}
doc["verdict"] = "PASS" if (not problems and oom_end == oom_start
                            and tot.get("FAIL", 0) == 0 and tot.get("ERROR", 0) == 0
                            and doc["collected_total"] == doc["executed_total"]) else "FAIL"
json.dump(doc, open(OUT, "w"), indent=1)
print("\nVERDICT %s | totals %s | collected %d executed %d | slice oom %d -> %d | %ss"
      % (doc["verdict"], tot, doc["collected_total"], doc["executed_total"],
         oom_start, oom_end, doc["elapsed_s"]), flush=True)
print("problem shards:", problems or "none", flush=True)
sys.exit(0 if doc["verdict"] == "PASS" else 2)
