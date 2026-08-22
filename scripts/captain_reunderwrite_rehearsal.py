"""CAPTAIN RE-UNDERWRITE REHEARSAL — bounded, live-safe wiring check.

Drives the real ReunderwriteTrigger + real captain_shadow.review()
through the full ladder and proves the orchestration contract before
tomorrow's natural session. Catches runtime wiring mistakes tonight
rather than at 09:31.

NOT sufficient for natural acceptance -- it is synthetic input into real
judgment code. Tomorrow's live session is the real test.

Writes ONLY to a temp directory: it must never contaminate a real
ledger (the exact class of bug that has bitten this repo twice).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from apex.frontier2 import captain_shadow
from apex.frontier2 import reunderwrite_ledger as rl
from apex.frontier2 import reunderwrite_trigger as rt

T0 = pd.Timestamp("2026-08-19T13:35:00Z")


def _inputs(**over):
    base = {
        "curve_state": "POSITIVE_TRANSITION", "curve_direction": "UP",
        "curve_expression": "CONFIRMED_EXPRESSION", "curve_likelihood": "LOW",
        "expectation_violation_state": "NONE", "participant_trap": "NONE",
        "participant_direction": "UNKNOWN", "propagation_state": "UNKNOWN",
        "leading_edge_entry_quality": "UNKNOWN", "observation_quality": "FULL",
        "system_cognition_state": "FULL", "model_market_tally_agrees": None,
        "assassin2_familiarity": "FAMILIAR", "assassin2_caution_label": "NONE",
    }
    base.update(over)
    return base


# Scenes chosen to walk the ladder. Captain picks its own state from the
# inputs -- the rehearsal asserts the ORCHESTRATION, and reports whatever
# state Captain actually chose rather than forcing one.
SCENES = [
    ("T0 candidate appears", _inputs(), 0),
    ("T1 curve strengthens", _inputs(curve_likelihood="HIGH"), 60),
    ("T2 propagation confirms",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="STRONG"), 120),
    ("T3 entry quality deteriorates",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="POOR"), 180),
    ("T4 heartbeat, nothing changed",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="POOR"), 540),
    ("T5 assassin objection",
     _inputs(curve_likelihood="HIGH", propagation_state="CONFIRMED",
             leading_edge_entry_quality="POOR",
             assassin2_familiarity="DATA_CONFLICT",
             assassin2_caution_label="SEVERE"), 600),
    ("T6 thesis breaks",
     _inputs(curve_state="NEGATIVE_TRANSITION", curve_direction="DOWN",
             curve_likelihood="LOW", propagation_state="BROKEN",
             leading_edge_entry_quality="POOR",
             assassin2_familiarity="DATA_CONFLICT",
             assassin2_caution_label="SEVERE",
             observation_quality="INVALID"), 660),
]


def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="apex_rehearsal_"))
    rl.LEDGER = tmp / "reunderwrite.jsonl"
    captain_shadow.LEDGER = tmp / "captain.jsonl"

    prior_cs = None
    prior_inputs = None
    last_review_at = None
    candidate_id = "REHEARSAL-LIVE"
    rows, reviews, state_changes, assassin_reruns = [], 0, 0, 0

    for label, inputs, offset in SCENES:
        now = T0 + pd.Timedelta(seconds=offset)
        secs = ((now - last_review_at).total_seconds()
                if last_review_at is not None else None)
        d = rt.evaluate(subject="REHEARSAL", candidate_id=candidate_id,
                        prior_inputs=prior_inputs, current_inputs=inputs,
                        prior_state=(prior_cs.state if prior_cs else None),
                        seconds_since_last_review=secs, known_from=now, now=now)
        if not d.should_review:
            rows.append({"scene": label, "reviewed": False,
                         "triggers": list(d.triggers),
                         "state": (prior_cs.state if prior_cs else None)})
            continue

        refreshed = rt.requires_fresh_assassin(d)
        assassin_reruns += int(refreshed)
        cs = captain_shadow.review(prior_cs, candidate_id=candidate_id,
                                   subject="REHEARSAL", current_inputs=inputs,
                                   now=now, known_from=now)
        captain_shadow.persist(cs)
        reviews += 1
        moved = (prior_cs is None) or (prior_cs.state != cs.state)
        state_changes += int(moved)
        rl.persist(rl.record(
            candidate_id=candidate_id, subject="REHEARSAL",
            review_number=reviews, review_time=now, trigger=d.triggers,
            previous_captain_state=(prior_cs.state if prior_cs else None),
            current_captain_state=cs.state, changed_inputs=d.changed_inputs,
            unchanged_inputs=d.unchanged_inputs,
            direction_quality=cs.direction_quality,
            transition_quality=cs.transition_quality,
            entry_quality=cs.entry_quality, data_quality=cs.data_quality,
            assassin_refreshed=refreshed, known_from=now))
        rows.append({"scene": label, "reviewed": True,
                     "triggers": list(d.triggers),
                     "prior": (prior_cs.state if prior_cs else None),
                     "state": cs.state, "assassin_refreshed": refreshed})
        prior_cs, prior_inputs, last_review_at = cs, inputs, now

    # ---- terminal lineage law -------------------------------------
    terminal_reached = prior_cs is not None and prior_cs.state in rt.TERMINAL_STATES
    revived = rt.evaluate(
        subject="REHEARSAL", candidate_id=candidate_id,
        prior_inputs=prior_inputs,
        current_inputs=_inputs(curve_likelihood="HIGH",
                               propagation_state="CONFIRMED"),
        prior_state="INVALIDATE", seconds_since_last_review=60.0,
        known_from=T0, now=T0)
    gen2 = rt.new_thesis_lineage_id("REHEARSAL", generation=2)
    fresh = rt.evaluate(subject="REHEARSAL", candidate_id=gen2,
                        prior_inputs=None, current_inputs=_inputs(),
                        prior_state=None, seconds_since_last_review=None,
                        known_from=T0, now=T0)

    counts = rl.review_counts_by_subject(rl.LEDGER)
    captain_review_rows = [
        json.loads(l) for l in rl.LEDGER.read_text().splitlines() if l.strip()]
    unchanged_rows = [r for r in captain_review_rows
                      if r["record_kind"] == "CAPTAIN_REVIEW"]

    checks = {
        "captain_reviewed_more_than_once": reviews > 1,
        "state_ladder_advanced": state_changes >= 3,
        "captain_review_row_exists_without_state_change": len(unchanged_rows) > 0,
        "assassin_reran_where_required": assassin_reruns > 0,
        "terminal_invalidate_reached": terminal_reached,
        "invalidated_lineage_cannot_resurrect": revived.should_review is False,
        "new_evidence_requires_gen2": (gen2 != candidate_id
                                       and fresh.should_review is True),
        "no_capital_or_execution_authority": all(
            w not in json.dumps(captain_review_rows).lower()
            for w in ("place_order", "submit_order", "capital_authority_granted",
                      "size_position")),
    }
    return {"kind": "captain_reunderwrite_rehearsal", "scenes": rows,
            "reviews": reviews, "state_changes": state_changes,
            "assassin_reruns": assassin_reruns,
            "review_counts": counts, "checks": checks,
            "verdict": "PASS" if all(checks.values()) else "FAIL",
            "ledger_dir": str(tmp), "decision_power": "NONE_FRONTIER_SHADOW"}


if __name__ == "__main__":
    r = main()
    for s in r["scenes"]:
        if s["reviewed"]:
            print(f"  {s['scene']:32s} {str(s['prior']):22s} -> "
                  f"{s['state']:22s} assassin={s['assassin_refreshed']} "
                  f"{s['triggers']}")
        else:
            print(f"  {s['scene']:32s} NOT REVIEWED (correctly silent)")
    print()
    for k, v in r["checks"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"\nVERDICT: {r['verdict']}")
    raise SystemExit(0 if r["verdict"] == "PASS" else 1)
