#!/usr/bin/env python
"""Generate APEX-003 CANDIDATE hypotheses THROUGH the discovery system.

This does not bypass the architecture: it instantiates real HypothesisDossier
objects, classifies them with the certified novelty classifier against the
actual APEX-001/002 feature signatures, and assembles ResearchDossiers with
swarm roles whose disagreement is preserved. It produces records, not
experiments.

DOES NOT: create APEX-003, spend a credit, access validation/holdout, compute
any IC/return/t-stat, run the reject-only screen against real data, rank by any
number, or search a combination space. Every hypothesis is drawn from published
literature predating both closed experiments (provenance epoch BEFORE_002), so
none is selected by a prior result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.features.registry import built_specs  # noqa: E402
from apex.research import novelty, swarm  # noqa: E402
from apex.research.hypothesis import (  # noqa: E402
    BEFORE_002,
    HypothesisDossier,
    Provenance,
)

# The two closed experiments' feature signatures, for novelty classification.
EXPERIMENTS = {
    "APEX-001": {"f1_mom_126", "f1_mom_63", "f2_close_over_sma200",
                 "f2_frac_above_sma50", "f3_vol_ratio", "f3_atr_over_close",
                 "f4_vs_sector", "f4_vs_market"},
    "APEX-002": {"nsi"},
}
KNOWN = {s.feature_id for s in built_specs()} | set().union(*EXPERIMENTS.values())

CREATED = "2026-08-12T00:00:00+00:00"


def _prov(descends: str = "") -> Provenance:
    return Provenance(epoch=BEFORE_002, author="research", created=CREATED,
                      motivating_source="published factor literature",
                      descends_from_experiment=descends)


def _science(**kw) -> dict:
    base = {"title": kw["title"], "author": "research", "date": "2026-08-12"}
    base.update({k: v for k, v in kw.items() if k != "title"})
    base["title"] = kw["title"]
    return base


# ---------------------------------------------------------------------------
# H1 -- gross profitability (Novy-Marx 2013)
# ---------------------------------------------------------------------------
H1 = HypothesisDossier(
    content={
        "title": "H1 gross profitability",
        "hypothesis": "Firms with higher gross profits scaled by assets earn "
                      "higher subsequent excess returns than low-profitability firms.",
        "economic_rationale": "Novy-Marx (2013): gross profitability is the "
            "cleanest accounting measure of economic productivity, less "
            "contaminated by discretionary items than net income. Profitable "
            "firms are underpriced because the signal is buried above the line "
            "and slowly incorporated.",
        "signal_definition": "gross profit / total assets, as-filed ARQ, "
                             "cross-sectionally ranked.",
        "directional_prediction": "high gross profitability outperforms low.",
        "timing": "as-filed at filing date <= T; forward 20 trading days.",
        "data_requirements": "SF1 gp, assets (as-filed ARQ).",
        "universe": "the frozen section-3 eligible universe, unchanged.",
        "horizon": "20 trading days.",
        "falsification_criterion": "mean cross-sectional Spearman IC of gross "
            "profitability against forward excess return is not reliably "
            "positive at the pre-registered hurdle over the validation period.",
        "author": "research", "date": "2026-08-12",
    },
    provenance=_prov(),
    economic_mechanism="risk-adjusted mispricing of productivity (quality)",
    feature_set=("prof_gross_profitability",),
    novelty_claim="a profitability/quality mechanism; no closed experiment used "
                  "any fundamental profitability feature.",
    known_risks=("profitability is correlated with sector composition",),
)

# ---------------------------------------------------------------------------
# H2 -- accruals (Sloan 1996)
# ---------------------------------------------------------------------------
H2 = HypothesisDossier(
    content={
        "title": "H2 accrual quality",
        "hypothesis": "Firms whose earnings are backed by cash flow (low "
                      "accruals) outperform firms with high accruals.",
        "economic_rationale": "Sloan (1996): investors fixate on headline "
            "earnings and underweight the difference between accrual and cash "
            "earnings. High-accrual earnings are less persistent; the market "
            "learns this slowly.",
        "signal_definition": "total accruals scaled by assets, as-filed ARQ, "
                             "ranked; lower is better.",
        "directional_prediction": "low-accrual firms outperform high-accrual.",
        "timing": "as-filed at filing date <= T; forward 20 trading days.",
        "data_requirements": "SF1 netinc, ncfo, assets (as-filed ARQ).",
        "universe": "the frozen section-3 eligible universe, unchanged.",
        "horizon": "20 trading days.",
        "falsification_criterion": "the low-accrual minus high-accrual IC is "
            "not reliably positive at the pre-registered hurdle over validation.",
        "author": "research", "date": "2026-08-12",
    },
    provenance=_prov(),
    economic_mechanism="earnings-quality / functional fixation on headline EPS",
    feature_set=("accr_total_accruals",),
    novelty_claim="an earnings-quality mechanism distinct from price, share "
                  "count, and profitability level.",
    known_risks=("accruals correlate with growth and with profitability",),
)

# ---------------------------------------------------------------------------
# H3 -- value conditioned on quality (RECOMBINATION, the library's purpose)
# ---------------------------------------------------------------------------
H3 = HypothesisDossier(
    content={
        "title": "H3 quality-conditioned value",
        "hypothesis": "Among cheap stocks, those that are also profitable "
                      "outperform cheap-but-unprofitable stocks; value and "
                      "quality are complementary, not redundant.",
        "economic_rationale": "Novy-Marx (2013) and Asness-Frazzini-Pedersen "
            "(2019): book-to-market alone buys distress as often as bargains. "
            "Conditioning value on profitability separates cheap-and-good from "
            "cheap-and-failing. The two mechanisms are economically distinct "
            "(mispricing of price level vs mispricing of productivity) and the "
            "combination is the standard quality-value argument, not a search.",
        "signal_definition": "rank composite of book-to-market and gross "
            "profitability, equal conceptual weight, ranked cross-sectionally. "
            "No weight tuning: equal weight is the pre-committed choice.",
        "directional_prediction": "cheap-and-profitable outperforms the universe.",
        "timing": "both inputs as-filed at filing date <= T; forward 20 days.",
        "data_requirements": "SF1 equity, gp, assets; price for book-to-market.",
        "universe": "the frozen section-3 eligible universe, unchanged.",
        "horizon": "20 trading days.",
        "falsification_criterion": "the composite IC is not reliably positive, "
            "OR it does not exceed either component alone in sign, at the hurdle.",
        "author": "research", "date": "2026-08-12",
    },
    provenance=_prov(),
    economic_mechanism="joint value + quality mispricing",
    feature_set=("val_book_to_market", "prof_gross_profitability"),
    novelty_claim="a two-mechanism recombination with a pre-committed equal "
                  "weight and an economic reason to combine.",
    known_risks=("a composite can hide that one leg does all the work",),
)

# ---------------------------------------------------------------------------
# H4 -- net buyback yield (the APEX-002-ADJACENT one, deliberately)
# ---------------------------------------------------------------------------
H4 = HypothesisDossier(
    content={
        "title": "H4 net payout yield",
        "hypothesis": "Firms returning cash through net buybacks (negative net "
                      "equity issuance in DOLLARS) outperform firms raising "
                      "equity.",
        "economic_rationale": "The payout literature (Boudoukh et al. 2007): "
            "total payout including repurchases predicts returns. This measures "
            "DOLLARS of financing cash flow, not share COUNT -- a firm can "
            "shrink share count via a small buyback while raising capital, or "
            "vice versa. The mechanism is capital return, not dilution.",
        "signal_definition": "net buyback yield from financing cash flow "
            "(negative ncfcommon over market cap), as-filed, ranked.",
        "directional_prediction": "high net payout outperforms net issuers.",
        "timing": "as-filed at filing date <= T; forward 20 trading days.",
        "data_requirements": "SF1 ncfcommon, marketcap (as-filed ARQ).",
        "universe": "the frozen section-3 eligible universe, unchanged.",
        "falsification_criterion": "net payout yield IC is not reliably positive "
            "at the hurdle over validation.",
        "horizon": "20 trading days.",
        "author": "research", "date": "2026-08-12",
    },
    provenance=_prov(),
    economic_mechanism="capital-return / payout yield",
    feature_set=("cap_net_buyback_yield",),
    novelty_claim="dollar payout, distinct from APEX-002's share-count ratio.",
    known_risks=("adjacent to APEX-002's mechanism; must argue it is not NSI "
                 "with a different numerator",),
)


def _views(hyp_key: str) -> tuple:
    """Role views with GENUINE disagreement. Prose and stance, never a score."""
    V = swarm.RoleView
    common_adversary_pead = "SF1 gives filing dates, not announcement dates"
    if hyp_key == "H1":
        return (
            V(swarm.THEORIST, True, "Gross profitability is the most robust "
              "quality proxy; the mechanism is well-identified."),
            V(swarm.FUNDAMENTAL, True, "gp and assets are 96%+ populated as-filed; "
              "the accounting is clean above the line."),
            V(swarm.QUANT, True, "a single ranked ratio; no transformation to tune."),
            V(swarm.ADVERSARY, False, "profitability loads on sector; the signal "
              "may be a sector bet in disguise, and quality underperformed for "
              "much of the 2010s.",
              ("sector confounding", "documented post-2010 decay")),
            V(swarm.REPLICATION, True, "orthogonal to the momentum block and to "
              "NSI in the feature audit; genuinely new information here."),
            V(swarm.PORTFOLIO, True, "low turnover, quarterly fundamentals; "
              "tradable at this universe's liquidity."),
            V(swarm.REGIME, False, "quality is conditional -- it pays in "
              "downturns and lags in momentum-driven melt-ups; an unconditional "
              "test may wash out.", ("regime dependence unmodelled",)),
            V(swarm.MICROSTRUCTURE, True, "20-day horizon, large caps; no "
              "microstructure obstacle."),
        )
    if hyp_key == "H2":
        return (
            V(swarm.THEORIST, True, "Functional fixation on headline EPS is a "
              "durable behavioural mechanism."),
            V(swarm.FUNDAMENTAL, True, "netinc and ncfo both ~95% populated; the "
              "accrual is a clean difference."),
            V(swarm.QUANT, False, "accruals correlate with growth and "
              "profitability; the marginal information over H1/H3 is unclear.",
              ("collinearity with growth and quality",)),
            V(swarm.ADVERSARY, False, "the accrual anomaly has decayed sharply "
              "post-2004 in published replications; this may already be arbitraged.",
              ("documented decay post-publication",)),
            V(swarm.REPLICATION, False, "risk of overlap with growth features; "
              "is this distinct from asset growth?",
              ("possible redundancy with grow_asset_growth",)),
            V(swarm.PORTFOLIO, True, "quarterly, low turnover, tradable."),
            V(swarm.REGIME, True, "the mechanism is not obviously regime-specific."),
            V(swarm.MICROSTRUCTURE, True, "no obstacle at this horizon."),
        )
    if hyp_key == "H3":
        return (
            V(swarm.THEORIST, True, "Value and quality capture DIFFERENT "
              "mispricings; combining them is the textbook quality-value case."),
            V(swarm.FUNDAMENTAL, True, "both inputs are well-populated as-filed."),
            V(swarm.QUANT, False, "a composite is one step toward a model; the "
              "equal weight is pre-committed, but a composite can mask which leg "
              "carries the signal.", ("attribution ambiguity in a composite",)),
            V(swarm.ADVERSARY, False, "two features means two chances to fit; the "
              "recombination could look better than either leg by construction "
              "even with fixed weights.",
              ("multiple-comparisons pressure from combining",)),
            V(swarm.REPLICATION, True, "the two components are near-orthogonal; "
              "this is a real recombination, not a relabelled single factor."),
            V(swarm.PORTFOLIO, True, "the joint sort is standard and tradable."),
            V(swarm.REGIME, True, "value and quality are somewhat "
              "counter-cyclical to each other, which is the point."),
            V(swarm.MICROSTRUCTURE, True, "no obstacle."),
        )
    # H4
    return (
        V(swarm.THEORIST, True, "Capital return is a distinct mechanism from "
          "dilution; dollars returned, not shares counted."),
        V(swarm.FUNDAMENTAL, True, "ncfcommon is 93% populated; it is the "
          "financing cash flow, economically different from a share-count ratio."),
        V(swarm.QUANT, False, "empirically this may correlate highly with NSI; "
          "without measuring it we cannot claim independence, and measuring it "
          "is a redundancy check, not a performance test.",
          ("possible high correlation with nsi",)),
        V(swarm.ADVERSARY, False, "this is APEX-002 with a dollar numerator. "
          "Even with a clean provenance epoch, a skeptic will read it as NSI "
          "re-run, and the burden is on us to show the mechanism differs.",
          ("mechanistically adjacent to a FAILED experiment",
           "risk of being a #002 modification")),
        V(swarm.REPLICATION, False, "until a redundancy pass shows net buyback "
          "yield is not rank-close to NSI, novelty is unproven.",
          ("novelty vs nsi not established",)),
        V(swarm.PORTFOLIO, True, "tradable, low turnover."),
        V(swarm.REGIME, True, "payout is mildly pro-cyclical; not disqualifying."),
        V(swarm.MICROSTRUCTURE, True, "no obstacle."),
    )


def main() -> int:
    out = {"candidates": [], "note": "records, not experiments; no credit spent"}
    order = [("H1", H1), ("H2", H2), ("H3", H3), ("H4", H4)]

    print("=" * 78)
    print("APEX-003 CANDIDATE GENERATION -- through the discovery system")
    print("=" * 78)
    print("  no credit, no holdout, no IC, no ranking; records only")
    print()

    prior_dossiers: dict = {}
    for key, hyp in order:
        assessment = novelty.classify_novelty(
            hyp, known_feature_ids=KNOWN,
            experiment_signatures=EXPERIMENTS, prior_dossiers=prior_dossiers,
        )
        combos = ()
        if key == "H3":
            combos = (novelty.CombinationProposal(
                combination_class=novelty.RANK_COMPOSITE,
                feature_ids=hyp.feature_set,
                economic_reason="value and quality are distinct mispricings; "
                    "conditioning value on profitability separates bargains "
                    "from distress. Equal weight is pre-committed.",
            ),)
        dossier = swarm.assemble(hyp, assessment, _views(key), combos)
        prior_dossiers[hyp.dossier_hash] = set(hyp.feature_set)

        d = dossier.as_dict()
        d["candidate"] = key
        d["dossier_hash_short"] = hyp.dossier_hash[:12]
        out["candidates"].append(d)

        print(f"--- {key}: {hyp.content['title']}")
        print(f"    novelty          : {assessment.classification}"
              + (f"  (nearest {assessment.nearest_prior})" if assessment.nearest_prior else ""))
        print(f"    feature_set      : {sorted(hyp.feature_set)}")
        print(f"    descends_from_failure : {hyp.requires_independent_rejustification()}")
        print(f"    unrebutted adversary  : {dossier.unrebutted()}")
        print(f"    dissenting roles : {len(dossier.dissent())} of {len(dossier.role_views)}")
        for obj in dossier.adversary_objections():
            print(f"      adversary: {obj}")
        print()

    Path("results").mkdir(exist_ok=True)
    Path("results/003_candidates.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("wrote results/003_candidates.json")
    print("APEX-003 NOT created. Credits unchanged. Holdout SEALED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
