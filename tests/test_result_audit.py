"""WM-0E RESULT-INTEGRITY CLOSURE V1.1 -- RESULT_AUDIT_REGISTRY_V1 (Astra finding 2).

Every REQUIRED check is tested independently: starting from a valid fixture
(a scratch COPY of the sealed historical court, read-only source), that one
check is made to FAIL or become BLOCKED, and the overall status is proven
unable to remain PASS. The historical directory is never opened for
writing. No forecast or bootstrap is recomputed anywhere here.
"""
import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from courts import final_court as F
from courts import result_audit as RA
from courts import result_validator as RV

REPO = Path(__file__).resolve().parents[1]
HIST = REPO / "evidence" / "final_court_v1"
SNAP_V1 = REPO / "evidence" / "result_integrity_v1" / "POST_HOC_AUDIT_SNAPSHOT_V1.json"
FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    if not HIST.is_dir() or not SNAP_V1.exists():
        pytest.fail("sealed historical court or V1 snapshot absent from this checkout -- the registry cannot be tested against nothing")
    dst = tmp_path_factory.mktemp("hist") / "court"
    shutil.copytree(HIST, dst)
    for p in dst.rglob("*"):
        if p.is_file():
            os.chmod(p, 0o644)                                                 # scratch copy is writable; source untouched
    trusted_v1 = json.load(open(SNAP_V1))["post_hoc_commitment"]["root_over_cell_files"]   # anchored at commit 9d1fca897
    return {"dir": str(dst), "trusted_v1": trusted_v1}


@pytest.fixture
def court(pristine, tmp_path):
    dst = tmp_path / "court"
    shutil.copytree(pristine["dir"], dst)
    return str(dst)


def _run(court_dir, **kw):
    kw.setdefault("trusted_root_v1", None)
    return RA.run_audit(court_dir, str(REPO), **kw)


def _edit_json(path, fn):
    d = json.load(open(path)); fn(d); json.dump(d, open(path, "w"), indent=1, default=str)


def test_registry_is_explicit_and_versioned():
    assert RA.AUDIT_VERSION == "RESULT_AUDIT_REGISTRY_V1" and len(RA.REQUIRED_CHECKS) == 14
    for cid in ("SURFACE_UNCHANGED", "RUNNER_UNCHANGED", "SEED_MANIFEST_LINKAGE", "REGRESSION_LINKAGE", "INVENTORY",
                "CELL_VALIDATION", "AGGREGATE_AGREEMENT", "RECOUNT_MATCHES_STORED", "COMMITMENT_AGREEMENT", "COMMITMENT_MATCHES_TRUSTED_ROOT"):
        assert cid in RA.CHECK_IDS
    good = {c: {"status": "PASS"} for c in RA.CHECK_IDS}
    assert RA.overall_status(good) == "PASS"
    for cid in RA.CHECK_IDS:
        for bad_status in ("FAIL", "BLOCKED", "UNKNOWN"):
            bad = dict(good); bad[cid] = {"status": bad_status}
            assert RA.overall_status(bad) != "PASS", (cid, bad_status)
        absent = dict(good); del absent[cid]
        assert RA.overall_status(absent) == "BLOCKED", cid
    mixed = dict(good); mixed["INVENTORY"] = {"status": "BLOCKED"}; mixed["CELL_VALIDATION"] = {"status": "FAIL"}
    assert RA.overall_status(mixed) == "FAIL"                                   # FAIL dominates BLOCKED
    assert RA.EXIT_CODES == {"PASS": 0, "FAIL": 2, "BLOCKED": 3}


