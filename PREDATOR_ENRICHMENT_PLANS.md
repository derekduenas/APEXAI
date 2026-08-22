# PREDATOR ENRICHMENT — THE THREE AUDIT REPORTS
2026-08-22. Audits and plans only. No live change, no purchase, no
model trained, no authority altered.

---

# 1. OPTIONS PhD HISTORICAL MEMORY REPORT

```
EXISTING DATA        results/option_analytics/live/  (305 MB)
                     states.jsonl    57,312 rows  133 MB
                     surfaces.jsonl  57,312 rows  160 MB
                     cycle_summaries    870 rows   11 MB
DATE RANGE           2026-08-18 17:23Z -> 2026-08-21 19:59Z   (3.1 DAYS)
UNIVERSE             SPY 19,108 · QQQ 19,108 · AAPL 19,096   (3 underlyings)
CHAIN QUALITY        DTE buckets 1-2 / 3-7 / 8-30 / >30 all populated
NBBO QUALITY         market_bid + market_ask on 57,312/57,312 (100%)
                     IV 52,137 (91%) · delta/gamma/rho 49,239 (86%)
                     state_quality HIGH 29,555 · MODERATE 19,127
                                   LOW 3,455 · REFUSED 5,175
```

**CRITICAL MISSING FIELDS** (absent from every record):
`bid_size` · `ask_size` · `volume` · `open_interest` ·
`underlying_bid` / `underlying_ask`

Without sizes there is no option-liquidity measure (the same law that
keeps equity liquidity NOT_ESTIMABLE); without OI there is no dealer
positioning; without underlying quotes no honest option-vs-equity
execution comparison.

**TIER RULING:** `TIER_A_REAL_CONTEMPORANEOUS` on the fields present —
these are genuine quoted markets with proper `event_time`/`known_from`,
not reconstructions. The deficiency is **span, not fidelity**: 3.1 days
and 3 underlyings is one regime, one week, effectively one market mood.

```
BEST HISTORICAL DATA SOURCE OPTIONS   EXTERNAL RESEARCH PENDING
```
No source is named here. Ranking vendors on coverage/cost/licence
requires web research I have not been authorized to spend on in this
task, and inventing a ranked table from memory would be exactly the
fabrication this program forbids. The *requirement spec* is below and
is what a source must satisfy.

**GOLD-STANDARD REQUIREMENT** (what any candidate must deliver):
timestamp · underlying · underlying_price (+bid/ask) · expiration ·
strike · call_put · bid · ask · bid_size · ask_size · last · volume ·
open_interest · IV or solvable inputs · rates · dividend assumptions ·
source · event_time · known_from — sufficient to reconstruct mid,
spread, spread_pct, surface, skew, term structure **without hindsight**.

```
RECOMMENDED INITIAL UNIVERSE   SPY, QQQ, IWM  (index/liquidity core)
                               + XLK, XLF, XLE (sector vol behaviour)
                               + AAPL, NVDA, TSLA, MSFT, AMZN (mega-cap,
                                 event-rich, deep chains)
                               declared BEFORE any outcome research
TARGET YEARS                   >= 5, must include a volatility shock,
                               a crush, and an earnings-heavy stretch
TARGET RESOLUTION              intraday snapshots (>= 1/min at the
                               touch); EOD-only is TIER_C for entry work
ESTIMATED STORAGE              current rate ~43 MB/day for 3 underlyings
                               -> ~10 names x 5 years is O(1-5 TB) raw,
                               O(100-300 GB) if restricted to a
                               moneyness/DTE window. A declared window
                               is mandatory, not optional.
```

```
REALIZED_VS_IMPLIED READINESS   PARTIAL — IV side is ready (91%
                                coverage, quality-tagged). Realized side
                                needs underlying history joined; equity
                                bars exist for all three underlyings, so
                                a 3-day RvI is computable TODAY, and it
                                is worth ~nothing statistically.
SURFACE MEMORY READINESS        PARTIAL — 57,312 surface records with
                                standardized_moneyness + delta_bucket.
                                Structurally ready, 3 days deep.
EXPRESSION COUNTERFACTUAL       BLOCKED — needs sizes + underlying
                                quotes to price a counterfactual fill
                                honestly. Mid-fills are forbidden.

CAN ACQUIRE NOW        add bid_size/ask_size/volume/open_interest to the
                       LIVE capture (fields the chain endpoint already
                       returns) -> every future day is complete
REQUIRES EXTERNAL      multi-year historical chains
REQUIRES API           venue/vendor entitlement
BLOCKED                expression counterfactual research
```

**NEXT EXACT ACQUISITION ACTION:** extend the live options capture to
persist `bid_size`, `ask_size`, `volume`, `open_interest` and the
underlying's bid/ask. It is a capture-schema change, costs nothing,
and every day it is delayed is a day of permanently incomplete history.
*Gated:* it touches a live daemon, so it waits behind Monday.

---

# 2. BTC PhD HISTORICAL MEMORY REPORT

