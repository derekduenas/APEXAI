"""WM-0E RESULT-INTEGRITY CLOSURE V1.1 -- real-path reproduction of Astra's three findings.

The V1 code (commit d0f3f967f) is loaded from the git object store, NOT from
the working tree, and exercised with the REAL identity helpers on a REAL
development cell produced by courts.final_court.run_cell on the development
qualification namespace. Then the repaired V1.1 code is run on the same
probes. Output: evidence/result_integrity_v1/REPAIR_EVIDENCE_V1_1_REPRODUCTION.json

No acceptance seed, no historical artifact, no statistical recomputation.
"""
import copy
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = "/opt/apex-research/world-model-shadow"
sys.path.insert(0, ROOT)
from courts import final_court as F                       # noqa: E402
from courts import result_validator as RV                 # noqa: E402
from courts import result_audit as RA                     # noqa: E402

BASE = "d0f3f967ff643399e4dca712c81fb97c15fba226"
FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"
OUT = ROOT + "/evidence/result_integrity_v1/REPAIR_EVIDENCE_V1_1_REPRODUCTION.json"


def load_base_module(rel_path, name):
    src = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (BASE, rel_path)], capture_output=True, text=True, check=True).stdout
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, name + ".py")
    open(p, "w").write(src)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod, src


def main():
    t0 = time.time()
    v1, v1_src = load_base_module("courts/result_validator.py", "result_validator_base_d0f3f96")
    _, audit_src = load_base_module("evidence/wm0e_result_integrity_audit.py", "audit_base_d0f3f96")
    assert getattr(v1, "VALIDATOR_VERSION", None) == "RESULT_VALIDATOR_V1", v1.VALIDATOR_VERSION
    out = {"base_commit": BASE, "base_validator_version": v1.VALIDATOR_VERSION, "repaired_validator_version": RV.VALIDATOR_VERSION,
           "method": "V1 code loaded from git object %s; real courts.final_court identity helpers; one real development cell per probe" % BASE[:9]}

    tmp = tempfile.mkdtemp()
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=F.QUALIFICATION_NAMESPACE, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    n0 = F.run_cell(defn, "N0", 0, tmp)                    # a two-world cell: has a companion seed
    out["fixture"] = {"namespace": defn.namespace, "purpose": defn.purpose, "control": "N0", "index": 0, "cell_id": n0["cell_id"],
                      "v1_accepts_genuine": v1.cell_failures(n0, defn) == [], "v11_accepts_genuine": RV.cell_failures(n0, defn) == []}

    # ---- FINDING 1: incomplete numeric validation
    probes = {}
    for name, mut in (("selector_G_hat_NaN", lambda c: c["block"]["selector_output"].__setitem__("G_hat", float("nan"))),
                      ("selector_K_N_True", lambda c: c["block"]["selector_output"].__setitem__("K_N", True)),
                      ("companion_seed_float", lambda c: c.__setitem__("companion_seed", float(c["companion_seed"])))):
        c = copy.deepcopy(n0); mut(c)
        f1 = v1.cell_failures(c, defn); f11 = RV.cell_failures(c, defn)
        probes[name] = {"V1_accepts": f1 == [], "V1_failures": f1[:3], "V1_1_refuses": bool(f11), "V1_1_reasons": f11[:3]}
    out["finding_1_incomplete_numeric_validation"] = {"probes": probes,
                                                      "reproduced": all(p["V1_accepts"] for p in probes.values()),
                                                      "repaired": all(p["V1_1_refuses"] for p in probes.values())}

    # ---- FINDING 2: final verdict did not enforce all recorded checks
    m = re.search(r'snap\["HISTORICAL_ARTIFACT_INTERNAL_CONSISTENCY"\] = (.*?)\n\s*snap\["elapsed_s"\]', audit_src, re.S)
    expr = m.group(1).strip() if m else None
    participating = sorted(set(re.findall(r'snap\["(\w+)"\]\["(\w+)"\]', expr or "")))
    recorded_not_enforced = [k for k in ("surface_unchanged_now", "runner_unchanged_now", "seed_manifest_hash_matches")
                             if k in audit_src and not any(k == p[1] for p in participating)]
    # evaluate the OLD expression on a fake snapshot with those three flags false and everything else true
    fake = {"definition": {"court_hash_matches": True, "surface_unchanged_now": False},
            "opening_marker": {"court_hash_matches": True, "precourt_regression_sha_matches": True, "runner_unchanged_now": False,
                               "seed_manifest_hash_matches": False},
            "frozen_judge_over_files_equals_stored_judgement": True}
    rep = {"ok": True}
    old_verdict = eval(expr, {"rep": rep, "snap": fake}) if expr else None   # noqa: S307 -- the sealed old expression, on synthetic flags
    # the repaired registry on the same three conditions: run on a scratch copy of the dev fixture court is not
    # possible (dev courts are NOT_ADJUDICABLE), so demonstrate the registry law directly:
    good = {c: {"status": "PASS"} for c in RA.CHECK_IDS}
    reg_cases = {}
    for cid in ("SURFACE_UNCHANGED", "RUNNER_UNCHANGED", "SEED_MANIFEST_LINKAGE"):
        bad = dict(good); bad[cid] = {"status": "FAIL"}; reg_cases[cid + "_FAIL"] = RA.overall_status(bad)
        bad = dict(good); bad[cid] = {"status": "BLOCKED"}; reg_cases[cid + "_BLOCKED"] = RA.overall_status(bad)
        bad = dict(good); del bad[cid]; reg_cases[cid + "_ABSENT"] = RA.overall_status(bad)
    out["finding_2_verdict_did_not_enforce_all_checks"] = {
        "old_expression": expr, "old_expression_participants": ["%s.%s" % p for p in participating],
        "recorded_but_not_enforced": recorded_not_enforced,
        "old_expression_with_those_three_false": old_verdict,
        "reproduced": old_verdict == "PASS" and len(recorded_not_enforced) == 3,
        "registry_version": RA.AUDIT_VERSION, "registry_required_checks": list(RA.CHECK_IDS),
        "registry_overall_when_each_fails_blocked_or_absent": reg_cases,
        "repaired": all(v != "PASS" for v in reg_cases.values())}

    # ---- FINDING 3: validator and commitment disagreed on legitimate infinities
    inf_cell = copy.deepcopy(n0)
    inf_cell["secondary"]["non_overlap_z"] = float("inf"); inf_cell["secondary"]["non_overlap_verdict"] = "SIGNAL_DETECTED"
    inf_cell["secondary"]["legacy_iid_z"] = float("-inf")
    v1_valid = v1.cell_failures(inf_cell, defn) == []
    try:
        v1.cell_digest(inf_cell); v1_commit = "ACCEPTED"
    except Exception as e:                                  # noqa: BLE001
        v1_commit = "REFUSED: %s" % e
    v11_valid = RV.cell_failures(inf_cell, defn) == []
    d = RV.cell_digest_v11(inf_cell)
    com = RV.court_commitment_v11([inf_cell]); ver = RV.verify_commitment_v11([inf_cell], com["root"], trusted_entries=com["entries"])
    flipped = copy.deepcopy(inf_cell); flipped["secondary"]["legacy_iid_z"] = float("inf")
    as_str = copy.deepcopy(inf_cell); as_str["secondary"]["legacy_iid_z"] = "-inf"
    try:
        RV.cell_digest_v11(as_str); str_digest_differs = RV.cell_digest_v11(as_str) != d; str_commit = "ACCEPTED_AS_STRING (digest differs: %s)" % str_digest_differs
    except RV.CommitmentFailure as e:
        str_commit = "REFUSED: %s" % e
    out["finding_3_validator_commitment_disagreement"] = {
        "fixture": "development N0 cell with secondary.non_overlap_z=+inf (verdict SIGNAL_DETECTED, consistent) and legacy_iid_z=-inf",
        "V1_validator_accepts": v1_valid, "V1_cell_digest": v1_commit, "reproduced": v1_valid and v1_commit.startswith("REFUSED"),
        "V1_1_validator_accepts": v11_valid, "V1_1_digest": d, "V1_1_commit_root": com["root"], "V1_1_verified": ver["verified"],
        "sign_flip_changes_digest": RV.cell_digest_v11(flipped) != d,
        "string_minus_inf": {"validator_refuses": bool(RV.cell_failures(as_str, defn)), "commitment": str_commit},
        "representation": com["representation"], "repaired": v11_valid and ver["verified"] and RV.cell_digest_v11(flipped) != d}
    out["elapsed_s"] = round(time.time() - t0, 1)
    out["all_three_reproduced_on_base"] = all(out[k]["reproduced"] for k in ("finding_1_incomplete_numeric_validation", "finding_2_verdict_did_not_enforce_all_checks", "finding_3_validator_commitment_disagreement"))
    out["all_three_repaired"] = all(out[k]["repaired"] for k in ("finding_1_incomplete_numeric_validation", "finding_2_verdict_did_not_enforce_all_checks", "finding_3_validator_commitment_disagreement"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1, default=str)
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("reproduced", "repaired", "probes", "recorded_but_not_enforced", "old_expression_with_those_three_false", "registry_overall_when_each_fails_blocked_or_absent", "V1_validator_accepts", "V1_cell_digest", "V1_1_verified", "sign_flip_changes_digest", "string_minus_inf")})
                      for k, v in out.items() if k not in ("method",)}, indent=1, default=str))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
