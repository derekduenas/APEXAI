#!/usr/bin/env python3
"""ALPHA-EXP-001B on REAL historical data -- executable only under a verified,
SIGNED admission decision. Without one, the only output is a named refusal.

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
from apex.world_model.exp001b.registration import EXPERIMENT_ID, INSTRUMENT, PERIODS, registration_hash
from apex.world_model.real_data import boundary, loader
from apex.world_model.real_data.boundary import RealDataRefused

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
    ap.add_argument("--label", default="exp001b")
    a = ap.parse_args(argv)

    try:
        if trust is None:
            grant = boundary.verify_decision(a.decision, experiment_id=EXPERIMENT_ID,
                                             registration_hash=registration_hash())
        else:
            grant = boundary.verify_decision_with(a.decision, trust, experiment_id=EXPERIMENT_ID,
                                                  registration_hash=registration_hash())
    except RealDataRefused as e:
        return _emit("AUTHORIZATION_REFUSED", contract=boundary.REAL_DATA_CONTRACT, refusal=str(e))

    periods = {k: v for k, v in PERIODS.items() if k in ("train", "validation", "evaluation")}
    sbp = loader.sessions_by_period(grant, periods, symbol=INSTRUMENT)
    plan = {"registration_hash": registration_hash(), "decision_sha256": grant.decision_sha256,
            "signer": grant.signer, "dataset_id": grant.dataset_id, "code_commit": grant.code_commit,
            "source_tree_sha256": grant.source_identity["tree_sha256"],
            "temporal_range": grant.temporal_range, "sessions": {k: len(v) for k, v in sbp.items()},
            "evaluation": "SEALED (not unsealed by this command)",
            "restricted_use": grant.availability.get("restricted_use"), "output_root": grant.output_root}
    if a.plan:
        return _emit("SCIENTIFIC_COMPLETE", status="PLAN", **plan)

    try:
        run_dir = boundary.open_run(grant, label=a.label)
    except RealDataRefused as e:
        return _emit("INVALID_INPUT_OR_FAILURE", status="RUN_DIR_REFUSED", refusal=str(e))
    try:
        rec = R.run({"train": sbp["train"], "validation": sbp["validation"], "evaluation": []},
                    ledger_dir=run_dir, session_loader=loader.loader_for(grant), evaluation_unsealed=False)
    except Exception as e:                                                   # noqa: BLE001
        rec = {"experiment": EXPERIMENT_ID, "status": "EXECUTION_FAILURE",
               "error": "%s: %s" % (type(e).__name__, str(e)[:400]), "traceback": traceback.format_exc()[-2000:]}
    outcome = R.STATUS.get(rec.get("status"), "INVALID_INPUT_OR_FAILURE")
    rec["process_outcome"] = outcome
    rec["plan"] = plan
    rec["runtime_at_end"] = boundary.runtime_provenance()
    sealed = boundary.seal_result(run_dir, rec)
    return _emit(outcome, status=rec.get("status"), why=rec.get("why") or rec.get("error"),
                 run_dir=str(run_dir), result=str(sealed))


if __name__ == "__main__":
    sys.exit(main())
