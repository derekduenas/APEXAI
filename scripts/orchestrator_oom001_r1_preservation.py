"""ORCHESTRATOR-OOM-001-R1 preservation evidence, measured against base."""
import json, os, re, subprocess

BASE = "9e8f416bafca76f7e21031522812323e63883638"
REPAIR = "810b72c8dc8b9422ba96f41d900cfd361f5ff1da"
WT = "/tmp/oom001r1_base_wt"


def sh(*a, cwd="/opt/apex-repo"):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True)


doc = {"kind": "oom001_r1_preservation", "base": BASE, "repair": REPAIR}
files = sh("git", "diff", "--name-only", BASE, REPAIR).stdout.split()
doc["changed_files"] = files
doc["only_the_primitive_and_its_new_test"] = sorted(files) == [
    "apex/governance/chain_ledger.py", "tests/test_chain_tail_bounded.py"]
doc["existing_test_modules_changed"] = [f for f in files if f.startswith("tests/test_")
                                        and f != "tests/test_chain_tail_bounded.py"]
doc["config_or_unit_files_changed"] = [f for f in files if f.startswith("config/")
                                       or f.endswith(".service") or f.endswith(".conf")]
doc["other_apex_modules_changed"] = [f for f in files if f.startswith("apex/")
                                     and f != "apex/governance/chain_ledger.py"]

# collection identity across every module
if not os.path.isdir(WT):
    sh("git", "worktree", "add", "--detach", WT, BASE)


def collect_all(root):
    mods = sorted(l for l in sh("git", "ls-files", "tests/", cwd=root).stdout.splitlines()
                  if os.path.basename(l).startswith("test_") and l.endswith(".py"))
    out = {}
    for m in mods:
        r = subprocess.run(["/opt/apex/shared/venv/bin/python", "-m", "pytest", m,
                            "--collect-only", "-q", "-p", "no:cacheprovider"],
                           cwd=root, capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": root, "HOME": "/home/apex"})
        out[m] = sorted(l.strip() for l in r.stdout.splitlines() if l.startswith(m + "::"))
    return out


b, h = collect_all(WT), collect_all("/opt/apex-repo")
lost = {m: sorted(set(b[m]) - set(h.get(m, []))) for m in b if set(b[m]) - set(h.get(m, []))}
gained = {m: sorted(set(h[m]) - set(b.get(m, []))) for m in h if set(h[m]) - set(b.get(m, []))}
doc["collection"] = {"modules_base": len(b), "modules_head": len(h),
                     "nodeids_base": sum(len(v) for v in b.values()),
                     "nodeids_head": sum(len(v) for v in h.values()),
                     "lost_nodeids": lost, "gained_nodeids": gained,
                     "no_coverage_lost": not lost}

# the governed semantics that must not have moved
src = open("/opt/apex-repo/apex/governance/chain_ledger.py").read()
doc["semantics_preserved"] = {
    "serialisation_line": 'json.dumps(body, sort_keys=True)' in src,
    "sha256_over_the_same_body": 'hashlib.sha256(' in src,
    "torn_flag_still_recorded": '"recovered_from_torn_tail"' in src,
    "trailing_newline_repair_kept": "needs_nl" in src,
    "thread_lock_kept": "_path_lock" in src,
    "flock_kept": "fcntl.flock" in src and "LOCK_EX" in src,
    "whole_file_read_removed": _no_whole_file_read(),
    "ceiling_declared": "MAX_TAIL_SEARCH_BYTES = 8 * 1024 * 1024" in src,
    "initial_window_unchanged": "INITIAL_TAIL_BYTES = 262144" in src}

wrapper = open("/home/apex/bin/wm_contained.sh").read()
doc["containment_unchanged"] = {
    "wrapper_sha256": subprocess.run(["sha256sum", "/home/apex/bin/wm_contained.sh"],
                                     capture_output=True, text=True).stdout.split()[0],
    "expected": "dfbb916b435ba0a4a0dde02ad34825c9eb924307989791b8241343426bd62699",
    "slice_max": open("/sys/fs/cgroup/wmresearch.slice/memory.max").read().strip()}
doc["containment_unchanged"]["matches"] = (
    doc["containment_unchanged"]["wrapper_sha256"] == doc["containment_unchanged"]["expected"])

doc["production_untouched"] = {
    "orchestrator_unit_MemoryMax": subprocess.run(
        ["systemctl", "show", "apex-orchestrator.service", "-p", "MemoryMax", "--value"],
        capture_output=True, text=True).stdout.strip(),
    "expected": "536870912",
    "release_symlink": subprocess.run(["readlink", "-f", "/opt/apex/current"],
                                      capture_output=True, text=True).stdout.strip(),
    "production_ledger_mtime": subprocess.run(
        ["stat", "-c", "%y", "/apex-data/runtime/results/ops/orchestrator.jsonl"],
        capture_output=True, text=True).stdout.strip(),
    "production_ledger_size": subprocess.run(
        ["stat", "-c", "%s", "/apex-data/runtime/results/ops/orchestrator.jsonl"],
        capture_output=True, text=True).stdout.strip()}

doc["all_preserved"] = all([doc["only_the_primitive_and_its_new_test"],
                            doc["collection"]["no_coverage_lost"],
                            not doc["existing_test_modules_changed"],
                            not doc["config_or_unit_files_changed"],
                            not doc["other_apex_modules_changed"],
                            all(doc["semantics_preserved"].values()),
                            doc["containment_unchanged"]["matches"],
                            doc["production_untouched"]["production_ledger_size"] == "438867453"])
json.dump(doc, open("/tmp/oom001r1_preservation.json", "w"), indent=1)
print("changed_files:", files)
print("collection:", {k: v for k, v in doc["collection"].items() if not k.endswith("nodeids")})
print("lost:", doc["collection"]["lost_nodeids"] or "NONE")
print("gained:", json.dumps(doc["collection"]["gained_nodeids"]))
print("semantics_preserved:", json.dumps(doc["semantics_preserved"]))
print("containment:", json.dumps(doc["containment_unchanged"]))
print("production_untouched:", json.dumps(doc["production_untouched"]))
print("ALL_PRESERVED:", doc["all_preserved"])
