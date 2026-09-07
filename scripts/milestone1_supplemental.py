"""Supplemental verification of the shards with external dependencies.

TWO PASSES.
  discovery   -- run each shard with a runtime audit hook to OBSERVE which
                 external files it actually opens and which subprocesses it
                 launches.
  verification-- hash every observed external file, re-run the same shards
                 with those inputs pinned, hash again, and compare.

Reported SEPARATELY from the original 215-shard run. It does not relabel that
run hermetic and does not erase the mid-run intervention at shard 114.
"""
import hashlib, json, os, re, subprocess, sys

WT = "/apex-data/tmp/m1_wt/integration"
OUT = "/apex-data/tmp/m1_runs/integration_supplemental"
AUDIT = "/apex-data/tmp/m1_audit"
PY = "/opt/apex/shared/venv/bin/python"
os.makedirs(OUT, exist_ok=True)
os.makedirs(AUDIT, exist_ok=True)

MODULES = {
 "tests/test_pulse_anchor_freshness.py": "fixture/data input",
 "tests/test_pulse_derived.py": "fixture/data input",
 "tests/test_research_board.py": "interpreter",
 "tests/test_whole_ledger_guard.py": "audit subject",
 "tests/test_unit_config.py": "host state",
}

AUDIT_HOOK_COVERAGE = {
 "observes": ["CPython `open` audit events raised by builtins.open, io.open "
              "and os.open in THIS interpreter",
              "subprocess.Popen audit events, giving each child's argv and "
              "therefore its interpreter"],
 "does_NOT_observe": [
   "file access performed inside native or C-extension libraries that call "
   "open(2) directly without going through the Python layer -- pandas, numpy, "
   "sqlite3 and zlib can all read this way",
   "activity inside a child process, UNLESS that child inherits PYTHONPATH and "
   "the audit environment variables and therefore loads the same hook",
   "memory-mapped reads, and reads through an already-open descriptor passed "
   "in from elsewhere"],
 "consequence": "the observed set is a LOWER BOUND on external dependencies, "
                "not a complete one. It is stronger than the source scan, "
                "which only finds literals, and weaker than a syscall trace.",
}


def h(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except OSError as e:
        return "UNREADABLE:%s" % type(e).__name__


def repo_state():
    g = lambda *a: subprocess.run(["git"] + list(a), cwd="/opt/apex-repo",
                                  capture_output=True, text=True).stdout.strip()
    return {"commit": g("rev-parse", "HEAD"), "tree": g("rev-parse", "HEAD^{tree}"),
            "branch": g("branch", "--show-current"),
            "tracked_dirty": len([l for l in g("status", "--porcelain").splitlines()
                                  if "exports" not in l])}


def run_shard(mod, tag):
    log = os.path.join(AUDIT, "%s.%s.audit" % (os.path.basename(mod), tag))
    open(log, "w").close()
    proc = subprocess.run(
        ["sudo", "-n", "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
         "--uid=apex", "--gid=apex", "--slice=wmresearch.slice",
         "-p", "MemoryMax=1400M", "-p", "MemorySwapMax=0", "-p", "Nice=10",
         "--working-directory=%s" % WT,
         "--setenv=PYTHONPATH=%s:%s" % (AUDIT, WT),
         "--setenv=APEX_AUDIT_WT=%s" % WT,
         "--setenv=APEX_AUDIT_LOG=%s" % log,
         "--setenv=HOME=/home/apex", "--",
         PY, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--rootdir=%s" % WT, "-rs", mod],
        capture_output=True, text=True)
    lines = sorted(set(open(log).read().splitlines())) if os.path.exists(log) else []
    opens = [l.split("\t", 1)[1] for l in lines if l.startswith("OPEN_OUTSIDE")]
    subs = [l.split("\t", 1)[1] for l in lines if l.startswith("SUBPROCESS")]
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return {"rc": proc.returncode, "summary": tail[-1] if tail else "",
            "opens_outside": opens, "subprocesses": subs, "log": log}


def child_provenance(subs):
    """Which interpreter each child ran, from the observed argv."""
    out = []
    for s in subs:
        m = re.findall(r"['\"]([^'\"]*(?:/bin/)?python[0-9.]*)['\"]", s)
        out.append({"argv_head": s[:180], "interpreter": m[0] if m else "NOT_A_PYTHON_CHILD",
                    "inherits_audit_env": "the child inherits PYTHONPATH and "
                        "APEX_AUDIT_* unless the test overrides env; when it "
                        "does inherit, its own opens appear in this same log"})
    return out


# ---------------------------------------------------------------- pass 1
print("=== PASS 1: discovery ===", flush=True)
discovery = {}
for mod in MODULES:
    r = run_shard(mod, "discovery")
    discovery[mod] = r
    print("  %-44s rc=%d opens_outside=%d subprocs=%d  %s"
          % (mod.replace("tests/", ""), r["rc"], len(r["opens_outside"]),
             len(r["subprocesses"]), r["summary"]), flush=True)

observed = sorted({p for r in discovery.values() for p in r["opens_outside"]})
print("\nexternal files actually opened (%d):" % len(observed), flush=True)
for p in observed:
    print("   ", p, flush=True)

# ---------------------------------------------------------------- pass 2
print("\n=== PASS 2: verification with those inputs pinned ===", flush=True)
before = {"files": {p: h(p) for p in observed}, "repo": repo_state(),
          "candidate": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT,
                                      capture_output=True, text=True).stdout.strip()}
verification = {}
for mod in MODULES:
    pre = {p: h(p) for p in observed}
    r = run_shard(mod, "verification")
    post = {p: h(p) for p in observed}
    changed = [p for p in observed if pre[p] != post[p]]
    r["external_changed_during_this_shard"] = changed
    r["external_stable"] = not changed
    r["child_provenance"] = child_provenance(r["subprocesses"])
    # An input seen only now was never hashed before the run, so it has no
    # "before" side. It is UNCOVERED, and must not be counted as verified.
    r["uncovered_by_discovery"] = sorted(set(r["opens_outside"]) - set(observed))
    verification[mod] = r
    print("  %-44s rc=%d stable=%s  %s"
          % (mod.replace("tests/", ""), r["rc"], not changed, r["summary"]), flush=True)

after = {"files": {p: h(p) for p in observed}, "repo": repo_state(),
         "candidate": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WT,
                                     capture_output=True, text=True).stdout.strip()}
