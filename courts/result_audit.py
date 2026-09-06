"""RESULT_AUDIT_REGISTRY_V1 -- the required-check registry for a sealed court.

Astra's review of V1 found that the audit's final verdict was a hand-written
boolean expression that recorded some checks (surface unchanged, runner
unchanged, manifest linkage) without letting them participate. This module
replaces that expression with an explicit, versioned REGISTRY: every
required check has a status of PASS, FAIL or BLOCKED and carries its own
evidence; the overall status is PASS only when EVERY required check is
PASS. Missing or unreadable evidence is BLOCKED, never a silent PASS.

THIS IS A CONSISTENCY AUDIT, NOT A STATISTICAL REPRODUCTION. No world is
generated, no forecast produced, no bootstrap re-run. A PASS says the
artifacts are internally consistent with the sealed protocol and with each
other, and that their result fields agree with a separately trusted
commitment when one is supplied. It says nothing about markets.

TRUST MODEL (see result_validator): protocol sealed before outcomes; result
commitments anchored when results are produced; later reads verified against
a separately trusted root. The trusted roots are CALLER inputs here. Without
one the commitment check is BLOCKED, not PASS.
"""
from __future__ import annotations

import hashlib
import json
import os

from courts import final_court as F
from courts import result_validator as RV
from regression import runner as RR

AUDIT_VERSION = "RESULT_AUDIT_REGISTRY_V1"
PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
EXIT_CODES = {PASS: 0, FAIL: 2, BLOCKED: 3}

REQUIRED_CHECKS = (
    ("DEFINITION_REDERIVES", "court_definition.json re-derives through define(): court_id and court_hash match the sealed file"),
    ("SURFACE_UNCHANGED", "scientific_surface_hash(root) equals the definition's sealed scientific_surface_hash"),
    ("RUNNER_UNCHANGED", "sha256(courts/final_court.py) equals the opening marker's runner_sha256 and the definition's runner.source_sha256"),
    ("OPENING_MARKER_IDENTITY", "opening marker names this court (id, hash, version, code commit) and is a one-way open record"),
    ("SEED_MANIFEST_LINKAGE", "seed_manifest.json recomputes from its rows and equals the definition's and the marker's manifest hash"),
    ("REGRESSION_LINKAGE", "pre-court regression artifact: sha256 equals marker and aggregate, verdict PASS, repo_commit == opening commit, surface unchanged"),
    ("INVENTORY", "exactly one well-named cell file per expected (control, index); no missing, unexpected, misnamed or duplicate cells"),
    ("CELL_VALIDATION", "every cell passes the frozen reader AND RESULT_VALIDATOR (types, domains, provenance, decision consistency)"),
    ("MANIFEST_AGREEMENT", "every cell's primary and companion seed equals its sealed manifest row"),
    ("AGGREGATE_AGREEMENT", "aggregate artifact: identity, counts, embedded cells semantically equal to files, stored judgement equals recount"),
    ("RECOUNT_MATCHES_STORED", "detections/directions recounted from numeric fields with the sealed rule equal the stored strings and counts; verdicts recomputed from sealed thresholds equal stored verdicts and status"),
    ("FROZEN_JUDGE_AGREES", "courts.final_court.judge() over the cell files equals the stored judgement"),
    ("COMMITMENT_AGREEMENT", "RESULT_COMMITMENT (V1 and V1.1) roots over the cell files equal the roots over the aggregate's embedded cells"),
    ("COMMITMENT_MATCHES_TRUSTED_ROOT", "the V1 root over the cell files equals a trusted root supplied by the caller independently of the payload"),
)
CHECK_IDS = tuple(c for c, _ in REQUIRED_CHECKS)


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _load_json(path):
    """(doc, error) -- never raises; an unreadable artifact is BLOCKED evidence."""
    if not os.path.exists(path):
        return None, "absent: %s" % path
    try:
        return json.load(open(path)), None
    except (OSError, ValueError) as e:
        return None, "unreadable %s: %s" % (path, type(e).__name__)


def _check(status, **evidence):
    return {"status": status, "evidence": evidence}


