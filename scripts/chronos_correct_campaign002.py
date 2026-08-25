"""Append the correction to Campaign #002's second plain answer.

Original preserved. The defect: 'did any candidate survive unseen
time WITHOUT relying on repeated research attempts' was answered YES
from family-level net survival. The net-positive survivor
(C2EDGE_002, 112 acts, +11.35R) was its family's THIRD attempt --
admitted legitimately under the predeclared charged-repeat sequential
framework, but not first-shot survival. The truthful answer is NO.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.correction import append_correction   # noqa: E402


def main() -> int:
    report = json.loads(
        Path("results/chronos/campaign_002.json").read_text())
    original = report["plain_answers"]
    corrected = {
        "did_the_cross_epoch_rebirth_channel_close": "YES",
        "did_any_candidate_survive_unseen_time_without_repeated_attempts": (
            "NO -- the only net-positive survivor (C2EDGE_002, 112 "
            "acts, +11.35R) was its family's THIRD attempt, admitted "
            "under the predeclared alpha-spending framework at "
            "alpha_3=0.00625. That admission is legitimate -- charged "
            "repeats are the framework's purpose -- but it is not "
            "first-shot survival, and the two must never be "
            "conflated. The family's attempt-1 edge died at -1.87R")}
    append_correction(
        Path("results/chronos/chronos_registry.jsonl"),
        correction_type="CLASSIFICATION_DEFECT",
        supersedes_record_id="campaign_002.json#plain_answers",
        original_record={"source": "campaign_002.json",
                         "field": "plain_answers", "value": original},
        defect_ids=["CHRONOS-C2-FAMILY-SURVIVAL-AS-FIRST-SHOT"],
        corrected_resolver_version="chronos_campaign_002 "
                                   "birth_attempt fix (post-1eae9db)",
        corrected_fields={"plain_answers": corrected},
        unchanged_fields_verified=[
            "n_epochs", "counters", "unique_families",
            "unique_mechanisms", "edges_born", "sealed_decisions",
            "sealed_total_R", "scientific_validity_decomposition"],
        why="the question 'without relying on repeated research "
            "attempts' was answered from family-level net survival, "
            "conflating two different questions. The rebirth channel "
            "DID close (33 clones blocked, 51 ids collapsed to 1 "
            "family, 21 tail-unresolved refusals); the survivor DID "
            "rely on repeated attempts, charged and predeclared. "
            "Both facts stand, separately, as the operator's law "
            "requires: if no, say no")
    print(json.dumps(corrected, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
