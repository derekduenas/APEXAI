"""WM-0E RESULT-INTEGRITY CLOSURE V1.1 -- RESULT_AUDIT_REGISTRY_V1.1 (Astra finding 2 + integration finding).

Every REQUIRED check is tested independently: starting from a valid fixture
(a scratch COPY of the sealed historical court, read-only source), that one
check is made to FAIL or become BLOCKED, and the overall status is proven
unable to remain PASS. The commitment VERSION CONTRACT is exercised through
the real run_audit entry point on a development court carrying a
producer-legitimate diagnostic infinity. The historical directory is never
opened for writing. No forecast or bootstrap is recomputed anywhere here.
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
COMMIT_CHECKS = ("COMMITMENT_AGREEMENT", "COMMITMENT_MATCHES_TRUSTED_ROOT")


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
    return RA.run_audit(court_dir, str(REPO), **kw)


def _edit_json(path, fn):
    d = json.load(open(path)); fn(d); json.dump(d, open(path, "w"), indent=1, default=str)


def _statuses(res, *ids):
    return {i: res["checks"][i]["status"] for i in ids}


def test_registry_is_explicit_and_versioned():
    assert RA.AUDIT_VERSION == "RESULT_AUDIT_REGISTRY_V1.1" and "V1" in RA.AUDIT_HISTORY and len(RA.REQUIRED_CHECKS) == 14
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


# ---------------------------------------------------------------- the version CONTRACT is fixed from caller inputs alone
def test_commitment_version_selection_is_explicit_and_deterministic():
    s = RA.select_commitment_versions(None, "a" * 64, None)
    assert s["required"] == ("V1",) and s["non_required"] == ("V1.1",) and s["selection"].startswith("derived")
    s = RA.select_commitment_versions(None, None, "b" * 64)
    assert s["required"] == ("V1.1",) and s["non_required"] == ("V1",)
    s = RA.select_commitment_versions(None, "a" * 64, "b" * 64)
    assert s["required"] == ("V1", "V1.1")
    s = RA.select_commitment_versions(None, None, None)
    assert s["required"] == () and s["non_required"] == ("V1", "V1.1")
    s = RA.select_commitment_versions(("V1.1",), "a" * 64, None)                 # explicit contract wins; the V1 root is NOT used
    assert s["required"] == ("V1.1",) and s["selection"] == "explicit" and s["supplied_but_not_required"] == ["V1"]
    s = RA.select_commitment_versions(("V1.1", "V1", "V1"), None, None)
    assert s["required"] == ("V1", "V1.1")                                       # canonical order, de-duplicated
    with pytest.raises(ValueError, match="unknown commitment version"):
        RA.select_commitment_versions(("V2",), None, None)


def test_pristine_copy_of_the_historical_court_passes_every_required_check(pristine, court):
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    bad = {k: v for k, v in res["checks"].items() if v["status"] != "PASS"}
    assert not bad, bad
    assert res["overall"] == "PASS" and res["exit_code"] == 0
    assert set(res["checks"]) == set(RA.CHECK_IDS)
    rc = res["checks"]["RECOUNT_MATCHES_STORED"]["evidence"]["recount"]
    assert {k: (v["detections"], v["direction"], v["verdict"]) for k, v in rc.items()} == {
        "N0": (1, 8, "PASS"), "N1": (1, 8, "PASS"), "N2": (0, 4, "PASS"), "N3": (0, 3, "PASS"), "N4": (0, 0, "PASS"), "P0": (45, 46, "PASS")}
    com = res["commitment"]
    assert com["V1"]["required"] is True and com["V1"]["executed"] is True and com["V1"]["root_files"] == pristine["trusted_v1"]
    assert com["V1.1"]["required"] is False and "NOT_REQUIRED" in com["V1.1"]["status"] and com["V1.1"]["informational_root_files"] != pristine["trusted_v1"]
    ev = res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["evidence"]
    assert ev["required_versions"] == ["V1"] and ev["executed_versions"] == ["V1"] and ev["non_required_versions"] == ["V1.1"]
    assert res["commitment_contract"]["selection"].startswith("derived")
    assert "NOT_PERFORMED" in res["historical_statistical_recomputation"]


def test_no_trusted_root_is_blocked_never_pass(court):
    res = _run(court)                                                            # no root, no explicit contract
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "BLOCKED", "COMMITMENT_MATCHES_TRUSTED_ROOT": "BLOCKED"}
    assert res["overall"] == "BLOCKED" and res["exit_code"] == 3
    assert res["commitment_contract"]["required"] == ()


def test_wrong_trusted_root_fails(court):
    res = _run(court, trusted_root_v1="0" * 64)
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL" and res["overall"] == "FAIL"
    res = _run(court, trusted_root_v11="0" * 64)
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}
    assert res["commitment"]["V1.1"]["verification_reason"].startswith("commitment root mismatch")


def test_finite_court_both_versions_required_both_must_verify(pristine, court):
    first = _run(court, trusted_root_v1=pristine["trusted_v1"], commitment_versions=("V1", "V1.1"))
    assert first["commitment"]["V1"]["verification"] == "PASS" and first["commitment"]["V1.1"]["verification"] == "BLOCKED"
    assert first["overall"] == "BLOCKED"                                        # V1.1 required, no V1.1 root: never PASS
    v11 = first["commitment"]["V1.1"]["root_files"]                              # obtained from a pristine read
    both = _run(court, trusted_root_v1=pristine["trusted_v1"], trusted_root_v11=v11, commitment_versions=("V1", "V1.1"))
    assert both["overall"] == "PASS"
    ev = both["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["evidence"]
    assert ev["required_versions"] == ev["executed_versions"] == ["V1", "V1.1"] and ev["non_required_versions"] == []
    wrong_v11 = _run(court, trusted_root_v1=pristine["trusted_v1"], trusted_root_v11="1" * 64)
    assert wrong_v11["commitment"]["V1"]["verification"] == "PASS" and wrong_v11["commitment"]["V1.1"]["verification"] == "FAIL"
    assert wrong_v11["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL" and wrong_v11["overall"] == "FAIL"
    wrong_v1 = _run(court, trusted_root_v1="1" * 64, trusted_root_v11=v11)
    assert wrong_v1["commitment"]["V1"]["verification"] == "FAIL" and wrong_v1["commitment"]["V1.1"]["verification"] == "PASS"
    assert wrong_v1["overall"] == "FAIL"
    # coherent alteration of one cell AND its aggregate twin: consistency passes, both commitments fail
    cp = os.path.join(court, "cells", "N2_05.json"); c = json.load(open(cp))
    step = 1.0 / RV.P_LATTICE if c["p"] < 1 else -1.0 / RV.P_LATTICE
    _edit_json(cp, lambda d: d.__setitem__("p", d["p"] + step))
    _edit_json(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"),
               lambda d: next(x for x in d["cells"] if x["control"] == "N2" and x["index"] == 5).__setitem__("p", c["p"] + step))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"], trusted_root_v11=v11)
    assert res["checks"]["CELL_VALIDATION"]["status"] == "PASS" and res["checks"]["AGGREGATE_AGREEMENT"]["status"] == "PASS"
    assert res["checks"]["COMMITMENT_AGREEMENT"]["status"] == "PASS"            # files and aggregate were altered together
    assert res["commitment"]["V1"]["verification"] == "FAIL" and res["commitment"]["V1.1"]["verification"] == "FAIL"
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "FAIL" and res["overall"] == "FAIL"


def test_explicit_v11_contract_ignores_a_supplied_v1_root_rather_than_silently_using_it(pristine, court):
    res = _run(court, trusted_root_v1=pristine["trusted_v1"], commitment_versions=("V1.1",))
    assert res["commitment_contract"]["supplied_but_not_required"] == ["V1"]
    assert res["commitment"]["V1"]["required"] is False and res["commitment"]["V1"]["trusted_root_supplied_but_ignored"] is True
    assert res["commitment"]["V1.1"]["verification"] == "BLOCKED"
    assert res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "BLOCKED" and res["overall"] != "PASS"


# ---------------------------------------------------------------- integration: a development court with a permitted diagnostic infinity
def _dev_court(dst, defn, cells):
    """A court directory in the runner's shape from in-memory cells (the
    cell files are rewritten so a test may carry altered diagnostics)."""
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


@pytest.fixture(scope="module")
def inf_dev(tmp_path_factory):
    """One real development N2 cell (real run_cell), then the frozen producer's
    zero-variance diagnostic outcome is placed on it: legacy_iid_z = -inf and
    non_overlap_z = +inf with its verdict kept consistent."""
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=F.QUALIFICATION_NAMESPACE, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    raw = F.run_cell(defn, "N2", 0, str(tmp_path_factory.mktemp("inf_raw")))
    cell = copy.deepcopy(raw)
    cell["secondary"]["legacy_iid_z"] = float("-inf")
    cell["secondary"]["non_overlap_z"] = float("inf"); cell["secondary"]["non_overlap_verdict"] = "SIGNAL_DETECTED"
    assert RV.cell_failures(cell, defn) == []                                  # legitimate under the producer contract
    trusted_v11 = RV.court_commitment_v11([cell])["root"]                       # computed from the pristine payload, held independently
    src = _dev_court(str(tmp_path_factory.mktemp("inf_court") / "court"), defn, [cell])
    return {"defn": defn, "cell": cell, "src": src, "trusted_v11": trusted_v11}


@pytest.fixture
def inf_court(inf_dev, tmp_path):
    dst = tmp_path / "court"; shutil.copytree(inf_dev["src"], dst)
    return str(dst)


def _alter_both(court_dir, fn):
    """Apply the same alteration to the cell file and its aggregate twin so
    file-vs-aggregate agreement stays intact and only the trusted root can tell."""
    _edit_json(os.path.join(court_dir, "cells", "N2_00.json"), fn)
    _edit_json(os.path.join(court_dir, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"), lambda d: fn(d["cells"][0]))


def test_v11_only_with_permitted_infinity_passes_both_commitment_checks(inf_dev, inf_court):
    res = _run(inf_court, trusted_root_v11=inf_dev["trusted_v11"], expected_indices=[0])
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "PASS"}
    assert res["checks"]["CELL_VALIDATION"]["status"] == "PASS"                # the infinity is legitimate
    ev = res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["evidence"]
    assert ev["required_versions"] == ev["executed_versions"] == ["V1.1"] and ev["non_required_versions"] == ["V1"]
    assert res["commitment"]["V1"]["required"] is False and "informational_error" in res["commitment"]["V1"]   # V1 cannot serialise; irrelevant
    # isolation: the only non-PASS checks are the ones a one-control development court cannot satisfy
    non_pass = {k for k, v in res["checks"].items() if v["status"] != "PASS"}
    assert non_pass == {"INVENTORY", "RUNNER_UNCHANGED", "OPENING_MARKER_IDENTITY", "SEED_MANIFEST_LINKAGE", "REGRESSION_LINKAGE",
                        "RECOUNT_MATCHES_STORED"}, non_pass
    assert res["overall"] != "PASS"


def test_v11_infinity_sign_flip_fails_the_trusted_root(inf_dev, inf_court):
    _alter_both(inf_court, lambda c: c["secondary"].__setitem__("legacy_iid_z", float("inf")))
    res = _run(inf_court, trusted_root_v11=inf_dev["trusted_v11"], expected_indices=[0])
    assert res["checks"]["CELL_VALIDATION"]["status"] == "PASS"                # still a legitimate value
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}


def test_v11_coherent_payload_alteration_fails_the_trusted_root(inf_dev, inf_court):
    p = inf_dev["cell"]["p"]; step = 1.0 / RV.P_LATTICE if p < 1 else -1.0 / RV.P_LATTICE
    _alter_both(inf_court, lambda c: c.__setitem__("p", p + step))
    res = _run(inf_court, trusted_root_v11=inf_dev["trusted_v11"], expected_indices=[0])
    assert res["checks"]["CELL_VALIDATION"]["status"] == "PASS"
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}


def test_v11_wrong_root_fails_and_no_root_is_blocked(inf_dev, inf_court):
    res = _run(inf_court, trusted_root_v11="2" * 64, expected_indices=[0])
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}
    res = _run(inf_court, expected_indices=[0])
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "BLOCKED", "COMMITMENT_MATCHES_TRUSTED_ROOT": "BLOCKED"}
    res = _run(inf_court, commitment_versions=("V1.1",), expected_indices=[0])   # required, but no root
    assert res["commitment"]["V1.1"]["verification"] == "BLOCKED" and res["checks"]["COMMITMENT_MATCHES_TRUSTED_ROOT"]["status"] == "BLOCKED"


def test_v1_required_on_an_infinity_payload_fails_without_falling_back(inf_dev, inf_court):
    res = _run(inf_court, trusted_root_v1="3" * 64, expected_indices=[0])
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "FAIL", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}
    assert "non-finite" in res["commitment"]["V1"]["files_error"] and res["commitment"]["V1.1"]["required"] is False
    both = _run(inf_court, trusted_root_v1="3" * 64, trusted_root_v11=inf_dev["trusted_v11"], expected_indices=[0])
    assert both["commitment"]["V1.1"]["verification"] == "PASS" and both["commitment"]["V1"]["verification"] == "FAIL"
    assert _statuses(both, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "FAIL", "COMMITMENT_MATCHES_TRUSTED_ROOT": "FAIL"}   # both required: both must verify


def test_nan_and_infinity_outside_permitted_fields_still_fail_validation_and_commitment(inf_dev, inf_court):
    _alter_both(inf_court, lambda c: c["secondary"].__setitem__("hac_t", float("inf")))
    res = _run(inf_court, trusted_root_v11=inf_dev["trusted_v11"], expected_indices=[0])
    assert res["checks"]["CELL_VALIDATION"]["status"] == "FAIL"
    assert res["checks"]["COMMITMENT_AGREEMENT"]["status"] == "FAIL" and "only admitted" in res["commitment"]["V1.1"]["files_error"]


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
    assert res["commitment"]["V1"]["agreement"] == "FAIL"


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


def test_missing_aggregate_does_not_block_trusted_root_verification_of_the_files(pristine, court):
    """Isolation: without an aggregate, AGREEMENT is BLOCKED (nothing to agree
    with) but the files still verify against the trusted root."""
    os.remove(os.path.join(court, "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json"))
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "BLOCKED", "COMMITMENT_MATCHES_TRUSTED_ROOT": "PASS"}


def test_corrupt_definition_is_BLOCKED(pristine, court):
    open(os.path.join(court, "court_definition.json"), "w").write("{not json")
    res = _run(court, trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["DEFINITION_REDERIVES"]["status"] == "BLOCKED" and res["overall"] != "PASS"


def test_surface_BLOCKED_when_root_has_no_world_model(pristine, court, tmp_path):
    res = RA.run_audit(court, str(tmp_path / "empty"), trusted_root_v1=pristine["trusted_v1"])
    assert res["checks"]["SURFACE_UNCHANGED"]["status"] == "BLOCKED" and res["overall"] != "PASS"


# ---------------------------------------------------------------- a partial (development) court is never adjudicable
def test_partial_development_court_is_BLOCKED_not_PASS(inf_dev, tmp_path):
    defn = inf_dev["defn"]
    cells = [copy.deepcopy(inf_dev["cell"])]
    cells[0]["secondary"]["legacy_iid_z"] = -4.0; cells[0]["secondary"]["non_overlap_z"] = -1.0; cells[0]["secondary"]["non_overlap_verdict"] = "NO_SIGNAL"
    out = _dev_court(str(tmp_path / "dev"), defn, cells)
    trusted = RV.court_commitment(cells)["root"]
    res = RA.run_audit(out, str(REPO), trusted_root_v1=trusted, expected_indices=[0])
    assert res["checks"]["INVENTORY"]["status"] == "FAIL"                     # only N2 present of six controls
    assert res["checks"]["RECOUNT_MATCHES_STORED"]["status"] == "BLOCKED"
    assert _statuses(res, *COMMIT_CHECKS) == {"COMMITMENT_AGREEMENT": "PASS", "COMMITMENT_MATCHES_TRUSTED_ROOT": "PASS"}
    assert res["overall"] != "PASS"