def test_pristine_copy_of_the_historical_court_passes_every_required_check(pristine, court):
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    bad = {k: v for k, v in res["checks"].items() if v["status"] != "PASS"}
    assert not bad, bad
    assert res["overall"] == "PASS" and res["exit_code"] == 0
    assert set(res["checks"]) == set(RA.CHECK_IDS)
    rc = res["checks"]["RECOUNT_MATCHES_STORED"]["evidence"]["recount"]
    assert {k: (v["detections"], v["direction"], v["verdict"]) for k, v in rc.items()} == {
        "N0": (1, 8, "PASS"), "N1": (1, 8, "PASS"), "N2": (0, 4, "PASS"), "N3": (0, 3, "PASS"), "N4": (0, 0, "PASS"), "P0": (45, 46, "PASS")}
    assert res["commitment"]["v1"]["root"] == pristine["trusted_v1"]
    assert res["commitment"]["v11"]["version"] == "RESULT_COMMITMENT_V1.1" and res["commitment"]["v11"]["root"] != pristine["trusted_v1"]
    assert "NOT_PERFORMED" in res["historical_statistical_recomputation"]


def test_no_trusted_root_is_blocked_never_pass(court):
    res = _run(court)                                                            # no trusted root supplied
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "BLOCKED"
    assert res["overall"] == "BLOCKED" and res["exit_code"] == 3


def test_wrong_trusted_root_fails(court):
    res = _run(court, trusted_root_v1="0" * 64)
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL" and res["overall"] == "FAIL"
    res = _run(court, trusted_root_v11="0" * 64)
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL"


def test_v11_trusted_root_from_a_pristine_read_verifies_and_a_coherent_change_fails(pristine, court):
    v11 = _run(court, trusted_root_v1=pristine["trusted_v1"])["commitment"]["v11"]["root"]   # obtained from the pristine copy
    assert _run(court, trusted_root_v1=pristine["trusted_v1"], trusted_root_v11=v11)["overall"] == "PASS"
    # coherent alteration of one cell AND its aggregate twin: consistency passes, commitments fail
    cp = os.path.join(court, "cells", "N2_05.json"); c = json.load(open(cp))
    step = 1.0 / RV.P_LATTICE if c["p"] < 1 else -1.0 / RV.P_LATTICE
    _edit_json(cp, lambda d: d.__setitem__("p", d["p"] + step))
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: next(x for x in d["cells"] if x["control"] == "N2" and x["index"] == 5).__setitem__("p", c["p"] + step))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"], trusted_root_v11=v11)
    assert res["checks"]["CELL_VALIDATION"]["status"] == "PASS" and res["checks"]["AGGREGATE_AGREEMENT"]["status"] == "PASS"
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL"
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["evidence"]["v1_verified"] is False
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["evidence"]["v11_verified"] is False
    assert res["overall"] == "FAIL"


