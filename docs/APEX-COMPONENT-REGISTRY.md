# APEX Component Registry (rendered from apex/governance/component_registry.py)

Machine-readable source of truth: `apex/governance/component_registry.py`.
Reconciled against the repository by `tests/test_component_registry.py` — a
component cannot be listed BUILT without a module, or omit a firewall layer.

## Maturity summary

- **ABSENT**: 2
- **PLANNED**: 11
- **UNDER_CONSTRUCTION**: 4
- **BUILT**: 1
- **CERTIFIED**: 27

**Total: 45 components.**

## Components

| Component | State | Module | New hyp | Credit | PIT | Purpose |
|---|---|---|:-:|:-:|:-:|---|
| alternative_data | ABSENT | `—` |  |  |  | sentiment / attention / positioning |
| event_data | ABSENT | `—` |  |  |  | earnings ANNOUNCEMENT dates for PEAD |
| backtest_engine | PLANNED | `—` |  |  |  | evaluator of signal+policy+costs; never an optimiser |
| capacity_engine | PLANNED | `—` |  |  |  | ADV/participation/impact/borrow -> capacity curves, net alpha |
| digital_twin_multifacet | PLANNED | `—` |  |  | Y | market/regime/portfolio/model state facets on the twin |
| execution | PLANNED | `—` |  |  |  | consume approved weights, emit fills; generates no research |
| lifecycle_attribution | PLANNED | `—` |  |  |  | feature/factor/model/regime/portfolio/cost/execution attribution |
| live_monitoring | PLANNED | `—` |  |  |  | drift/decay detection; REVIEW/PAUSE/KILL, never retune |
| model_registry | PLANNED | `—` |  |  |  | versioned model artifacts, family accounting, drift |
| paper_shadow | PLANNED | `—` |  |  |  | RESEARCH->VALIDATED->PAPER->SHADOW->LIVE state machine |
| portfolio_construction | PLANNED | `—` |  |  |  | signal->policy separation; sizing/neutralisation/limits |
| research_memory | PLANNED | `—` |  |  |  | durable cumulative record of every hypothesis/rejection/lineage/abandonment reason, unifying ledger + screen_log + dossiers |
| risk_engine | PLANNED | `—` |  |  |  | exposure/drawdown/tail limits; independent of alpha |
| causal_executors | UNDER_CONSTRUCTION | `—` |  |  |  | placebo / neutralised-re-test runners |
| combination_engine | UNDER_CONSTRUCTION | `apex.research.novelty` | Y | Y |  | bounded CombinationProposal (object built); marginal-IC testing PLANNED |
| ml_estimator | UNDER_CONSTRUCTION | `—` | Y | Y |  | supervised/nonlinear models, nested purged walk-forward CV |
| regime_state_builders | UNDER_CONSTRUCTION | `—` |  |  | Y | PIT builders for trailing-vol/breadth/trend state series |
| cost_model | BUILT | `apex.evaluate.turnover` |  |  |  | drift-aware turnover + per-side cost (decile-spread scope) |
| auditors | CERTIFIED | `apex.audit.execution_path` |  |  |  | lookahead, cross-sectional, import-closure isolation |
| causal_claim | CERTIFIED | `apex.causal.claim` | Y | Y |  | claim object; refuses 'confirmed' w/o rung+assumptions+placebo |
| contamination_control | CERTIFIED | `apex.research.hypothesis` |  |  |  | provenance epochs; descendant-of-failure flagging |
| decile_engine | CERTIFIED | `apex.evaluate.deciles` |  |  |  | equal-count deciles, orientation-aware |
| digital_twin | CERTIFIED | `apex.research.twin` |  |  | Y | deterministic PIT state at T; v1 = eligibility+features |
| feature_factory | CERTIFIED | `apex.features.factory` |  |  | Y | PIT-safe feature builders |
| feature_pit_validation | CERTIFIED | `apex.features.pit_validation` |  |  | Y | per-feature PIT checks |
| feature_redundancy | CERTIFIED | `apex.features.redundancy` |  |  |  | structural + empirical redundancy detection |
| feature_registry | CERTIFIED | `apex.features.registry` |  |  |  | canonical FeatureSpecs, lifecycle, 23 features |
| firewalls | CERTIFIED | `apex.governance.firewalls` |  |  |  | layer-boundary contracts armed before their engines |
| human_gate | CERTIFIED | `apex.research.gate` |  |  |  | presents; decides nothing; cannot register |
| hypothesis_dossier | CERTIFIED | `apex.research.hypothesis` | Y |  |  | frozen hypothesis wrapping the certified screening Dossier |
| ic_engine | CERTIFIED | `apex.evaluate.ic` |  |  |  | Spearman IC, Newey-West HAC t |
| ml_search_accounting | CERTIFIED | `apex.ml.search_ledger` |  |  |  | file-drawer denominator; select_best refuses; NO fitting |
| novelty_engine | CERTIFIED | `apex.research.novelty` |  |  |  | NOVEL/RECOMBINATION/REDUNDANT/MODIFICATION/DUPLICATE, no score |
| null_simulation | CERTIFIED | `apex.evaluate.reference` |  |  |  | simulated HAC dispersion null |
| pit_data | CERTIFIED | `apex.data.snapshot_loader` |  |  | Y | point-in-time frozen vendor data with known_from |
| regime_engine | CERTIFIED | `apex.regime.engine` | Y | Y | Y | deterministic PIT regime assignment from declared def |
| registration | CERTIFIED | `apex.registration` |  | Y |  | signing, protocol pin, unlock tokens |
| research_attribution | CERTIFIED | `apex.report.attribution` |  |  |  | section-9 sector attribution of a decile spread |
| research_ledger | CERTIFIED | `apex.governance.ledger` |  | Y |  | hash-chained credit ledger with annulment |
| research_manifest | CERTIFIED | `apex.research.manifest` |  |  |  | content-addressed science identity; science!=provenance!=presentation |
| research_swarm | CERTIFIED | `apex.research.swarm` | Y |  |  | 8 epistemic roles; disagreement preserved; no score |
| screening | CERTIFIED | `apex.governance.screening` |  |  |  | reject-only, S1-S13, tamper-evident log |
| stats_robustness | CERTIFIED | `apex.stats.robustness` |  |  |  | block bootstrap, permutation null, subperiod, multiple-comparison |
| success_criteria | CERTIFIED | `apex.evaluate.criteria` |  |  |  | per-experiment registered criteria; never hardcoded |
| universe | CERTIFIED | `apex.universe` |  |  | Y | section-3 eligibility, survivorship-safe |

## Governance facts recorded per component

name · state · purpose · module · inputs · outputs · dependencies ·
allowed/forbidden deps · PIT requirement · holdout access · is-new-hypothesis ·
consumes-credit · optimize-allowed · provenance · tests-required ·
activation-prereqs · downstream · failure-behavior.

The 18 fields live on the `Component` dataclass; this table renders the
load-bearing ones. Read the module for the full record of any component.
