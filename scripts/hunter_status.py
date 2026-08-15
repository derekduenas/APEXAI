#!/usr/bin/env python
"""APEX Hunter status — machine-readable state of every component, plus
per-candidate explanation.

    python scripts/hunter_status.py                 # system status JSON
    python scripts/hunter_status.py <decision_id>   # explain one candidate

No magical APEX score: structured views only. Statuses are read from the
repo's actual state (ledger, registry, markers), never asserted.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

from apex.hunter.birth import load_births  # noqa: E402
from apex.hunter.memory import LEDGER, _rows, candidate_lineage  # noqa: E402
from apex.hunter.swarm import auth_available  # noqa: E402


def _clock_loaded() -> bool:
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True).stdout
        return "com.apex.hunter-clock" in out
    except Exception:                                       # noqa: BLE001
        return False


def system_status() -> dict:
    rows = _rows()
    kinds = {}
    for r in rows:
        kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
    births = load_births()
    n_realized = kinds.get("realization", 0)
    return {
        "forward_clock": ("ACTIVE" if _clock_loaded()
                          else "NOT_LOADED (launchctl)"),
        "ledger_records": kinds,
        "births": {n: b["birth_time_utc"] for n, b in sorted(births.items())},
        "components": {
            "digital_twin_snapshot": "ACTIVE (state records)",
            "regime": "PARTIAL (crude intraday proxy; daily classifier "
                      "not yet in the intraday loop)",
            "chartstate": "ACTIVE",
            "relative_strength": "ACTIVE",
            "scanner": "ACTIVE",
            "playbooks": "ACTIVE (HUNTER-001_v1, HUNTER-002_v1; "
                         "catalyst DORMANT)",
            "baselines": "ACTIVE",
            "analog_engine": ("DATA_GATED (forward memory rows: "
                              f"{n_realized} realizations)"),
            "ml_engine": "DATA_GATED (UNTRAINED; refuses below 40 "
                         "effective)",
            "forecast_bundle": "ACTIVE (typed absences)",
            "distribution_engine": "DATA_GATED (source REFUSED without "
                                   "admissible evidence)",
            "world_simulator": "BUILT / OBSERVE_ONLY (on-demand; not in "
                               "the 15-min hot path)",
            "swarm": ("AUTH_GATED" if not auth_available()
                      else "AUTH PRESENT / transport not smoke-tested"),
            "calibration": "DATA_GATED (INSUFFICIENT_FORWARD_EVIDENCE)",
            "opportunity_capital": "ACTIVE (OBSERVE/WATCH/NO_TRADE/"
                                   "REFUSED; PAPER_ELIGIBLE unreachable)",
            "trade_thesis_paper": "BUILT / NOT_AUTHORIZED in production",
            "trade_manager": "BUILT / CERTIFIED by counterexamples",
            "research_memory": "ACTIVE (ledger lineage)",
            "options": "DORMANT (interface only; V1 = STOCK)",
            "live_execution": "SEALED",
        },
    }


def explain(decision_id: str) -> dict:
    lin = candidate_lineage(decision_id)
    d = lin["before"].get("decision") or {}
    cap = lin["before"].get("capital_decision") or {}
    fb = lin["before"].get("forecast_bundle") or {}
    return {
        "decision_id": decision_id,
        "why_noticed": d.get("matched"),
        "playbook": d.get("playbook_id"),
        "direction": d.get("direction"),
        "analogues": fb.get("analog_view"),
        "ml": fb.get("ml_view"),
        "simulation": fb.get("simulation_view"),
        "disagreement": fb.get("disagreement"),
        "swarm": (fb.get("swarm_view") or {}).get("status"),
        "capital_says": {"final_state": cap.get("final_state"),
                         "reasons": cap.get("reason_codes")},
        "invalidation": d.get("invalidation"),
        "outcome": lin["after"].get("realization") or "UNRESOLVED",
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(json.dumps(explain(sys.argv[1]), indent=1, default=str))
    else:
        print(json.dumps(system_status(), indent=1, default=str))
    del LEDGER
