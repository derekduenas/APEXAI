"""Seal the PARALLAX initial research questions (P1-P4) on the board.

Questions only. No thresholds, no scores, no build authorizations.
Idempotent: refuses to re-seal a question id that is already on the
board.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402

BOARD = Path("results/edgeforge/research_board.jsonl")

QUESTIONS = [
    ("PARALLAX-P1", "Do FAILED_POSITIVE_REACTION violations follow a "
     "different later-path distribution than EXPECTED_REACTION events "
     "on the same session? (Descriptive: paths, not P&L.)"),
    ("PARALLAX-P2", "Do FAILED_NEGATIVE_REACTION violations (bad news, "
     "no selloff) resolve differently than failed positives -- or is "
     "the asymmetry an artifact of trend regime?"),
    ("PARALLAX-P3", "When the index/sector confirms the expectation "
     "but the symbol does not (RELATIVE_DISLOCATION), how often does "
     "the symbol catch up vs prove the expectation wrong?"),
    ("PARALLAX-P4", "Do dislocations persist long enough, after "
     "realistic friction, to be ECONOMICALLY_EXPRESSIBLE at all -- or "
     "are they INFORMATIONAL_VIOLATIONS only? (Measurement, not a "
     "trading proposal.)"),
]


def main() -> int:
    existing = set()
    if BOARD.exists():
        for line in BOARD.read_text().splitlines():
            try:
                existing.add(json.loads(line).get("question_id"))
            except (json.JSONDecodeError, AttributeError):
                continue
    sealed = 0
    for qid, q in QUESTIONS:
        if qid in existing:
            print(f"{qid}: already sealed, skipping")
            continue
        chain_append(BOARD, {
            "kind": "research_question", "question_id": qid,
            "question": q, "status": "OPEN",
            "origin": "PARALLAX_SHADOW_OBSERVATORY commissioning; "
                      "seeded by session 2026-08-28 catalyst-reaction "
                      "disagreements (23 of 24 classified, 14 "
                      "FAILED_POSITIVE_REACTION)",
            "evidence_standard": "prospective sealed expectations "
                                 "only; retrospective commissioning "
                                 "rows excluded; episode accounting "
                                 "mandatory",
            "resolution_authority": "NONE -- answering a question "
                                    "grants no build or trading "
                                    "authority",
            "decision_power": "PARALLAX_SHADOW_OBSERVATORY"})
        sealed += 1
        print(f"{qid}: sealed")
    print(f"sealed={sealed} skipped={len(QUESTIONS) - sealed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
