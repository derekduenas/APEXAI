"""WM-0E RESULT-INTEGRITY CLOSURE V1 -- read-only audit of the historical court.

Reads (never writes to) evidence/final_court_v1/: the sealed definition, the
opening marker, the seed manifest, all 300 cell files and the aggregate.
Runs RESULT_VALIDATOR_V1 over every artifact, recounts detections and
directions from validated numeric fields with the sealed rule, recomputes
the acceptance verdicts from the sealed thresholds, records per-file byte
hashes SEPARATELY from semantic equality, reproduces the original reader
gap on COPIES in a temporary directory, and computes a RESULT_COMMITMENT_V1
root over the historical cells.

THAT ROOT IS A POST-HOC AUDIT SNAPSHOT. It binds the artifacts from the
moment this script ran. It cannot establish that they were unaltered
between the court's sealing (2026-09-05T20:16Z) and now, and it does not
retroactively strengthen the original seal. No pre-outcome commitment of
result payloads exists for COURT-FINAL-f6ba5c856014.

Nothing statistical is recomputed: no world, no forecast, no bootstrap.
Output: evidence/result_integrity_v1/POST_HOC_AUDIT_SNAPSHOT_V1.json
"""
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
import time

ROOT = "/opt/apex-research/world-model-shadow"
sys.path.insert(0, ROOT)
from courts import final_court as F                       # noqa: E402
from courts import result_validator as RV                 # noqa: E402
from regression import runner as RR                       # noqa: E402

