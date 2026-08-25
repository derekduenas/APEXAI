"""Append the correction to Campaign #001's first-pass classification.

The original report is preserved verbatim. The defect:
survived_unseen_time was computed as bool(retired) -- retirement
counted as survival -- which inflated EDGE_AUTHORITY to
RESEARCH_CANDIDATE. Corrected at the family level: 2,003 sealed
decisions netting -7.05R; the 15 positive retirees are clones of a
family whose siblings lost more, and selecting them would be
survivorship.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos.scoring import classify_experiment      # noqa: E402
from apex.governance.correction import append_correction   # noqa: E402


def main() -> int:
    report = json.loads(
        Path("results/chronos/campaign_001.json").read_text())
    original = report["classification"]
    corrected = classify_experiment(
        economic_positive=False,
        false_discovery_restraint="DEMONSTRATED",
        survived_unseen_time=False)
    append_correction(
        Path("results/chronos/chronos_registry.jsonl"),
        correction_type="CLASSIFICATION_DEFECT",
        supersedes_record_id="campaign_001.json#classification",
        original_record={"source": "campaign_001.json",
                         "field": "classification",
                         "value": original},
        defect_ids=["CHRONOS-C1-SURVIVED-AS-RETIRED"],
        corrected_resolver_version="chronos_campaign family-survival "
                                   "fix (post-567159f)",
        corrected_fields={"classification": corrected},
        unchanged_fields_verified=[
            "n_epochs", "epoch_restraint_fail_rate", "sealed_total_R",
            "edges_born", "edges_retired", "sealed_decisions"],
        why="survived_unseen_time was computed as bool(retired): "
            "retirement -- the edge DYING out of sample -- was counted "
            "as surviving unseen time, inflating EDGE_AUTHORITY to "
            "RESEARCH_CANDIDATE. Per-edge survival would also be "
            "survivorship: 51 births in 58 epochs are monthly rebirths "
            "of the same marginal hypothesis; the 15 positive clones "
            "(+53.6R) belong to a family whose siblings lost -60.4R, "
            "netting -7.05R over 2,003 sealed decisions. A family that "
            "nets negative over 2,003 sealed out-of-sample decisions "
            "did not survive unseen time, whatever its luckiest clones "
            "did")
    print(json.dumps({"original": {k: original[k] for k in
                                   ("ECONOMIC_TEST_RESULT",
                                    "SCIENTIFIC_VALIDITY",
                                    "EDGE_AUTHORITY")},
                      "corrected": {k: corrected[k] for k in
                                    ("ECONOMIC_TEST_RESULT",
                                     "SCIENTIFIC_VALIDITY",
                                     "EDGE_AUTHORITY")}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
