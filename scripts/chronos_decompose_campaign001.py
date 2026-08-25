"""Append Campaign #001's scientific validity decomposition.

The campaign is accepted and preserved verbatim. This appends what a
single verdict could not say: it passed one defense and exposed
failure in another. PASSED_FALSE_DISCOVERY_CONTROL was true, and
still sounded like the whole process passed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos.scoring import (                        # noqa: E402
    scientific_validity_decomposition)
from apex.governance.chain_ledger import chain_append      # noqa: E402

DECOMP = scientific_validity_decomposition(components={
    "CAUSAL_INTEGRITY": {
        "verdict": "PASS",
        "evidence": "forward-only clock; known_from enforced through "
                    "the single KnowledgeHorizon read path; zero "
                    "causal violations in 58 epochs"},
    "POISON_CONTROL": {
        "verdict": "PASS",
        "evidence": "nine-trap catalog planted and self-attacked "
                    "every epoch; 58/58 FIREWALL_HELD"},
    "WITHIN_EPOCH_FALSE_DISCOVERY_CONTROL": {
        "verdict": "PASS",
        "evidence": "p99 null bar frozen in the discovery zone each "
                    "epoch; 0/58 restraint failures vs Experiment "
                    "000's temperature 1.0"},
    "CROSS_EPOCH_MULTIPLICITY_CONTROL": {
        "verdict": "FAIL",
        "evidence": "51 births in 58 epochs were the same marginal "
                    "hypothesis reborn monthly under fresh ids; "
                    "equivalent hypotheses received unlimited "
                    "chances across time. No identity layer existed"},
    "SURVIVORSHIP_CONTROL": {
        "verdict": "PASS",
        "evidence": "full-family economics reported (-7.05R over "
                    "2,003 sealed decisions); the +53.6R positive "
                    "clone subset was explicitly refused as "
                    "survivorship in the appended correction"},
    "VALIDATION_DISCIPLINE": {
        "verdict": "PASS",
        "evidence": "frozen hypotheses; killed-in-validation stayed "
                    "dead; no threshold adjusted after validation or "
                    "test"},
    "LOCKBOX_INTEGRITY": {
        "verdict": "PASS",
        "evidence": "2025-01-01..2026-06-01 untouched; every ingested "
                    "bar guarded structurally"},
})


def main() -> int:
    rec = {"kind": "campaign_scientific_decomposition",
           "campaign": "CHRONOS_CAMPAIGN_001",
           "appended": "2026-08-25", "decomposition": DECOMP,
           "note": "the campaign is accepted; this names which "
                   "defense failed so PASSED_FALSE_DISCOVERY_CONTROL "
                   "cannot be read as the whole process passing"}
    chain_append(Path("results/chronos/chronos_registry.jsonl"), rec)
    print(json.dumps({
        "components": {c: v["verdict"]
                       for c, v in DECOMP["components"].items()},
        "OVERALL_SCIENTIFIC_AUTHORITY":
            DECOMP["OVERALL_SCIENTIFIC_AUTHORITY"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
