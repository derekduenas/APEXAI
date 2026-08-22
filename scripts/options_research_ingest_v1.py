"""APEX OPTIONS RESEARCH V1 -- ingestion (F O1/O2/O22).

Ingests the operator-commissioned deep research report (the verbatim
source lives at results/research_library/sources/
APEX_OPTIONS_RESEARCH_V1_source_report.md -- this script reads it, it
never re-embeds or paraphrases it) into the Research Library under
collection=OPTIONS, registers the 10 OPT-001..010 mechanisms (only
OPT-001/002/003 in the v1-active set; OPT-004..010 are named but
apex_status=UNTESTED and expression_candidate.py structurally refuses
to reference them), registers the 3 hypotheses (all mechanically
PROPOSED_ONLY -- hypotheses.propose() has no status parameter), and
advances the APEX_OPTIONS_RESEARCH_V1 program from NOT_STARTED to
RESEARCH_INGESTED.

Idempotent: documents.ingest() dedupes on content hash, mechanisms and
hypotheses are only (re-)registered if not already present, and the
program status only ever moves forward.

No confirmatory credit is spent. No mechanism is ever registered as
PROMOTED -- the library's own API mechanically refuses that (see
apex/research_library/mechanisms.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from apex.research_library import documents, hypotheses, mechanisms, programs
from apex.options_research import birth as options_birth

REPO = Path(__file__).resolve().parents[1]
SOURCE_REPORT = REPO / "results" / "research_library" / "sources" / \
    "APEX_OPTIONS_RESEARCH_V1_source_report.md"

REPORT_TITLE = "APEX Options Expression Research: When Options Beat Stock or No Trade"

# 10 mechanisms. OPT-001/002/003 are the only ones expression_candidate.py's
# ACTIVE_MECHANISM_IDS will ever accept on a real candidate; OPT-004..010
# are registered so the vocabulary exists, but are REGISTERED_NOT_ACTIVE.
MECHANISMS = [
    dict(mechanism_id="OPT-001-DIRECTIONAL-CONVEXITY", name="Directional Convexity",
        claimed_mechanism=(
            "When APEX's forward distribution implies a large, well-timed "
            "directional move, a long option's convex payoff can dominate "
            "the linear payoff of stock on a risk-matched basis."),
        why_it_might_exist=(
            "Stock exposes the full linear downside for the same directional "
            "bet; a bounded-loss convex instrument only outperforms when the "
            "realized move clears its breakeven, which requires a genuine "
            "distributional edge, not just a directional guess."),
        expected_behavior=(
            "On a risk-matched panel, the long option's expectancy exceeds "
            "stock's when direction_quality is STRONG and the realized move "
            "clears premium plus costs before the horizon."),
        required_data=("underlying forward distribution", "option premium",
                       "conservative-taker fill"),
        active=True),
    dict(mechanism_id="OPT-002-RICH-WING-VERTICALIZATION", name="Rich-Wing Verticalization",
        claimed_mechanism=(
            "When the far wing of the option surface is priced rich relative "
            "to the near wing for a directional thesis, selling the rich "
            "wing against the long leg (a debit vertical) can reduce the "
            "cost of expressing the same directional thesis."),
        why_it_might_exist=(
            "Skew/wing richness is a standing feature of many surfaces; "
            "verticalizing captures it as a financing benefit only if the "
            "capped upside still covers the thesis's expected move."),
        expected_behavior=(
            "A debit vertical's net-of-cost expectancy exceeds the "
            "equivalent long call/put's when wing richness is real and the "
            "thesis's expected move sits within the vertical's capped range."),
        required_data=("option surface skew/wing pricing", "premium for both legs",
                       "legged/combo fill economics"),
        active=True),
    dict(mechanism_id="OPT-003-APEX-FORWARD-VOL-GAP", name="APEX Forward Vol Gap",
        claimed_mechanism=(
            "When APEX's own forward distribution implies materially wider "
            "realized-move uncertainty than the option surface's implied "
            "volatility prices in, a long-volatility structure (straddle/"
            "strangle) can be underpriced relative to APEX's own forward view."),
        why_it_might_exist=(
            "APEX's forward distribution is built from intelligence the "
            "option surface may not fully price -- a genuine information or "
            "timing edge, not merely a volatility risk premium bet."),
        expected_behavior=(
            "A long-volatility structure's net-of-cost expectancy is positive "
            "when APEX's implied path_uncertainty/magnitude_range exceeds "
            "the surface's atm_iv by a margin that survives spread and theta."),
        required_data=("atm_iv", "APEX forward path_uncertainty/magnitude_range",
                       "term structure"),
        active=True),
    dict(mechanism_id="OPT-004-CALENDAR-SPREADS", name="Calendar Spreads",
        claimed_mechanism="Term-structure richness/cheapness across two expiries.",
        why_it_might_exist="Term structure can dislocate around known events.",
        expected_behavior="Deferred -- not modeled in v1.",
        required_data=("term structure across >=2 expiries",), active=False),
    dict(mechanism_id="OPT-005-IRON-CONDORS", name="Iron Condors",
        claimed_mechanism="Range-bound premium harvesting via a 4-leg structure.",
        why_it_might_exist="Realized vol can run persistently below implied in range regimes.",
        expected_behavior="Deferred -- not modeled in v1.",
        required_data=("full surface across 4 strikes", "realized-vol regime classifier"),
        active=False),
    dict(mechanism_id="OPT-006-DEALER-GAMMA-POSITIONING", name="Dealer Gamma Positioning",
        claimed_mechanism="Dealer hedging flow amplifies or dampens realized moves near large gamma strikes.",
        why_it_might_exist="Dealer hedging is a real, documented microstructure effect.",
        expected_behavior="Deferred -- OPEN_INTEREST != DEALER_POSITION_SIGN, no data source yet (F O7).",
        required_data=("dealer positioning sign (not open interest alone)",),
        active=False),
    dict(mechanism_id="OPT-007-NAKED-SHORT-STRUCTURES", name="Naked Short Structures",
        claimed_mechanism="Selling uncovered premium against a thesis of range-bound or mean-reverting price.",
        why_it_might_exist="Premium selling can be profitable in low-realized-vol regimes.",
        expected_behavior="Deferred -- unbounded loss profile is out of scope for a shadow research v1.",
        required_data=("realized-vol regime classifier", "tail-risk model"), active=False),
    dict(mechanism_id="OPT-008-GAMMA-SCALPING", name="Gamma Scalping",
        claimed_mechanism="Dynamic delta-hedging a long-gamma position to monetize realized vs implied vol.",
        why_it_might_exist="A long-gamma position's P&L is a function of realized vol path, independent of direction.",
        expected_behavior="Deferred -- economics depend intensely on hedge frequency and transaction costs (per the source report's own conclusion).",
        required_data=("continuous underlying quotes", "hedge transaction cost model"),
        active=False),
    dict(mechanism_id="OPT-009-ZERO-DTE-STRUCTURES", name="Zero-DTE Structures",
        claimed_mechanism="Same-day expiry structures exploiting rapid theta decay / gamma risk.",
        why_it_might_exist="0DTE has a distinct risk/reward profile from ordinary-expiry options.",
        expected_behavior="Deferred -- SEPARATE_RESEARCH_BUCKET_NOT_ACTIVE_V1 (F O9).",
        required_data=("intraday surface refresh at high frequency",), active=False),
    dict(mechanism_id="OPT-010-COMPLEX-MULTILEG-VOLATILITY", name="Complex Multi-Leg Volatility",
        claimed_mechanism="Butterflies, ratio spreads, and other >2-leg volatility structures.",
        why_it_might_exist="Multi-leg structures can isolate specific surface-shape views.",
        expected_behavior="Deferred -- not modeled in v1.",
        required_data=("full surface across >=3 strikes", "combo-fill economics for >2 legs"),
        active=False),
]

HYPOTHESES = [
    dict(hypothesis_id="H_OPT_DIRECTIONAL_CONVEXITY", mechanism_id="OPT-001-DIRECTIONAL-CONVEXITY",
        statement=(
            "On a risk-matched panel, a long option's net expectancy exceeds "
            "stock's when APEX direction_quality=STRONG and the option's "
            "structural horizon satisfies the DTE-matching law."),
        market="US equities, APEX-eligible universe",
        primary_metric="mean_net_expectancy (option) - mean_net_expectancy (stock), risk-matched",
        minimum_sample="TBD -- no prospective observation window has opened yet",
        falsification=(
            "the option's risk-matched expectancy is not durably positive "
            "relative to stock across a prospective, non-cherry-picked "
            "sample of resolved outcomes"),
        regime_requirements="no regime restriction proposed yet -- untested",
        cost_requirements="must survive CONSERVATIVE_TAKER fills, not DIAGNOSTIC_MIDPOINT",
        prospective_test_design=(
            "seal OPTIONS_BEFORE_CARD at candidate time, resolve at all due "
            "RESOLUTION_HORIZONS, no cherry-picking (F O20)")),
    dict(hypothesis_id="H_OPT_VERTICALIZATION", mechanism_id="OPT-002-RICH-WING-VERTICALIZATION",
        statement=(
            "When the option surface's far wing is priced rich relative to "
            "the near wing, a debit vertical's net-of-cost expectancy "
            "exceeds the equivalent single-leg long option's."),
        market="US equities, APEX-eligible universe",
        primary_metric="mean_net_expectancy (vertical) - mean_net_expectancy (single leg)",
        minimum_sample="TBD -- no prospective observation window has opened yet",
        falsification="verticalization does not durably reduce net cost relative to single-leg exposure",
        regime_requirements="no regime restriction proposed yet -- untested",
        cost_requirements="must model LEGGED_FILL vs COMBO_FILL separately, never assume simultaneous fills",
        prospective_test_design="same as H_OPT_DIRECTIONAL_CONVEXITY, compared structure-vs-structure"),
    dict(hypothesis_id="H_OPT_FORWARD_VOL_GAP", mechanism_id="OPT-003-APEX-FORWARD-VOL-GAP",
        statement=(
            "When APEX's forward path_uncertainty/magnitude_range implies "
            "materially wider realized-move uncertainty than the surface's "
            "atm_iv prices in, a long-volatility structure's net-of-cost "
            "expectancy is durably positive."),
        market="US equities, APEX-eligible universe",
        primary_metric="mean_net_expectancy (straddle/strangle), net of theta and spread",
        minimum_sample="TBD -- no prospective observation window has opened yet",
        falsification="the vol gap does not translate into positive net-of-cost expectancy prospectively",
        regime_requirements="requires a numeric APEX forward magnitude/timing estimate, which Curve does not yet emit (F O8) -- structurally NOT_YET_ESTIMABLE until that exists",
        cost_requirements="must survive theta decay over the full holding horizon, not just at entry",
        prospective_test_design="straddle/strangle enters ONLY under OPT-003 conditions, never a default (F O4)"),
]


def ingest_report(*, now) -> tuple:
    content = SOURCE_REPORT.read_text()
    doc, verdict = documents.ingest(
        title=REPORT_TITLE, collection="OPTIONS", document_type="RESEARCH_REPORT",
        source_type="OPERATOR_COMMISSIONED_DEEP_RESEARCH",
        source_name="APEX Options Expression Research",
        source_reference=str(SOURCE_REPORT.relative_to(REPO)), content=content,
        research_status="REVIEWED", evidence_class="UNASSESSED",
        known_limitations=("no live options tick-history purchased yet",
                           "Alpaca OPRA entitlement carries no Greeks/IV (F O24)"),
        known_from=now, now=now)
    return doc, verdict


def _existing_ids(path: Path, key: str) -> set:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.add(json.loads(line).get(key))
        except json.JSONDecodeError:
            continue
    return out


def register_mechanisms(*, now, document_id: str) -> list:
    already = _existing_ids(mechanisms.LEDGER, "mechanism_id")
    out = []
    for m in MECHANISMS:
        if m["mechanism_id"] in already:
            continue
        rec = mechanisms.register_mechanism(
            mechanism_id=m["mechanism_id"], name=m["name"],
            description=m["claimed_mechanism"], market="US equities",
            time_horizon="intraday to multi-day", claimed_mechanism=m["claimed_mechanism"],
            why_it_might_exist=m["why_it_might_exist"],
            expected_behavior=m["expected_behavior"],
            falsification="prospective resolved outcomes do not support the claimed_mechanism",
            supporting_documents=(document_id,), required_data=m["required_data"],
            known_failure_modes=(() if m["active"] else ("REGISTERED_NOT_ACTIVE -- out of v1 scope",)),
            evidence_status="THEORETICAL", apex_status="UNTESTED",
            known_from=now, now=now)
        out.append(rec)
    return out


def register_hypotheses(*, now) -> list:
    already = _existing_ids(hypotheses.LEDGER, "hypothesis_id")
    return [hypotheses.propose(known_from=now, now=now, **h) for h in HYPOTHESES
           if h["hypothesis_id"] not in already]


def main():
    now = pd.Timestamp.now(tz="UTC")

    doc, verdict = ingest_report(now=now)
    print(f"[ingest] {verdict}: {doc.document_id}")

    mech_recs = register_mechanisms(now=now, document_id=doc.document_id)
    print(f"[mechanisms] registered {len(mech_recs)}")

    hyp_recs = register_hypotheses(now=now)
    print(f"[hypotheses] proposed {len(hyp_recs)}")

    prog = programs.update_program_status(
        "APEX_OPTIONS_RESEARCH_V1", now=now, status="RESEARCH_INGESTED", document_count=1)
    print(f"[program] APEX_OPTIONS_RESEARCH_V1 -> {prog['status']}")

    minted = options_birth.mint_all(now=now)
    print(f"[births] minted {len(minted)} new (of {len(options_birth.BIRTH_VERSIONS)} total)")

    return {"document": doc.as_record(), "verdict": verdict,
           "mechanisms": [m.as_record() for m in mech_recs],
           "hypotheses": [h.as_record() for h in hyp_recs],
           "program": prog, "births_minted": len(minted)}


if __name__ == "__main__":
    result = main()
    print(json.dumps({"summary": {
        "document_id": result["document"]["document_id"],
        "verdict": result["verdict"],
        "mechanism_count": len(result["mechanisms"]),
        "hypothesis_count": len(result["hypotheses"]),
        "program_status": result["program"]["status"],
        "births_minted": result["births_minted"],
    }}, indent=2))
