# APEX HUNTER — Current-State Inventory, Gap Analysis, and P0 Plan

Date: 2026-08-15. Suite green before modifications: 736 passed. The prior
directive's discovery exercise is RUNNING under its frozen spec (589c6d92…)
and is not cancelled by this migration; its results feed Hunter baselines.

## 1. CURRENT STATE INVENTORY (from the component registry, reconciled)

CERTIFIED (28): PIT data, universe, feature registry/factory/redundancy/
pit-validation, digital twin (research), discovery layer, screening,
registration, research ledger, criteria, firewalls, auditors, stats, causal
claims, regime engine, IC/decile engines, null simulation, attribution,
manifest, viability, human gate, contamination control.
ACTIVE (4): reality harness/producers, world_state, paper_shadow (paper).
BUILT (10): llm_producers (blocked on CLI auth), expression engine,
world_vintage (macro feed pending FRED), exploration governance, portfolio
construction (ladder), risk engine, capacity engine, cost model,
distribution estimator, opportunity engine, holdout capacity (A-009).
UNDER_CONSTRUCTION (4): ml_estimator, causal executors, regime state
builders, combination engine.
PLANNED/ABSENT: research_memory (v1 chained log exists from the discovery
exercise), backtest_engine, model_registry, execution, live_monitoring,
lifecycle_attribution, calibration_harness, discovery_exercise_runner
(RUNNING NOW), event/alternative data.

## 2. EXISTING → TARGET MAPPING

| Hunter directive layer | Existing substrate | Verdict |
|---|---|---|
| APEX CORE | everything above | **FORBIDDEN_TO_CHANGE** (behavior) / sovereign |
| Live Twin facets | apex/world (state vars, staleness, vintage) | REUSABLE + NEEDS_EXTENSION (intraday facets) |
| Regime engine | apex/world online classifier + uncertainty | REUSABLE + NEEDS_EXTENSION (axes, BOCPD) |
| ChartState | none | NEW_COMPONENT (P1, data-gated) |
| Scanner/funnel | none | NEW_COMPONENT (P1, data-gated) |
| Playbook engine | contract NEW; governance = existing dossiers | NEW contract, EXISTING governance |
| Distribution layer | apex/distribution | REUSABLE + NEEDS_EXTENSION (intraday horizons) |
| Calibration | config/calibration.yaml + reality loop | REUSABLE (add model-lifecycle states) |
| ML | apex/exploration (purged CV, trials, DSR/PBO) | REUSABLE as-is |
| APEX CAPITAL | apex/portfolio/{risk,capacity} + apex/opportunity | **REUSABLE — do NOT duplicate under a new package name** |
| TradeThesis / state machine / decision ledger | none | NEW_COMPONENT (**P0, data-free**) |
| BrokerAdapter | none | NEW_COMPONENT (**P0 interface only**) |
| Event replay (intraday) | daily-grid replay exists (discovery runner) | NEW_COMPONENT (P1, data-gated) |
| Research memory | results/research_memory.jsonl (chained, v1) | NEEDS_EXTENSION (schema per directive) |
| Options expression | apex/expression (defined-risk, CALIBRATED-gated) | REUSABLE; dormant until real chain history |

## 3. GAP ANALYSIS — the binding constraint, stated first

**DATA_GAP #1 (blocks all of P1): the repository contains ZERO intraday
data.** Sharadar SEP is daily. No minute bars, no NBBO, no L2, no auction
imbalance, no timestamped news, no options chains. The Robinhood MCP is
**not connected to this environment** (no such tools exist in this session)
→ BLOCKED_EXTERNAL. P1 (replay, scanner, ChartState) cannot begin until the
operator wires an intraday source (Robinhood MCP, Databento/Massive minute
archive, or equivalent). P0 is deliberately data-free and proceeds now.
Other externals, unchanged: headless CLI auth (swarm), FRED key (macro).

## 4. DEPENDENCY GRAPH (target, enforced by firewalls at P0)

