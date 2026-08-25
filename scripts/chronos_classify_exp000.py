"""Append the research qualification to CHRONOS Experiment 000.

The original record is NOT rerun, NOT replaced, NOT cleaned. The
permissive threshold, the winning moon phase, the lucky candidate --
all preserved. This appends the three-line classification so nobody
six months from now reads 'CHALLENGER_DOMINATED' without seeing the
nonsense controls standing next to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos.scoring import classify_experiment      # noqa: E402
from apex.edgeforge.registry import record_result          # noqa: E402


def main() -> int:
    reg = Path("results/chronos/chronos_registry.jsonl")
    classification = classify_experiment(
        economic_positive=True,            # +3.11R / 8 acts, sealed
        false_discovery_restraint="FAILED",  # temp 1.0, moon phase won
        survived_unseen_time=True)         # and none of it matters
    rec = record_result(
        reg, discovery_id="CHRONOS_DEMO_FOLD_SEARCH",
        status="CONTRADICTED",
        result={"experiment": "EXP_000",
                "classification": classification,
                "preserved_as": "calibration artifact -- threshold too "
                                "permissive, hallucination temperature "
                                "1.0, moon phase won, candidate got "
                                "lucky",
                "never": "rerun with the corrected threshold; the "
                         "corrected machinery is a new lineage "
                         "(Campaign #001, EXP 001+)"},
        why="economic success cannot rescue scientific invalidity; "
            "the discovery engine could not distinguish real "
            "structure from deliberate nonsense")
    print(json.dumps({k: classification[k] for k in
                      ("ECONOMIC_TEST_RESULT", "SCIENTIFIC_VALIDITY",
                       "EDGE_AUTHORITY")}, indent=1))
    print("appended:", rec.get("status", "CONTRADICTED"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
