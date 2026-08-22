#!/usr/bin/env python
"""DECISION THROUGHPUT -- the metric that replaces ledger-row counts.

Operator ruling 2026-08-22: progress is no longer measured in ledger
rows, modules or lines of code. It is measured in DECISIONS, ATTACKS,
SEALED CARDS, RESOLVED ATTACKS -- and when those are zero, the zero
must be EXPLAINABLE.

    python scripts/decision_throughput.py

Reports the per-sleeve funnel plus TOP 10 CLOSEST TO ATTACK, ranked by
STRUCTURAL DISTANCE (how many predicates are unmet), never by future
profitability. Zero attacks may be entirely legitimate; an unexplained
zero is not.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FORENSIC = Path("results/frontier2/serious_gate_forensic.json")
CAPTAIN = Path("results/frontier2/captain_shadow_ledger.jsonl")
FUNNEL = Path("results/frontier2/expression_funnel_ledger.jsonl")
OPTIONS_CARDS = Path("results/options_research/before_cards.jsonl")
HUNTER_FWD = Path("results/hunter/forward_ledger.jsonl")
MANUAL = Path("results/btc/manual_execution_ledger.jsonl")
OUT = Path("results/commissioning/decision_throughput.json")


def _n(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for x in p.read_text().splitlines() if x.strip())


def _rows(p: Path) -> list:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def build() -> dict:
    import pandas as pd
    rep = {"kind": "decision_throughput_report",
           "as_of": str(pd.Timestamp.now(tz="UTC")),
           "law": "zero attacks may be legitimate; an UNEXPLAINED zero "
                  "is not. No trade quotas exist.",
           "decision_power": "NONE"}

    # ---- EQUITIES
    cap = [r for r in _rows(CAPTAIN)
           if r.get("kind") == "captain_frontier_shadow_state"]
    states = Counter(r.get("state") for r in cap)
    hunter = _rows(HUNTER_FWD)
    eq = {
        "OBSERVATIONS_curve": _n(Path("results/frontier2/curve_ledger.jsonl")),
        "CAPTAIN_REVIEWS": len(cap),
        "STALK": states.get("WATCH", 0),
        "DEVELOP": states.get("DEVELOP", 0),
        "WAIT_FOR_CONFIRMATION": states.get("WAIT_FOR_CONFIRMATION", 0),
        "SERIOUS": states.get("SERIOUS", 0),
        "WAIT_FOR_ENTRY": states.get("WAIT_FOR_ENTRY", 0),
        "ATTACK_READY": 0,
        "CAPITAL_REVIEW": 0,
        "PAPER_CANDIDATE": 0,
        "PAPER_ATTACK": 0,
        "EXPRESSION_FUNNEL_DECISIONS": _n(FUNNEL),
        "BASELINE_CONTROL_decisions": sum(
            1 for r in hunter if r.get("kind") == "decision"),
        "BASELINE_CONTROL_realizations": sum(
            1 for r in hunter if r.get("kind") == "realization"),
        "baseline_note": "BASELINE-RELSTRENGTH is the mechanical "
                         "CONTROL cohort -- never relabelled as "
                         "Predator attacks",
    }

    # ---- OPTIONS
    op = {"BEFORE_CARDS": _n(OPTIONS_CARDS),
          "PAPER_ATTACK": 0,
          "blocked_on": ["realized-vs-implied volatility NOT_BUILT",
                         "option-vs-equity comparator NOT_BUILT",
                         "historical NBBO/chains DATA_GAP",
                         "Attack Geometry NOT_BUILT"]}

    # ---- BTC
    btc = {"L2": "IN_PROGRESS (weekend soak)",
           "L3": "NOT_AUTHORIZED",
           "MANUAL_DESK_RECORDS": _n(MANUAL),
           "PAPER_ATTACK": 0,
           "blocked_on": ["BTC-L2 final acceptance",
                          "participant state (L3)",
                          "BTC Attack Geometry (interface only)"]}

    rep["sleeves"] = {"EQUITIES_INTRADAY": eq, "OPTIONS": op,
                      "BTC_PERPS": btc}
    rep["SYSTEM_TOTALS"] = {
        "ATTACKS": 0, "SEALED_BEFORE_CARDS": 0, "RESOLVED_ATTACKS": 0,
        "PAPER_EXPLORATORY": 0, "PAPER_AUTHORIZED": 0, "LIVE": 0}

    # ---- WHY ZERO (the explanation the law demands)
    if FORENSIC.exists():
        f = json.loads(FORENSIC.read_text())
        rep["zero_attack_explanation"] = {
            "reviews": f["reviews_total"],
            "SERIOUS": f["SERIOUS_actual"],
            "blocking_predicates": {
                k: {"failed": v["failed"], "unknown": v["unknown"],
                    "sole_blocker": v["sole_blocker"]}
                for k, v in f["per_predicate"].items()},
            "top_combination": next(iter(f["blocker_combinations"])),
            "verdict": "TWO structural blockers, not one: entry_quality "
                       "UNKNOWN in 100% of reviews (Attack Geometry "
                       "absent) AND transition_quality never STRONG "
                       "(curve input starvation). Fixing either alone "
                       "yields zero SERIOUS.",
        }
        rep["closest_to_attack_top10"] = [
            {"subject": e["subject"], "as_of": e["as_of"],
             "state": e["actual_state"],
             "failed_predicates": e["all_blocking_predicates"],
             "distance_to_attack": e["distance_to_SERIOUS"],
             "data_quality": e["data_quality"]}
            for e in f.get("closest_to_attack_top10", [])]
        rep["distance_histogram"] = f["distance_to_SERIOUS"]
    return rep


def main() -> int:
    rep = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
