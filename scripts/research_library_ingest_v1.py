#!/usr/bin/env python
"""APEX RESEARCH LIBRARY V1 — initial ingestion. A one-time (idempotent
-- duplicate detection makes re-running safe) governance act: mints the
library birth, registers the empty OPTIONS/BTC_PERPS program
namespaces, ingests the real documents this repository actually
contains, and extracts a small number of genuinely-read structured
mechanisms/hypothesis candidates from the blueprint document. Nothing
here is invented -- every source_reference below was verified to exist
on disk before this script was written.

    python scripts/research_library_ingest_v1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

from apex.research_library.birth import mint  # noqa: E402
from apex.research_library.documents import ingest  # noqa: E402
from apex.research_library.hypotheses import propose  # noqa: E402
from apex.research_library.mechanisms import register_mechanism  # noqa: E402
from apex.research_library.programs import PROGRAMS, register_program  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
NOW = pd.Timestamp.now(tz="UTC")


def _ingest_file(path: str, *, title: str, collection: str, document_type: str,
                 source_type: str, evidence_class: str = "UNASSESSED",
                 known_limitations: tuple = ()) -> tuple:
    p = REPO / path
    if not p.exists():
        print(f"SKIP (not found): {path}")
        return None, "NOT_FOUND"
    content = p.read_text()
    doc, verdict = ingest(
        title=title, collection=collection, document_type=document_type,
        source_type=source_type, source_name=path, source_reference=path,
        content=content, known_from=NOW, now=NOW, evidence_class=evidence_class,
        known_limitations=known_limitations)
    print(f"{verdict:12s} v{doc.version} {path}")
    return doc, verdict


def main() -> int:
    print("=== BIRTH ===")
    mint(now=NOW)

    print("\n=== PROGRAMS ===")
    for prog in PROGRAMS:
        register_program(prog, now=NOW)

    print("\n=== ELITE_TRADING ===")
    blueprint, _ = _ingest_file(
        "docs/PROFIT-MACHINE-BLUEPRINT.md",
        title="APEX Profit Machine — The Governing Blueprint",
        collection="ELITE_TRADING", document_type="DOCTRINE", source_type="INTERNAL",
        evidence_class="THEORETICAL",
        known_limitations=(
            "This is the OPERATOR'S GOVERNING RULING (2026-08-15) that says it "
            "governs off 'the deep-research top 1% trader blueprint' -- it is "
            "the closest real match in this repo to the title 'Building a "
            "Top-1% APEX Hunter: Research Blueprint for an Intraday + "
            "Options-Capable Profit Machine', but no file under that exact "
            "title was found anywhere in the repository. The original raw "
            "deep-research document, if it exists outside this repo, was not "
            "located.",))
    grad, _ = _ingest_file(
        "docs/HUNTER-GRADUATION-CRITERIA.md",
        title="Hunter Graduation Criteria — Top 1% Defined Before The Data Exists",
        collection="ELITE_TRADING", document_type="DOCTRINE", source_type="INTERNAL")
    fitness, _ = _ingest_file(
        "docs/AUDIT/TOP1PCT-FITNESS-AUDIT.md", title="Top-1% Fitness Audit",
        collection="ELITE_TRADING", document_type="APEX_INTERNAL_REPORT",
        source_type="INTERNAL")

    print("\n=== RESEARCH_METHODS ===")
    _ingest_file("APEX-Research-Protocol-v1.0-Experiment-001.md",
                title="APEX Research Protocol v1.0", collection="RESEARCH_METHODS",
                document_type="DOCTRINE", source_type="INTERNAL")
    _ingest_file("APEX-PROFIT-MACHINE-EXERCISE-SPEC.md",
                title="APEX Profit Machine — Historical Discovery Exercise Spec (Frozen)",
                collection="RESEARCH_METHODS", document_type="DOCTRINE",
                source_type="INTERNAL")

    print("\n=== APEX_INTERNAL_LESSONS ===")
    _ingest_file("docs/AUDIT/DAY1-PARTIAL-SESSION-INTEGRITY.md",
                title="Day-1 Partial-Session Integrity — Ratified Finding",
                collection="APEX_INTERNAL_LESSONS", document_type="FAILURE_ANALYSIS",
                source_type="INTERNAL", evidence_class="EMPIRICALLY_SUPPORTED")
    _ingest_file("results/frontier/FRONTIER_NEXTGEN_BUILD_MAP.md",
                title="APEX Frontier Next-Gen Build Map",
                collection="APEX_INTERNAL_LESSONS", document_type="APEX_INTERNAL_REPORT",
                source_type="INTERNAL")
    _ingest_file("results/APEX-PROFIT-MACHINE-DISCOVERY-EXERCISE.md",
                title="APEX Profit Machine — Historical Discovery Exercise",
                collection="APEX_INTERNAL_LESSONS", document_type="EXPERIMENT_RESULT",
                source_type="INTERNAL")
    _ingest_file("APEX-002-Protocol-Net-Share-Issuance.md",
                title="APEX Experiment #002 — Net Share Issuance",
                collection="APEX_INTERNAL_LESSONS", document_type="EXPERIMENT_RESULT",
                source_type="INTERNAL")
    _ingest_file("APEX-002-ERRATUM-001-decile-orientation.md",
                title="APEX-002 Erratum #001 — Decile Orientation",
                collection="APEX_INTERNAL_LESSONS", document_type="FAILURE_ANALYSIS",
                source_type="INTERNAL")
    _ingest_file("APEX-003-Protocol-Gross-Profitability.md",
                title="APEX Experiment #003 — Gross Profitability",
                collection="APEX_INTERNAL_LESSONS", document_type="EXPERIMENT_RESULT",
                source_type="INTERNAL")
    _ingest_file("APEX-004-Protocol-Smallcap.md",
                title="APEX Experiment #004 — Small-Cap Gross Profitability",
                collection="APEX_INTERNAL_LESSONS", document_type="EXPERIMENT_RESULT",
                source_type="INTERNAL")

    # ---- CANDIDATE inventory only (NOT ingested this pass) --------------
    print("\n=== CANDIDATE (inventoried, not ingested) ===")
    for cand in ("docs/AUDIT/APEX-RED-TEAM-AUDIT.md", "docs/AUDIT/DIGITAL-TWIN-AUDIT.md",
                "docs/AUDIT/ENFORCEMENT-DOCTRINE.md",
                "docs/AUDIT/INTELLIGENCE-ENGINE-AUDIT.md",
                "docs/AUDIT/MUSEUM-OF-NEGATIVE-CONTROLS.md",
                "docs/AUDIT/STRATEGY-SCIENCE-AUDIT.md", "docs/AUDIT/TEST-SUITE-AUDIT.md"):
        exists = (REPO / cand).exists()
        print(f"{'CANDIDATE' if exists else 'UNKNOWN':10s} {cand}")

    print("\n=== UNKNOWN (no file artifact found) ===")
    for name in ("FastWatch failure post-mortem", "Frontier progress failure post-mortem",
                "DATA-2 sensory upgrade report"):
        print(f"UNKNOWN    {name} -- exists only as session narrative "
             f"tonight, not as a committed file; not fabricated as a source")

    # ---- extracted mechanisms, from the blueprint's ACTUAL content -------
    print("\n=== MECHANISMS EXTRACTED (from the blueprint document) ===")
    if blueprint is not None:
        m1 = register_mechanism(
            mechanism_id="ELITE-001-ASSASSIN-DOCTRINE",
            name="The Assassin as a logical pipeline stage, not one agent",
            description="Qualitative (adversarial), statistical (disagreement, "
            "analogue support), data-quality, economic and existential attacks "
            "are separate named attack classes against a candidate trade, each "
            "recorded whether it lands or not.",
            market="EQUITIES_INTRADAY", time_horizon="INTRADAY",
            claimed_mechanism="Rejection economics: a stage that adds no EV to "
            "the surviving population is prestige, not edge; a stage that "
            "subtracts EV is actively hurting.",
            why_it_might_exist="Distributing 'prove this trade is bad' across "
            "independent attack classes surfaces failure modes a single "
            "evaluator would not (qualitative bias blind spots differ from "
            "statistical ones).",
            expected_behavior="Per-stage funnel_economics (N, 60m EV) should "
            "show survivorship IMPROVING EV at each successive stage.",
            falsification="A stage's survivors show no better (or worse) "
            "forward EV than the population it drew from.",
            supporting_documents=(blueprint.document_id,),
            known_failure_modes=("Epoch-1 grants qualitative attacks only a "
                                 "wounding (WATCH-cap) power, not a kill, "
                                 "specifically because this has not yet been "
                                 "forward-validated -- a deferred versioned "
                                 "ruling, stated explicitly in the source.",),
            evidence_status="THEORETICAL", apex_status="OBSERVATIONAL",
            known_from=NOW, now=NOW)
        print(f"registered {m1.mechanism_id}")

        m2 = register_mechanism(
            mechanism_id="ELITE-002-SELECTIVITY-OVER-ACTIVITY",
            name="Selectivity over activity as the governing design axiom",
            description="The system is designed to find RARE asymmetric "
            "opportunities and reject mediocre trades aggressively, rather "
            "than to predict stock direction generally.",
            market="EQUITIES_INTRADAY", time_horizon="INTRADAY",
            claimed_mechanism="A machine that concentrates capital only when "
            "'the complete evidence stack earns it' outperforms one that "
            "trades every marginal signal, because false positives are far "
            "more numerous than true asymmetric setups.",
            why_it_might_exist="Base-rate asymmetry: genuinely asymmetric "
            "opportunities are rare by construction; a low-frequency, "
            "high-bar filter concentrates on the tail where edge concentrates.",
            expected_behavior="Realized hit-rate and EV per trade should be "
            "materially better than the unfiltered universe average, at the "
            "cost of low trade frequency.",
            falsification="Aggressive filtering shows no EV improvement over "
            "an unfiltered baseline, i.e. selectivity is theater, not signal.",
            supporting_documents=(blueprint.document_id,) + (
                (grad.document_id,) if grad else ()),
            known_from=NOW, now=NOW)
        print(f"registered {m2.mechanism_id}")

        h1 = propose(
            hypothesis_id="ELITE-H1-ASSASSIN-EMPLOYMENT-CONTRACT",
            mechanism_id=m1.mechanism_id,
            statement="Candidates the Assassin wounds (SURVIVED_WOUNDED) show "
            "worse forward 60m EV than candidates it passes clean "
            "(SURVIVED_CLEAN), controlling for the same playbook.",
            market="EQUITIES_INTRADAY", primary_metric="ret_60m by verdict cohort",
            secondary_metrics=("mfe", "mae", "hit_rate"),
            required_data=("resolved forward realizations tagged with "
                           "assassin_review.verdict",),
            minimum_sample="the same >=20 per group / >=10 distinct dates rule "
                          "used elsewhere in this codebase's learning registries",
            falsification="wounded and clean cohorts show statistically "
            "indistinguishable forward EV",
            regime_requirements="both cohorts must span the same regime mix",
            cost_requirements="none beyond what Hunter already records",
            prospective_test_design="passive observational tagging of the "
            "existing forward ledger; no new experiment credit required, this "
            "is exactly what apex.frontier.learning.H_ASSASSIN already tracks",
            known_from=NOW, now=NOW)
        print(f"proposed {h1.hypothesis_id} (status={h1.status})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
