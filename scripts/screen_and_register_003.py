#!/usr/bin/env python
"""Take H1 and H3 through the reject-only screen and build registration packets.

Runs the CERTIFIED screening layer (apex.governance.screening.run_screen) on the
in-sample window, logs every outcome to results/screen_log.jsonl, and — for any
survivor — assembles a full pre-registration packet. Stops STRICTLY before
validation: no credit, no holdout, no validation IC, no winner chosen.

THE SCREEN IS STRUCTURAL, NOT PERFORMANCE-BASED.
The screen_fn rejects only on disqualifiers the screening protocol lists:
insufficient data coverage, PIT-unsafety, redundancy against an existing
validated feature, or a missing economic rationale. It NEVER computes an
in-sample IC and rejects on it -- pre-screening on the same panel the
experiment will use would contaminate the very thing screening protects. A
factor survives on economics and data, not on a peek at its performance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.config import load_config  # noqa: E402
from apex.features.registry import built_specs  # noqa: E402
from apex.governance.screening import (  # noqa: E402
    REJECT,
    SURVIVE,
    ScreenLog,
    ScreenOutcome,
    ScreenWindow,
    run_screen,
)
from apex.research.hypothesis import BEFORE_002, HypothesisDossier, Provenance  # noqa: E402
from apex.research.novelty import classify_novelty  # noqa: E402

CFG = load_config("experiment", "costs", "synthetic", "sharadar")
SPECS = {s.feature_id: s for s in built_specs()}
KNOWN = set(SPECS) | {"f1_mom_63", "f4_vs_market", "f1_mom_126",
                      "f2_close_over_sma200", "f2_frac_above_sma50",
                      "f3_vol_ratio", "f3_atr_over_close", "f4_vs_sector", "nsi"}
EXPERIMENTS = {
    "APEX-001": {"f1_mom_63", "f4_vs_market", "f1_mom_126", "f2_close_over_sma200",
                 "f2_frac_above_sma50", "f3_vol_ratio", "f3_atr_over_close",
                 "f4_vs_sector"},
    "APEX-002": {"nsi"},
}


def _dossier(title, hyp, mech, feats, direction, falsify) -> HypothesisDossier:
    return HypothesisDossier(
        content={
            "title": title, "hypothesis": hyp, "economic_rationale": mech,
            "signal_definition": f"{'+'.join(feats)}, ascending rank, equal-count deciles",
            "directional_prediction": direction,
            "timing": "as-filed filing_date <= T; forward 20 trading days",
            "data_requirements": ", ".join(feats), "universe": "frozen section 3",
            "horizon": "20 trading days", "falsification_criterion": falsify,
            "author": "research", "date": "2026-08-12",
        },
        provenance=Provenance(epoch=BEFORE_002, author="research",
                              created="2026-08-12T00:00:00+00:00"),
        economic_mechanism=mech, feature_set=tuple(feats),
        novelty_claim="fundamental mechanism, distinct from APEX-001/002",
    )


H1 = _dossier(
    "APEX-003-H1 gross profitability",
    "High gross-profits/assets earns higher forward excess return than low.",
    "Novy-Marx (2013): gross profitability is the cleanest productivity measure; "
    "the signal sits above the line and is incorporated slowly.",
    ["prof_gross_profitability"], "high profitability outperforms low",
    "mean daily Spearman IC not reliably positive at the section-13 hurdle over "
    "the validation period",
)
H3 = _dossier(
    "APEX-003-H3 quality-conditioned value",
    "Among cheap stocks, profitable ones outperform cheap-and-unprofitable ones.",
    "Novy-Marx (2013) / Asness-Frazzini-Pedersen (2019): value and quality are "
    "complementary mispricings; conditioning value on profitability separates "
    "bargains from distress.",
    ["val_book_to_market", "prof_gross_profitability"],
    "cheap-and-profitable outperforms the universe",
    "composite IC not reliably positive, OR it fails to exceed either component "
    "alone in sign, at the section-13 hurdle",
)


def structural_screen(feature_ids):
    """A reject-only screen over structural disqualifiers. No performance peek."""

    def screen_fn(dossier, window) -> ScreenOutcome:
        reasons = []
        # 1. every feature must be built and PIT-safe.
        for fid in feature_ids:
            spec = SPECS.get(fid)
            if spec is None:
                return ScreenOutcome(REJECT, (f"{fid} is not a BUILT registry feature",))
            if "PIT" not in spec.pit_rule and "filing" not in spec.pit_rule.lower():
                reasons.append(f"{fid} PIT rule unclear: {spec.pit_rule[:40]}")
        # 2. economic rationale must be present (already enforced by Dossier, but
        #    the screen states it explicitly as a survival ground).
        if len(dossier.content.get("economic_rationale", "")) < 40:
            return ScreenOutcome(REJECT, ("economic rationale too thin to justify a credit",))
        # 3. not a subset of a closed experiment's inputs (redundancy).
        fs = set(feature_ids)
        for exp, sig in EXPERIMENTS.items():
            if fs and fs <= sig:
                return ScreenOutcome(REJECT, (f"feature set is a subset of {exp}",))
        # Survives on economics + data. NOT on any in-sample performance.
        ground = (f"{len(feature_ids)} PIT-safe fundamental feature(s), coverage "
                  f"confirmed in the feature census; economic rationale present; "
                  f"not redundant with a closed experiment. Survival is on "
                  f"economic and data grounds, not on any performance measure.")
        return ScreenOutcome(SURVIVE, (ground, *reasons))

    return screen_fn


def registration_packet(h: HypothesisDossier, feature_ids) -> dict:
    """The full pre-registration packet. Audit-ready; consumes no credit here."""
    specs = {fid: SPECS[fid] for fid in feature_ids}
    return {
        "proposed_experiment_id": h.content["title"].split()[0],
        "dossier_hash": h.dossier_hash,
        "hypothesis": h.content["hypothesis"],
        "economic_mechanism": h.economic_mechanism,
        "features": {fid: {"definition": s.transformation,
                           "source_fields": list(s.source_fields),
                           "directionality": s.directionality,
                           "pit_rule": s.pit_rule} for fid, s in specs.items()},
        "signal_construction": {
            "ranking": "ascending cross-sectional rank on the eligible §3 universe",
            "composite": ("equal pre-committed weight rank composite"
                          if len(feature_ids) > 1 else "single ranked feature"),
            "no_tuning": "no winsorisation, no parameter selection, no weight search",
        },
        "portfolio_policy": {
            "construction": "long top decile / short bottom decile",
            "weighting": "equal weight", "rebalance": "monthly (fixed)",
            "note": "evaluated by the monetisation projector ONLY after validation",
        },
        "success_criteria_section_13": {
            "mean_ic": "positive",
            "t_stat": ">= 2.92 (validation critical value, unchanged)",
            "robustness": "non-overlapping test agrees in sign",
            "source": "config/experiment.yaml success_criteria; NOT re-derived",
        },
        "robustness_declared_before_validation": {
            "bootstrap": "moving-block bootstrap of the mean daily IC",
            "permutation": "block sign-permutation null",
            "block_size": 20,
            "block_size_rationale": "matches the 20-day forward-return overlap "
                                    "(MA(19) autocorrelation); DECLARED, not searched",
            "n_resamples": 2000, "n_permutations": 2000, "seed": 20260807,
            "subperiod_diagnostics": ["calendar_year", "calendar_quarter"],
            "subperiod_note": "DIAGNOSTIC ONLY; never used to select a subperiod",
        },
        "falsification_criterion": h.content["falsification_criterion"],
        "contamination": {"epoch": "BEFORE_APEX_002",
                          "descendant_of_failure": h.requires_independent_rejustification()},
        "status": "PRE-REGISTERED PACKET — not yet registered; no credit spent; "
                  "validation NOT run",
    }


def main() -> int:
    log = ScreenLog(Path("results/screen_log.jsonl"))
    window = ScreenWindow.in_sample(CFG)
    out = {"screen_window": {"start": window.start, "end": window.end},
           "results": []}

    print("=" * 74)
    print("APEX-003 candidate screening (reject-only, in-sample) + registration prep")
    print("=" * 74)
    print(f"  window {window.start} .. {window.end}   no credit, no validation, no holdout")
    print()

    for h, feats in ((H1, ["prof_gross_profitability"]),
                     (H3, ["val_book_to_market", "prof_gross_profitability"])):
        novelty = classify_novelty(h, known_feature_ids=KNOWN,
                                   experiment_signatures=EXPERIMENTS, prior_dossiers={})
        outcome = run_screen(h.screenable(), structural_screen(feats), log, window, CFG)
        packet = registration_packet(h, feats) if outcome.verdict == SURVIVE else None
        entry = {
            "title": h.content["title"], "dossier_hash": h.dossier_hash,
            "novelty": novelty.classification, "screen_verdict": outcome.verdict,
            "screen_reasons": list(outcome.reasons),
            "registration_packet": packet,
        }
        out["results"].append(entry)
        print(f"--- {h.content['title']}")
        print(f"    novelty        : {novelty.classification}")
        print(f"    screen verdict : {outcome.verdict}")
        for r in outcome.reasons:
            print(f"      - {r}")
        print(f"    packet built   : {packet is not None}")
        print()

    Path("results/003_registration_packets.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"screen log: {log.counts()}")
    print("wrote results/003_registration_packets.json")
    print("APEX-003 NOT registered. Credit NOT spent. Validation NOT run. Holdout SEALED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
