"""Append Campaign #003's completion record and plain answers.

Both artifacts are stamped; this row ties them together on the chain
and answers the two final questions the way the predeclared rules
force them to be answered.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append      # noqa: E402


def main() -> int:
    roster = json.loads(Path(
        "results/chronos/campaign_003_roster.json").read_text())
    arch = json.loads(Path(
        "results/chronos/survivor_archaeology.json").read_text())
    rec = {
        "kind": "CHRONOS_CAMPAIGN_003_COMPLETE",
        "artifacts": ["campaign_003_roster.json",
                      "survivor_archaeology.json"],
        "roster_verdict": roster["three_level_hallucination"]["verdict"],
        "hallucination_rates": {
            k: roster["three_level_hallucination"][k] for k in
            ("SPEC_HALLUCINATION_RATE", "FAMILY_HALLUCINATION_RATE",
             "MECHANISM_HALLUCINATION_RATE")},
        "denominator_honesty": roster["denominator_honesty"],
        "survivor_verdict": arch["verdict"],
        "selection_p_hat":
            arch["selection_permutation_test"]["p_hat"],
        "campaign_status": {
            "SCIENTIFIC_PROCESS_AUTHORITY": "QUALIFIED_REPLAY_ONLY",
            "ECONOMIC_EDGE_STATUS": "UNPROVEN",
            "TRADING_AUTHORITY": "NONE"},
        "plain_answers": {
            "can_the_scientist_control_false_discovery_across_an_evolving_roster": (
                "YES on this evidence: 0 false specs, 0 false "
                "families, 0 false mechanisms admitted across 348 "
                "nonsense attempts spanning 21 nonsense families and "
                "20 nonsense mechanisms. Honesty: 342 of 348 attempts "
                "were refused by the budget schedule before scoring, "
                "so protection came primarily from refusal-by-budget; "
                "only ~6 nonsense attempts were ever scored, and the "
                "denominators are small and stated"),
            "did_the_campaign_002_survivor_contain_information_beyond_regime_beta": (
                "NO. BASELINE_REPACKAGING under the predeclared "
                "rules: the +11.35R over 112 picked days ranks at "
                "p_hat=0.141 against 2,000 random same-size subsets "
                "of its own active period -- indistinguishable from "
                "random day-picking in a generous window where even "
                "coin-flip RANDOM_ELIGIBLE made +21.1R. Beta 0.26. "
                "The within-UP_HIVOL cell shows p_hat=0.022, but that "
                "cell was selected post hoc among four and the "
                "overall gate failed first; recorded as a residual "
                "observation, not a finding")},
        "law": "if either answer is NO, say NO",
    }
    chain_append(Path("results/chronos/chronos_registry.jsonl"), rec)
    print(json.dumps(rec["plain_answers"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