```
EXISTING HISTORY BY SOURCE

DERIBIT     funding_hourly     64,093 rows  17 MB   2019 -> 2026-08
            perp_bars_daily     2,791 rows 644 KB   daily OHLCV
            (OI measured OI_REALTIME live: 80 changes/84 polls)
COINBASE    spot candles to 2020 available via API; NOT yet pulled
KRAKEN      OI_DELAYED (4/84 measured); no history pulled
BITNOMIAL   charts_price_daily     22 rows   (product born 2026-07-23)
            charts_voi_daily       16 rows
            funding_8h_settled      3 rows   (publication began 08-21)
OTHER       live derivatives_ledger 408 polls (251 lineage-eligible)
            WS book+trades ledgers accumulating this weekend
```

```
INTRADAY OPEN INTEREST
AVAILABLE     NO — this is the single largest BTC historical gap
BEST SOURCE   Deribit (the only venue measured OI_REALTIME); its
              history API would need a dedicated pull
DATE RANGE    none held
CADENCE       n/a
```

```
FUNDING HISTORY    STRONG — Deribit hourly 2019->now (7 years, multiple
                   regimes incl. 2021 mania, 2022 deleveraging)
MARK/INDEX HISTORY PARTIAL — Deribit index_price inside funding records;
                   Bitnomial only per settled 8h interval
PERP/SPOT HISTORY  PARTIAL — Deribit daily bars; Coinbase spot not pulled
BOOK HISTORY       NOT AVAILABLE — accumulating prospectively only
LIQUIDATION        NOT_AVAILABLE — and no candle-inferred substitute
                   will ever be created
```

**PRIMARY DATA GAPS, ranked**
1. **Intraday OI** — without it, leverage expansion/contraction (the
   core of participant state) is unlearnable historically.
2. **Intraday spot/perp** — daily bars cannot express spot-leads-perp.
3. **Coinbase spot candles** — authorized, simply not yet pulled.
4. Book history — accept the gap; accumulate forward.

```
CAN ACQUIRE NOW          Coinbase spot candles (already authorized);
                         Deribit OI/volatility history endpoints;
                         Deribit intraday bars (1m/5m/1h)
EXTERNAL SOURCE REQUIRED tick-level book history; liquidation feeds
```

**WORLD LAB EPISODE READINESS:** funding-anchored daily episodes are
possible today (~2,700 subject-days). Joint participant-state episodes
(price × OI × funding × premium) are **blocked on intraday OI**.

**ESTIMATED HISTORICAL EXPERIENCES POSSIBLE**
`~2,700` daily funding/price episodes now ·
`~500,000+` intraday joint-state episodes if 1m OI+spot+perp are
acquired over the Deribit era.

**NEXT EXACT ACQUISITION ACTION:** pull Deribit intraday
(1m/1h) perp bars + OI history + Coinbase spot candles into the
immutable raw store, venue-labelled, cadence-declared. Runs entirely
in the World Lab; touches no live daemon.

```
BTC-L2   UNCHANGED        BTC-L3   NOT_AUTHORIZED
```

---

# 3. EQUITY QUOTE ENRICHMENT PLAN

```
QUOTE SOURCE AVAILABLE   YES — ALREADY FLOWING, NOT PERSISTED
```
`apex/intraday/alpaca_fabric.py::_apply_quote` already subscribes to
and parses the quote channel and maintains an in-memory `self.quotes`
map. `apex/intraday/equity_fabric.py` does the same. **Nothing writes
them to disk.** Your suspicion was exactly right: this is a
persistence/canonicalization problem, not an acquisition problem.

```
FIELDS AVAILABLE TODAY   bid (bp) · ask (ap) · bid_size (bs)
                         ask_size (as) · event_time (t) · known_from
                         (+ future-timestamp rejection already enforced)
CADENCE                  quote messages far exceed trades; the module
                         notes quotes as the dominant message class
```

**CANONICAL SCHEMA (proposed):**
`symbol · event_time · known_from · bid · ask · bid_size · ask_size ·
spread_abs · spread_bps · quote_age_s · source · quality`

**QUALITY RULES:** crossed (bid>ask) → INVALID · locked (bid==ask) →
flagged, not silently valid · negative/zero size → INVALID ·
stale beyond policy → DEGRADED · missing side → INVALID ·
future timestamp → rejected (already implemented). **UNKNOWN ≠ 0.**

**PERSISTENCE PLAN:** do NOT store every update (quotes dominate the
stream). Store a canonical 1s top-of-book sample plus every quote whose
spread or size changes materially, with the retention policy declared
and the sampling loss measured — a lossy policy must *say* it is lossy.

**ATTACK GEOMETRY FIELDS UNLOCKED:** `liquidity_quality` (real) ·
`spread_quality` · `quote_freshness` · `entry_feasibility` ·
`chase_risk` measured against the executable market.

**STRONG ENTRY REQUIREMENTS (evidence categories, thresholds NOT set
here and never from outcomes):** good structural entry · bounded
invalidation · not chased · fresh quote · acceptable spread ·
acceptable top-of-book size. Existing standards do not loosen because
quote data arrives.

```
CHANGES SAFE BEFORE MONDAY    design only (this document)
CHANGES GATED UNTIL AFTER     any fabric change, any persistence,
MONDAY COMMISSIONING          any Attack Geometry field addition
```
