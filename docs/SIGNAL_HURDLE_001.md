# SIGNAL_HURDLE_001 — what a real signal must clear (2026-09-12)

One page, no code, nothing built. This is the hurdle rate every future directional signal on the options path must
clear, and nobody had computed it. Measured inputs come from the burned 2026-09-11 SPY session; the arithmetic is
shown so you can substitute your own numbers.

## Measured inputs

| Input | Value | Source |
|---|---|---|
| relative spread on cap-feasible calls (ask ≤ $5.00) | median **0.86%**, p90 **1.12%** of mid | 661 quotes, 2026-09-11 session |
| round-trip spread cross (enter at ask, exit at bid) | **0.86%** of premium at the median | same |
| fees, 1 contract round trip | $0.04 + $0.05 = **$0.09** | `ROBINHOOD_RHF_2026` v2026-09-12b |
| premium of a cap-feasible contract | $4.54–4.97, call it **$4.75** ($475) | same session |
| theta over 15 minutes, 21 DTE, ~18% IV, 1% OTM | see below | Black-Scholes |

## The toll, per round trip

**Spread.** Entering at the ask and exiting at the bid pays the full spread once: 0.86% of $475 = **$4.09**.
Not 1.6–1.8%: the earlier estimate double-counted, since crossing at entry and at exit together is *one* spread,
not two half-spreads on top of each other. At the p90 spread it is 1.12% = **$5.32**.

**Fees.** $0.09.

**Theta.** A 21-DTE option at ~18% implied vol has roughly 0.5% of its premium in daily time decay near the money;
over 15 minutes of a 6.5-hour session that is about 1/26 of a day, so ≈ 0.02% of premium = **$0.09**. Small at this
horizon, and it is the one term that does not scale with spread.

**Total toll ≈ $4.27 per round trip**, or **0.90% of premium**, dominated almost entirely by the spread.

## The hurdle

The position is one long call, 1% out of the money, 21 DTE. Its delta is roughly **0.42**. A move of *x* percent in
SPY moves the option by approximately `0.42 × x × (S/premium)` = `0.42 × x × 765/4.75` = **67.6 × x** percent of
premium.

**To break even the option must gain 0.90% of premium**, so the required underlying move is

```
x = 0.90% / 67.6 = 0.0133%   ≈ 1.3 basis points of SPY, in the right direction, within 15 minutes
```

That is the *break-even move*, and it is small. The hurdle is not the size of the move. **The hurdle is the hit
rate**, because a wrong call loses the same delta-scaled amount plus the toll.

For a symmetric ±*m* move with hit rate *p*, expected P&L in percent of premium is

```
E = 67.6 × m × (2p − 1) − 0.90
```

Setting E = 0 gives the required accuracy:

```
p* = 0.5 + 0.90 / (2 × 67.6 × m)   with m in percent
```

| Typical 15-min SPY move *m* | Required hit rate *p** |
|---|---|
| 0.05% (5 bp, a quiet 15 minutes) | **63.3%** |
| 0.10% (10 bp) | **56.7%** |
| 0.15% (15 bp) | **54.4%** |
| 0.25% (25 bp, an active 15 minutes) | **52.7%** |
| 0.50% (50 bp, news) | **51.3%** |

On the 2026-09-11 session SPY's 15-minute moves ran around 0.05–0.15%, so **the standing hurdle is roughly 55–63%
directional accuracy on 15-minute SPY direction.**

## What that means

- A coin flip loses. `HEURISTIC_DIRECTION_V1` is a coin flip with a momentum prior nobody has tested, so its
  expected result is negative, and that is the prediction of record.
- **55–63% on 15-minute index direction is a very high bar.** It is well above what published intraday index
  literature supports for a simple signal, which is the honest reason to expect every simple signal to fail here.
- The hurdle falls fastest with **spread**, not with accuracy. Halving the effective spread (better strike choice,
  a limit at mid, a more liquid contract) moves the 0.10% row from 56.7% to 53.4%. **Execution is the cheaper
  lever than prediction**, and it is the one this system has actually measured.
- The hurdle also falls with **larger expected moves**: a signal that fires only when a large move is likely
  (an event, a volatility regime) needs far less accuracy than one that fires every 15 minutes.

## Standing use

Every future signal proposal states, before it is measured: which row of that table it claims, on what population,
and why. A proposal that cannot name its row has not been specified.

Caveats: one session, one underlying, one volatility regime; delta and theta are Black-Scholes approximations at
18% implied vol; the spread figures are from a calm morning and will be worse at the open and on event days.
