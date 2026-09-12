"""MILESTONE 1: regression with source provenance.

A dedicated worktree per candidate, a manifest of every tracked file before
and after, generated outputs written outside the source tree, explicit exit
status per shard, and subprocesses pointed at the candidate under test.

An unexplained source change during the run invalidates the run's attribution.
This creates NEW evidence for these candidates; it repairs nothing historical.
"""
import hashlib, json, os, re, subprocess, sys, time

CANDIDATE = sys.argv[1]                 # commit-ish
NAME = sys.argv[2]                      # short label
MODE = sys.argv[3]                      # "full" | "focused"
WT = "/apex-data/tmp/m1_wt/%s" % NAME
OUT = "/apex-data/tmp/m1_runs/%s" % NAME
REPO = "/opt/apex-repo"
PY = "/opt/apex/shared/venv/bin/python"
SLICE_EV = "/sys/fs/cgroup/wmresearch.slice/memory.events"


def run(*a, cwd=None):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def manifest(root):
    """sha256 of every TRACKED file, plus the untracked inventory."""
    _, files, _ = run("git", "ls-files", cwd=root)
    m = {}
    for f in files.splitlines():
        p = os.path.join(root, f)
        try:
            m[f] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        except (OSError, IsADirectoryError):
            m[f] = "UNREADABLE"
    _, untracked, _ = run("git", "ls-files", "--others", "--exclude-standard", cwd=root)
    return {"tracked": m, "tracked_count": len(m),
            "digest": hashlib.sha256(
                json.dumps(m, sort_keys=True).encode()).hexdigest(),
            "untracked": sorted(untracked.splitlines())}


def slice_oom():
    for line in open(SLICE_EV):
        if line.startswith("oom_kill "):
            return int(line.split()[1])
    return -1


# ---------------------------------------------------------- dedicated checkout
os.makedirs(os.path.dirname(WT), exist_ok=True)
os.makedirs(OUT, exist_ok=True)
if os.path.isdir(WT):
    run("git", "worktree", "remove", "--force", WT, cwd=REPO)
rc, o, e = run("git", "worktree", "add", "--detach", WT, CANDIDATE, cwd=REPO)
assert rc == 0, e
rc, commit, _ = run("git", "rev-parse", "HEAD", cwd=WT)
rc, tree, _ = run("git", "rev-parse", "HEAD^{tree}", cwd=WT)
rc, dirty, _ = run("git", "status", "--porcelain", cwd=WT)

before = manifest(WT)
print("candidate %s\n  worktree %s\n  commit %s\n  tree %s\n  clean %s\n"
      "  tracked files %d  manifest %s\n  untracked before %d"
      % (NAME, WT, commit, tree, not dirty, before["tracked_count"],
         before["digest"][:16], len(before["untracked"])), flush=True)

# ---------------------------------------------------------- the modules to run
_, files, _ = run("git", "ls-files", "tests/", cwd=WT)
mods = sorted(f for f in files.splitlines()
              if os.path.basename(f).startswith("test_") and f.endswith(".py"))
if MODE == "focused":
    keep = ("test_chain_tail_bounded.py", "test_orchestrator_incident_history.py")
    _, grep, _ = run("bash", "-c",
                     "grep -rln 'chain_append\\|chain_ledger' tests/*.py", cwd=WT)
    mods = sorted(set(["tests/" + k for k in keep]) | set(grep.splitlines()))
print("  shards planned %d\n" % len(mods), flush=True)

COUNT = re.compile(r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed)")
KEY = {"passed": "PASS", "failed": "FAIL", "error": "ERROR", "errors": "ERROR",
       "skipped": "SKIP", "xfailed": "XFAIL", "xpassed": "XPASS"}

