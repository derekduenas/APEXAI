# APEX Full System Architecture — raw data to live P&L

One objective: find durable, statistically defensible, economically explainable
alpha and convert it into a profitable, risk-controlled trading system — without
destroying the scientific integrity that makes the alpha believable.

The authoritative, machine-readable component list is
`apex/governance/component_registry.py` (45 components), reconciled against the
repository by `tests/test_component_registry.py`. This document is its narrative.

## The graph, with governance relationships (not a linear pipeline)

```
 DATA/PIT ─▶ UNIVERSE ─▶ FEATURE LIBRARY ─▶ DIGITAL TWIN
                                                 │
                                                 ▼
   DISCOVERY { swarm · causal-critique · novelty · combination } ─▶ HUMAN GATE
                                                 │
                                                 ▼
                                    REJECT-ONLY SCREEN (in-sample)
                                                 │
                                                 ▼
                                    REGISTERED HYPOTHESIS  ── credit debit
                                                 │
        ┌── in one experiment ────────────────────────────────────────┐
        │  STATISTICAL VALIDATION · ML* · REGIME* · ROBUSTNESS         │
        │  (* ML and REGIME conditioning are THEMSELVES new hypotheses)│
        └───────────────────────────┬─────────────────────────────────┘
                                     ▼
                            LOCKED VALIDATION (one look)
                                     │
                        ┌────────────┴────────────┐
                        │  VERDICT — the only gate │
                        └────────────┬────────────┘
                                     ▼  VALIDATED_ALPHA only
   MONETISATION { backtest · costs · capacity · borrow · portfolio }
                                     │
                       PAPER ─▶ SHADOW ─▶ LIVE
                                     │
   MONITORING { drift · attribution · risk · execution }
                                     │
                                     ▼
   RESEARCH FEEDBACK ── re-enters ONLY as a new provenance-stamped hypothesis
```

## The eight governance relationships that make it not-a-pipeline

1. **ML is a new hypothesis.** A model consumes a credit; it is not a free
   refinement of a validated factor. (`ml_estimator.is_new_hypothesis`)
2. **Regime conditioning is a new hypothesis.** "Trade only in regime X" is a
   strategy, not an observation. (`regime_engine.is_new_hypothesis`)
3. **Signal combination is a new hypothesis.** (`combination_engine`)
4. **Portfolio policy ≠ alpha.** A signal is validated; a policy is versioned,
   never fitted to validation. (`portfolio_construction`)
5. **Backtesting evaluates, never optimises.** (`backtest_engine`)
6. **Monitoring observes, never retunes.** REVIEW/PAUSE/KILL only.
7. **Live results are not training data.** They re-enter research only as a
   hand-authored dossier with declared provenance.
8. **A failed experiment cannot select its successor.** (contamination epochs)

Each is a `forbidden` edge in `apex.governance.firewalls` and a flag in the
component registry, enforced by tests.

## The completeness guarantee

Every component from raw data to live monitoring is in the registry with 18
governance facts. A component cannot be silently forgotten: the reconciliation
test fails if the registry omits a firewall layer, mis-states a lifecycle, or
lets a placeholder claim "built". The operator no longer owns completeness by
memory — the test suite does.

## Data gaps (honest, permanent under this vendor)

Event/announcement dates, sentiment, positioning, analyst estimates: ABSENT,
recorded as data gaps, not "planned". Full causal identification (IV/RDD/DiD):
unsupported; `CausalClaim` refuses it.
