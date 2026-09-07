# FIRST ECONOMIC PROGRAM — one opportunity family, one horizon

Direction preserved: **event-conditioned, options-informed mispricing,
including second-order transmission, within a small, sufficiently liquid
universe.** The 15-minute-to-five-day range is an exploration envelope. One
family and one horizon are selected here, **before any real row is read**,
and the selection is recorded so the search burden is one, not the number
of things considered.

EXP-001 is not rewritten. Its registration (`1a3f55a5…`), controls,
development history and limitations stand; its adjudication concerns its
registered hypothesis only. The program below is drafted as a separately
identified proposal, **ALPHA-EXP-002 (PROPOSAL, not registered)**.

## 1. Candidates enumerated (all, before choosing)

| Family | Horizon | Admissible data on box | Mechanism | Expressions available | Execution feasibility | Effective sample | Account-size fit |
|---|---|---|---|---|---|---|---|
| F1 SPY/QQQ/IWM scheduled-macro windows (FOMC, CPI, NFP) | H_1D: prior close → event-day close | ETF 1m bars 2016→; option chains per-minute 2018→ (SPY/QQQ/IWM); **event calendar NOT on box** (public, reconstructible with provenance) | information release, transmission through rates → index/sector; dispersion often priced pre-event | defined-max-loss structures (debit verticals, straddles/strangles, calendars) from the prior-close chain | liquid; contract granularity fine at SPY; 1-day horizon avoids 15m option illiquidity | ~250 events 2018–2025 (correlated across the 3 ETFs; ~1 independent) | good |
| F2 single-name earnings (AAPL/MSFT/NVDA) | H_1D | 1m bars via PIT corpus; option chains 2018→; **earnings calendar NOT on box** | idiosyncratic information release; implied-move vs realized | straddles/strangles, verticals | liquid | ~96 events on 3 names | good |
| F3 second-order transmission: macro → sector ETFs (XLF, XLE, XLK…) | H_1D–H_5D | ETF bars 2016→; **no option chains for sector ETFs on box** | rate/inflation surprise → sector dispersion | stock comparators only (not PRIME-eligible) | fine for shares; no certified expression | ~250 events | poor without options |
| F4 intraday 15m post-release continuation | H_15M | ETF bars; option chains per-minute (SPY) | post-release order-flow persistence | 0DTE only from late 2022; otherwise shares | 15m option comparison NOT_ESTIMABLE before 2022 | large bar count, few events | poor |
| F5 broad single-name event universe (300 PIT names) | H_1D–H_5D | PIT bars; membership; **no option chains; no event corpus** | earnings dispersion | shares only | fine | large | poor without options |

## 2. Selection

**Recommended: F1, H_1D.** Reasons, in mandate order:

1. *Admissible data coverage* — the underlying bars and per-minute option
   quotes (with a per-row publication law) are on box for all three ETFs;
   only the event calendar must be acquired, and it is small, official and
   publication-timestamped (release schedules are published a year ahead).
2. *Economic mechanism* — a scheduled information release with a
   measurable published expectation and a measurable implied distribution
   at the prior close.
3. *Available expressions* — the fundable class (DEFINED_MAX_LOSS option
   structures) exists at this horizon; EXP-001's stock comparators do not
   fund.
4. *Execution feasibility* — SPY option liquidity at 1–5 DTE is the best
   available; the interim valuation model for early exit can be built from
   the same per-minute chain.
5. *Effective sample* — ~250 events; dependence across the three ETFs is
   handled by treating SPY as primary and QQQ/IWM as transmission
   comparators.
6. *Account-size constraints* — single-contract granularity at SPY fits
   the retail-capacity scale; capacity ceiling assessed via
   `assess_capacity`.

F2 is the second candidate (fewer events, needs an earnings calendar with
publication provenance). F3 is the *second-order transmission* extension of
F1 and is kept as a research comparator until sector-ETF chains are
acquired. F4 and F5 are deferred: no certified expression.

## 3. Search burden recorded

One family, one horizon, one target, chosen before data. Any later change
of horizon or family is a new proposal with its own registration; results
from an abandoned proposal are reported, not discarded.

## 4. ALPHA-EXP-002 — PROPOSAL (not registered; registration is a separate act)

- **Hypothesis:** conditional on the prior-close option-implied
  distribution of SPY's event-day return and the published expectation for
  the scheduled release, a physical forecast that combines the implied
  distribution with the realized-volatility state predicts the event-day
  log return distribution with higher out-of-sample log likelihood than the
  implied distribution alone (risk-premium-adjusted).
- **Comparator M0:** the implied distribution (risk-neutral → physical by a
  declared premium adjustment fit on train). **M1:** M0 reweighted by a
  fitted conditional adjustment (features: rv_30 at prior close, event
  type, published expectation where available).
- **Data (each through the real-data boundary, separately admitted):**
  history-b ETF bars (SPY primary; QQQ/IWM comparators); history-a option
  chains (prior-close snapshot, publication-timestamped); a scheduled-event
  calendar to be acquired with source and publication time.
- **Splits:** train 2018–2021, validation 2022–2023, evaluation 2024–
  (sealed), reserve 2026+.
- **Statistic:** DM-HAC on log-likelihood differential; null N0 (outcomes
  permuted across events); N1 (implied distribution shifted by one event).
- **Economic stage:** defined-max-loss structures selected by after-cost
  expected value from the chain; entry at prior close, exit at event-day
  close *or* by a declared management policy with interim valuation from
  the per-minute chain; costs = quoted spread + fees; contract granularity.
  Readout: after-cost mean, HAC SE, certified-loss exceedance frequency,
  capacity at declared participation.
- **Search budget:** 2 model families, 1 feature set, 0 tuned
  hyperparameters, 1 horizon.
- **Blockers before registration:** event calendar acquisition and
  eligibility; option-implied estimator at daily horizon from the chain
  (C6 comparator); management-policy valuation model; admission decisions
  for two datasets.

## 5. What this does not claim

No family here is known to be mispriced. The choice is a research
allocation, not a forecast of success. An EXP-002 failure would adjudicate
its hypothesis, not the architecture.
