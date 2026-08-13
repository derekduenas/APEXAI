# APEX Full Architecture Audit — current vs target

**Date:** 2026-08-12 · **credits 2/5 · holdout SEALED · APEX-003 does not exist**
Nothing in the experiment/ledger/criteria/screening path modified. Architecture
reconciliation only — no engine built to look complete, no credit, no model, no
backtest, no broker.

## Method

Grounded in the actual repository (14 packages) and cross-checked against the
machine-readable registry (45 components) and the firewall table (10 layers).
Every "BUILT" claim is verified by `tests/test_component_registry.py`, which
fails if a component names a module that does not exist.

## Reconciliation, by layer

| Layer | Target | Current |
|---|---|---|
| PIT data / universe / features / redundancy / PIT-validation | certified | **BUILT + CERTIFIED** |
| Digital Twin (v1) | multi-facet | **BUILT + CERTIFIED** (facets PLANNED) |
| Discovery: dossier / swarm / novelty / contamination / gate / manifest | certified | **BUILT + CERTIFIED** |
| Combination engine | marginal-IC testing | **UNDER CONSTRUCTION** (object built) |
| Research memory | cumulative | **PLANNED** — split across ledger + screen_log + git today |
| Governance: screening / registration / ledger / criteria / firewalls / auditors | certified | **BUILT + CERTIFIED** |
| Statistics: IC / NW / null / decile / robustness / attribution | certified | **BUILT + CERTIFIED** |
| ML search accounting | denominator | **BUILT + CERTIFIED** |
| ML estimator / model registry | governed models | **UNDER CONSTRUCTION / PLANNED** |
| Causal claim object | refusal object | **BUILT + CERTIFIED** |
| Causal executors | placebo/neutralised runners | **UNDER CONSTRUCTION** |
| Regime engine | PIT assignment | **BUILT + CERTIFIED** |
| Regime state builders | vol/breadth/trend | **UNDER CONSTRUCTION** |
| Cost model | full frictions | **BUILT** (decile-spread scope; borrow omitted) |
| Portfolio / risk / backtest / capacity | monetisation | **PLANNED** (need validated alpha) |
| Paper / shadow | promotion machine | **PLANNED** |
| Execution / monitoring / lifecycle attribution | deployment | **PLANNED** |
| Event / sentiment / positioning / analyst data | — | **ABSENT (DATA GAP)** |
| Full causal identification (IV/RDD/DiD) | — | **ABSENT (DATA GAP)** |

## Maturity counts (from the registry)

CERTIFIED 27 · BUILT 1 · UNDER_CONSTRUCTION 4 · PLANNED 11 · ABSENT 2 · TOTAL 45.

## What the last several turns actually delivered (grounded, not remembered)

Governance substrate → feature library (23) → discovery/swarm/twin → screening
→ criteria/annulment → firewalls (armed before engines) → five reusable engines
(stats-robustness, manifest, ml-accounting, causal-claim, regime) → this
registry. The one closed experiment path (APEX-001, APEX-002) is untouched.

## The single most important finding

**Research memory is the one discovery-layer gap that is neither built nor a
data limitation.** Today the record of what has been tried is split across the
research ledger (experiments), the screen log (screens), and git history
(everything else). A cumulative research memory — every hypothesis, rejection,
lineage, and abandonment reason in one queryable place — is what stops the
system rediscovering the same dead ends. It is P1, buildable for zero credits,
and it is now in the registry as PLANNED so it cannot be forgotten again.
