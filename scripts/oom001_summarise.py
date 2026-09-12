"""REGRESSION-OOM-001: assemble the return evidence and reconcile the run
against the recorded previous regression, shard by shard."""
import json, subprocess

reg = json.load(open("/tmp/oom001_regression.json"))
pres = json.load(open("/tmp/oom001_preservation.json"))
prev = reg["previous_run"]
prev_tot, tot = prev["totals"], reg["totals"]

# ---- where every count difference comes from
def shard(mod):
    return next((s for s in reg["shard_detail"] if s["module"] == mod), None)

nr, mem = shard("tests/test_null_rig.py"), shard("tests/test_null_rig_memory.py")
recovered = nr["counts"].get("PASS", 0)
recovered_skip = nr["counts"].get("SKIP", 0)
new_guard = mem["counts"].get("PASS", 0)
expected_pass = prev_tot["PASS"] + recovered + new_guard
expected_skip = prev_tot["SKIP"] + recovered_skip

recon = {
 "previous": {"commit": prev["commit"], "shards": prev["shards"],
              "totals": prev_tot, "problem_shards": prev["problem_shards"],
              "verdict": prev["verdict"]},
 "this_run": {"commit": reg["commit"], "shards": reg["shards"], "totals": tot,
              "problem_shards": reg["problem_shards"], "verdict": reg["verdict"]},
 "shard_delta": reg["shards"] - prev["shards"],
 "shard_delta_explained": "tests/test_null_rig_memory.py, the new equivalence module",
 "pass_delta": tot["PASS"] - prev_tot["PASS"],
 "pass_delta_explained": {
    "recovered_from_the_previously_OOM_killed_module": recovered,
    "new_equivalence_guards": new_guard,
    "expected_total": expected_pass, "observed_total": tot["PASS"],
    "reconciles": expected_pass == tot["PASS"]},
 "skip_delta": tot["SKIP"] - prev_tot["SKIP"],
 "skip_delta_explained": {
    "recovered_pre_existing_DEFERRED_skip_in_test_null_rig": recovered_skip,
    "newly_introduced_skips": 0,
    "expected_total": expected_skip, "observed_total": tot["SKIP"],
    "reconciles": expected_skip == tot["SKIP"]},
 "fail_error": {"FAIL": tot.get("FAIL", 0), "ERROR": tot.get("ERROR", 0)},
 "accounting": {"collected": reg["collected_total"], "executed": reg["executed_total"],
                "every_collected_test_accounted_for":
                    reg["collected_total"] == reg["executed_total"]},
 "oom": {"slice_oom_kill_before": reg["slice_oom_kill_before"],
         "slice_oom_kill_after": reg["slice_oom_kill_after"],
         "new_oom_kills": reg["slice_oom_kill_after"] - reg["slice_oom_kill_before"],
         "shards_with_a_unit_oom": [s["module"] for s in reg["shard_detail"] if s["oomed"]]},
}

peaks = sorted((s["peak_mib"] or 0, s["module"]) for s in reg["shard_detail"])
doc = {
 "kind": "oom001_return", "version": "REGRESSION_OOM_001_V1",
 "defect": "TEST-NULL-RIG-MEMORY-001",
 "base_commit": pres["base"], "repair_commit": reg["commit"],
 "source_repair": {"branch": "world-model-shadow-v0", "commit": "dcc541c14",
                   "title": "WM-0E-R6.1 test-support repair"},
 "reconciliation": recon,
 "failing_module_verification": {
    "module": "tests/test_null_rig.py",
    "collected": nr["collected"], "executed": nr["executed"], "counts": nr["counts"],
    "peak_mib": nr["peak_mib"], "cap_mib": 1400, "unit_oom_kill": nr["unit_oom_kill"],
    "seconds": nr["seconds"], "collected_ids": nr["collected_ids"],
    "skip_reasons": nr["skipped_reasons"]},
 "new_module": {"module": "tests/test_null_rig_memory.py", "collected": mem["collected"],
                "counts": mem["counts"], "peak_mib": mem["peak_mib"],
                "collected_ids": mem["collected_ids"]},
 "preservation": pres,
 "memory": {"cap_mib_per_shard": 1400, "slice_ceiling": pres["containment"]["slice_max"],
            "highest_peak": {"mib": peaks[-1][0], "module": peaks[-1][1]},
            "top_five_peaks": [{"module": m, "peak_mib": p} for p, m in peaks[-5:][::-1]],
            "headroom_mib_at_the_worst_shard": round(1400 - peaks[-1][0], 1)},
 "all_skips": reg["all_skips"],
 "elapsed_s": reg["elapsed_s"],
}
doc["verdict"] = "PASS" if all([
    reg["verdict"] == "PASS", recon["pass_delta_explained"]["reconciles"],
    recon["skip_delta_explained"]["reconciles"],
    recon["accounting"]["every_collected_test_accounted_for"],
    recon["oom"]["new_oom_kills"] == 0, not recon["oom"]["shards_with_a_unit_oom"],
    tot.get("FAIL", 0) == 0, tot.get("ERROR", 0) == 0, pres["all_preserved"]]) else "FAIL"

json.dump(doc, open("/opt/apex-repo/results/oom001_RETURN.json", "w"), indent=1)
json.dump(reg, open("/opt/apex-repo/results/oom001_bounded_regression.json", "w"), indent=1)

print("VERDICT:", doc["verdict"])
print("shards %d (prev %d, %+d)" % (reg["shards"], prev["shards"], recon["shard_delta"]))
print("totals :", json.dumps(tot))
print("prev   :", json.dumps(prev_tot))
print("PASS  %d = %d prev + %d recovered + %d new  -> reconciles %s"
      % (tot["PASS"], prev_tot["PASS"], recovered, new_guard,
         recon["pass_delta_explained"]["reconciles"]))
print("SKIP  %d = %d prev + %d recovered pre-existing + 0 new -> reconciles %s"
      % (tot["SKIP"], prev_tot["SKIP"], recovered_skip,
         recon["skip_delta_explained"]["reconciles"]))
print("collected %d == executed %d : %s" % (reg["collected_total"], reg["executed_total"],
      recon["accounting"]["every_collected_test_accounted_for"]))
print("slice oom %d -> %d (new %d)" % (recon["oom"]["slice_oom_kill_before"],
      recon["oom"]["slice_oom_kill_after"], recon["oom"]["new_oom_kills"]))
print("problem shards:", reg["problem_shards"] or "none")
print("worst peak: %.1f MiB (%s), headroom %.1f MiB"
      % (peaks[-1][0], peaks[-1][1], doc["memory"]["headroom_mib_at_the_worst_shard"]))
print("preservation all_preserved:", pres["all_preserved"])
