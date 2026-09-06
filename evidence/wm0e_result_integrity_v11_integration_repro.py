"""WM-0E RESULT-INTEGRITY V1.1 INTEGRATION REPAIR -- real run_audit reproduction, before and after.

BEFORE: courts/result_audit.py as committed at a27a1275d (loaded from the git
object store, not the working tree) is run on a development court whose one
cell carries the frozen producer's diagnostic infinity, supplying ONLY a
correct V1.1 trusted root. Expected (Astra): COMMITMENT_AGREEMENT=FAIL and
COMMITMENT_MATCHES_TRUSTED_ROOT=BLOCKED, because V1 was computed first.
AFTER: the repaired module on the same court and root -> both PASS.

Development fixture only; no acceptance seed, no historical artifact touched,
no statistical recomputation.
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = "/opt/apex-research/world-model-shadow"
sys.path.insert(0, ROOT)
from courts import final_court as F                       # noqa: E402
from courts import result_validator as RV                 # noqa: E402
from courts import result_audit as RA                     # noqa: E402

BASE = "a27a1275d5645cd52d52f7e108e76dd97ad84d67"
FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"
OUT = ROOT + "/evidence/result_integrity_v1/REPAIR_EVIDENCE_V1_1_INTEGRATION_REPRODUCTION.json"


def load_base_audit():
    src = subprocess.run(["git", "-C", ROOT, "show", "%s:courts/result_audit.py" % BASE], capture_output=True, text=True, check=True).stdout
    p = os.path.join(tempfile.mkdtemp(), "result_audit_base_a27a127.py")
    open(p, "w").write(src)
    spec = importlib.util.spec_from_file_location("result_audit_base_a27a127", p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def dev_court(dst, defn, cells):
    os.makedirs(os.path.join(dst, "cells"))
    for c in cells:
        json.dump(c, open(os.path.join(dst, "cells", "%s_%02d.json" % (c["control"], c["index"])), "w"), indent=1)
    json.dump(F.seed_manifest(defn.namespace), open(os.path.join(dst, "seed_manifest.json"), "w"))
    json.dump({"definition": defn.canonical(), "court_hash": defn.court_hash}, open(os.path.join(dst, "court_definition.json"), "w"))
    agg = {"court_id": defn.court_id, "court_hash": defn.court_hash, "code_commit": defn.code_commit, "precourt_tree_commit": "DEV",
           "surface_hash": FROZEN_SURFACE, "precourt_regression_artifact_sha256": "0" * 64, "cells_expected": len(F.CONTROLS),
           "cells_executed": len(cells), "duplicate_cells": 0, "missing_cells": len(F.CONTROLS) - len(cells), "integrity_failure": None,
           "judgement": F.judge(cells),
           "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1": "FAIL", "runner": F.RUNNER_VERSION, "oom_kill_before": 0, "oom_kill_after": 0,
           "elapsed_s": 1.0, "resource": {}, "cells": copy.deepcopy(cells)}
    json.dump(agg, open(os.path.join(dst, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"), "w"), default=str)
    return dst


def main():
    t0 = time.time()
    base = load_base_audit()
    assert base.AUDIT_VERSION == "RESULT_AUDIT_REGISTRY_V1", base.AUDIT_VERSION
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=F.QUALIFICATION_NAMESPACE, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    raw = F.run_cell(defn, "N2", 0, tempfile.mkdtemp())
    cell = copy.deepcopy(raw)
    cell["secondary"]["legacy_iid_z"] = float("-inf")
    assert RV.cell_failures(cell, defn) == []
    trusted_v11 = RV.court_commitment_v11([cell])["root"]
    ver = RV.verify_commitment_v11([cell], trusted_v11)
    court = dev_court(os.path.join(tempfile.mkdtemp(), "court"), defn, [cell])

    def pick(res):
        return {k: res["checks"][k]["status"] for k in ("COMMITMENT_AGREEMENT", "COMMITMENT_MATCHES_TRUSTED_ROOT", "CELL_VALIDATION")}

    before = base.run_audit(court, ROOT, trusted_root_v1=None, trusted_root_v11=trusted_v11, expected_indices=[0])
    after = RA.run_audit(court, ROOT, trusted_root_v1=None, trusted_root_v11=trusted_v11, expected_indices=[0])
    b, a = pick(before), pick(after)
    out = {"base_commit": BASE, "base_audit_version": base.AUDIT_VERSION, "repaired_audit_version": RA.AUDIT_VERSION,
           "fixture": {"namespace": defn.namespace, "purpose": defn.purpose, "control": "N2", "index": 0, "cell_id": cell["cell_id"],
                       "diagnostic": "secondary.legacy_iid_z = -inf", "validator_accepts": True,
                       "v11_commit_and_verify_direct": ver["verified"], "trusted_root_v11": trusted_v11},
           "call": "run_audit(court, ROOT, trusted_root_v1=None, trusted_root_v11=<correct V1.1 root>, expected_indices=[0])",
           "before": {"statuses": b, "commitment_reason": before["checks"]["COMMITMENT_AGREEMENT"]["evidence"].get("reason"),
                      "reproduced": b["COMMITMENT_AGREEMENT"] == "FAIL" and b["COMMITMENT_MATCHES_TRUSTED_ROOT"] == "BLOCKED"},
           "after": {"statuses": a, "contract": after["commitment_contract"],
                     "per_version": {v: {k: e[k] for k in e if k in ("required", "executed", "status", "agreement", "verification", "files_error", "informational_error")}
                                     for v, e in after["commitment"].items()},
                     "repaired": a["COMMITMENT_AGREEMENT"] == "PASS" and a["COMMITMENT_MATCHES_TRUSTED_ROOT"] == "PASS"},
           "elapsed_s": round(time.time() - t0, 1)}
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print(json.dumps({k: out[k] for k in ("before", "after")}, indent=1, default=str))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
