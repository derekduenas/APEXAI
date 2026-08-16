"""Research Memory 2.0 — the unified lineage view over the ONE chained
forward ledger.

The ledger already IS the memory: BEFORE-outcome records (scan, decision,
forecast_bundle, capital_decision, world_simulation) and AFTER-outcome
records (realization) are separate appended kinds, hash-chained, and
never mutated — so "never overwrite the BEFORE record" is structural, not
procedural. This module adds the two things a memory needs: a LINEAGE
view (everything APEX believed about a candidate, then what happened) and
the STRUCTURAL TIME FIREWALL for analogue retrieval — a Monday query
physically cannot see a Tuesday outcome, because rows are filtered on
formation time AND outcome-resolution time before anything else runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

LEDGER = Path("results/hunter/forward_ledger.jsonl")


def _rows(ledger: Path = LEDGER) -> list:
    if not ledger.exists():
        return []
    out = []
    for x in ledger.read_text().splitlines():
        if not x.strip():
            continue
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            continue                             # torn line: reader survives
    return out


def candidate_lineage(decision_id: str, ledger: Path = LEDGER) -> dict:
    """BEFORE: decision, bundle, capital, simulation. AFTER: realization.
    Missing pieces are typed absences, never fabricated."""
    out = {"decision_id": decision_id, "before": {}, "after": {}}
    for r in _rows(ledger):
        k = r.get("kind")
        if r.get("decision_id") != decision_id \
                and r.get("candidate_id") != decision_id:
            continue
        if k == "decision":
            out["before"]["decision"] = r
        elif k == "forecast_bundle":
            out["before"]["forecast_bundle"] = r
        elif k == "capital_decision":
            out["before"]["capital_decision"] = r
        elif k == "world_simulation":
            out["before"].setdefault("world_simulations", []).append(r)
        elif k == "realization":
            out["after"]["realization"] = r
        elif k == "paper_order":
            out["before"]["paper_order"] = r
    return out


def _regime_label(day_return) -> str | None:
    if day_return is None:
        return None
    if day_return > 0:
        return "UP"
    return "DOWN" if day_return < 0 else "FLAT"


def analog_memory_rows(as_of, ledger: Path = LEDGER,
                       horizon_minutes: int = 60) -> list:
    """Rows for the analog engine, ALL forward class, with the structural
    time firewall applied here as well (defense in depth: the engine
    re-applies it). resolved_at = end of the realization's session — a
    conservative, deterministic bound."""
    t = pd.Timestamp(as_of)
    decisions, realized = {}, {}
    for r in _rows(ledger):
        if r.get("kind") == "decision" \
                and not r.get("playbook_id", "").startswith("BASELINE-"):
            decisions[r["decision_id"]] = r
        elif r.get("kind") == "realization" and r.get("resolvable"):
            realized[r["decision_id"]] = r
    rows = []
    for did, d in decisions.items():
        o = realized.get(did)
        if o is None:
            continue
        resolved_at = (pd.Timestamp(d["session_date"], tz="America/New_York")
                       + pd.Timedelta(hours=16, minutes=30)).tz_convert("UTC")
        if pd.Timestamp(d["t_utc"]) >= t or resolved_at >= t:
            continue                              # the firewall
        rows.append({"decision_id": did, "candidate": d, "outcome": o,
                     "resolved_at": str(resolved_at),
                     "session_date": d["session_date"],
                     "symbol": d["symbol"],
                     # LAB-08: the row carries the class of the RECORD it
                     # came from, not the class of the ledger we hoped to
                     # be reading. The engine verifies it downstream.
                     "evidence_class": d.get("evidence_class"),
                     "regime": _regime_label(
                         (d.get("market_state") or {}).get("day_return"))})
    del horizon_minutes
    return rows
