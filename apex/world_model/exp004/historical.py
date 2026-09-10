"""EXP-004 on admitted historical data, through the governed path.

Called by scripts/alpha_exp_real_execute.py with --experiment ALPHA-EXP-004.
It never decides admission: the route that admitted the files supplies the
session loader. It opens fit and development only; evaluation and reserve are
never requested.

THE ONLY EXECUTION ENTRY POINT THIS MODULE USES IS `run.tournament`.
`apex.world_model.exp004.synthetic` is deliberately NOT imported here, directly
or transitively: reduced inference parameters must be unreachable from an
admitted run. `run.tournament` takes no inference parameters at all, so the
registered B = 10,000 and seed = 20260909 are the only values an admitted run
can use, and every record it produces carries run_mode = HISTORICAL."""
from __future__ import annotations

import time

from .registration import (DEVELOPMENT_STATUS, EXPERIMENT_ID, INSTRUMENT, PERIODS,
                           SEALED_NEVER_REQUESTED, registration_hash)
from .run import HISTORICAL, tournament          # tournament ONLY; never synthetic

PERIOD_ROLES = {"fit": PERIODS["fit"], "development": PERIODS["development"]}
NEVER_OPENED = tuple(SEALED_NEVER_REQUESTED)
REQUIRED_PERIODS = ("fit", "development")
ENTRY_POINT = "apex.world_model.exp004.run.tournament"
FORBIDDEN_MODULE = "apex.world_model.exp004.synthetic"

STATUS = {
    "SELECTED": "SCIENTIFIC_COMPLETE",
    "NOT_SELECTED": "SCIENTIFIC_COMPLETE",
    "INTEGRITY_FAILURE": "INVALID_INPUT_OR_FAILURE",
}


def _load_sessions(paths: list, session_loader, role: str) -> list:
    """Load full sessions in chronological order. The loader takes symbol and
    date from the committed manifest, never from this module."""
    sessions = [session_loader(p) for p in sorted(paths)]
    sessions.sort(key=lambda s: s["session_date"])
    return sessions


def run(sessions_by_period: dict, *, ledger_dir=None, session_loader, **unused) -> dict:
    """Adapter: load admitted sessions for the two open periods and hand them to
    `run.tournament`. No inference parameters exist to pass; nothing here can
    reach the synthetic entry point."""
    t0 = time.time()
    rec = {"experiment": EXPERIMENT_ID, "registration_hash": registration_hash(),
           "adapter": {"entry_point": ENTRY_POINT, "forbidden_module": FORBIDDEN_MODULE,
                       "inference_parameters_accepted": False,
                       "note": "the adapter passes sessions only; B and seed come from the registration"},
           "period_roles": {k: list(v) for k, v in PERIOD_ROLES.items()},
           "development_status": DEVELOPMENT_STATUS,
           "never_opened": list(NEVER_OPENED),
           "evaluation": "SEALED: never requested by this run",
           "instrument": INSTRUMENT, "stages": []}
    if unused:
        rec.update(status="INTEGRITY_FAILURE",
                   refusal={"kind": "AdapterRefused", "stage": "adapter",
                            "detail": "UNEXPECTED_ARGUMENTS: %s; this adapter accepts no inference parameters"
                                      % sorted(unused)})
        return rec
    forbidden = [k for k in sessions_by_period if k in NEVER_OPENED]
    if forbidden:
        rec.update(status="INTEGRITY_FAILURE",
                   refusal={"kind": "AdapterRefused", "stage": "adapter",
                            "detail": "SEALED_PERIODS_OFFERED: %s" % forbidden})
        return rec
    missing = [k for k in REQUIRED_PERIODS if not sessions_by_period.get(k)]
    if missing:
        rec.update(status="INTEGRITY_FAILURE",
                   refusal={"kind": "AdapterRefused", "stage": "adapter",
                            "detail": "NO_SESSIONS_FOR_REQUIRED_PERIOD: %s" % missing})
        return rec

    try:
        fit = _load_sessions(sessions_by_period["fit"], session_loader, "fit")
        rec["stages"].append({"stage": "load:fit", "sessions": len(fit),
                              "first": fit[0]["session_date"], "last": fit[-1]["session_date"]})
        dev = _load_sessions(sessions_by_period["development"], session_loader, "development")
        rec["stages"].append({"stage": "load:development", "sessions": len(dev),
                              "first": dev[0]["session_date"], "last": dev[-1]["session_date"]})
    except Exception as e:                                                   # noqa: BLE001
        kind = type(e).__name__
        rec.update(status="INTEGRITY_FAILURE",
                   refusal={"kind": kind, "stage": "load",
                            "detail": "%s: %s" % (kind, str(e)[:500])})
        return rec

    result = tournament(fit, dev)                    # the ONLY invocation; no parameters exist to pass
    fit = dev = None

    rec["result"] = result
    rec["status"] = result.get("status", "INTEGRITY_FAILURE")
    rec["run_mode"] = result.get("run_mode")
    ip = result.get("inference_parameters") or {}
    rec["inference_parameters"] = ip
    # an admitted record must be a historical one: refuse anything else outright
    if rec["run_mode"] != HISTORICAL or not ip.get("historical_path_valid") or ip.get("NOT_FOR_HISTORICAL_USE"):
        rec.update(status="INTEGRITY_FAILURE",
                   refusal={"kind": "AdapterRefused", "stage": "result",
                            "detail": "NON_HISTORICAL_RESULT: run_mode=%r historical_path_valid=%r"
                                      % (rec["run_mode"], ip.get("historical_path_valid"))})
    rec["economics"] = "NONE (distributional only)"
    rec["elapsed_s"] = round(time.time() - t0, 2)
    return rec
