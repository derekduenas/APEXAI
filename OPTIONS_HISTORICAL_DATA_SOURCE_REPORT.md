# APEX OPTIONS HISTORICAL DATA SOURCE REPORT
2026-08-22. **Research only. No purchase, no subscription, no
credentials, no APEX change. Authority OBSERVE.**

Every figure below was read from the provider's own current page this
session. Where a page did not state a fact, it is marked UNKNOWN
rather than inferred.

```
CURRENT OPTIONS MEMORY   57,312 states / ~3.1 days / SPY, QQQ, AAPL
```

---

## PROVIDERS EVALUATED

### ThetaData
```
years        since June 2012 (tier-gated: 4y / 8y / 12y)
resolution   tick · 1-second OHLC · 1-minute · EOD
NBBO         "100% NBBO coverage"; every NBBO quote reported by OPRA
bid/ask      YES        sizes: implied by NBBO, not separately stated -> UNKNOWN
volume       YES (complete trade data)
OI           YES - daily updates, all strikes/expirations
IV/Greeks    YES - 1st/2nd/3rd order, Black-Scholes
API          REST + streaming        bulk: UNKNOWN
cost         Value $40/mo (4y, 1-min) · Standard $80/mo (8y, tick NBBO)
             · Pro $160/mo (12y, tick NBBO + every trade)
licensing    UNKNOWN
limitations  OI is DAILY, not intraday - matters for causality (below)
```

### ORATS — 1-minute historical
```
years        since Aug 2020 (~6 years)
resolution   1-minute
NBBO         quoted bid/ask                         sizes: YES
volume       YES        OI: YES
IV           YES - bid, mid, ask AND smoothed
Greeks       YES - delta gamma theta vega rho phi driftlessTheta
             + theoretical values + underlying price
coverage     5,000+ symbols
delivery     AWS S3, ~50 TB, 14-day access window
cost         $199/month recurring  OR  $1,500 one-time for history
             (+ "$1-2k" estimated S3 storage/transfer)
limitations  starts 2020 -> NO COVID crash, NO 2019 baseline;
             50 TB is unusable whole - selective pull mandatory
```

### Cboe DataShop — Option Quote Intervals
```
years        January 2012 to present
resolution   1/5/10/15/20/30/60/390/405-minute snapshots
NBBO         YES, with sizes      volume: YES
OI           optional add-on      IV/Greeks: optional add-on
fields       underlying, quote datetime, root, expiration, strike,
             type, OHLC, volume, NBBO+sizes
storage      full market w/ calcs @1min = 2,300 GB/yr compressed
             SPY alone w/ calcs @1min  =    20 GB/yr compressed
cost         NOT DISPLAYED - quote-form only -> UNKNOWN
limitations  price opacity; per-symbol configuration required
```

### Databento — OPRA
```
years        OPRA since 2013
resolution   mbo (L3) · mbp-10 · mbp-1 · trades · ohlcv
NBBO         YES with sizes       volume: YES (trades)
OI           via statistics schema
IV/Greeks    NOT PROVIDED (raw market data, not analytics)
coverage     1.6M+ equity-option symbols
cost         consumption-based, historical "from $0.04/GB";
             $125 free credits for new users
delivery     API + flat files
limitations  no IV/Greeks - APEX would compute them (we already have
             bsm + american_binomial + iv_triple commissioned)
```

### Massive (formerly Polygon.io)
```
years        Basic 2y (free) · Starter 15-min delayed · Developer 4y
             · Advanced 5y+
NBBO         quote access on higher tiers    sizes: UNKNOWN
OI           UNKNOWN        IV/Greeks: real-time on higher tiers
cost         free · $29 · $79 · $199 per month
limitations  Advanced tier is "Non-pros only"; shallower history than
             ThetaData/Cboe at comparable price
```

### HistoricalOptionData.com
```
resolution   END OF DAY ONLY - "All of our data is end of day data"
fields       last, bid, ask at close; explicitly NO intraday high/low
coverage     ~5,700 symbols, ~1.4M contracts, 620k rows/day
cost         UNKNOWN (not on the overview page)
APEX FIT     INSUFFICIENT - EOD cannot support intraday entry
             decisions or spread economics
```

---

## APEX FITNESS SCORING

| | ThetaData | ORATS 1m | Cboe | Databento | Massive |
|---|---|---|---|---|---|
| A realized-vs-implied | EXCELLENT | EXCELLENT | GOOD | GOOD¹ | PARTIAL |
| B surface memory | EXCELLENT | EXCELLENT | GOOD | GOOD¹ | PARTIAL |
| C skew memory | EXCELLENT | EXCELLENT | GOOD | GOOD¹ | PARTIAL |
| D term structure | EXCELLENT | EXCELLENT | GOOD | GOOD¹ | PARTIAL |
| E attack geometry | EXCELLENT | GOOD² | GOOD² | EXCELLENT | PARTIAL |
| F expression counterfactual | EXCELLENT | GOOD² | GOOD² | EXCELLENT | POOR |
| G execution realism | EXCELLENT | GOOD² | GOOD² | EXCELLENT | POOR |
| H event/expiry research | GOOD | GOOD | GOOD | GOOD | PARTIAL |
| I regime coverage | EXCELLENT (2012) | PARTIAL (2020) | EXCELLENT (2012) | GOOD (2013) | POOR |

