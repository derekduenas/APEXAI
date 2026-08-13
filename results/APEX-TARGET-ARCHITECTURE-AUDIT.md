# APEX Target-Architecture Audit — current state vs target

**Date:** 2026-08-12 · commit after `d676456` · **credits 2/5 · holdout SEALED**
**Nothing modified** in the experiment/ledger/criteria/screening path. This turn
added governance declarations and their enforcement tests only — no ML, causal,
portfolio, backtest, or execution engine.

## What changed this turn

The master audit (`APEX-MASTER-ARCHITECTURE-AUDIT.md`) named one dangerous gap:
*the validation → downstream boundary is unguarded, safe only because the
downstream layers are absent.* **That gap is now closed structurally, before the
layers exist:**

- `apex/governance/firewalls.py` — every planned layer's boundary as a
  `LayerContract` (allowed/forbidden imports, new-hypothesis flag, credit flag,
  holdout flag, optimize flag), consumed by the audited `module_closure` walk.
  Not a parallel framework — a declaration the existing auditor enforces.
- `tests/test_architecture_firewalls.py` — 18 tests. The core test is
  parametrised over every layer and **arms the instant a layer's package
  appears**: absent layers pass vacuously today, and the same test enforces the
  forbidden set the moment `apex/ml/`, `apex/portfolio/`, `apex/execution/` etc.
  are created. Two live firewalls (discovery ⇏ registration; evaluation ⇏
  screen/discovery) are enforced now.
- Five per-layer governance docs + the target-architecture doc.

Guard count: 39 → **41 load-bearing**, audit PASS.

## Current state vs target, by layer

| Layer | Target | Current | Firewall armed? |
|---|---|---|---|
| Data / PIT / universe | certified | **BUILT + CERTIFIED** | n/a (source layer) |
| Feature registry / factory / redundancy | certified | **BUILT + CERTIFIED** | yes (implicit) |
| Digital Twin | multi-facet | **BUILT (v1: eligibility+features+PIT)** | via discovery contract |
| Discovery / swarm / novelty / gate | certified | **BUILT + CERTIFIED** | **yes, live** (`discovery`) |
| Screening / registration / ledger / credits | certified | **BUILT + CERTIFIED** | protected target |
| Statistics (IC/NW/decile/null) | full toolkit | **BUILT**; bootstrap/subperiod UNDER CONSTRUCTION | **yes, live** (`statistics`) |
| Causal | placebo/neutralised | **PLANNED** (governance written) | **yes, armed** (`causal`) |
| ML | governed experiment | **PLANNED** (governance written) | **yes, armed** (`ml`) |
| Regime | pre-specified | **PLANNED** (reporting config only) | **yes, armed** (`regime`) |
| Portfolio | signal≠policy | **PLANNED** (governance written) | **yes, armed** (`portfolio`) |
| Backtest | evaluator-only | **PLANNED** (governance written) | **yes, armed** (`backtest`) |
| Risk | independent limits | **PLANNED** | **yes, armed** (`risk`) |
| Execution / paper / shadow / live | consumer-only | **PLANNED** (governance written) | **yes, armed** (`execution`) |
| Monitoring / drift / attribution | detect-only | **PLANNED** (research attribution BUILT) | **yes, armed** (`monitoring`) |
| Reproducibility / notebook | evidence surface | **UNDER CONSTRUCTION** (artifacts+git) | n/a |

## The two firewalls live today

```
[PASS] discovery ⇏ {pipeline, registration, ledger}   (up-direction blocked)
[PASS] evaluation ⇏ {screening, discovery}            (S13; evidence isolation)
```

Both were already true; they are now *tests that fail if broken*, not properties
that happen to hold.

## What each of the ten Phase-1 firewalls maps to

| # | Phase-1 firewall | Where it lives now |
|---|---|---|
| 1 | Validation → downstream | `firewalls` contracts `ml/causal/regime/portfolio/backtest` forbid the up-direction |
| 2 | Holdout → absolute | `no_contract_may_access_the_holdout` (every contract `may_access_holdout=False`) |
| 3 | ML → experiment | `ml` contract: `is_new_hypothesis` + `consumes_credit`; ML governance doc |
| 4 | Portfolio → experiment | `portfolio` contract + governance doc (policy≠signal) |
| 5 | Regime → experiment | `regime` contract: conditioning is a new hypothesis |
| 6 | Causal → experiment | `causal` contract + ladder governance |
| 7 | Backtest ⇏ mutate hypothesis | `backtest` contract forbids registration/discovery; doc: evaluator-only |
| 8 | Execution ⇏ feed research | `execution` widest forbidden set; live governance doc |
| 9 | Monitoring → review/kill not retune | `monitoring` contract; live governance doc |
| 10 | Reproducibility/provenance | fingerprints/hashes on every result (BUILT); notebook UNDER CONSTRUCTION |

## Honest gaps that remain (not closed this turn, by design)

1. **Bootstrap/permutation null + reusable subperiod module** — Phase-2, cheap,
   no ML dependency. The highest-value next *build* (not this turn).
2. **Digital Twin multi-facet** (market/regime/portfolio/model state) — each a
   versioned field gated by `assert_no_future_leak`, added when its consumer is.
3. **Reproducibility notebook** — artifacts + git today; a real evidence surface
   is UNDER CONSTRUCTION.
4. **The engines themselves** — ML/causal/portfolio/backtest/risk/execution are
   PLANNED with governance and armed firewalls, deliberately unbuilt.

## The classification the whole exercise protects

```
FEATURE → DISCOVERY_CANDIDATE → SCREENED_CANDIDATE → REGISTERED_EXPERIMENT
  → VALIDATED_ALPHA → (monetisation) → PAPER → SHADOW → LIVE
                    ↘ FAILED / DEPRECATED
```

A feature is not an alpha because it exists. A validated factor is not money
until the monetisation layer says it is implementable. Nothing in this turn
moved a single component along that ladder — it built the rails the ladder runs
on, and made them fail loudly if bypassed.

## State, unchanged

```
ledger        6 entries, chain verifies, credits 2/5
APEX-001      CLOSED — INCONCLUSIVE      APEX-002  CLOSED — FAILURE + erratum
screen_log    does not exist            APEX-003  does not exist
holdout       SEALED                    guard audit  PASS (41 load-bearing)
```
