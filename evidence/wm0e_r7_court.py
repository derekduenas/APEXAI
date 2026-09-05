"""WM-0E-R7 court runner. Modes:
  predeclare <commit> <surface_hash>        -> seed manifest, collision audit, budget snapshot,
                                              court definition JSON (all BEFORE any outcome)
  open <commit> <surface_hash> <regression_artifact_path>
                                           -> verifies definition hash == committed, writes
                                              R7_COURT_OPENED once, runs all 300 cells, judges, seals
Contained. One sitting. No development."""
import json, os, sys, time, hashlib, resource
sys.path.insert(0, "/opt/apex-research/world-model-shadow")
from courts import final_court as F
from apex.world_model import bootstrap as BS
from apex.world_model.canonical import content_hash

ROOT = "/opt/apex-research/world-model-shadow"; OUT = ROOT + "/evidence/final_court"; os.makedirs(OUT, exist_ok=True)
CREATION_TIME = 1757000000.0

def oom_count():
    for line in open("/sys/fs/cgroup/wmresearch.slice/memory.events"):
        if line.startswith("oom_kill "): return int(line.split()[1])
    return 0

mode = sys.argv[1]
if mode == "predeclare":
    commit, surface = sys.argv[2], sys.argv[3]
    man = F.seed_manifest(); aud = F.collision_audit(man); snap = F.r7_budget_snapshot()
    json.dump({**man, "status": "SEALED_UNCONSUMED", "collision_audit": aud}, open(OUT + "/seed_manifest.json", "w"), indent=1)
    json.dump(snap, open(OUT + "/research_budget_final_pre_r7.json", "w"), indent=1)
    defn = F.define(commit, CREATION_TIME, surface)
    json.dump({"definition": defn.canonical(), "court_hash": defn.court_hash, "status": "SEALED_BEFORE_OUTCOMES",
               "R7_ACCEPTANCE_SET_STATUS": "SEALED_UNCONSUMED", "R7_PRIOR_SEED_COLLISIONS": aud["count"]},
              open(OUT + "/court_definition.json", "w"), indent=1)
    print("court_id", defn.court_id, "| court_hash", defn.court_hash[:16], "| manifest", man["manifest_hash"][:16], "seeds", man["all_seeds_count"],
          "| collisions", aud["count"], "| budget", snap["snapshot_hash"][:16], "ledger attempts", len(snap["ledger"]["attempts"]), "| cells expected", len(F.CONTROLS) * F.N_INDEX)
    sys.exit(0 if aud["count"] == 0 else 2)

if mode == "open":
    surface, reg_path, tree_commit = sys.argv[2], sys.argv[3], sys.argv[4]
    committed = json.load(open(OUT + "/court_definition.json"))
    commit = committed["definition"]["code_commit"]                 # the CODE commit the definition sealed
    defn = F.define(commit, CREATION_TIME, surface)
    if defn.court_hash != committed["court_hash"] or defn.court_id != committed["definition"]["court_id"]:
        raise F.CourtIntegrityFailure("court definition drifted from the committed one")
    reg = json.load(open(reg_path)); reg_sha = hashlib.sha256(open(reg_path, "rb").read()).hexdigest()
    if reg["verdict"] != "PASS" or reg["repo_commit"] != tree_commit or reg["scientific_contract_changed"] or reg["scientific_surface_hash_after"] != surface:
        raise F.CourtIntegrityFailure("pre-court regression not PASS on the exact pre-court tree")
    marker = OUT + "/R7_COURT_OPENED.json"
    if os.path.exists(marker):
        raise F.CourtIntegrityFailure("court already opened; R7 seeds are CONSUMED")
    oom0 = oom_count(); t0 = time.time()
    F._write_once(marker, {"R7_COURT_OPENED": True, "court_id": defn.court_id, "court_hash": defn.court_hash, "code_commit": commit,
                           "precourt_tree_commit": tree_commit, "tree_differs_from_code_commit_by": "sealed predeclaration evidence only (no code)",
                           "seed_manifest_hash": defn.seed_manifest_hash, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "precourt_regression_artifact_sha256": reg_sha, "acceptance_set": "CONSUMED from this instant",
                           "oom_kill_baseline": oom0})
    os.makedirs(OUT + "/cells", exist_ok=True)
    print("COURT OPENED", defn.court_id, "cells expected", len(F.CONTROLS) * F.N_INDEX, flush=True)
    cells, invalid = [], None
    try:
        for i in range(F.N_INDEX):
            for ctl in F.CONTROLS:
                c = F.run_cell(defn, ctl, i, OUT)
                cells.append(c)
                if oom_count() != oom0:
                    raise F.CourtIntegrityFailure("OOM during court")
            print("index %2d/50 done | " % (i + 1) + " ".join("%s:%s" % (c["control"], "DET" if c["verdict"] == "SIGNAL_DETECTED" else "no") for c in cells[-6:]), flush=True)
    except F.CourtIntegrityFailure as e:
        invalid = "%s: %s" % (type(e).__name__, e)
    except Exception as e:                                   # noqa: BLE001
        invalid = "UNEXPECTED %s: %s" % (type(e).__name__, str(e)[:300])
    verdict_doc = F.judge(cells) if cells else {"controls": {}, "cross_control": {}, "all_pass": False}
    ids = [c["cell_id"] for c in cells]
    status = "RUN_INVALID" if (invalid or len(cells) != len(F.CONTROLS) * F.N_INDEX or len(set(ids)) != len(ids)) else ("PASS" if verdict_doc["all_pass"] else "FAIL")
    out = {"court_id": defn.court_id, "court_hash": defn.court_hash, "code_commit": commit, "precourt_tree_commit": tree_commit, "surface_hash": surface,
           "precourt_regression_artifact_sha256": reg_sha, "cells_expected": len(F.CONTROLS) * F.N_INDEX, "cells_executed": len(cells),
           "duplicate_cells": len(ids) - len(set(ids)), "missing_cells": len(F.CONTROLS) * F.N_INDEX - len(cells),
           "integrity_failure": invalid, "judgement": verdict_doc, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V0": status,
           "oom_kill_before": oom0, "oom_kill_after": oom_count(), "elapsed_s": round(time.time() - t0, 1),
           "resource": {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), "cgroup": open("/proc/self/cgroup").read().strip()},
           "cells": cells}
    json.dump(out, open(OUT + "/FINAL_SYNTHETIC_ACCEPTANCE_COURT_V0.json", "w"), indent=1, default=str)
    for ctl, r in verdict_doc.get("controls", {}).items():
        extra = " dir %d/50" % r["direction"] if ctl == "P0" else ""
        print("%-3s %-30s det %2d/%d %s%s | p med %.3f | t med %+.2f | bl med %s | HAC %d NOV %d | eval %s train %s" % (
            ctl, r["identity"][:30], r["detections"], r["cells"], r["verdict"], extra, r["p"]["med"], r["t_obs"]["med"], r["block"]["med"], r["hac_detections"], r["non_overlap_detections"], r["usable_eval"], r["n_train"]), flush=True)
    print("overlap:", verdict_doc.get("cross_control", {}).get("overlap_by_index"), "| pooled:", verdict_doc.get("cross_control", {}).get("pooled_negative_detections"))
    print("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V0:", status, "| integrity:", invalid, "| oom", oom0, "->", out["oom_kill_after"], "| elapsed %.0fs rss %.0fMiB" % (out["elapsed_s"], out["resource"]["ru_maxrss_MiB"]), flush=True)