¹ raw quotes only — APEX computes IV/Greeks with its own commissioned
pricing stack, which is arguably *better* (we control the model).
² 1-minute snapshots, not tick: entry economics are approximated to the
minute. Adequate for our hold horizons; not tick-accurate.

---

## RESOLUTION TRADEOFF — the money question

**1-minute is the right target. Tick is not needed and costs an order
of magnitude more.**

APEX's equity Attack Geometry operates on 1-minute bars and expected
holds are 20–90 minutes. An options sleeve whose entries are minute-
resolved is coherent with the rest of the system. Tick/NBBO buys
sub-second fill realism we cannot use — manual/paper execution latency
alone is seconds to tens of seconds. EOD is disqualifying.

```
MINIMUM VIABLE HISTORY   2 years, 1-minute, core universe
PREFERRED HISTORY        2020-present (ORATS) - includes 2022 bear,
                         2024 ETF era, 2025-26
IDEAL HISTORY            2012-present (ThetaData/Cboe) - adds 2018 vol
                         shock, 2020 COVID crash, 2021 speculation
```

---

## RECOMMENDATIONS

```
BEST OVERALL     THETADATA PRO  $160/mo - 12 years, tick NBBO, every
                 trade, daily OI, Greeks. Deepest regime coverage of
                 any option we found, at hobbyist price.

BEST VALUE       THETADATA STANDARD $80/mo - 8 years (2018+), tick NBBO.
                 Captures 2018 vol shock, COVID, 2021, 2022 bear.
                 $960/yr for the full history APEX needs.

BEST INITIAL     ORATS ONE-TIME $1,500 - 1-minute since Aug 2020, with
PILOT            sizes + volume + OI + IV + Greeks ALREADY COMPUTED,
                 5,000 symbols. One payment, no recurring, and it is
                 the single fastest path from zero to a real Options
                 World Lab. Budget $1-2k more for S3 transfer.
```

**Recommended initial universe (declared BEFORE any outcome research):**
SPY · QQQ · IWM · XLK XLF XLE XLV XLI XLY XLP XLB XLU XLRE XLC ·
AAPL MSFT NVDA AMZN META GOOGL TSLA — 22 names.

**Estimated storage** (anchored on Cboe's published 20 GB/yr for SPY
alone at 1-min with calcs): SPY/QQQ/IWM chains are the heaviest;
sector ETFs and mega-caps are materially thinner. Order of magnitude
**~150–300 GB/year** for the 22-name universe at 1-minute with
calculations; **~1–2 TB for a 6-year pull**. Restricting to a
moneyness band (say 0.80–1.20) and DTE ≤ 120 would cut this several-
fold and is recommended.

---

## LIVE CAPTURE GAP — corrected and sharpened

My earlier audit said sizes were missing. The code says something more
precise:

```
bid_size / ask_size   AVAILABLE LIVE, USED, NOT PERSISTED
                      apex/option_analytics/live_quality.py carries
                      bid_size/ask_size and computes depth =
                      min(bid_size, ask_size); chain_adapter._depth()
                      gates on bid_size+ask_size >= 5 contracts.
                      They simply never reach states.jsonl.

volume / open_interest  NOT IN THE CANONICAL FEED AT ALL
                      chain_adapter.build_surface_for documents them as
                      "honestly NO_SUPPORT -- the canonical feed does
                      not carry them (yet)".
```

So persisting sizes is **trivial** (the values are already in hand),
while volume/OI require a feed change or a second source. Both remain
GATED until after Monday.

---

## OI CAUSALITY CONCERN (applies to every vendor)

Open interest is published **once daily, after the close**, and is not
knowable contemporaneously with an intraday quote. Every provider
above reflects that. The corpus must therefore stamp OI with its real
publication time and the World Lab must refuse to let an intraday
state at 10:31 read an OI value that only became known that evening.
**This is a leakage vector, and it is the one most likely to be
gotten wrong by default.**

```
FIELDS NO SOURCE SOLVES WELL
  intraday open interest        (structurally unavailable, all vendors)
  dealer positioning            (must be inferred, never observed)
  true multi-leg fill economics (quoted legs only; spread books differ)
```

---

## NEXT ACTIONS

**RECOMMENDED PILOT TEST:** before any purchase, take a **single
representative day** and compare ThetaData vs ORATS on the same
symbols — SPY plus two mega-caps — checking quote timestamps, spread
distributions, IV agreement against our own commissioned pricing
stack, and OI publication stamps. Two sources, one day, one verdict.
ThetaData's $40 Value tier is a cheap way to run that test.

**RECOMMENDED NEXT ACTION (free, do first):** after Monday, persist
`bid_size`/`ask_size` in the live options capture — the values are
already computed in memory and thrown away every cycle. Every day of
delay is a permanently incomplete day of proprietary history.

```
NO PURCHASE MADE   ·   NO APEX CHANGE   ·   AUTHORITY OBSERVE
```