COURT = ROOT + "/evidence/final_court_v1"
OUT_DIR = ROOT + "/evidence/result_integrity_v1"
OUT = OUT_DIR + "/POST_HOC_AUDIT_SNAPSHOT_V1.json"


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    snap = {"LABEL": "POST_HOC_AUDIT_SNAPSHOT -- created AFTER outcomes (%s). NOT a pre-outcome seal. Cannot establish "
                     "pre-outcome integrity and does not strengthen the original seal." % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "validator": RV.VALIDATOR_VERSION, "commitment": RV.COMMITMENT_VERSION,
            "historical_statistical_recomputation": "NOT_PERFORMED (no world generated, no forecast, no bootstrap re-run)",
            "court_dir": COURT}

    # ---- definition: re-derived through the real identity helper
    dd = json.load(open(COURT + "/court_definition.json"))
    d = dd["definition"]
    defn = F.define(d["code_commit"], d["creation_time"], d["scientific_surface_hash"])
    snap["definition"] = {"file_sha256": sha(COURT + "/court_definition.json"), "status": dd.get("status"),
                          "court_id": defn.court_id, "court_hash_recomputed": defn.court_hash,
                          "court_hash_stored": dd["court_hash"], "court_hash_matches": defn.court_hash == dd["court_hash"] == d.get("court_hash", dd["court_hash"]),
                          "court_id_matches": defn.court_id == d["court_id"], "namespace": defn.namespace, "purpose": defn.purpose,
                          "seed_manifest_hash": defn.seed_manifest_hash, "surface_hash": d["scientific_surface_hash"],
                          "surface_hash_now": RR.scientific_surface_hash(ROOT)["hash"]}
    snap["definition"]["surface_unchanged_now"] = snap["definition"]["surface_hash_now"] == d["scientific_surface_hash"]

    # ---- opening marker
    op = json.load(open(COURT + "/R7_1_COURT_OPENED.json"))
    reg = COURT + "/precourt_regression/BOUNDED_FULL_REGRESSION_V0.json"
    snap["opening_marker"] = {"file_sha256": sha(COURT + "/R7_1_COURT_OPENED.json"), "utc": op.get("utc"),
                              "court_id_matches": op.get("court_id") == defn.court_id, "court_hash_matches": op.get("court_hash") == defn.court_hash,
                              "code_commit": op.get("code_commit"), "opening_commit": op.get("R7_1_OPENING_COMMIT"),
                              "runner": op.get("runner"), "runner_sha256_recorded": op.get("runner_sha256"),
                              "runner_sha256_now": sha(F.__file__), "runner_unchanged_now": sha(F.__file__) == op.get("runner_sha256"),
                              "seed_manifest_hash_matches": op.get("seed_manifest_hash") == defn.seed_manifest_hash,
                              "precourt_regression_sha_recorded": op.get("precourt_regression_artifact_sha256"),
                              "precourt_regression_sha_now": sha(reg), "precourt_regression_sha_matches": sha(reg) == op.get("precourt_regression_artifact_sha256"),
                              "oom_kill_baseline": op.get("oom_kill_baseline")}

    # ---- the audit proper (read-only)
    rep = RV.audit_court(COURT, defn)
    snap["audit"] = rep

    # ---- frozen judge() over the FILE cells, compared to the stored judgement (real helper, not a recount)
    agg = json.load(open(COURT + "/FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"))
    file_cells = [F.load_cell(os.path.join(COURT, "cells", n), defn) for n in sorted(os.listdir(COURT + "/cells")) if n.endswith(".json")]
    fj = F.judge(file_cells)
    snap["frozen_judge_over_files_equals_stored_judgement"] = (fj == agg["judgement"])
    snap["stored_status"] = agg.get("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1")

    # ---- byte hashes, reported separately from semantic equality
    snap["byte_hashes"] = {"cells": rep["file_sha256"], "aggregate": sha(COURT + "/FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
                           "seed_manifest": sha(COURT + "/seed_manifest.json"), "court_definition": sha(COURT + "/court_definition.json"),
                           "opening_marker": sha(COURT + "/R7_1_COURT_OPENED.json"), "budget_snapshot": sha(COURT + "/research_budget_final_pre_r7.json"),
                           "run_log": sha(COURT + "/run_log.txt"),
                           "note": "the aggregate embeds cell OBJECTS, not cell FILES; only semantic equality is meaningful between them"}
    snap["semantic_equality_individual_vs_aggregate"] = "PASS" if not any("aggregate counterpart" in f or "file counterpart" in f for f in rep["failures"]) else "FAIL"

    # ---- reproduction of the original reader gap on COPIES (originals untouched)
    repro = {"method": "copies of historical cells in a temporary directory; courts.final_court.load_cell with the real "
                       "identity helpers and the re-derived definition; originals never opened for writing"}
    with tempfile.TemporaryDirectory() as tmp:
        base = json.load(open(COURT + "/cells/N2_00.json"))
        os.makedirs(tmp + "/cells")
        json.dump(base, open(tmp + "/cells/N2_00.json", "w"), indent=1)
        repro["baseline_reader_accepts_genuine_copy"] = F.load_cell(tmp + "/cells/N2_00.json", defn)["cell_id"] == base["cell_id"]
        repro["baseline_validator_accepts_genuine_copy"] = RV.cell_failures(base, defn) == []
        for name, field, value in (("verdict_flipped", "verdict", "SIGNAL_DETECTED"), ("p_nan", "p", float("nan")), ("direction_flipped", "positive", True)):
            bad = copy.deepcopy(base); bad[field] = value
            p = "%s/cells/%s.json" % (tmp, name)
            json.dump(bad, open(p, "w"), indent=1)
            try:
                r = F.load_cell(p, defn)
                accepted = (math.isnan(r["p"]) if field == "p" else r[field] == value)
            except F.CourtIntegrityFailure as e:
                accepted = False; repro[name + "_reader_error"] = str(e)
            fails = RV.cell_failures(bad, defn)
            repro[name] = {"original_reader_accepts": accepted, "validator_refuses": bool(fails), "validator_reasons": fails[:3]}
    snap["original_reader_gap_reproduction"] = repro
    snap["ORIGINAL_READER_RESULT_VALIDATION"] = ("GAP_CONFIRMED" if all(repro[k]["original_reader_accepts"] and repro[k]["validator_refuses"]
                                                                       for k in ("verdict_flipped", "p_nan", "direction_flipped")) else "NOT_REPRODUCED")

    # ---- post-hoc commitment over the 300 historical FILE cells (and the aggregate's embedded copies)
    com_files = RV.court_commitment(file_cells)
    com_agg = RV.court_commitment(agg["cells"])
    snap["post_hoc_commitment"] = {"LABEL": "POST_HOC_AUDIT_SNAPSHOT -- computed after outcomes; NOT a pre-outcome commitment",
                                   "version": com_files["version"], "fields": com_files["fields"], "cells": com_files["cells"],
                                   "root_over_cell_files": com_files["root"], "root_over_aggregate_embedded_cells": com_agg["root"],
                                   "files_and_aggregate_roots_agree": com_files["root"] == com_agg["root"],
                                   "entries": com_files["entries"],
                                   "what_this_proves": "from now on, any change to an adjudication field of any of these 300 cells changes this root",
                                   "what_this_cannot_prove": "that the cells were not altered between 2026-09-05T20:16Z and this snapshot"}

    snap["HISTORICAL_ARTIFACT_INTERNAL_CONSISTENCY"] = "PASS" if (rep["ok"] and snap["definition"]["court_hash_matches"]
                                                                 and snap["opening_marker"]["court_hash_matches"]
                                                                 and snap["opening_marker"]["precourt_regression_sha_matches"]
                                                                 and snap["frozen_judge_over_files_equals_stored_judgement"]) else "FAIL"
    snap["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(snap, open(OUT, "w"), indent=1, default=str)

    rc = rep["recount"]["controls"]
    print("definition re-derived:", snap["definition"]["court_id_matches"], snap["definition"]["court_hash_matches"], "| surface unchanged:", snap["definition"]["surface_unchanged_now"])
    print("opening marker:", {k: v for k, v in snap["opening_marker"].items() if k.endswith("matches") or k.endswith("now") and isinstance(v, bool)})
    inv = rep["inventory"]
    print("inventory: expected %d found %d unique_ids %d missing %d unexpected %d misnamed %d dup_ids %d dup_keys %d" % (
        inv["expected"], inv["found_files"], inv["unique_cell_ids"], len(inv["missing"]), len(inv["unexpected"]), len(inv["misnamed"]),
        len(inv["duplicate_cell_ids"]), len(inv["duplicate_control_index"])))
    print("cell validation failures:", len(rep["cell_failures"]), "| manifest failures:", len(rep["manifest"].get("failures", [])),
          "| aggregate failures:", len(rep["aggregate"].get("failures", [])), "| all failures:", rep["failures"][:5])
    for ctl, r in rc.items():
        print("  %s recount det %2d dir %2d idx %s | stored det %2d pos %2d match %s | %s -> %s" % (
            ctl, r["detections"], r["direction"], r["detected_indices"], r["stored_verdict_detections"], r["stored_positive_count"],
            r["stored_matches_recount"], r["rule"], r["verdict"]))
    print("recount all_pass:", rep["recount"]["all_pass"], "| stored status:", snap["stored_status"], "| frozen judge == stored:", snap["frozen_judge_over_files_equals_stored_judgement"])
    print("reader gap:", snap["ORIGINAL_READER_RESULT_VALIDATION"], {k: (v["original_reader_accepts"], v["validator_refuses"]) for k, v in repro.items() if isinstance(v, dict)})
    print("post-hoc commitment root (files):", com_files["root"][:32], "| == aggregate root:", com_files["root"] == com_agg["root"])
    print("HISTORICAL_ARTIFACT_INTERNAL_CONSISTENCY:", snap["HISTORICAL_ARTIFACT_INTERNAL_CONSISTENCY"], "| elapsed %.1fs" % snap["elapsed_s"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
