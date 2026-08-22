# APEX PREDATOR PhD SCORECARD
Built 2026-08-22 from repository evidence. Superseding scorecard for
`PREDATOR_PHD_MATRIX.md` (which stays as the Phase-1 snapshot).

**No arbitrary 1–10 scores.** Every cell carries status + evidence +
missing requirement + next task + graduation requirement.

## Status vocabulary
```
NOT_BUILT · DATA_GAP · INPUT_STARVED · PARTIAL · BUILT_UNPROVEN
PROSPECTIVE_TESTING · ECONOMICALLY_VALIDATED
```

## The six-level maturity model
```
L1 KNOWLEDGE → L2 HISTORICAL MEMORY → L3 INTERPRETATION
→ L4 ATTACK INTELLIGENCE → L5 MONETIZATION → L6 PROVEN COMBAT
```
Nothing reaches L6 without sealed prospective evidence. Today **no
faculty in any sleeve is past L4**, and none has produced a single
prospective attack.

---

## EQUITIES_INTRADAY

| Faculty | Status | Evidence | Missing | Next task | Graduation |
|---|---|---|---|---|---|
| DOMAIN_KNOWLEDGE | PARTIAL (L3) | RS/sector/breadth/RVOL/VWAP/gap live | time-of-day, industry, break-retest | after Monday | used in a SERIOUS |
| HISTORICAL_MEMORY | PARTIAL (L2) | `apex/analog/engine.py` — real analog engine w/ leakage law + time firewall; EODHD-scoped | intraday depth history; cross-sleeve episode contract | Episode Factory | analogs answer a live query |
| DATA_FITNESS | PARTIAL | 164 symbols 1m OHLCV + 11 sector SPDRs | **no persisted quotes** | quote persistence (post-Monday) | liquidity dimension lit |
| MECHANISM_INTELLIGENCE | PARTIAL | pattern conjunctions, propagation, participant_pressure | mechanism never reaches a decision | Monday | named mechanism on an Opportunity |
| PARTICIPANT_INTELLIGENCE | PARTIAL | participant_pressure ledger 50,239 | no trap/forced taxonomy | after paper combat | discriminates on outcomes |
| ATTACK_GEOMETRY | BUILT_UNPROVEN (L4) | v1, 16 property tests, GOOD 7.5% on real windows | STRONG unreachable (no quotes) | Monday natural acceptance | contributes to a real SERIOUS |
| FAILURE_INTELLIGENCE | NOT_BUILT | — | no failure library | Episode Factory | failure families named |
| FORWARD_DISTRIBUTION | INPUT_STARVED | `apex/forecast` exists; never FORECAST_CALIBRATED | resolved prospective outcomes | paper combat | calibration measured |
| EXPRESSION_INTELLIGENCE | PARTIAL | funnel wired, **0 decisions** | reachable SERIOUS | Monday | first sealed BEFORE card |
| EXECUTION_INTELLIGENCE | BUILT_UNPROVEN | paper harness commissioned | no fills ever | after authority | slippage measured |
| PROSPECTIVE_COMBAT | NOT_BUILT | 758 BASELINE-RELSTRENGTH control decisions only | authority + SERIOUS | post-Monday | first paper attack |
| ECONOMIC_PROOF | NOT_BUILT | — | everything above | — | positive R after costs |

---

## OPTIONS

| Faculty | Status | Evidence | Missing | Next task | Graduation |
|---|---|---|---|---|---|
| DOMAIN_KNOWLEDGE | PARTIAL (L1–L3) | bsm, american_binomial, surface_physics, no_arbitrage, iv_triple commissioned | realized-vol; breakeven | RvI foundation | RvI faculty live |
| HISTORICAL_MEMORY | **DATA_GAP** | **3.1 days**, 3 underlyings, 57,312 states | years of chains; regimes | acquisition (below) | multi-regime memory |
| DATA_FITNESS | PARTIAL/TIER_A-narrow | real bid+ask 100%, IV 91%, Greeks 86%, spot, rate, div | **bid_size, ask_size, volume, OI, underlying bid/ask absent** | add sizes+OI to live capture | full chain state |
| MECHANISM_INTELLIGENCE | PARTIAL | surfaces 57,312 w/ moneyness + delta buckets | skew/term as decisions | Enrichment 02 | surface anomaly named |
| PARTICIPANT_INTELLIGENCE | NOT_BUILT | — | dealer positioning needs OI | after OI capture | — |
| ATTACK_GEOMETRY | NOT_BUILT | — | everything | Enrichment 03 | — |
| FAILURE_INTELLIGENCE | NOT_BUILT | — | — | Episode Factory | — |
| FORWARD_DISTRIBUTION | NOT_BUILT | forward_distribution.py stub | history | — | — |
| EXPRESSION_INTELLIGENCE | PARTIAL | expression_engine, execution_model, no-mid-fill law | **option-vs-equity comparator absent** | Enrichment 03 | OPTION_ATTACK / EQUITY_BETTER emitted |
| EXECUTION_INTELLIGENCE | PARTIAL | fill realism law commissioned | no fills | — | — |
| PROSPECTIVE_COMBAT | NOT_BUILT | **before_cards.jsonl = 0 rows** | all of the above | — | — |
| ECONOMIC_PROOF | NOT_BUILT | — | — | — | — |

---

## BTC_PERPS

| Faculty | Status | Evidence | Missing | Next task | Graduation |
|---|---|---|---|---|---|
| DOMAIN_KNOWLEDGE | PARTIAL (L1) | semantics registry: ticks, funding intervals, OI cadence, price lineage | participant theory unencoded | Enrichment 02 (L2-gated) | — |
| HISTORICAL_MEMORY | **DATA_GAP** | Deribit 64,093 hourly funding (2019→) + 2,791 daily bars; Bitnomial 22 daily + 3 funding intervals | **intraday OI history**; book history | acquisition (below) | joint-state episodes |
| DATA_FITNESS | GOOD live / thin history | WS book+trades, funding, OI cadence-classified, cross-venue age-gated | liquidations NOT_AVAILABLE; no live native index | — | — |
| MECHANISM_INTELLIGENCE | NOT_BUILT | — | L3 authorization | after L2 verdict | — |
| PARTICIPANT_INTELLIGENCE | NOT_BUILT | — | L3 authorization | **Enrichment 02** | — |
| ATTACK_GEOMETRY | NOT_BUILT (interface only) | stub | L3 | Enrichment 03 | — |
| FAILURE_INTELLIGENCE | NOT_BUILT | — | — | — | — |
| FORWARD_DISTRIBUTION | NOT_BUILT | — | — | — | — |
| EXPRESSION_INTELLIGENCE | PARTIAL | manual Kraken desk COMMISSIONED, 19 tests | nothing to express | — | — |
| EXECUTION_INTELLIGENCE | **BUILT_UNPROVEN (best of the three)** | manual desk + latency capture + fill reconciliation | operator fills | — | first confirmed fill |
| PROSPECTIVE_COMBAT | NOT_BUILT | — | L2 PASS → L3 | — | — |
| ECONOMIC_PROOF | NOT_BUILT | — | — | — | — |

---

## THE STRUCTURAL ASYMMETRY

```
EQUITIES  strongest intelligence · weakest execution path
BTC       strongest execution path · no intelligence yet (L3 gated)
OPTIONS   strongest pricing math · almost no historical memory
```

Each sleeve is blocked on a *different* thing, which is why they can be
enriched in parallel without competing for the same fix.
