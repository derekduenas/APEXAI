# APEX PREDATOR PhD COMPLETENESS MATRIX
Built 2026-08-22 from repository evidence, not aspiration.
No code was changed to produce this document.

## Cell legend
```
COMMISSIONED  passed a natural acceptance gate; frozen or provisionally frozen
LIVE          running in a daemon and emitting records right now
PARTIAL       implemented but incomplete or never exercised end-to-end
INPUT_STARVED code exists and is wired, but its inputs never arrive
NOT_BUILT     no implementation
DATA_GAP      the limiting factor is data, not code
```

## THE HEADLINE FINDING (all three sleeves)
```
OBSERVATION THROUGHPUT   ~200,000 records
DECISION THROUGHPUT      0 expression decisions, 0 attacks
```
Evidence: `results/frontier2/curve_ledger.jsonl` 55,391 rows ·
`propagation_ledger` 50,239 · `participant_pressure_ledger` 50,239 ·
`captain_shadow_ledger` 4,760 — and
`results/frontier2/expression_funnel_ledger.jsonl` **0 rows**,
`results/options_research/before_cards.jsonl` **0 rows**.

Captain state distribution across all 4,760 shadow records:
`DEVELOP 2942 · WAIT_FOR_CONFIRMATION 891 · WATCH 444 · IGNORE 245 ·
DEGRADE 238 · SERIOUS 0`.

**The organism has never once reached SERIOUS.** Every sleeve's
monetization blocker is downstream of intelligence, not inside it.

---

## 1. EQUITIES INTRADAY

| Competency | State | Evidence |
|---|---|---|
| price / trend structure | LIVE | frontier2 curve + hunter senses |
| relative strength | LIVE | 16 modules; BASELINE-RELSTRENGTH playbook emits real decisions |
| sector leadership | LIVE | 53 modules reference sector |
| industry leadership | PARTIAL | sector present, industry rarely distinguished |
| breadth | LIVE | 33 modules |
| RVOL | LIVE | 25 modules |
| VWAP / AVWAP | LIVE | 27 modules |
| opening range | PARTIAL | 10 modules, no dedicated ORB geometry |
| gap structure | LIVE | 45 modules |
| volatility | LIVE | curve V2 z-scores |
| liquidity | PARTIAL | 36 modules; no L2-depth-derived executable liquidity |
| break / retest | PARTIAL | no canonical retest detector |
| compression | PARTIAL | 9 modules |
| extension / failed extension | PARTIAL | 6 modules — thinnest structural family |
| momentum | LIVE | 16 modules |
| mean reversion | PARTIAL | implicit only |
| traps | PARTIAL | 22 modules, no canonical trap object |
| sector rotation | PARTIAL | 15 modules |
| event context | LIVE | apex/events + event-capture daemon |
| time of day | **NOT_BUILT** | 1 module mentions it; no time-of-day conditioning anywhere |
| **entry geometry** | **NOT_BUILT** | L7 unbuilt — named the largest gap since the ladder was written |
| forward distribution | PARTIAL | apex/forecast exists; only FORECAST_CALIBRATED may authorize, never reached |
| outcome resolution | **LIVE** | 758 decisions + 758 realizations with MFE/MAE at 15/30/60/90m |

**Biggest intelligence gap:** Entry Geometry (L7) — thesis quality is
computed, entry quality is not.
**Biggest data gap:** intraday depth/L2 history (Alpaca gives trades and
quotes forward-only; no historical book).
**Biggest monetization blocker:** Captain never issues SERIOUS, so the
expression funnel receives nothing. The only decisions that exist are
from the *mechanical baseline* playbook, not the Predator.

---

## 2. OPTIONS