changed_overall = sorted(p for p in observed if before["files"][p] != after["files"][p])

doc = {
 "kind": "integration_supplemental_external_input_verification",
 "version": "M1_SUPPLEMENTAL_V2",
 "relationship_to_the_original_run":
   "SEPARATE AND ADDITIONAL. The original 215-shard integration run stands as "
   "recorded, including the intervention at shard 114 that set /opt/apex-repo "
   "to the candidate commit. This run does not make that one hermetic and does "
   "not erase the intervention.",
 "audit_hook_coverage": AUDIT_HOOK_COVERAGE,
 "modules": MODULES,
 "discovery_pass": discovery,
 "external_files_actually_opened": observed,
 "before": before, "after": after,
 "external_files_changed_across_verification": changed_overall,
 "external_inputs_stable": not changed_overall,
 "uncovered_by_discovery": sorted({p for r in verification.values()
                                   for p in r["uncovered_by_discovery"]}),
 "coverage_claim": None,
 "repo_unchanged": before["repo"] == after["repo"],
 "candidate_unchanged": before["candidate"] == after["candidate"],
 "verification_pass": verification,
 "environment": {"python": PY, "containment": "wmresearch.slice, MemoryMax=1400M",
                 "PYTHONPATH": "%s:%s" % (AUDIT, WT), "working_directory": WT,
                 "audit_env": ["APEX_AUDIT_WT", "APEX_AUDIT_LOG"]},
}
unc = doc["uncovered_by_discovery"]
doc["coverage_claim"] = (
    "Every external file the verification pass opened was also seen in "
    "discovery, so each has a before and after hash."
    if not unc else
    "INCOMPLETE COVERAGE. The verification pass opened %d file(s) that "
    "discovery did not see, so they have no before-hash and are NOT verified "
    "stable: %s. Reported as uncovered rather than folded into the coverage "
    "claim." % (len(unc), unc))
doc["verdict"] = "PASS" if (all(r["rc"] == 0 for r in verification.values())
                            and not changed_overall
                            and before["repo"] == after["repo"]
                            and before["candidate"] == after["candidate"]) else "FAIL"
if unc:
    doc["verdict"] = "PASS_WITH_UNCOVERED_INPUTS" if doc["verdict"] == "PASS" else doc["verdict"]
json.dump(doc, open(os.path.join(OUT, "supplemental.json"), "w"), indent=1)
print("\nVERDICT %s" % doc["verdict"])
print("external files changed during verification:", changed_overall or "none")
print("uncovered by discovery:", doc["uncovered_by_discovery"] or "none")
print("coverage:", doc["coverage_claim"])
print("shared checkout unchanged:", before["repo"] == after["repo"], before["repo"])
print("candidate unchanged:", before["candidate"] == after["candidate"])
