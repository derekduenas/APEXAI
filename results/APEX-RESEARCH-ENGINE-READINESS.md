# APEX Research Engine Readiness

**Date:** 2026-08-12 · **credits 2/5 · holdout SEALED · APEX-003 does not exist**
**Nothing in the experiment/ledger/criteria/screening path modified.** No model
fitted, no credit spent, no validation rerun, no alpha claim, no broker.

## Component status

| Component | Status |
|---|---|
| Statistical robustness (block bootstrap, block permutation, subperiod, effect size, multiple-comparison) | **BUILT + CERTIFIED** (`apex.stats.robustness`) |
| Research manifest / reproducibility (science≠provenance≠presentation) | **BUILT + CERTIFIED** (`apex.research.manifest`) |
| ML search accounting (file-drawer denominator, no fitting) | **BUILT + CERTIFIED** (`apex.ml.search_ledger`) |
| Causal claim object (refuses 'confirmed'; no fake identification) | **BUILT + CERTIFIED** (`apex.causal.claim`) |
| Regime assignment (declared def, PIT-safe, no discovery) | **BUILT + CERTIFIED** (`apex.regime.engine`) |
| Firewalls (every layer boundary armed) | **BUILT + CERTIFIED** (`apex.governance.firewalls`) |
| Existing statistics (IC / Newey-West / decile / HAC null / attribution) | **BUILT + CERTIFIED** |
| Digital Twin (v1: eligibility + features + PIT) | **BUILT + CERTIFIED** |
| ML model fitting / CV / feature importance / calibration | **UNDER CONSTRUCTION** — governance + accounting built; the estimator is not, and the first `.fit()` remains prohibited |
| Causal test runners (placebo/neutralised execution) | **UNDER CONSTRUCTION** — the claim object exists; the test executors do not |
| Regime state variables (trailing vol / breadth / trend builders) | **UNDER CONSTRUCTION** — the engine assigns from a declared state series; the PIT builders for those series are not written |
| Digital Twin multi-facet (market/portfolio/model state) | **PLANNED** |
| Portfolio construction (signal≠policy objects) | **PLANNED** — needs a validated alpha to monetise |
| Risk engine | **PLANNED** |
| Realistic backtest / capacity | **PLANNED** — needs portfolio |
| Attribution expansion (regime/interaction/cost) | **PLANNED** — research attribution BUILT |
| Paper / shadow / promotion state machine | **PLANNED** |
| Execution / broker | **PLANNED** (correctly downstream) |
| Live monitoring / drift | **PLANNED** |
| Reproducibility notebook UI | **PLANNED** — manifest substrate BUILT |
| Event/announcement features · sentiment · positioning · analyst | **DATA GAP** — vendor lacks the data |
| Full causal identification (IV/RDD/DiD) | **DATA GAP** — no instrument/shock; `CausalClaim` refuses it |
| An optimiser over validation/holdout · a model before its governance · a broker selecting strategy | **FORBIDDEN** — armed firewalls |

## Design decisions that remain GOVERNANCE decisions (yours, not mine)

1. **When to write the ML estimator.** The accounting and governance are built;
   the first `.fit()` needs an explicit ML governance declaration per the ML
   doc. Whether that happens before or after a first fundamental factor is
   validated is a sequencing call.
2. **Whether a regime-conditioned or causal claim spends a credit now.** The
   contracts say both are new hypotheses (`consumes_credit=True`). Whether to
   register one is a research-priority decision, not an engineering one.
3. **The block size for the bootstrap/permutation on the real IC series.** The
   engine takes it as a declared argument; 20 (matching the forward overlap) is
   the natural pre-registration, but it must be declared in a protocol, not
   chosen by the engine.

## Report

- **Files changed:** `apex/stats/robustness.py`, `apex/research/manifest.py`,
  `apex/ml/search_ledger.py`, `apex/causal/claim.py`, `apex/regime/engine.py`
  (+ `__init__` files); `apex/governance/firewalls.py` (status flips);
  `tests/test_architecture_claims.py` (reconciled);
  `scripts/audit_conformance_guards.py` (guards); 2 docs; this readiness report.
- **Tests added:** `tests/test_research_engines.py` (29). Firewall + claim tests
  updated for the three new packages.
- **Total tests:** 572 passed, 1 skipped.
- **Guard count:** 47 load-bearing with demonstrated counterexamples (was 41),
  7 ordinary. Audit PASS.
- **Now BUILT:** 5 reusable deterministic engines + firewalls.
- **Still PLANNED:** ML estimator, causal executors, regime state builders,
  Twin multi-facet, portfolio, risk, backtest, attribution-expansion, paper/
  shadow, execution, monitoring, notebook UI.
- **Data gaps:** event/sentiment/positioning/analyst features; full causal ID.
- **Performance:** the new engines are O(resamples × n) for bootstrap/permutation
  (seconds at n≈1000, 2000 resamples) and O(1) object construction elsewhere;
  none recomputes features or panels. The readiness-computation slowness the
  prompt flagged lives in the feature-audit path (full-panel rebuilds), not
  here; a content-addressed feature cache is PLANNED, not built this turn,
  because it must first be proven result-identical (a deterministic-equivalence
  test) — its own careful task, and building it under time pressure is how a
  cache silently changes a number.

## Final state, unchanged

```
credits 2/5   APEX-003 nonexistent   holdout untouched   ledger 6 entries
APEX-002 unchanged + erratum preserved   no model fitted   no alpha result
no portfolio performance   no broker   no external data
```

The repository now contains a certified substrate capable of doing the rest
later, under governance — not a list of future features.