| Competency | State | Evidence |
|---|---|---|
| underlying distribution | PARTIAL | apex/distribution 185 loc |
| realized volatility | **NOT_BUILT** | 0 modules match realized_vol in either options package |
| implied volatility | COMMISSIONED | iv_triple, bsm, american_binomial |
| IV vs realized | **NOT_BUILT** | requires realized vol first |
| surface | COMMISSIONED | surface_physics + no_arbitrage |
| skew | PARTIAL | 3 modules |
| term structure | PARTIAL | 2 modules |
| gamma / vega / theta | LIVE | 8 / 6 / 7 modules |
| convexity | PARTIAL | 4 modules |
| event volatility | PARTIAL | not joined to apex/events |
| strike selection | PARTIAL | 11 modules |
| DTE selection | PARTIAL | 7 modules |
| vertical economics | PARTIAL | expression_engine exists, never exercised |
| liquidity / spread | PARTIAL | 12 modules |
| fill realism | COMMISSIONED | execution_model; no-midpoint-fill law |
| breakeven | **NOT_BUILT** | 1 module mentions it |
| option-vs-equity expression comparison | **NOT_BUILT** | the core law `GOOD UNDERLYING THESIS != GOOD OPTION TRADE` has no implementation |
| before cards | INPUT_STARVED | file exists, **0 rows** |

**Biggest intelligence gap:** realized-vs-implied volatility — the
foundational options edge, entirely absent.
**Biggest data gap:** historical options NBBO/chains (305MB of live
analytics, no point-in-time historical chain — already flagged in the
World Lab inventory as *the* gap).
**Biggest monetization blocker:** no expression comparator; the sleeve
cannot answer OPTION_ATTACK vs EQUITY_BETTER vs NO_TRADE.

---

## 3. BTC PERPS

| Competency | State | Evidence |
|---|---|---|
| spot state | LIVE | Coinbase poller |
| perp state | LIVE | Bitnomial WS + Deribit |
| open interest | LIVE | cadence-classified per venue |
| funding | LIVE | settled 8h intervals, native semantics |
| basis primitives | PARTIAL | separated spreads only; no canonical basis (correctly deferred to L3) |
| mark / index | PARTIAL | interval-anchored; no live native index |
| book | COMMISSIONING | WS book VALID, reconciliation instrumented |
| liquidity | PARTIAL | top-of-book only; no depth-decay measures |
| cross-venue state | LIVE | same-poll reconciliation with age gating |
| leverage expansion / contraction | **NOT_BUILT** | BTC-L3, not authorized |
| long trap / short trap | **NOT_BUILT** | BTC-L3 |
| short covering / long deleveraging | **NOT_BUILT** | BTC-L3 |
| cascade risk / exhaustion | **NOT_BUILT** | BTC-L3 |
| weekend structure | **NOT_BUILT** | first weekend of data being captured now |
| entry geometry | **NOT_BUILT** | BTC-L3+ |
| historical memory | DATA_GAP | Deribit 64,093 funding records back to 2019; **Bitnomial product born 2026-07-23, funding published from 2026-08-21** |
| manual execution desk | **COMMISSIONED** | 19 tests, READY_MANUAL_INTERFACE attested |

**Biggest intelligence gap:** participant-state reconstruction — by
design, gated behind BTC-L2 final acceptance.
**Biggest data gap:** Bitnomial has ~1 month of existence and 3 settled
funding intervals. Our live capture *is* the historical record; there is
almost no past to mine. Deribit must carry historical memory.
**Biggest monetization blocker:** BTC-L3 authorization (Sunday's gate) —
and it is the *only* sleeve whose execution path is fully commissioned.

---

## CROSS-SLEEVE SUMMARY

| | Equities | Options | BTC |
|---|---|---|---|
| domain state | LIVE | PARTIAL | LIVE |
| mechanism intelligence | PARTIAL | PARTIAL | NOT_BUILT |
| historical memory | PARTIAL | DATA_GAP | DATA_GAP |
| **attack geometry** | **NOT_BUILT** | **NOT_BUILT** | **NOT_BUILT** |
| assassin | LIVE (×3 impls) | NOT_BUILT | NOT_BUILT |
| forward distribution | PARTIAL | PARTIAL | NOT_BUILT |
| monetization intelligence | INPUT_STARVED | INPUT_STARVED | COMMISSIONED (desk only) |

**Attack Geometry is NOT_BUILT in all three sleeves.** It is the single
faculty missing everywhere, and it sits directly upstream of every
attack decision. That is the consolidated roadmap's first target.
