"""BOUNDED_FULL_REGRESSION_V0 -- deterministic fresh-process module sharding.

  collect   one fresh contained pytest process collects the ENTIRE authoritative
            inventory (testpaths = tests/); any collection error -> FAIL.
  shards    ONE collected module per shard, modules sorted canonically; the
            expected nodeid set of a shard is read from the sealed master.
  run       each shard = a NEW pytest process under the containment wrapper,
            sequentially; per shard: unit/cgroup, MemoryMax, peak, elapsed,
            exit code, OOM delta on the slice, observed nodeids, outcomes.
            observed nodeids must == expected nodeids.
  reconcile union(expected) == master, union(observed) == master, 0 missing,
            0 unexpected, 0 duplicate, 0 unaccounted; totals; skip manifest.
Pure functions do the judging so the runner can be self-tested on
miniature inventories without any containment.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUNNER_VERSION = "BOUNDED_FULL_REGRESSION_V0"
SHARD_LAW = "ONE_MODULE_PER_FRESH_PROCESS"
WRAPPER = ["/home/apex/bin/wm_contained.sh"]
PY = "/opt/apex/shared/venv/bin/python"
SLICE_EVENTS = "/sys/fs/cgroup/wmresearch.slice/memory.events"
SURFACE_DIR = "apex/world_model"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon_hash(obj) -> str:
    return sha(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())


def runner_hash() -> str:
    return sha(Path(__file__).read_bytes())


# ---------------------------------------------------------------- §1 surface
def scientific_surface_hash(root: str) -> dict:
    """Every runtime World Model implementation file; tests, runner, evidence
    and caches excluded by construction (only apex/world_model/*.py)."""
    files = sorted(p for p in Path(root, SURFACE_DIR).glob("*.py"))
    entries = [(str(p.relative_to(root)), sha(p.read_bytes())) for p in files]
    return {"name": "WORLD_MODEL_SCIENTIFIC_SURFACE_HASH_V0", "files": len(entries),
            "entries": entries, "hash": canon_hash(entries)}


# ---------------------------------------------------------------- §2/§3 collect
def collect_master(exec_prefix: list, out_path: str, scope: str = "tests", cwd: str | None = None) -> dict:
    env = dict(os.environ, REGRESSION_OUT=out_path)
    cmd = exec_prefix + [PY if exec_prefix else sys.executable, "-m", "pytest", scope, "--collect-only", "-q",
                         "--rootdir", cwd or os.getcwd(), "-p", "no:cacheprovider", "-p", "regression.plugin"]
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)
    if not os.path.exists(out_path):
        raise SystemExit("collection produced no inventory (exit %d): %s" % (proc.returncode, proc.stderr[-800:]))
    doc = json.load(open(out_path))
    doc["collection"] = {"cmd": cmd, "returncode": proc.returncode, "elapsed_s": round(time.time() - t0, 1)}
    nodeids = [it["nodeid"] for it in doc["collected"]]
    doc["nodeids"] = nodeids
    doc["files"] = sorted({it["file"] for it in doc["collected"]})
    doc["inventory_hash"] = canon_hash(nodeids)
    doc["ok"] = (not doc["collect_errors"]) and proc.returncode == 0 and len(nodeids) == len(set(nodeids))
    json.dump(doc, open(out_path, "w"), indent=1)
    return doc


# ---------------------------------------------------------------- §4 shards
def shards_from_master(master: dict) -> list:
    by_file = {}
    for it in master["collected"]:
        by_file.setdefault(it["file"], []).append(it["nodeid"])
    return [{"index": i, "module": f, "expected": sorted(by_file[f]), "expected_hash": canon_hash(sorted(by_file[f]))}
            for i, f in enumerate(sorted(by_file))]


# ---------------------------------------------------------------- §5-§9 run
def _oom_count() -> int:
    try:
        for line in open(SLICE_EVENTS):
            if line.startswith("oom_kill "):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def run_shard(shard: dict, exec_prefix: list, out_dir: str, cwd: str | None = None) -> dict:
    out = os.path.join(out_dir, "shard_%03d.json" % shard["index"])
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, REGRESSION_OUT=out)
    cmd = exec_prefix + [PY if exec_prefix else sys.executable, "-m", "pytest", shard["module"], "-q",
                         "--rootdir", cwd or os.getcwd(), "-p", "no:cacheprovider", "-p", "regression.plugin"]
    oom0 = _oom_count(); t0 = time.time()
    proc = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)
    rec = {"index": shard["index"], "module": shard["module"], "expected_hash": shard["expected_hash"],
           "cmd": cmd, "returncode": proc.returncode, "elapsed_s": round(time.time() - t0, 2),
           "oom_delta": _oom_count() - oom0, "fresh_process": True, "reported": os.path.exists(out)}
    if rec["reported"]:
        doc = json.load(open(out))
        rec.update({"observed": sorted(doc["results"]), "observed_hash": canon_hash(sorted(doc["results"])),
                    "results": doc["results"], "totals": doc["totals"], "collect_errors": doc["collect_errors"],
                    "resource": doc["resource"], "exitstatus": doc["exitstatus"], "report_path": out})
    else:
        rec.update({"observed": [], "observed_hash": None, "results": {}, "totals": {}, "collect_errors": [],
                    "resource": None, "stderr_tail": proc.stderr[-800:]})
    return judge_shard(shard, rec)


def judge_shard(shard: dict, rec: dict) -> dict:
    problems = []
    if rec["oom_delta"] > 0:
        problems.append("SHARD_RESOURCE_FAILURE")
    if not rec["reported"]:
        problems.append("UNREPORTED_RESULT")
    if rec.get("collect_errors"):
        problems.append("COLLECTION_ERROR")
    exp, obs = set(shard["expected"]), set(rec.get("observed", []))
    if obs != exp:
        problems.append("SHARD_COLLECTION_MISMATCH(missing=%d,extra=%d)" % (len(exp - obs), len(obs - exp)))
    if rec["reported"]:
        for n, r in rec["results"].items():
            if r["outcome"] in ("FAIL", "ERROR", "UNREPORTED", "XPASS"):
                problems.append("%s:%s" % (r["outcome"], n))
    if rec["returncode"] not in (0, 5) and not problems:      # 5 = no tests collected
        problems.append("PROCESS_FAILURE(rc=%d)" % rec["returncode"])
    rec["problems"] = problems
    rec["ok"] = not problems
    return rec


# ---------------------------------------------------------------- §10-§12 reconcile
def reconcile(master: dict, shards: list, shard_recs: list, prior_skip_manifest: dict | None = None) -> dict:
    master_set = set(master["nodeids"])
    exp_union, obs_union, seen = set(), [], {}
    for s in shards:
        exp_union |= set(s["expected"])
    for r in shard_recs:
        for n in r.get("observed", []):
            obs_union.append(n); seen[n] = seen.get(n, 0) + 1
    obs_set = set(obs_union)
    dup = sorted(n for n, k in seen.items() if k > 1)
    outcomes = {}
    for r in shard_recs:
        for n, res in r.get("results", {}).items():
            outcomes[n] = res
    unaccounted = sorted(n for n in master_set if n not in outcomes or outcomes[n]["outcome"] == "UNREPORTED")
    totals = {k: sum(1 for r in outcomes.values() if r["outcome"] == k) for k in ("PASS", "FAIL", "ERROR", "SKIP", "XFAIL", "XPASS", "UNREPORTED")}
    skips = {n: r["detail"] for n, r in sorted(outcomes.items()) if r["outcome"] == "SKIP"}
    skip_cmp = None
    if prior_skip_manifest is not None:
        prior = prior_skip_manifest.get("skips", {})
        skip_cmp = {"unchanged": sorted(n for n in skips if n in prior and prior[n] == skips[n]),
                    "reason_drift": sorted(n for n in skips if n in prior and prior[n] != skips[n]),
                    "new": sorted(n for n in skips if n not in prior),
                    "removed": sorted(n for n in prior if n not in skips)}
    rec = {"name": "FULL_REGRESSION_RECONCILIATION_V0", "master_count": len(master_set),
           "expected_union_equals_master": exp_union == master_set,
           "observed_union_equals_master": obs_set == master_set,
           "missing": sorted(master_set - obs_set), "unexpected": sorted(obs_set - master_set),
           "duplicates": dup, "unaccounted": unaccounted, "totals": totals,
           "shards_ok": sum(1 for r in shard_recs if r["ok"]), "shards_failed": [r["module"] for r in shard_recs if not r["ok"]],
           "shard_problems": {r["module"]: r["problems"] for r in shard_recs if not r["ok"]},
           "skip_manifest": {"name": "FULL_REGRESSION_SKIP_MANIFEST_V0", "count": len(skips), "skips": skips,
                             "hash": canon_hash(skips)}, "skip_comparison": skip_cmp,
           "master_inventory_hash": master["inventory_hash"],
           "executed_inventory_hash": canon_hash(sorted(obs_set)),
           "shard_inventory_hashes": {r["module"]: r.get("observed_hash") for r in shard_recs}}
    new_unexplained = len(skip_cmp["new"]) if skip_cmp else 0
    rec["new_unexplained_skips"] = new_unexplained
    rec["ok"] = (rec["expected_union_equals_master"] and rec["observed_union_equals_master"] and not rec["missing"]
                 and not rec["unexpected"] and not dup and not unaccounted and totals["FAIL"] == 0 and totals["ERROR"] == 0
                 and totals["XPASS"] == 0 and totals["UNREPORTED"] == 0 and not rec["shards_failed"] and new_unexplained == 0)
    return rec


# ---------------------------------------------------------------- CLI
def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["collect", "run", "all"])
    ap.add_argument("--root", default="/opt/apex-research/world-model-shadow")
    ap.add_argument("--out", default="evidence/bounded_regression")
    ap.add_argument("--uncontained", action="store_true", help="self-test only")
    ap.add_argument("--prior-skips", default=None)
    a = ap.parse_args(argv)
    root = a.root; out_dir = os.path.join(root, a.out); os.makedirs(out_dir, exist_ok=True)
    prefix = [] if a.uncontained else WRAPPER
    commit = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", root, "status", "--short"], capture_output=True, text=True).stdout.strip()
    surface_before = scientific_surface_hash(root)
    T0 = time.time()
    master_path = os.path.join(out_dir, "master_inventory.json")
    if a.mode in ("collect", "all"):
        master = collect_master(prefix, master_path, cwd=root)
        print("master inventory: %d nodeids in %d files, errors %d, hash %s, ok %s" % (
            master["collected_count"], len(master["files"]), len(master["collect_errors"]), master["inventory_hash"][:16], master["ok"]), flush=True)
        if not master["ok"]:
            print("COLLECTION FAILED -> R6 FAIL"); return 2
    else:
        master = json.load(open(master_path))
    if a.mode == "collect":
        return 0
    shards = shards_from_master(master)
    json.dump({"shard_law": SHARD_LAW, "count": len(shards), "shards": shards, "hash": canon_hash([s["expected_hash"] for s in shards])},
              open(os.path.join(out_dir, "shard_plan.json"), "w"), indent=1)
    print("shards: %d (one module per fresh process)" % len(shards), flush=True)
    recs = []
    for s in shards:
        r = run_shard(s, prefix, out_dir, cwd=root)
        recs.append(r)
        res = r.get("resource") or {}
        cg = (res.get("cgroup") or {}) if res else {}
        print("shard %3d/%d %-52s rc=%s %6.1fs rss=%6.1fMiB peak=%s oom=%d %s %s" % (
            s["index"] + 1, len(shards), s["module"][:52], r["returncode"], r["elapsed_s"], res.get("ru_maxrss_MiB", -1),
            (int(cg["memory_peak"]) // 1048576 if cg.get("memory_peak") else "?"), r["oom_delta"],
            "/".join("%s=%d" % (k, v) for k, v in (r.get("totals") or {}).items() if v), "OK" if r["ok"] else "PROBLEMS:" + ";".join(r["problems"])[:120]), flush=True)
    prior = json.load(open(a.prior_skips)) if a.prior_skips and os.path.exists(a.prior_skips) else None
    rec = reconcile(master, shards, recs, prior)
    surface_after = scientific_surface_hash(root)
    peaks = [int(r["resource"]["cgroup"]["memory_peak"]) for r in recs if r.get("resource") and r["resource"]["cgroup"].get("memory_peak")]
    art = {"name": RUNNER_VERSION, "repo_commit": commit, "worktree_dirty": bool(dirty),
           "scientific_surface_hash_before": surface_before["hash"], "scientific_surface_hash_after": surface_after["hash"],
           "scientific_contract_changed": surface_before["hash"] != surface_after["hash"], "surface_files": surface_before["files"],
           "master_inventory_hash": master["inventory_hash"], "master_count": master["collected_count"],
           "collection_env": master["env"], "runner_hash": runner_hash(), "plugin_hash": sha(Path(root, "regression/plugin.py").read_bytes()),
           "containment": {"wrapper": WRAPPER[0], "unit_memory_max": "1400M", "slice": "wmresearch.slice", "orchestrator": "uncontained light loop; every collection and shard process contained"} if prefix else {"uncontained_selftest": True},
           "shard_law": SHARD_LAW, "shard_count": len(shards), "shard_plan_hash": canon_hash([s["expected_hash"] for s in shards]),
           "shard_evidence_hashes": {r["module"]: sha(Path(r["report_path"]).read_bytes()) for r in recs if r.get("report_path")},
           "reconciliation": rec, "reconciliation_hash": canon_hash(rec),
           "totals": rec["totals"], "skip_manifest_hash": rec["skip_manifest"]["hash"],
           "elapsed_total_s": round(time.time() - T0, 1),
           "max_shard_memory_peak_MiB": (max(peaks) // 1048576) if peaks else None,
           "max_shard_ru_maxrss_MiB": max((r["resource"]["ru_maxrss_MiB"] for r in recs if r.get("resource")), default=None),
           "shard_oom_events": sum(r["oom_delta"] for r in recs), "fresh_process_per_shard": all(r["fresh_process"] for r in recs),
           "verdict": "PASS" if (rec["ok"] and surface_before["hash"] == surface_after["hash"] and sum(r["oom_delta"] for r in recs) == 0) else "FAIL",
           "shards": recs}
    json.dump(art, open(os.path.join(out_dir, "BOUNDED_FULL_REGRESSION_V0.json"), "w"), indent=1)
    print("totals", rec["totals"], "| missing %d unexpected %d dup %d unaccounted %d | shards failed %s | surface changed %s | max peak %s MiB | oom %d" % (
        len(rec["missing"]), len(rec["unexpected"]), len(rec["duplicates"]), len(rec["unaccounted"]), rec["shards_failed"][:5], art["scientific_contract_changed"], art["max_shard_memory_peak_MiB"], art["shard_oom_events"]))
    print("BOUNDED_FULL_REGRESSION_V0:", art["verdict"], "elapsed %.0fs" % art["elapsed_total_s"], flush=True)
    return 0 if art["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