def overall_status(checks: dict) -> str:
    """PASS only if every REQUIRED check is PASS; FAIL dominates BLOCKED;
    a required check absent from the registry is BLOCKED."""
    statuses = [checks.get(c, {}).get("status", BLOCKED) for c in CHECK_IDS]
    if any(s == FAIL for s in statuses):
        return FAIL
    if any(s != PASS for s in statuses):
        return BLOCKED
    return PASS


def run_audit(court_dir: str, root_dir: str, *, trusted_root_v1: str | None = None, trusted_root_v11: str | None = None,
              expected_indices=None, marker_name: str = "R7_1_COURT_OPENED.json",
              regression_rel: str = "precourt_regression/BOUNDED_FULL_REGRESSION_V0.json",
              aggregate_name: str = "FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1.json") -> dict:
    """Read-only. Returns the registry with an overall status and exit code."""
    checks = {}
    out = {"audit_version": AUDIT_VERSION, "validator": RV.VALIDATOR_VERSION, "court_dir": court_dir, "root_dir": root_dir,
           "required_checks": [{"id": c, "requirement": r} for c, r in REQUIRED_CHECKS],
           "historical_statistical_recomputation": "NOT_PERFORMED (no world generated, no forecast, no bootstrap re-run)"}

    # ---- definition
    dd, err = _load_json(os.path.join(court_dir, "court_definition.json"))
    defn = None
    if err or not isinstance(dd, dict) or "definition" not in dd:
        checks["DEFINITION_REDERIVES"] = _check(BLOCKED, reason=err or "no 'definition' object")
    else:
        d = dd["definition"]
        try:
            defn = F.define(d["code_commit"], d["creation_time"], d["scientific_surface_hash"],
                            namespace=d["seeds"]["namespace"], purpose=d.get("purpose", "ACCEPTANCE"))
            ok = defn.court_id == d.get("court_id") and defn.court_hash == dd.get("court_hash") == d.get("court_hash", dd.get("court_hash"))
            checks["DEFINITION_REDERIVES"] = _check(PASS if ok else FAIL, court_id=defn.court_id, court_hash_recomputed=defn.court_hash,
                                                    court_hash_stored=dd.get("court_hash"), court_id_stored=d.get("court_id"),
                                                    sealed_status=dd.get("status"), namespace=defn.namespace, purpose=defn.purpose)
        except Exception as e:                                  # noqa: BLE001 -- refused definitions are FAIL evidence
            checks["DEFINITION_REDERIVES"] = _check(FAIL, reason="define() refused: %s: %s" % (type(e).__name__, e))
    out["definition"] = {"sealed_surface": (dd or {}).get("definition", {}).get("scientific_surface_hash") if isinstance(dd, dict) else None}

    # ---- surface
    sealed_surface = out["definition"]["sealed_surface"]
    try:
        now = RR.scientific_surface_hash(root_dir)["hash"] if os.path.isdir(os.path.join(root_dir, "apex", "world_model")) else None
    except Exception as e:                                      # noqa: BLE001
        now = None; surf_err = "%s: %s" % (type(e).__name__, e)
    else:
        surf_err = None if now else "apex/world_model absent under root_dir"
    if sealed_surface is None or now is None:
        checks["SURFACE_UNCHANGED"] = _check(BLOCKED, sealed=sealed_surface, now=now, reason=surf_err or "no sealed surface in definition")
    else:
        checks["SURFACE_UNCHANGED"] = _check(PASS if now == sealed_surface else FAIL, sealed=sealed_surface, now=now)

    # ---- opening marker + runner
    mk, merr = _load_json(os.path.join(court_dir, marker_name))
    runner_now = _sha(F.__file__)
    if merr or not isinstance(mk, dict):
        checks["RUNNER_UNCHANGED"] = _check(BLOCKED, reason=merr or "marker not an object", runner_sha256_now=runner_now)
        checks["OPENING_MARKER_IDENTITY"] = _check(BLOCKED, reason=merr or "marker not an object")
    else:
        def_runner = (dd or {}).get("definition", {}).get("runner", {}).get("source_sha256") if isinstance(dd, dict) else None
        ok = (mk.get("runner_sha256") == runner_now and mk.get("runner") == F.RUNNER_VERSION
              and (def_runner is None or def_runner == runner_now))
        checks["RUNNER_UNCHANGED"] = _check(PASS if ok else FAIL, runner_sha256_now=runner_now, marker_runner_sha256=mk.get("runner_sha256"),
                                            definition_runner_sha256=def_runner, marker_runner=mk.get("runner"), runner_version_now=F.RUNNER_VERSION)
        if defn is None:
            checks["OPENING_MARKER_IDENTITY"] = _check(BLOCKED, reason="definition did not re-derive")
        else:
            opened_key = [k for k in mk if k.endswith("_COURT_OPENED")]
            ok = (mk.get("court_id") == defn.court_id and mk.get("court_hash") == defn.court_hash and mk.get("code_commit") == defn.code_commit
                  and mk.get("court_version") == F.COURT_VERSION and bool(opened_key) and mk.get(opened_key[0]) is True and bool(mk.get("utc")))
            checks["OPENING_MARKER_IDENTITY"] = _check(PASS if ok else FAIL, marker_court_id=mk.get("court_id"), marker_court_hash=mk.get("court_hash"),
                                                       marker_code_commit=mk.get("code_commit"), marker_version=mk.get("court_version"),
                                                       opened_flag={k: mk.get(k) for k in opened_key}, utc=mk.get("utc"),
                                                       opening_commit=mk.get("R7_1_OPENING_COMMIT") or mk.get("opening_commit"))

    # ---- the directory audit (inventory, cells, manifest, aggregate, recount)
    rep = None
    if defn is not None:
        rep = RV.audit_court(court_dir, defn, expected_indices=expected_indices, aggregate_name=aggregate_name)
        inv = rep["inventory"]
        inv_ok = (inv["cells_dir_present"] and not inv["missing"] and not inv["unexpected"] and not inv["misnamed"]
                  and not inv["duplicate_cell_ids"] and not inv["duplicate_control_index"] and inv["found_files"] == inv["expected"] > 0)
        checks["INVENTORY"] = _check(PASS if inv_ok else FAIL, **{k: (v if not isinstance(v, list) or len(v) < 20 else "%d items" % len(v))
                                                                   for k, v in inv.items()})
        if inv["found_files"] == 0 or not inv["cells_dir_present"]:
            checks["CELL_VALIDATION"] = _check(BLOCKED, reason="no cell files to validate")
        else:
            checks["CELL_VALIDATION"] = _check(PASS if not rep["cell_failures"] else FAIL, cells_read=len(rep["cells"]),
                                               failing_cells=len(rep["cell_failures"]),
                                               failures={k: v[:4] for k, v in list(rep["cell_failures"].items())[:10]})
        man = rep["manifest"]
        if man.get("status") != "PRESENT":
            checks["MANIFEST_AGREEMENT"] = _check(BLOCKED, reason="seed manifest absent")
        else:
            checks["MANIFEST_AGREEMENT"] = _check(PASS if not man["failures"] else FAIL, rows=man.get("rows"), failures=man["failures"][:10])
        ag = rep["aggregate"]
        if not ag.get("present"):
            checks["AGGREGATE_AGREEMENT"] = _check(BLOCKED, reason=ag.get("status"))
        else:
            checks["AGGREGATE_AGREEMENT"] = _check(PASS if not ag["failures"] else FAIL, stored_status=ag.get("status"), failures=ag["failures"][:10])
    else:
        for c in ("INVENTORY", "CELL_VALIDATION", "MANIFEST_AGREEMENT", "AGGREGATE_AGREEMENT"):
            checks[c] = _check(BLOCKED, reason="definition did not re-derive")

    # ---- seed manifest linkage (definition <-> marker <-> file)
    man_path = os.path.join(court_dir, "seed_manifest.json")
    mj, mjerr = _load_json(man_path)
    if defn is None or mjerr or not isinstance(mj, dict):
        checks["SEED_MANIFEST_LINKAGE"] = _check(BLOCKED, reason=mjerr or "definition did not re-derive")
    else:
        from apex.world_model.canonical import content_hash
        recomputed = content_hash(mj.get("cells", []))
        marker_hash = mk.get("seed_manifest_hash") if isinstance(mk, dict) else None
        if marker_hash is None:
            checks["SEED_MANIFEST_LINKAGE"] = _check(BLOCKED, reason="opening marker unavailable", file_hash=mj.get("manifest_hash"), recomputed=recomputed)
        else:
            ok = recomputed == mj.get("manifest_hash") == defn.seed_manifest_hash == marker_hash and mj.get("namespace") == defn.namespace
            checks["SEED_MANIFEST_LINKAGE"] = _check(PASS if ok else FAIL, file_hash=mj.get("manifest_hash"), recomputed=recomputed,
                                                     definition=defn.seed_manifest_hash, marker=marker_hash, namespace=mj.get("namespace"))

    # ---- regression linkage
    reg_path = os.path.join(court_dir, regression_rel)
    rj, rerr = _load_json(reg_path)
    agg, aerr = _load_json(os.path.join(court_dir, aggregate_name))
    if rerr or not isinstance(rj, dict) or not isinstance(mk, dict):
        checks["REGRESSION_LINKAGE"] = _check(BLOCKED, reason=rerr or "opening marker unavailable")
    else:
        reg_sha = _sha(reg_path)
        opening_commit = mk.get("R7_1_OPENING_COMMIT") or mk.get("opening_commit")
        agg_sha = agg.get("precourt_regression_artifact_sha256") if isinstance(agg, dict) else None
        ok = (reg_sha == mk.get("precourt_regression_artifact_sha256") and (agg_sha is None or agg_sha == reg_sha)
              and rj.get("verdict") == "PASS" and rj.get("repo_commit") == opening_commit and rj.get("worktree_dirty") is False
              and rj.get("scientific_contract_changed") is False and rj.get("scientific_surface_hash_after") == sealed_surface)
        checks["REGRESSION_LINKAGE"] = _check(PASS if ok else FAIL, artifact_sha256=reg_sha, marker_sha256=mk.get("precourt_regression_artifact_sha256"),
                                              aggregate_sha256=agg_sha, verdict=rj.get("verdict"), repo_commit=rj.get("repo_commit"),
                                              opening_commit=opening_commit, dirty=rj.get("worktree_dirty"),
                                              surface_after=rj.get("scientific_surface_hash_after"), totals=rj.get("totals"))

    # ---- recount vs stored; frozen judge; commitments
    if rep is None or not rep["cells"]:
        for c in ("RECOUNT_MATCHES_STORED", "FROZEN_JUDGE_AGREES", "COMMITMENT_AGREEMENT", "COMMITMENT_MATCHES_TRUSTED_ROOT"):
            checks[c] = _check(BLOCKED, reason="no validated cells")
    else:
        rc = rep["recount"]
        n_index = len(list(range(F.N_INDEX)) if expected_indices is None else list(expected_indices))
        stored_j = agg.get("judgement", {}) if isinstance(agg, dict) else {}
        stored_c = stored_j.get("controls", {}) if isinstance(stored_j, dict) else {}
        counts_ok = all(r["stored_matches_recount"] for r in rc["controls"].values())
        if n_index != F.N_INDEX:
            checks["RECOUNT_MATCHES_STORED"] = _check(BLOCKED, reason="thresholds are sealed for %d cells per control; %d present -> NOT_ADJUDICABLE" % (F.N_INDEX, n_index),
                                                      counts_match_stored=counts_ok, recount=rc["controls"])
        elif not isinstance(agg, dict):
            checks["RECOUNT_MATCHES_STORED"] = _check(BLOCKED, reason="aggregate unavailable", recount=rc["controls"])
        else:
            verd_ok = all(stored_c.get(k, {}).get("verdict") == r["verdict"] for k, r in rc["controls"].items())
            status_ok = agg.get("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1") == ("PASS" if rc["all_pass"] else "FAIL")
            full = len(rep["valid_cells"]) == len(F.CONTROLS) * F.N_INDEX
            checks["RECOUNT_MATCHES_STORED"] = _check(PASS if (counts_ok and verd_ok and status_ok and full) else FAIL,
                                                      counts_match_stored=counts_ok, verdicts_match_stored=verd_ok, status_matches=status_ok,
                                                      all_cells_valid=full, stored_status=agg.get("FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1"),
                                                      recount={k: {kk: v[kk] for kk in ("cells", "detections", "direction", "detected_indices", "verdict")}
                                                               for k, v in rc["controls"].items()}, recount_all_pass=rc["all_pass"])
        try:
            fj = F.judge(list(rep["cells"].values()))
            if not isinstance(agg, dict):
                checks["FROZEN_JUDGE_AGREES"] = _check(BLOCKED, reason="aggregate unavailable")
            else:
                checks["FROZEN_JUDGE_AGREES"] = _check(PASS if fj == stored_j else FAIL, equal=fj == stored_j,
                                                       frozen_all_pass=fj.get("all_pass"), stored_all_pass=stored_j.get("all_pass") if isinstance(stored_j, dict) else None)
        except Exception as e:                                  # noqa: BLE001
            checks["FROZEN_JUDGE_AGREES"] = _check(FAIL, reason="judge() raised %s: %s" % (type(e).__name__, e))
        try:
            files_v1 = RV.court_commitment(list(rep["cells"].values()))
            files_v11 = RV.court_commitment_v11(list(rep["cells"].values()))
            if isinstance(agg, dict) and isinstance(agg.get("cells"), list):
                agg_v1 = RV.court_commitment(agg["cells"]); agg_v11 = RV.court_commitment_v11(agg["cells"])
                ok = files_v1["root"] == agg_v1["root"] and files_v11["root"] == agg_v11["root"]
                checks["COMMITMENT_AGREEMENT"] = _check(PASS if ok else FAIL, v1_root_files=files_v1["root"], v1_root_aggregate=agg_v1["root"],
                                                        v11_root_files=files_v11["root"], v11_root_aggregate=agg_v11["root"])
            else:
                checks["COMMITMENT_AGREEMENT"] = _check(BLOCKED, reason="aggregate unavailable", v1_root_files=files_v1["root"], v11_root_files=files_v11["root"])
            out["commitment"] = {"v1": {"version": files_v1["version"], "root": files_v1["root"], "cells": files_v1["cells"]},
                                 "v11": {"version": files_v11["version"], "root": files_v11["root"], "cells": files_v11["cells"],
                                         "representation": files_v11["representation"], "entries": files_v11["entries"]}}
            if trusted_root_v1 is None and trusted_root_v11 is None:
                checks["COMMITMENT_MATCHES_TRUSTED_ROOT"] = _check(BLOCKED, reason="no trusted root supplied by the caller; a root stored next to the payload is not evidence",
                                                                   v1_root_files=files_v1["root"], v11_root_files=files_v11["root"])
            else:
                ev = {"v1_root_files": files_v1["root"], "v11_root_files": files_v11["root"], "trusted_root_v1": trusted_root_v1, "trusted_root_v11": trusted_root_v11}
                oks = []
                for label, root, fn in (("v1", trusted_root_v1, RV.verify_commitment), ("v11", trusted_root_v11, RV.verify_commitment_v11)):
                    if root is None:
                        continue
                    try:
                        fn(list(rep["cells"].values()), root); oks.append(True); ev[label + "_verified"] = True
                    except RV.CommitmentFailure as e:
                        oks.append(False); ev[label + "_verified"] = False; ev[label + "_reason"] = str(e)
                checks["COMMITMENT_MATCHES_TRUSTED_ROOT"] = _check(PASS if all(oks) else FAIL, **ev)
        except RV.CommitmentFailure as e:
            checks["COMMITMENT_AGREEMENT"] = _check(FAIL, reason=str(e))
            checks["COMMITMENT_MATCHES_TRUSTED_ROOT"] = _check(BLOCKED, reason="commitment could not be computed: %s" % e)

    out["checks"] = checks
    out["overall"] = overall_status(checks)
    out["exit_code"] = EXIT_CODES[out["overall"]]
    if rep is not None:
        out["report"] = {k: v for k, v in rep.items() if k not in ("cells", "valid_cells")}
    return out
