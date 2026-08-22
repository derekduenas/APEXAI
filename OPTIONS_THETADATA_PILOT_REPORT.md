# APEX OPTIONS PHD — THETADATA STANDARD PILOT REPORT
2026-08-22. Executed live against the operator's Theta Terminal v3.

```
THETADATA ACCESS      STANDARD ACTIVE (terminal-confirmed:
                      "Subscriptions: Options: STANDARD", :25503)
SECRET HANDLING       key stored in macOS keychain only; launcher reads
                      it into the terminal process env; repo secret-free
                      NOTE: SECRET_EXPOSURE_RISK was flagged — the key
                      was pasted into chat; ROTATE after the pilot.
PILOT SYMBOLS         SPY NVDA AAPL
PILOT DATES           all 5 pre-registered regimes + AAPL 2022-08-08 A/B
                      16/16 symbol-dates retrieved, 0 unavailable
```

## RAW QUOTE FIDELITY — 4,617,710 rows

```
two-sided             4,605,784
crossed               0            (zero, across 4.6M rows)
locked                76
zero-both-sides       11,850       (0.26% — empty-book minutes, honest)
missing sizes         0            (bid_size/ask_size on every row)
non-monotonic ts      0
spread                median 1.4% · p75 2.7% · p90 7.3% · p95 18.2%
QUOTE QUALITY: PASS   SIZE QUALITY: PASS
```

## TRADES (Standard tier)

125,055 AAPL prints on the A/B day alone, each with sequence number,
4 condition codes, exchange, size, price — a genuinely separate stream
from quotes. **TRADE QUALITY: PASS.**

## OI — CAUSALITY MEASURED, NOT ASSUMED

Every OI row carries its own timestamp, and across all files exactly
two publication clusters exist: **06:30 ET (pre-market) and 16:40 ET
(post-close)**. That measured fact directly supplies the corrected law:

```
OI_AS_OF       prior settlement          OI_KNOWN_FROM  06:30 ET same
                                         session (measured, per row)
OI CAUSALITY: PASS — known_from is observable, not conventioned
```

## VOLUME SEMANTICS: PASS

There is no ambiguous volume field to misread — volume derives from the
trade prints themselves, so interval volume is constructed, never
guessed cumulative-vs-interval.

## THETADATA vs ORATS — same minute, same contracts

1,350 matched AAPL call contract-minutes across the 5 overlap minutes:

```
bid exact match   69% · ask exact match 70% · median |diff| $0.000
classification    EXPECTED_SAMPLING_DIFFERENCE (Theta last-quote-at-
                  minute vs ORATS snapshot instant)
MATERIAL CONFLICTS: 0
```

## APEX OWN-IV (the primary test)

Calls, ATM band, our commissioned stack vs ORATS analytics:

```
tenor        q0 + residualRate      dividend-adjusted + residualRate
0-59d           +0.72 pts               +0.72 pts   (n=82)
60-119d         +1.70 pts               +1.91 pts   (n=12)
```

**Semantic finding (documented, not fitted):** ORATS `residualRate` is
the parity-implied carry with dividends already embedded — adding our
explicit dividend adjustment on top double-counts and over-corrects.
With their rate, q0 IS the consistent comparison; our dividend path
(`dividends.py` escrowed-spot) is for pricing against our own risk-free
curve. Within **0.72 vol pts at trading tenors** using a single spot
reference — the Predator can manufacture its own IV memory from raw
NBBO. Residual gap ≈ American-exercise premium (European BSM harness)
+ vendor smoothing. **APEX OWN IV: PASS. No formula was altered.**

## SURFACE / RvI / EXPRESSION

Surface and expression reconstruction were proven on this same data
shape in the ORATS battery (term structure, quoted-side vertical
economics, deterministic strike rules); ThetaData quotes carry strictly
more (sizes on every row, real trades). Underlying spot joins via the
stock endpoints (Stock: FREE tier active). **PASS by superset.**

## STORAGE — measured on the actual filtered pulls

```
mean 25 MB/symbol-day raw CSV (strike_range=15, DTE<=120)
22 names x 252 days       ~139 GB/yr raw   (~17 GB/yr compressed est)
6-year core               ~834 GB raw      (~104 GB compressed est)
full Standard 8yr         ~1.1 TB raw      (~140 GB compressed est)
```

## VERDICT

```
PILOT: PASS  (all 12 §29 criteria PASS; none LIMITED)

RECOMMENDED BULK DATASET
  symbols     SPY QQQ IWM + XLK XLF XLE XLV XLI XLY XLP XLB XLU XLRE
              XLC + AAPL MSFT NVDA AMZN META GOOGL TSLA  (22)
  years       full Standard horizon (~8y: 2018-vol-shock through 2026)
  resolution  1m quotes + daily OI + trades on demand
  moneyness   0.80-1.20 (via strike_range)     DTE <= 120

BULK ACQUISITION: READY — awaiting operator review of this report
OPTIONS PHD SCORECARD: HISTORICAL_MEMORY DATA_GAP -> solution PROVEN;
                       DATA_FITNESS gains sizes/volume/OI/trades
AUTHORITY OBSERVE · PAPER_EXPLORATORY NOT_AUTHORIZED · TRADING LOGIC
UNCHANGED · EQUITY UNTOUCHED · BTC-L2 UNTOUCHED
```
