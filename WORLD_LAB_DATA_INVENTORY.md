# APEX WORLD LAB — DATA INVENTORY (v1, 2026-08-21)
**Law: inventory before models. Nothing below is "training data" merely
because it exists; tiers are assigned per the constitution.**

## EQUITIES_INTRADAY
| Source | Range | Resolution | Tier | Notes |
|---|---|---|---|---|
| Sharadar snapshot (on-box, 5.6GB, frozen) | multi-year daily | EOD | **B** | fundamentals+prices; PIT-quality per prior APEX audits; delisted coverage present (verify point-in-time membership fields before DISCOVERY use) |
| Alpaca canonical session bars (on-box, 83MB) | 2026-08-18 → live | 1m | **A** | our own commissioned pipeline; condition-filtered; continuity-labeled; grows daily |
| Alpaca REST historical bars (probed, works) | years (verify exact depth) | 1m+ | **A/B** | independent aggregates; used Fri for L3 reconciliation; execution-realistic for bars, not quotes |
| MISSING for honest breadth history | — | — | — | point-in-time index membership + historical sector classification through time — must be acquired before any breadth-history hypothesis |

## OPTIONS
| Source | Range | Resolution | Tier | Notes |
|---|---|---|---|---|
| APEX option_analytics live ledger (305MB) | 2026-08-19 → live | ~1min cycles | **A** | real contemporaneous bid/ask/IV/BSM greeks/depth — small but execution-realistic; grows daily |
| Historical chains w/ NBBO | NOT ACQUIRED | — | — | the hard gap; candidates (OPRA-derived vendors) cost money; **no midpoint-fill fantasies permitted**; until acquired, options history = TIER C at best |

## BTC_PERPS (weekend priority)
| Source | Range | Resolution | Tier | Notes |
|---|---|---|---|---|
| Coinbase arena raw events (on-box, 344MB, growing ~1GB/day) | ~2026-08-19 → live | tick/book | **A** (spot) | our own capture, hash-chained |
| Coinbase REST candles (probed to 2020-03) | ≥2015 → live | 1m–1d | **B** | deep spot history confirmed (COVID-crash day retrievable) |
| Deribit funding history (probed to Aug 2024, 168 rows/wk) | years | 8h/1h | **B** | REAL historical funding for the offshore-perp behavior corpus |
| Deribit ticker (live poller) | 2026-08-21 → live | 15s | **B** | mark/index/funding/OI flowing; **OI = OI_REALTIME (measured 80 changes/84 polls) — the intraday participant-pressure source** |
| **Bitnomial PBTCUCZ50 (PRIMARY venue)** (live poller) | 2026-08-21 → live | 15s | **A-candidate** | **UNITS RESOLVED_BY_SPEC**: Product Data prices are TICKS × price_increment($5) → USD (15,467→$77,335); Charts OHLC is USD ALREADY (double-conversion forbidden, tested); CASH SETTLED per live spec 5614; **OI = DAILY_PUBLISHED (measured 1 change/67 polls) — polled 15s but NOT intraday info**; residual −1.48% same-poll discount vs Deribit/Coinbase = open L2 market-semantics question; charts history = acquisition #1 |
| Kraken Futures ticker (live poller) | 2026-08-21 → live | 15s | **B** | second US-adjacent perp reference |
| OKX funding (live poller) | 2026-08-21 → live | 15s | **B** | third funding reference |
| Binance / Bybit | — | — | **UNUSABLE (from this host)** | HTTP 451/403 geo-blocks, recorded; their public HISTORICAL dumps may still be legally obtainable — investigate separately |
| Liquidation events | NOT ACQUIRED | — | — | no reachable live source yet; operator: separate approved source needed |
| Hyperliquid | — | — | **excluded for execution** (US-person terms); research-data legality TBD before any use |

## VENUE ARCHITECTURE (operator ruling 2026-08-21)
Primary perp venue: **BITNOMIAL** (US-regulated, 8h funding, WS+REST,
DMA path later) · Broker front-end: Kraken Derivatives US · Spot
reference: Coinbase · Second regulated reference: Coinbase CDE (hourly
funding — different mechanism, keep separate) · Liquidations:
separately sourced · Hyperliquid execution: NO.

## NEXT ACQUISITIONS (ranked)
1. Bitnomial charts history (price/volume/OI) — documented public REST
2. Deribit full funding + trades history walk (years)
3. Coinbase candles bulk walk (spot regimes back to 2015+)
4. Point-in-time equity membership/classification source
5. Liquidation stream source (approved)
6. Historical options chains w/ real NBBO (budget decision)
