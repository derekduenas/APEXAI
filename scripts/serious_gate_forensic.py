#!/usr/bin/env python
"""SERIOUS GATE FORENSIC -- why has APEX never reached SERIOUS?

Reconstructs, for every real captain_shadow review, the exact predicate
set the live code requires for SERIOUS, and attributes the blockage.

THE LIVE PREDICATE (read from apex/frontier2/captain_shadow.py, never
guessed, never modified):

    SERIOUS  <=>  not lethal
                  and direction_quality  == STRONG
                  and entry_quality      in (STRONG, GOOD)
                  and transition_quality == STRONG

    WAIT_FOR_ENTRY <=> direction STRONG and entry in
                       (WEAK, POOR, ACCEPTABLE)

    lethal  <=>  model_familiarity == DATA_CONFLICT or
                 data_quality == INVALID

LAWS OBEYED:
  * NO future outcome information is read. This is mechanics only.
  * NO threshold is changed. Nothing is tuned.
  * The question is never "would it have been profitable" -- only
    "how far is the organism from naturally authorizing consideration".

    python scripts/serious_gate_forensic.py

Writes results/frontier2/serious_gate_forensic.json (+ per-review
JSONL) and prints the attribution.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LEDGER = Path("results/frontier2/captain_shadow_ledger.jsonl")
OUT = Path("results/frontier2/serious_gate_forensic.json")
PER_REVIEW = Path("results/frontier2/serious_gate_forensic.jsonl")

# mirrored from captain_shadow.py -- asserted equal at runtime below
ENTRY_STRONG = ("STRONG", "GOOD")
ENTRY_WEAK = ("WEAK", "POOR", "ACCEPTABLE")
LETHAL_FAMILIARITY = ("DATA_CONFLICT",)

PREDICATES = ("not_lethal", "transition_STRONG", "direction_STRONG",
              "entry_GOOD_or_STRONG")


def _assert_mirror() -> None:
    """The forensic must describe the CODE, not a memory of it."""
    from apex.frontier2 import captain_shadow as cs
    assert cs._ENTRY_QUALITY_STRONG == ENTRY_STRONG, "entry tiers drifted"
    assert cs._ENTRY_QUALITY_WEAK == ENTRY_WEAK, "entry tiers drifted"
    assert cs._LETHAL_FAMILIARITY == LETHAL_FAMILIARITY, "lethal drifted"


def evaluate(rec: dict) -> dict:
    """Predicate pass/fail map for one review. UNKNOWN is its own
    outcome and is NEVER counted as a pass."""
    tq = rec.get("transition_quality", "UNKNOWN")
    dq = rec.get("direction_quality", "UNKNOWN")
    eq = rec.get("entry_quality", "UNKNOWN")
    data_q = rec.get("data_quality", "UNKNOWN")
    fam = rec.get("model_familiarity", "UNKNOWN")

    lethal = fam in LETHAL_FAMILIARITY or data_q == "INVALID"
    p = {"not_lethal": not lethal,
         "transition_STRONG": tq == "STRONG",
         "direction_STRONG": dq == "STRONG",
         "entry_GOOD_or_STRONG": eq in ENTRY_STRONG}
    # UNKNOWN vs actively-failing is a different diagnosis
    unknown = {"transition_STRONG": tq == "UNKNOWN",
               "direction_STRONG": dq == "UNKNOWN",
               "entry_GOOD_or_STRONG": eq == "UNKNOWN",
               "not_lethal": data_q == "UNKNOWN" and fam == "UNKNOWN"}
    failed = [k for k in PREDICATES if not p[k]]
    return {"review_id": rec.get("candidate_id"),
            "subject": rec.get("subject"),
            "as_of": rec.get("as_of"),
            "known_from": rec.get("known_from"),
            "actual_state": rec.get("state"),
            "transition_quality": tq, "direction_quality": dq,
            "entry_quality": eq, "data_quality": data_q,
            "model_familiarity": fam,
            "curve_likelihood":
                (rec.get("inputs_snapshot") or {}).get("curve_likelihood"),
            "curve_direction":
                (rec.get("inputs_snapshot") or {}).get("curve_direction"),
            "leading_edge_rank":
                (rec.get("inputs_snapshot") or {}).get("leading_edge_rank"),
            "predicate_pass_fail_map": p,
            "predicate_unknown_map": unknown,
            "first_blocking_predicate": failed[0] if failed else None,
            "all_blocking_predicates": failed,
            "minimal_blocker_set": failed,
            "distance_to_SERIOUS": len(failed),
            "serious_eligible": not failed,
            "wait_for_entry_eligible": (p["not_lethal"] and
                                        p["direction_STRONG"] and
                                        eq in ENTRY_WEAK)}


def build() -> dict:
    _assert_mirror()
    rows = [json.loads(x) for x in LEDGER.read_text().splitlines()
            if x.strip()]
    reviews = [r for r in rows
               if r.get("kind") == "captain_frontier_shadow_state"]
    ev = [evaluate(r) for r in reviews]

    with open(PER_REVIEW, "w") as f:
        for e in ev:
            f.write(json.dumps(e, sort_keys=True) + "\n")

    per_pred = {}
    for k in PREDICATES:
        passed = sum(1 for e in ev if e["predicate_pass_fail_map"][k])
        unk = sum(1 for e in ev if e["predicate_unknown_map"].get(k))
        sole = sum(1 for e in ev if e["minimal_blocker_set"] == [k])
        part = sum(1 for e in ev
                   if k in e["all_blocking_predicates"] and
                   len(e["all_blocking_predicates"]) > 1)
        per_pred[k] = {"evaluated": len(ev), "passed": passed,
                       "failed": len(ev) - passed, "unknown": unk,
                       "sole_blocker": sole, "part_of_multi_blocker": part}

    dist = Counter(e["distance_to_SERIOUS"] for e in ev)
    combos = Counter(tuple(e["all_blocking_predicates"]) for e in ev)

    # progression funnel using the ACTUAL logical requirements
    f_live = sum(1 for e in ev if e["predicate_pass_fail_map"]["not_lethal"])
    f_trans = sum(1 for e in ev
                  if e["predicate_pass_fail_map"]["not_lethal"] and
                  e["predicate_pass_fail_map"]["transition_STRONG"])
    f_dir = sum(1 for e in ev
                if e["predicate_pass_fail_map"]["not_lethal"] and
                e["predicate_pass_fail_map"]["transition_STRONG"] and
                e["predicate_pass_fail_map"]["direction_STRONG"])
    f_entry = sum(1 for e in ev if e["serious_eligible"])

    closest = sorted(
        [e for e in ev if e["distance_to_SERIOUS"] > 0],
        key=lambda e: (e["distance_to_SERIOUS"], str(e["as_of"])))[:10]

    return {"kind": "serious_gate_forensic",
            "law": "mechanics only -- no outcome information, no "
                   "threshold changed, UNKNOWN never counted as pass",
            "predicate_source": "apex/frontier2/captain_shadow.py "
                                "(mirror asserted at runtime)",
            "reviews_total": len(ev),
            "actual_state_distribution":
                dict(Counter(e["actual_state"] for e in ev).most_common()),
            "SERIOUS_actual": sum(1 for e in ev
                                  if e["actual_state"] == "SERIOUS"),
            "WAIT_FOR_ENTRY_actual": sum(
                1 for e in ev if e["actual_state"] == "WAIT_FOR_ENTRY"),
            "SERIOUS_eligible_recomputed": f_entry,
            "WAIT_FOR_ENTRY_eligible_recomputed": sum(
                1 for e in ev if e["wait_for_entry_eligible"]),
            "per_predicate": per_pred,
            "distance_to_SERIOUS": {str(k): v
                                    for k, v in sorted(dist.items())},
            "blocker_combinations":
                {" + ".join(k) if k else "(none)": v
                 for k, v in combos.most_common(10)},
            "progression_funnel": {
                "reviews": len(ev), "not_lethal": f_live,
                "and_transition_STRONG": f_trans,
                "and_direction_STRONG": f_dir,
                "and_entry_GOOD_or_STRONG": f_entry},
            "entry_quality_distribution":
                dict(Counter(e["entry_quality"] for e in ev).most_common()),
            "transition_quality_distribution":
                dict(Counter(e["transition_quality"]
                             for e in ev).most_common()),
            "direction_quality_distribution":
                dict(Counter(e["direction_quality"]
                             for e in ev).most_common()),
            "closest_to_attack_top10": closest,
            "decision_power": "NONE"}


def main() -> int:
    rep = build()
    OUT.write_text(json.dumps(rep, indent=1))
    slim = {k: v for k, v in rep.items() if k != "closest_to_attack_top10"}
    print(json.dumps(slim, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
