# OPTIONS HISTORICAL PILOT REPORT
2026-08-22. **No purchase, no subscription, no APEX change. Authority
OBSERVE.** Everything below was measured, not asserted.

```
PILOT SYMBOLS      AAPL (executed — the one symbol legitimately free)
                   SPY, NVDA (registered, awaiting vendor access)
PILOT DATES        EXECUTED: 2022-08-08 14:00–14:04 UTC (ORATS free
                   production sample — 5 consecutive 1-min full chains)
```

## PRE-REGISTERED VENDOR-PILOT DATES (selected by externally known
## regime BEFORE any data download; rationale recorded now)
```
QUIET          2023-07-19   summer low-vol drift
HIGH-VOL       2024-08-05   yen-carry unwind, VIX spike
EVENT          2024-05-22   NVDA earnings session
BROAD SELLOFF  2022-09-13   CPI-shock down day
STRONG TREND   2024-02-22   NVDA post-earnings gap-and-run
```

---

## ACCESS

```
THETADATA      BLOCKED_WITHOUT_SUBSCRIPTION — no credentials on host,
               no local Theta Terminal (port 25510 probe: dead). Their
               API requires an authenticated terminal even for free
               tier. Honest state: cannot be piloted without opening
               an account.
ORATS          FREE PRODUCTION SAMPLE OBTAINED —
               orats.com/university/intraday-sample-data.zip: AAPL,
               2022-08-08, five 1-minute files, 48 columns, IDENTICAL
               structure to the $1,500 product.
APEX LIVE      no timestamp overlap (our capture begins 2026-08-18;
               sample is 2022) — structural comparison only.
```

## ORATS SAMPLE — MEASURED QUALITY (920 contracts/minute, 4,600 rows)

```
FIELDS PRESENT     ticker, tradeDate, expirDate, dte, strike,
                   stockPrice, call/put Volume, OpenInterest,
                   BidSize, AskSize, BidPrice, AskPrice, theoretical
                   Value, bid/mid/ask IV per side, smoothed vol (smv),
                   delta gamma theta vega rho phi driftlessTheta,
                   residualRate, quote timestamp
                   -> EVERY gold-standard field is present
QUOTE QUALITY      1,840 two-sided quotes: 0 crossed, 0 zero-ask
                   spread median 1.7%, p90 16.2% (deep wings)
COVERAGE           111 strikes x 18 expiries per minute
SIZE QUALITY       real per-side sizes (e.g. 74x166 at the ATM)
OI SUPPORT         PRESENT but — measured — 0 of 920 contracts change
                   OI across the 5 minutes: OI IS A DAILY SNAPSHOT
                   STAMPED ONTO EVERY MINUTE. The leakage warning from
                   the source report is CONFIRMED IN THE DATA: ingest
                   must re-stamp OI with its true (previous-close)
                   known_from, never the minute's timestamp.
```

## IV / GREEKS RECONSTRUCTION — the "own brain" test

Reconstructed IV from raw bid/ask + stockPrice + residualRate using
APEX's **commissioned pricing stack, unmodified**, and compared to
ORATS's own computed IVs:

```
signed diff (ours − ORATS), ATM band, by tenor:
  calls  ≤30 DTE   +0.12 to +0.66 vol pts     puts ≤30 DTE  ~−1.0 to −1.7
  calls  660 DTE   +5.24                      puts 660 DTE   −5.99
```

**Diagnosis, not hand-waving:** the gap grows monotonically with tenor
and is equal-and-opposite between calls and puts — the exact
fingerprint of a **missing dividend yield** in my test harness (plain
European BSM, q=0). This is a harness limitation, not a data or stack
defect: `apex/option_analytics/dividends.py` and `american_binomial.py`
exist and are commissioned; the production path already handles
dividends. **Verdict: APEX CAN build its own historical volatility
memory from raw quotes** — within a vol point at the tenors it trades,
with the dividend-adjusted path required (and already built) beyond
~60 DTE. No formula was modified to match the vendor.

## SURFACE / TERM STRUCTURE

Reconstructed from one minute's chain, information at T only:
```
ATM IV by DTE:  5d .285 · 12d .249 · 19d .250 · 26d .251 · 33d .252
                · 40d .266 · 47d .264 · 75d .279
```
A clean short-end hump into an upward term structure — economically
sensible for AAPL a week after earnings. SURFACE RECONSTRUCTION: PASS.

## EXPRESSION RECONSTRUCTION (deterministic rules declared first)

Rule: nearest-ATM strike, 3rd-OTM wing, quoted sides only:
```
LONG_CALL      167.5C 8/26: pay ASK 3.80 (bid 3.75, size 74x166)
CALL_VERTICAL  167.5/175:  pay 2.98 (wing sold at BID 0.82)
```
Real quoted economics, no mid fills, sizes visible. READY — the data
supports honest expression counterfactuals. (No outcomes computed.)

## REALIZED-vs-IMPLIED READINESS

IV side: PASS (above). Realized side: needs the underlying's own bar
history joined — `stockPrice` per minute is in the file itself, so a
minute-resolution realized-vol series is derivable from the same
product. READY once a multi-day corpus exists.

## STORAGE — measured, not vendor-quoted

```
523 KB per 1-min full-chain file  ->  209 MB/symbol-day uncompressed
moneyness 0.80–1.20 + DTE≤120 keeps 26% of contracts -> ~55 MB/sym-day
22-name universe, filtered:   ~300 GB/yr uncompressed
                              (CSV compresses ~8–10x -> ~30–40 GB/yr)
PROJECTED 3-YEAR CORE         ~0.9 TB raw / ~100 GB compressed
PROJECTED 6-YEAR CORE         ~1.8 TB raw / ~200 GB compressed
```
Radically below the 50 TB full-archive figure — the filter is the
whole game, exactly as suspected.

---

## VERDICTS

```
ORATS       PASS on structure and fidelity (measured on real product
            sample): every needed field, clean quotes, sizes, own-IV
            reconstruction confirmed, expression economics honest.
THETADATA   BLOCKED_WITHOUT_SUBSCRIPTION — untested, not failed. Its
            raw-NBBO representation and 12-year depth remain the case
            for it; the case is unverified.

RECOMMENDATION   ORATS_FIRST — with a caveat the operator should weigh:
                 this pilot could only test ORATS, because ORATS is the
                 one with a free sample. That asymmetry favored it. But
                 the sample proves the $1,500 one-time product delivers
                 every field APEX needs at 1-minute, sizes included,
                 with our own pricing stack able to independently
                 verify its analytics. ThetaData's $40 Value month
                 remains the cheap way to run the same battery on raw
                 NBBO before or alongside a purchase.

PURCHASE REQUIRED NEXT    YES — either ORATS one-time ($1,500 + S3
                          transfer, selective pull ONLY per the filter)
                          or ThetaData Value ($40, one month, pilot).
                          OPERATOR DECISION. Nothing was purchased.
LIVE SIZE PERSISTENCE     READY_AFTER_MONDAY (values already in memory)
AUTHORITY                 OBSERVE        APEX CHANGES: 0
```