shards, t0, oom0 = [], time.time(), slice_oom()
for i, mod in enumerate(mods, 1):
    # collection identities, from the candidate
    cr = subprocess.run([PY, "-m", "pytest", mod, "--collect-only", "-q",
                         "-p", "no:cacheprovider"], cwd=WT, capture_output=True,
                        text=True, env={**os.environ, "PYTHONPATH": WT,
                                        "HOME": "/home/apex"})
    ids = [l.strip() for l in cr.stdout.splitlines() if l.startswith(mod + "::")]
    log = os.path.join(OUT, "shard_%03d.txt" % i)      # OUTSIDE the source tree
    # one fresh contained process; --working-directory and PYTHONPATH both the
    # candidate, so every subprocess a test spawns imports the candidate too
    proc = subprocess.run(
        ["sudo", "-n", "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
         "--uid=apex", "--gid=apex", "--slice=wmresearch.slice",
         "-p", "MemoryMax=1400M", "-p", "MemorySwapMax=0", "-p", "Nice=10",
         "--working-directory=%s" % WT, "--setenv=PYTHONPATH=%s" % WT,
         "--setenv=HOME=/home/apex", "--",
         "/bin/bash", "-c",
         'CG=/sys/fs/cgroup$(awk -F: "{print \\$3}" /proc/self/cgroup | head -1); '
         '%s -m pytest -q -p no:cacheprovider --rootdir=%s -rs %s; rc=$?; '
         'echo "__PEAK__=$(cat $CG/memory.peak 2>/dev/null || echo NA)"; '
         'echo "__UOOM__=$(awk "/^oom_kill /{print \\$2}" $CG/memory.events '
         '2>/dev/null || echo NA)"; exit $rc' % (PY, WT, mod)],
        capture_output=True, text=True)
    txt = proc.stdout + proc.stderr
    open(log, "w").write(txt)
    counts = {}
    for line in txt.splitlines()[-14:]:
        if any(w in line for w in (" passed", " failed", " error", " skipped")):
            for n, w in COUNT.findall(line):
                if w in KEY:
                    counts[KEY[w]] = counts.get(KEY[w], 0) + int(n)
    ex = sum(counts.get(k, 0) for k in ("PASS", "FAIL", "ERROR", "SKIP", "XFAIL", "XPASS"))
    peak = re.search(r"__PEAK__=(\S+)", txt)
    uoom = re.search(r"__UOOM__=(\S+)", txt)
    rec = {"n": i, "module": mod, "rc": proc.returncode, "collect_rc": cr.returncode,
           "collected": len(ids), "collected_ids": ids, "executed": ex,
           "counts": counts,
           "peak_mib": round(int(peak.group(1)) / 1048576, 1)
                       if peak and peak.group(1).isdigit() else None,
           "unit_oom": uoom.group(1) if uoom else None,
           "log": log,
           "skips": [l.strip() for l in txt.splitlines() if l.startswith("SKIPPED")]}
    rec["accounted"] = rec["collected"] == ex
    rec["ok"] = proc.returncode == 0 and rec["accounted"] and rec["unit_oom"] in ("0", None)
    shards.append(rec)
    print("[%3d/%3d] rc=%d %-52s c=%-3d x=%-3d peak=%sMiB%s"
          % (i, len(mods), proc.returncode, mod.replace("tests/", ""),
             rec["collected"], ex, rec["peak_mib"], "" if rec["ok"] else "  <<< PROBLEM"),
          flush=True)

after = manifest(WT)
oom1 = slice_oom()
tot = {}
for s in shards:
    for k, v in s["counts"].items():
        tot[k] = tot.get(k, 0) + v
changed = sorted(f for f in set(before["tracked"]) | set(after["tracked"])
                 if before["tracked"].get(f) != after["tracked"].get(f))
new_untracked = sorted(set(after["untracked"]) - set(before["untracked"]))
problems = [s["module"] + "(rc=%d)" % s["rc"] for s in shards if not s["ok"]]

doc = {"kind": "milestone1_provenance_regression", "version": "M1_PROVENANCE_V1",
       "candidate": NAME, "mode": MODE, "commit": commit, "tree": tree,
       "worktree": WT, "outputs_dir": OUT,
       "outputs_outside_source_tree": not OUT.startswith(WT),
       "source_tree_clean_at_start": not dirty,
       "manifest_before": {"digest": before["digest"],
                           "tracked_files": before["tracked_count"],
                           "untracked": before["untracked"]},
       "manifest_after": {"digest": after["digest"],
                          "tracked_files": after["tracked_count"],
                          "untracked": after["untracked"]},
       "tracked_files_changed_during_the_run": changed,
       "new_untracked_files_during_the_run": new_untracked,
       "source_identity_held": not changed,
       "attribution": ("VALID -- no tracked source file changed during the run"
                       if not changed else
                       "INVALID -- tracked source changed mid-run: %s" % changed),
       "subprocess_imports": {"PYTHONPATH": WT, "working_directory": WT,
                              "note": "both point at the candidate worktree, so "
                                      "a test's child process imports the "
                                      "candidate and not the shared checkout"},
       "shards": len(shards), "totals": tot,
       "collected_total": sum(s["collected"] for s in shards),
       "executed_total": sum(s["executed"] for s in shards),
       "slice_oom_before": oom0, "slice_oom_after": oom1,
       "problem_shards": problems,
       "all_skips": sorted({x for s in shards for x in s["skips"]}),
       "elapsed_s": round(time.time() - t0, 1), "shard_detail": shards}
doc["verdict"] = "PASS" if (not problems and oom1 == oom0 and not changed
                            and tot.get("FAIL", 0) == 0 and tot.get("ERROR", 0) == 0
                            and doc["collected_total"] == doc["executed_total"]) else "FAIL"
json.dump(doc, open(os.path.join(OUT, "regression.json"), "w"), indent=1)
print("\nVERDICT %s | totals %s | collected %d executed %d | slice oom %d->%d | %ss"
      % (doc["verdict"], tot, doc["collected_total"], doc["executed_total"],
         oom0, oom1, doc["elapsed_s"]), flush=True)
print("source identity held:", doc["source_identity_held"],
      "| manifest", before["digest"][:16], "->", after["digest"][:16], flush=True)
print("new untracked during run:", new_untracked or "none", flush=True)
print("problem shards:", problems or "none", flush=True)
