# APEX Feature Architecture — CURRENT → TARGET

**Date:** 2026-08-12 · infrastructure, not an experiment · credits 2/5 · holdout SEALED

This is the information substrate. It computes no forward return, no IC, and no
predictive statistic, and it ranks nothing by performance. Its purpose is to let
future experiments test different economic mechanisms instead of restating
momentum.

---

## The pipeline

```
Raw PIT data (frozen Sharadar snapshot: SF1, SEP, DAILY, ACTIONS, TICKERS)
      |
      v
Canonical Feature Factory        apex/features/factory.py
      |    one descriptor interpreter; earliest-filing PIT discipline
      v
Feature Registry                 apex/features/registry.py
      |    ONE feature = ONE authoritative definition (a descriptor)
      v
Feature Validation               apex/features/pit_validation.py
      |    knowability measured per feature, not asserted
      v
Redundancy / Lineage             apex/features/redundancy.py
      |    identical vs correlated, made visible, never auto-deleted
      v
Research Feature Library         (this document + the readiness report)
      |
      +-- Discovery / Swarm      NOT IMPLEMENTED — documented as future consumer
              |
              v
      Cheap screening            apex/governance/screening.py  (S1-S13)
              |
              v
      Human hypothesis choice    (the boundary the whole system protects)
              |
              v
      APEX register              apex/registration.py  (signed, credit-consuming)
              |
              v
      Validation / Holdout       apex/pipeline.py, gated
```

**The feature library and any future discovery layer never create an APEX
experiment.** Registration is a separate signed act that spends a credit.
`test_screening.py::...an_unregistered_survivor_cannot_enter_validation` and the
`UnregisteredExperiment` gate enforce that a feature — or a screened dossier —
cannot become an experiment by itself.

## Fifteen families: CURRENT status

Status vocabulary: **BUILT** (factory computes it from frozen data) ·
**PARTIALLY BUILT** · **DATA AVAILABLE BUT UNUSED** (fields present, no builder)
· **DATA NOT AVAILABLE** · **ARCHITECTURAL INTENT ONLY**.

| # | Family | Status | Notes |
|---|---|---|---|
| 1 | Price / market | BUILT (pre-existing) | f1, f2, f4 — one momentum block, 6 redundant components |
| 2 | Volatility | BUILT (pre-existing) | f3_vol_ratio, f3_atr_over_close |
| 3 | Fundamental (raw) | BUILT | as-filed SF1 ARQ now consumed by 14 features |
| 4 | Valuation | BUILT | book/market, earnings yield, sales/price — as-filed over PIT market cap |
| 5 | Profitability / quality | BUILT | gross profitability, operating profitability, ROE, ROA, gross/net margin |
| 6 | Growth | BUILT | asset growth, sales growth |
| 7 | Accruals / earnings quality | BUILT | total accruals (Sloan) |
| 8 | Capital allocation | BUILT | NSI (#002) + net buyback yield |
| 9 | Liquidity / trading | DATA AVAILABLE BUT UNUSED | Amihud, turnover — SEP volume present, builders pending |
| 10 | Event / underreaction | DATA NOT AVAILABLE | no earnings announcement date; filing date ≠ announcement |
| 11 | Market / macro | DATA AVAILABLE BUT UNUSED | benchmark & VIX in the panel; no macro features built |
| 12 | Sentiment / attention / positioning | DATA NOT AVAILABLE | no short interest, 13F, options, estimates, news |
| 13 | Regime | ARCHITECTURAL INTENT ONLY | B5 regime reporting exists; no per-security regime feature |
| 14 | Cross-sectional / relative | BUILT (mechanism) | sector/market demeaning exists (f4); reusable, not generalised |
| 15 | Interaction / composite | ARCHITECTURAL INTENT ONLY | deferred until ≥2 families independently demonstrate something |

## CURRENT → TARGET

**CURRENT (before this build):** one momentum family measured six ways, two
volatility terms, one share-count signal. ~4 effective dimensions, three of
them from `closeadj`.

**CURRENT (after this build):** the above plus 14 PIT-safe fundamental features
spanning valuation, profitability, growth, accruals, leverage, and a second
capital-allocation measure. Effective new dimensions ≈ 12 (only the
profitability cluster ROA/ROE/operating-profitability collapses at ρ≥0.70);
total effective dimensionality is now materially broader than momentum.

**TARGET:** a multi-mechanism, PIT-safe library where an experiment can test a
genuinely different economic question, and — eventually, and only once families
have independently demonstrated something — combinations of independent
families. The combination layer (family 15) is deliberately last: it multiplies
the multiple-comparisons problem by the number of combinations considered, and
is not reachable until the individual mechanisms have standing.

## The redundancy control

Two registered #001 components (`f1_mom_63`, `f4_vs_market`) were rank-identical
by construction and nothing detected it. The library now detects duplication at
two levels, and **makes it visible rather than deleting it**:

- **Structural** (`structural_findings`): compares registry descriptors before
  compute. Catches identical formulas and reciprocal ratios.
- **Empirical** (`empirical_findings`): rank-identical transformations,
  per-date-scalar differences (the exact f1/f4 signature), and correlation.

**Identical information** (same formula / rank-identical / per-date-scalar) is
distinguished from **correlated information** (high |ρ|, economically related,
legitimately distinct). Correlated features are reported, never removed. The
new library has **0 identical and 13 correlated** pairs.

## Digital Twin / Research Swarm

Searched the codebase: **neither is implemented.** They are documented here as
future *consumers* of the canonical library, not built, and no fake integration
was created. When they exist, their interface is the registry + factory output:
a wide feature frame and a `known_from` frame per feature, PIT-validated.

## Lifecycle: a feature is not an alpha

`FEATURE → DISCOVERY_CANDIDATE → SCREENED_CANDIDATE → REGISTERED_EXPERIMENT →
VALIDATED_ALPHA` (or `FAILED` / `DEPRECATED`). All 23 features are `FEATURE`.
Nothing here is an alpha; NSI is a `FEATURE` that was tested as APEX-002 and
`FAILED`. The word "alpha" is reserved for something that has cleared a
pre-registered holdout, which nothing has.
