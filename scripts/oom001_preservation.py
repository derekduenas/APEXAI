"""REGRESSION-OOM-001 preservation evidence.

The claim under test is that this brick changed HOW the fixtures hold memory
and nothing else. Each check is a measurement against the base commit, not an
assertion about intent.
"""
import json, os, re, subprocess

BASE = "15ce57581757c80f2ec7df424fa29ae33a69d273"
HEAD = subprocess.run(["git", "-C", "/opt/apex-repo", "rev-parse", "HEAD"],
                      capture_output=True, text=True, check=True).stdout.strip()
WT = "/tmp/oom001_base_wt"
doc = {"kind": "oom001_preservation", "base": BASE, "head": HEAD}


def sh(*a, cwd="/opt/apex-repo"):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True)


# ---- 1. exactly which files this brick touched
files = sh("git", "diff", "--name-only", BASE, HEAD).stdout.split()
doc["changed_files"] = files
doc["only_two_test_support_files"] = sorted(files) == [
    "tests/conftest.py", "tests/test_null_rig_memory.py"]

# ---- 2. no test case file, config, or production module was touched
doc["touched_outside_test_support"] = [f for f in files if f not in
                                       ("tests/conftest.py", "tests/test_null_rig_memory.py")]
doc["config_files_changed"] = [f for f in files if f.startswith("config/")]
doc["apex_package_changed"] = [f for f in files if f.startswith("apex/")]
doc["existing_test_modules_changed"] = [f for f in files if f.startswith("tests/test_")
                                        and f != "tests/test_null_rig_memory.py"]

# ---- 3. the failing module is byte-identical
doc["test_null_rig_unchanged"] = sh("git", "diff", "--quiet", BASE, HEAD, "--",
                                    "tests/test_null_rig.py").returncode == 0

# ---- 4. collection identity across EVERY module, base vs head
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


base_ids, head_ids = collect_all(WT), collect_all("/opt/apex-repo")
lost = {m: sorted(set(base_ids[m]) - set(head_ids.get(m, []))) for m in base_ids
        if set(base_ids[m]) - set(head_ids.get(m, []))}
gained = {m: sorted(set(head_ids[m]) - set(base_ids.get(m, []))) for m in head_ids
          if set(head_ids[m]) - set(base_ids.get(m, []))}
doc["collection"] = {
    "modules_base": len(base_ids), "modules_head": len(head_ids),
    "nodeids_base": sum(len(v) for v in base_ids.values()),
    "nodeids_head": sum(len(v) for v in head_ids.values()),
    "lost_nodeids": lost, "gained_nodeids": gained,
    "no_coverage_lost": not lost}

# ---- 5. statistical controls and thresholds
nr_base = sh("git", "show", "%s:tests/test_null_rig.py" % BASE).stdout
nr_head = open("/opt/apex-repo/tests/test_null_rig.py").read()
doc["assertions"] = {
    "assert_statements_base": len(re.findall(r"^\s*assert\b", nr_base, re.M)),
    "assert_statements_head": len(re.findall(r"^\s*assert\b", nr_head, re.M)),
    "skip_markers_base": nr_base.count("@pytest.mark.skip("),
    "skip_markers_head": nr_head.count("@pytest.mark.skip("),
    "identical": nr_base == nr_head}
cfg_base = sh("git", "show", "%s:config/synthetic.yaml" % BASE).stdout
cfg_head = open("/opt/apex-repo/config/synthetic.yaml").read()
doc["null_rig_config_unchanged"] = cfg_base == cfg_head
doc["seed_parameters"] = {k: re.search(r"^\s*%s:\s*(\S+)" % k, cfg_head, re.M).group(1)
                          for k in ("n_seeds", "n_seeds_fast", "n_securities", "base_seed")}

# ---- 6. the computation itself: old body preserved verbatim
cf_base = sh("git", "show", "%s:tests/conftest.py" % BASE).stdout
cf_head = open("/opt/apex-repo/tests/conftest.py").read()


def body(src, fn):
    m = re.search(r"def %s\(seed: int, alpha: float\):(.*?)\n\n\n" % fn, src, re.S)
    t = m.group(1)
    return re.sub(r'"""'.join(["", ".*?", ""]), "", t, flags=re.S).strip()


doc["computation_body_verbatim"] = body(cf_base, "_run") == body(cf_head, "_compute")

# ---- 7. containment unchanged
wrapper = open("/home/apex/bin/wm_contained.sh").read()
doc["containment"] = {
    "wrapper_MemoryMax": re.findall(r"MemoryMax=(\S+)", wrapper),
    "slice_max": open("/sys/fs/cgroup/wmresearch.slice/memory.max").read().strip(),
    "unit_cap_used_by_this_brick": "1400M",
    "wrapper_sha256": subprocess.run(["sha256sum", "/home/apex/bin/wm_contained.sh"],
                                     capture_output=True, text=True).stdout.split()[0]}

doc["all_preserved"] = all([
    doc["only_two_test_support_files"], doc["test_null_rig_unchanged"],
    doc["collection"]["no_coverage_lost"], doc["assertions"]["identical"],
    doc["null_rig_config_unchanged"], doc["computation_body_verbatim"],
    not doc["config_files_changed"], not doc["apex_package_changed"],
    not doc["existing_test_modules_changed"]])

json.dump(doc, open("/tmp/oom001_preservation.json", "w"), indent=1)
for k in ("changed_files", "only_two_test_support_files", "test_null_rig_unchanged",
          "null_rig_config_unchanged", "computation_body_verbatim", "all_preserved"):
    print("%-32s %s" % (k + ":", doc[k]))
print("collection:", json.dumps({k: v for k, v in doc["collection"].items()
                                 if k != "lost_nodeids" and k != "gained_nodeids"}))
print("lost nodeids:", doc["collection"]["lost_nodeids"] or "NONE")
print("gained nodeids:", json.dumps(doc["collection"]["gained_nodeids"]))
print("assertions:", json.dumps(doc["assertions"]))
print("containment:", json.dumps(doc["containment"]))