# ---------------------------------------------------------------- one test per required check: FAIL
def test_DEFINITION_REDERIVES_fails_on_a_tampered_court_hash(pristine, court):
    _edit_json(os.path.join(court, "court_definition.json"), lambda d: d.__setitem__("court_hash", "f" * 64))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["DEFINITION_REDERIVES"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_SURFACE_UNCHANGED_fails_when_the_scientific_surface_differs(pristine, court, tmp_path):
    root = tmp_path / "root"; (root / "apex").mkdir(parents=True)
    shutil.copytree(REPO / "apex" / "world_model", root / "apex" / "world_model", ignore=shutil.ignore_patterns("__pycache__"))
    with open(root / "apex" / "world_model" / "bootstrap.py", "a") as fh:
        fh.write("\n# one more line\n")
    res = RA.run_audit(court, str(root), trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["SURFACE_UNCHANGED"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert res["checks"]["SURFACE_UNCHANGED"]["evidence"]["sealed"] == FROZEN_SURFACE


def test_RUNNER_UNCHANGED_fails_when_the_marker_records_a_different_runner(pristine, court):
    _edit_json(os.path.join(court, "R7_1_COURT_OPENED.json"), lambda d: d.__setitem__("runner_sha256", "0" * 64))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["RUNNER_UNCHANGED"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_OPENING_MARKER_IDENTITY_fails_on_a_foreign_court_id(pristine, court):
    _edit_json(os.path.join(court, "R7_1_COURT_OPENED.json"), lambda d: d.__setitem__("court_id", "COURT-FINAL-000000000000"))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["OPENING_MARKER_IDENTITY"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_SEED_MANIFEST_LINKAGE_fails_when_the_marker_hash_differs(pristine, court):
    _edit_json(os.path.join(court, "R7_1_COURT_OPENED.json"), lambda d: d.__setitem__("seed_manifest_hash", "1" * 64))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["SEED_MANIFEST_LINKAGE"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert res["checks"]["RUNNER_UNCHANGED"]["status"] == "PASS"               # isolated: only the linkage broke


def test_REGRESSION_LINKAGE_fails_when_the_artifact_is_not_the_one_the_marker_bound(pristine, court):
    _edit_json(os.path.join(court, "precourt_regression", "BOUNDED_FULL_REGRESSION_V0.json"), lambda d: d.__setitem__("verdict", "PASS "))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["REGRESSION_LINKAGE"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_INVENTORY_fails_on_a_missing_cell(pristine, court):
    os.remove(os.path.join(court, "cells", "N3_17.json"))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["INVENTORY"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert res["checks"]["INVENTORY"]["evidence"]["missing"] == ["N3_17.json"]


def test_CELL_VALIDATION_fails_on_a_flipped_verdict(pristine, court):
    _edit_json(os.path.join(court, "cells", "N4_09.json"), lambda d: d.__setitem__("verdict", "SIGNAL_DETECTED"))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["CELL_VALIDATION"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert "N4_09.json" in res["checks"]["CELL_VALIDATION"]["evidence"]["failures"]


def test_CELL_VALIDATION_fails_on_nested_selector_nan_and_bool(pristine, court):
    _edit_json(os.path.join(court, "cells", "N2_01.json"), lambda d: d["block"]["selector_output"].__setitem__("G_hat", float("nan")))
    _edit_json(os.path.join(court, "cells", "N2_02.json"), lambda d: d["block"]["selector_output"].__setitem__("K_N", True))
    _edit_json(os.path.join(court, "cells", "N0_03.json"), lambda d: d.__setitem__("companion_seed", float(d["companion_seed"])))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    ev = res["checks"]["CELL_VALIDATION"]["evidence"]
    assert ev["failing_cells"] == 3 and res["overall"] == "FAIL"


def test_MANIFEST_AGREEMENT_fails_when_a_manifest_row_disagrees_with_its_cell(pristine, court):
    _edit_json(os.path.join(court, "seed_manifest.json"), lambda d: d["cells"][7].__setitem__("primary_seed", d["cells"][7]["primary_seed"] + 1))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["MANIFEST_AGREEMENT"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_AGGREGATE_AGREEMENT_fails_when_an_embedded_cell_differs_from_its_file(pristine, court):
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: next(x for x in d["cells"] if x["control"] == "P0" and x["index"] == 12).__setitem__("t_obs", 0.0))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["AGGREGATE_AGREEMENT"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_RECOUNT_MATCHES_STORED_fails_when_the_stored_verdict_disagrees_with_the_recount(pristine, court):
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: d["judgement"]["controls"]["N1"].__setitem__("verdict", "FAIL"))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["RECOUNT_MATCHES_STORED"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert res["checks"]["RECOUNT_MATCHES_STORED"]["evidence"]["verdicts_match_stored"] is False


def test_FROZEN_JUDGE_AGREES_fails_on_a_changed_diagnostic_in_the_stored_judgement(pristine, court):
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: d["judgement"]["controls"]["N3"].__setitem__("acf1_d_med", 0.0))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["FROZEN_JUDGE_AGREES"]["status"] == "FAIL" and res["overall"] == "FAIL"
    assert res["checks"]["AGGREGATE_AGREEMENT"]["status"] == "PASS"          # isolated: only the judge disagreement


def test_COMMITMENT_AGREEMENT_fails_when_files_and_aggregate_commit_to_different_payloads(pristine, court):
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: next(x for x in d["cells"] if x["control"] == "N0" and x["index"] == 22).__setitem__("sd_d", 1.0))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["COMMITMENT_AGREEMENT"]["status"] == "FAIL" and res["overall"] == "FAIL"


# ---------------------------------------------------------------- one test per required check: BLOCKED (evidence unavailable)
@pytest.mark.parametrize("remove,blocked", [
    ("court_definition.json", ("DEFINITION_REDERIVES", "OPENING_MARKER_IDENTITY", "INVENTORY", "CELL_VALIDATION")),
    ("R7_1_COURT_OPENED.json", ("RUNNER_UNCHANGED", "OPENING_MARKER_IDENTITY", "SEED_MANIFEST_LINKAGE", "REGRESSION_LINKAGE")),
    ("seed_manifest.json", ("SEED_MANIFEST_LINKAGE", "MANIFEST_AGREEMENT")),
    ("precourt_regression/BOUNDED_FULL_REGRESSION_V0.json", ("REGRESSION_LINKAGE",)),
    ("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json", ("AGGREGATE_AGREEMENT", "RECOUNT_MATCHES_STORED", "FROZEN_JUDGE_AGREES", "COMMITMENT_AGREEMENT")),
    ("cells", ("CELL_VALIDATION", "RECOUNT_MATCHES_STORED", "COMMITMENT_MATCHES_TRUSTED_ROOT")),
])
def test_missing_evidence_is_BLOCKED_never_PASS(pristine, court, remove, blocked):
    target = os.path.join(court, remove)
    shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    for cid in blocked:
        assert res["checks"][cid]["status"] == "BLOCKED", (remove, cid, res["checks"][cid])
    assert res["overall"] != "PASS" and res["exit_code"] != 0


def test_corrupt_definition_is_BLOCKED(pristine, court):
    open(os.path.join(court, "court_definition.json"), "w").write("{not json")
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["DEFINITION_REDERIVES"]["status"] == "BLOCKED" and res["overall"] != "PASS"


def test_surface_BLOCKED_when_root_has_no_world_model(pristine, court, tmp_path):
    res = RA.run_audit(court, str(tmp_path / "empty"), trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["SURFACE_UNCHANGED"]["status"] == "BLOCKED" and res["overall"] != "PASS"


# ---------------------------------------------------------------- a partial (development) court is never adjudicable
def test_partial_development_court_is_BLOCKED_not_PASS(tmp_path):
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=F.QUALIFICATION_NAMESPACE, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    out = str(tmp_path / "dev")
    cells = [F.run_cell(defn, "N2", 0, out)]
    json.dump(F.seed_manifest(F.QUALIFICATION_NAMESPACE), open(os.path.join(out, "seed_manifest.json"), "w"))
    json.dump({"definition": defn.canonical(), "court_hash": defn.court_hash}, open(os.path.join(out, "court_definition.json"), "w"))
    agg = {"court_id": defn.court_id, "court_hash": defn.court_hash, "code_commit": defn.code_commit, "precourt_tree_commit": "DEV",
           "surface_hash": FROZEN_SURFACE, "precourt_regression_artifact_sha256": "0" * 64, "cells_expected": 1, "cells_executed": 1,
           "duplicate_cells": 0, "missing_cells": 0, "integrity_failure": None, "judgement": F.judge(cells),
           "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1": "FAIL", "runner": F.RUNNER_VERSION, "oom_kill_before": 0, "oom_kill_after": 0,
           "elapsed_s": 1.0, "resource": {}, "cells": copy.deepcopy(cells)}
    json.dump(agg, open(os.path.join(out, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"), "w"), default=str)
    trusted = RV.court_commitment(cells)["root"]
    # expected_indices restricts inventory to what exists; the thresholds still cannot adjudicate 1 cell
    res = RA.run_audit(out, str(REPO), trusted_root_v1=trusted, expected_indices=[0])
    assert res["checks"]["INVENTORY"]["status"] == "FAIL"                     # only N2 present of six controls
    assert res["checks"]["RECOUNT_MATCHES_STORED"]["status"] == "BLOCKED"
    assert res["overall"] != "PASS"
