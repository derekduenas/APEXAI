"""REGRESSION-OOM-001: build and INSPECT the execution plan before running."""
import json, subprocess, os
os.chdir("/opt/apex-repo")
mods = sorted(
    l for l in subprocess.run(["git", "ls-files", "tests/"], capture_output=True, text=True,
                              check=True).stdout.splitlines()
    if os.path.basename(l).startswith("test_") and l.endswith(".py"))
prev = json.load(open("results/pulse010r_bounded_regression.json"))
plan = {"kind": "oom001_execution_plan", "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip(),
        "law": "ONE_MODULE_PER_FRESH_PROCESS; unit MemoryMax=1400M; slice ceiling untouched",
        "modules": mods, "shards": len(mods),
        "previous_run": {"commit": prev["commit"], "shards": prev["shards"],
                         "totals": prev["totals"], "problem_shards": prev["problem_shards"],
                         "verdict": prev["verdict"]},
        "delta_vs_previous": len(mods) - prev["shards"]}
json.dump(plan, open("/tmp/oom001_plan.json", "w"), indent=1)
print("commit           :", plan["commit"])
print("shards planned   :", plan["shards"], "(previous run %d, delta %+d)"
      % (prev["shards"], plan["delta_vs_previous"]))
print("new vs previous  : tests/test_null_rig_memory.py"
      if "tests/test_null_rig_memory.py" in mods else "MISSING new module!")
print("null rig present :", "tests/test_null_rig.py" in mods)
print()
print("acceptance surfaces that must NOT be executed:")
for pat in ("world_model", "courts/", "acceptance", "seed"):
    hits = [m for m in mods if pat in m]
    print("  %-12s %s" % (pat, hits or "none in tests/"))
print()
print("first 6 modules:", mods[:6])
print("last 6 modules :", mods[-6:])