CORE (sovereign) → HUNTER (contracts P0; intelligence P1) → CAPITAL
(existing portfolio/opportunity) → EXECUTION (adapter interface P0; paper →
shadow → limited-live LATER) → OBSERVABILITY (reality loop, attribution).
FORBIDDEN: execution → research mutation; hunter → registration/ledger;
LLM → any live mutation (tool-level, not prompt-level).

## 5. PROPOSED PACKAGE TREE (P0 slice only)

    apex/hunter/__init__.py      placement + firewall statement
    apex/hunter/contracts.py     TradeThesis (immutable+hashed),
                                 PlaybookDefinition, FailClosed conditions
    apex/hunter/lifecycle.py     model/strategy lifecycle + mechanical
                                 calibration gating (4 canonical states)
    apex/hunter/statemachine.py  trade state machine + chained decision
                                 ledger + stop-never-widens rule
    apex/hunter/broker.py        abstract BrokerAdapter (live methods are
                                 structurally disabled in this phase)

## 6. MIGRATION RISKS

(a) Memory: this Mac OOMs at ~5GB working sets (two incidents recorded);
intraday event lakes are far larger — P1 needs storage/format decisions
(parquet, per-day partitions) before code. (b) Horizon collision: 15-90m
targets vs the 20d research grid — kept as SEPARATE declared horizons with
separate calibration ledgers; no shared thresholds. (c) Cadence: the
nightly loop is daily; Hunter is intraday — the live loop needs its own
scheduler LATER, never touching the nightly research jobs. (d) Registry
bloat: CAPITAL must reuse portfolio/opportunity, not fork them.

## 7. COMPONENTS THAT MUST NOT BE REWRITTEN

Everything CERTIFIED/ACTIVE in §1; the ledgers (append-only); the frozen
protocols and amendments; the reality loop's producer identities; the
frozen discovery-exercise spec; the paper track. The Hunter consumes them.

## 8-9. P0 PLAN + ACCEPTANCE TESTS

Build §5's four modules with tests proving: thesis immutability + hash
recoverability; every state transition requires a declared rule and lands
in the chained decision ledger; a stop can NEVER move away from the
position (the directive's cardinal rule, counterexampled); calibration
gating is mechanical (DEGRADED loses live eligibility structurally; no API
exists for an LLM to flip states); BrokerAdapter exposes no enabled live
path; fail-closed conditions veto decisions (unknown never becomes safe).
Suite green before (DONE: 736) and after.

## 10. CONTRADICTIONS between directive and existing architecture

1. Directive's calibration states (UNCALIBRATED_MODEL/PAPER_GRADE/
   CALIBRATED/DEGRADED) vs the distribution estimator's source statuses
   (SYNTHETIC/UNCALIBRATED_MODEL/HISTORICAL_EMPIRICAL/CALIBRATED): these
   are DIFFERENT AXES — one is model lifecycle, one is distribution
   provenance. Resolution: keep both, map explicitly in lifecycle.py;
   never merge them into one enum.
2. "Three frozen playbooks" vs hypothesis governance: a playbook making a
   predictive claim IS a hypothesis — it enters via dossier/screening like
   everything else. P0 ships the CONTRACT; no playbook is claimed to have
   alpha by being coded (the directive itself agrees).
3. Hunter's continuous scanning vs the 5(+A-009) credit budget: Hunter
   decisions are DEVELOPMENT/paper-grade forever until something graduates
   into a registered experiment. No contradiction, but worth stating: the
   Hunter cannot mint confirmatory evidence any more than the swarm can.
4. Robinhood-first framing vs this environment: the MCP is absent here;
   the BrokerAdapter abstraction (which the directive itself mandates)
   resolves this — Robinhood is a future adapter, not a present tool.
5. No other contradictions found: the LLM firewall, fail-closed rules,
   PIT discipline, and no-Kelly-until-calibrated all match existing law.
