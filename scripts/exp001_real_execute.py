#!/usr/bin/env python3
"""ALPHA-EXP-001 on REAL historical data -- executable only under a verified
admission decision. Without one, the only output is a named refusal.

    exp001_real_execute.py --decision PATH --plan      # list what WOULD run; opens no rows
    exp001_real_execute.py --decision PATH --execute   # run train+validation; evaluation stays SEALED

Evaluation unsealing is NOT a flag here. It is a separate authorization and
a separate command; this one always runs with evaluation_unsealed=False.
Exit codes: 0 completed (including NO_SIGNAL), 3 refused, 2 usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from apex.world_model.exp001 import run as R
from apex.world_model.exp001.registration import (EXPERIMENT_ID, INSTRUMENT, PERIODS,
                                                  registration_hash)
from apex.world_model.real_data import boundary, loader
from apex.world_model.real_data.boundary import RealDataRefused


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision", default=None)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--output-name", default="exp001_real")
    a = ap.parse_args(argv)

    try:
        grant = boundary.verify_decision(a.decision, experiment_id=EXPERIMENT_ID,
                                         registration_hash=registration_hash())
    except RealDataRefused as e:
        print(json.dumps({"experiment": EXPERIMENT_ID, "status": "REFUSED",
                          "contract": boundary.REAL_DATA_CONTRACT, "refusal": str(e)}, indent=1))
        return 3

    periods = {k: v for k, v in PERIODS.items() if k in ("train", "validation", "evaluation")}
    sbp = loader.sessions_by_period(grant, periods, symbol=INSTRUMENT)
    plan = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(),
            "decision_digest": grant.decision_digest, "dataset_id": grant.dataset_id,
            "code_commit": grant.code_commit, "temporal_range": grant.temporal_range,
            "sessions": {k: len(v) for k, v in sbp.items()},
            "evaluation": "SEALED (not unsealed by this command)",
            "restricted_use": grant.availability.get("restricted_use"),
            "output_root": grant.output_root}
    if a.plan:
        print(json.dumps({"status": "PLAN", **plan}, indent=1))
        return 0

    out = boundary.open_output(grant, a.output_name)
    rec = R.run({"train": sbp["train"], "validation": sbp["validation"], "evaluation": []},
                ledger_dir=out, declared_class="REAL_HISTORICAL_ADMITTED",
                evaluation_unsealed=False, session_loader=loader.loader_for(grant))
    rec["plan"] = plan
    (out / "exp001_real_result.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: rec.get(k) for k in ("experiment", "status", "why", "route")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
