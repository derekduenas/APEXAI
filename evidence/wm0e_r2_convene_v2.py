"""Seal NULL_COURT_V2, run it ONCE, persist everything. Nothing is decided after.
Usage: convene_v2.py <code_commit> <calibration.json> <out.json>"""
import json, sys, time, resource
from apex.world_model.court_v2 import convene_v2
from apex.world_model import bootstrap as BS
COMMIT, CAL, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
t0 = time.time()
defn, res = convene_v2(code_commit=COMMIT, creation_time=1756900000.0, calibration_path=CAL)
out = {"definition": defn.canonical(), "court_hash": res["court_hash"],
       "bootstrap_contract_hash": BS.content_identity(),
       "results": res["results"], "verdicts": res["verdicts"],
       "court_pass": res["court_pass"], "elapsed_s": round(time.time() - t0, 1),
       "resource_truth": {"ru_maxrss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), "cgroup": open("/proc/self/cgroup").read().strip(), "unit_memory_max": open("/sys/fs/cgroup" + open("/proc/self/cgroup").read().strip().split("::")[-1] + "/memory.max").read().strip(), "bootstrap_B": BS.B_REPLICATIONS, "cells_completed": sum(len(r["cells"]) for r in res["results"].values())}}
json.dump(out, open(OUT, "w"), indent=1, default=str)
print("court_id   :", defn.court_id); print("court_hash :", res["court_hash"]); print("elapsed    : %.1fs" % out["elapsed_s"]); print()
print("%-4s %-16s %3s %4s  %-7s %-7s %-6s %-6s %-14s %s" % ("ctl", "verdict", "n", "det", "p_med", "t_med", "bl_med", "hacdet", "iid_z_med", "note"))
for c, r in res["results"].items():
    j = r["judgement"]
    if j["court_verdict"] == "INVALID":
        print("%-4s %-16s %3d  %s" % (c, j["court_verdict"], j["n"], j["errors"][:1])); continue
    s = j["secondary_diagnostics"]
    note = ("exp %.2f max %d" % (j["expected_false_positives_nominal"], j["max_tolerated"]) if c != "P0"
            else "det_rate %.2f dir %.2f" % (j["detection_rate"], j["positive_direction_rate"]))
    print("%-4s %-16s %3d %4d  %-7.3f %+-7.2f %-6d %-6d %+-14.2f %s" % (
        c, j["court_verdict"], j["n"], j["detections"], j["p_bootstrap"]["median"], j["t_obs"]["median"],
        j["block_length"]["median"], s["hac_detections"], s["legacy_iid_z"]["median"], note))
print(); print("COURT_PASS :", res["court_pass"])
