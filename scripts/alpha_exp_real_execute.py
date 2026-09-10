#!/usr/bin/env python3
"""Registered experiments on REAL historical data -- executable only under a
verified, SIGNED admission decision. Without one, the only output is a named
refusal.

    alpha_exp_real_execute.py --decision PATH --plan      # list what WOULD run; opens no rows
    alpha_exp_real_execute.py --decision PATH --execute   # train + validation; evaluation stays SEALED

Process outcomes (exit code):
    0  SCIENTIFIC_COMPLETE        READY / NO_OPPORTUNITY / NO_SIGNAL / EVALUATION_NO_SIGNAL, or PLAN
    3  AUTHORIZATION_REFUSED      no/invalid decision, or admission refused during the run
    4  EVALUATION_SEALED          validation SIGNAL_DETECTED; evaluation remains sealed (expected)
    5  INVALID_INPUT_OR_FAILURE   INVALID_INPUT, INSUFFICIENT_EVIDENCE, or an execution error
    2  usage

Evaluation unsealing is NOT a flag here; it is a separate authorization and
a separate command. Every run gets a unique, exclusively created directory
with immutable identity/authority records and exactly one sealed result.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback

from apex.world_model.exp001b import run as R
from apex.world_model.exp001b.registration import EXPERIMENT_ID as EXP001B_ID, INSTRUMENT, PERIODS, registration_hash
from apex.world_model.exp002 import historical as H2
from apex.world_model.exp002.registration import EXPERIMENT_ID as EXP002_ID
from apex.world_model.exp002.registration import registration_hash as exp002_registration_hash
from apex.world_model.exp004 import historical as H4
from apex.world_model.exp004.registration import EXPERIMENT_ID as EXP004_ID
from apex.world_model.exp004.registration import registration_hash as exp004_registration_hash
from apex.world_model.real_data import boundary, loader
from apex.world_model.real_data.boundary import RealDataRefused

# One governed path, two registered experiments. The decision must name the
# experiment AND its registration hash; the boundary refuses a mismatch, so an
# EXP-001B admission cannot authorise EXP-002 or the reverse.
EXPERIMENTS = {
    EXP001B_ID: {"registration_hash": registration_hash,
                 "periods": lambda: {k: v for k, v in PERIODS.items() if k in ("train", "validation", "evaluation")},
                 "status": R.STATUS,
                 "run": lambda sbp, run_dir, grant: R.run(
                     {"train": sbp["train"], "validation": sbp["validation"], "evaluation": []},
                     ledger_dir=run_dir, session_loader=loader.loader_for(grant), evaluation_unsealed=False)},
    EXP002_ID: {"registration_hash": exp002_registration_hash,
                "periods": lambda: dict(H2.PERIOD_ROLES),          # fit, development, observed; never evaluation
                "status": H2.STATUS,
                "run": lambda sbp, run_dir, grant: H2.run(
                    {"fit": sbp["fit"], "development": sbp["development"], "observed": sbp.get("observed", [])},
                    ledger_dir=run_dir, session_loader=loader.loader_for(grant))},
    # EXP-004 binds to apex.world_model.exp004.historical, whose ONLY execution
    # entry point is exp004.run.tournament. That function takes no inference
    # parameters, so an admitted run cannot use anything but the registered
    # B = 10,000 / seed = 20260909, and exp004.synthetic is unreachable from here.
    EXP004_ID: {"registration_hash": exp004_registration_hash,
                "periods": lambda: dict(H4.PERIOD_ROLES),          # fit, development; never evaluation or reserve
                "status": H4.STATUS,
                "run": lambda sbp, run_dir, grant: H4.run(
                    {"fit": sbp["fit"], "development": sbp["development"]},
                    ledger_dir=run_dir, session_loader=loader.loader_for(grant))},
}
EXPERIMENT_ID = EXP001B_ID                                    # default; overridden per invocation

EXIT = {"SCIENTIFIC_COMPLETE": 0, "AUTHORIZATION_REFUSED": 3, "EVALUATION_SEALED": 4,
        "INVALID_INPUT_OR_FAILURE": 5}


def _emit(outcome: str, **kw) -> int:
    print(json.dumps({"experiment": EXPERIMENT_ID, "process_outcome": outcome, **kw}, indent=1, default=str))
    return EXIT[outcome]


def main(argv=None, *, trust: boundary.TrustConfig | None = None) -> int:
    """`trust` is a TESTING interface only: the CLI never sets it and
    production callers must not. None means production_trust()."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", default=None)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--label", default=None)
    ap.add_argument("--experiment", default=EXP001B_ID, choices=sorted(EXPERIMENTS))
    a = ap.parse_args(argv)
    global EXPERIMENT_ID
    EXPERIMENT_ID = a.experiment
    X = EXPERIMENTS[a.experiment]
    reg_hash = X["registration_hash"]()
    if a.label is None:
        a.label = a.experiment.lower().replace("alpha-", "").replace("-", "")

    try:
        if trust is None:
            grant = boundary.verify_decision(a.decision, experiment_id=a.experiment,
                                             registration_hash=reg_hash)
        else:
            grant = boundary.verify_decision_with(a.decision, trust, experiment_id=a.experiment,
                                                  registration_hash=reg_hash)
    except RealDataRefused as e:
        return _emit("AUTHORIZATION_REFUSED", contract=boundary.REAL_DATA_CONTRACT, refusal=str(e))

    periods = X["periods"]()
    sbp = loader.sessions_by_period(grant, periods, symbol=INSTRUMENT)
    plan = {"experiment": a.experiment, "registration_hash": reg_hash, "decision_sha256": grant.decision_sha256,
            "signer": grant.signer, "dataset_id": grant.dataset_id, "code_commit": grant.code_commit,
            "source_tree_sha256": grant.source_identity["tree_sha256"],
            "temporal_range": grant.temporal_range, "sessions": {k: len(v) for k, v in sbp.items()},
            "evaluation": "SEALED (not unsealed by this command)", "sealed_periods_never_requested": [k for k in ("evaluation", "reserve") if k not in periods],
            "restricted_use": grant.availability.get("restricted_use"), "output_root": grant.output_root}
    if a.plan:
        return _emit("SCIENTIFIC_COMPLETE", status="PLAN", **plan)

    # The modules ALREADY IMPORTED must be the admitted bytes. A recorded path
    # proves nothing about what is in it.
    trust_for_run = trust or boundary.production_trust()
    imports = boundary.verify_imports_against_commit(grant.code_commit, trust_for_run.checkout_root,
                                                     trust_for_run.relevant_source_paths)
    if not imports["all_imports_match_admitted_commit"]:
        return _emit("AUTHORIZATION_REFUSED", status="IMPORT_PROVENANCE_REFUSED",
                     refusal="IMPORTED_SOURCE_NOT_ADMITTED: %d mismatched, %d outside checkout, "
                             "%d untracked at the admitted commit"
                             % (len(imports["mismatched"]), len(imports["outside_checkout"]),
                                len(imports["untracked_at_commit"])),
                     imports={k: imports[k] for k in ("mismatched", "outside_checkout", "untracked_at_commit")})
    try:
        run_dir = boundary.open_run(grant, label=a.label, extra={"imports": imports})
    except RealDataRefused as e:
        return _emit("INVALID_INPUT_OR_FAILURE", status="RUN_DIR_REFUSED", refusal=str(e))
    try:
        rec = X["run"](sbp, run_dir, grant)
    except Exception as e:                                                   # noqa: BLE001
        rec = {"experiment": a.experiment, "status": "EXECUTION_FAILURE",
               "error": "%s: %s" % (type(e).__name__, str(e)[:400]), "traceback": traceback.format_exc()[-2000:]}
    outcome = X["status"].get(rec.get("status"), "INVALID_INPUT_OR_FAILURE")
    rec["plan"] = plan
    rec["runtime_at_end"] = boundary.runtime_provenance()
    rec["imports_at_start"] = imports
    # Recompute source identity at COMPLETION. The raw record is preserved
    # either way; a run whose relevant source moved under it is not evidence.
    src = boundary.recheck_source_identity(grant, trust_for_run)
    rec["source_identity_at_completion"] = src
    rec["acceptance_qualification"] = src["acceptance_qualification"]
    if not src["unchanged"]:
        outcome = "INVALID_INPUT_OR_FAILURE"
        rec["invalidated"] = ("relevant source changed between admission and completion; the "
                              "scientific record below is preserved but is NOT acceptable evidence")
    rec["process_outcome"] = outcome
    sealed = boundary.seal_result(run_dir, rec)
    return _emit(outcome, status=rec.get("status"), why=rec.get("why") or rec.get("error"),
                 acceptance_qualification=rec["acceptance_qualification"],
                 run_dir=str(run_dir), result=str(sealed))


if __name__ == "__main__":
    sys.exit(main())
