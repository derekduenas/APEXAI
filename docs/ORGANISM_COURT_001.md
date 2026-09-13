# ORGANISM-COURT-001 — the connected decision path (2026-09-13)

Branch `organism-court-001`, base `304e342ec0452d61d83b07c0c024221efc304d93` (verified). Separate clean worktree.
**No production code was changed** — the court is additive: `apex/court/`, one test module, evidence.

## What this is, and is not

Integration verification. Every number here comes from a **declared synthetic world** (`ORGANISM_COURT_WORLD_V1`,
seed 20260913, frozen before any flight). **Nothing here is evidence of calibration, edge or profitability.**

## LAYER_RECEIPT_V1

Four states, measured differently and never collapsed: **AVAILABLE**, **EXECUTED**, **VALID** (runtime-measured)
and **USED** — which is *discovered*, not declared: the court scans persisted records written by the real
downstream path for the output's identity, and records the **field path** where it was found. A producer label or
a caller-supplied consumer name is never accepted. Every receipt carries what it cannot establish.

## Where the flow actually stops

| route | result |
|---|---|
| `PILOT_RULE_V2` | full round trip: forecast → intent → fill → exit → Book, P&L independently recomputed |
| `FULL_FUNNEL_V1`, 500 bars | `fit=READY`, funnel **TRADE**, all stages execute: regime, variance, implied, simulation, expression-war, PRIME |
| `FULL_FUNNEL_V1`, 40 bars | **WAIT** — `PRIME_ABSTAIN: UNSUPPORTED_STATE: INSUFFICIENT_HISTORY: 12 < 400 bars` |
| `JOINT_FUNNEL_V1` | **UNREACHABLE** — `requires joint_engine and joint_context_fn` |

The engine's **own** declaration of what it did not invoke: `enrichment NOT_INVOKED`, `fusion NOT_INVOKED: no
learned weights`, `jumps NOT_MODELLED`, `svi_surface NOT_INVOKED: ATM implied vol only (no surface fit, no skew)`.
The variance model that actually ran was **`EWMA_FALLBACK`, not GARCH**.

Full map: `docs/evidence/organism_court_001/LAYER_MAP.txt`.

## Two corrections the court forced on itself

1. **The future-bar flight was testing my own filter.** The court filtered bars before calling `compose()`, so the
   real causality guard never fired. Corrected to pass unfiltered; `compose()` refuses with
   `FUTURE_BAR_IN_SNAPSHOT`, which is the system's guard, not the court's.
2. **A snapshot-id assumption was wrong.** Two worlds differing only in the option chain share a `snapshot_id` —
   that is exactly what content-addressing means. The test now asserts that identical market state gives the same
   id and a *different state* gives a different one.

## Verdicts, stated separately

| | |
|---|---|
| **Connected-path correctness** | PASS for the rule route and the full-funnel route, on synthetic inputs, with independent reconstruction agreeing on P&L |
| **Architecture completeness** | **FAIL** — setup detection / Strategy Lab, Experience + challenger learning, and cross-instrument (stock/ETF) expression do not exist on this line; JOINT is unreachable; GARCH fell back |
| **Operational readiness** | **NOT READY** — fee authorization is unauthored, the deployed release lacks the repairs, the hold stands |
| **Profitability evidence** | **NONE.** No claim of any kind. |

The organism is not complete. Required organs are missing and are named above.
