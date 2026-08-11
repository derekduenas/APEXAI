# APEX Research Protocol v1.0
## Experiment #001 — Price-Based Swing Ranking Signal

**Status:** Pre-registered / unexecuted
**Registered:** 2026-08-11
**Research budget:** Consumes 1 of 5 confirmatory experiments against the locked holdout
**Author:** Derek Duenas

> This document is written before results exist. Any change after registration must be recorded as an amendment with a date and a reason, and any amendment made after seeing validation results disqualifies the holdout test.

---

## 1. Research Question

Does a fixed, equal-weighted composite of four price/volume factors rank US equities such that higher-ranked stocks earn statistically significant higher forward 20-day excess returns, after realistic trading costs?

This is a test of **information content**, not of profitability, strategy design, or capital growth.

---

## 2. Hypothesis

**H1 (primary):** The cross-sectional Spearman rank correlation between the APEX Score at time *T* and the subsequent 20-trading-day excess return is positive, with a mean IC ≥ 0.015 and a Newey-West-corrected t-statistic ≥ 2.5.

**H0:** Mean IC ≤ 0.

**H2 (secondary):** The equal-weighted top decile of APEX Score outperforms the equal-weighted bottom decile by ≥ 4% annualized, net of the cost model in §8.

**Excess return — locked definition:**

```
Excess Return(i, T) = R(i, T+1 → T+21) − Median[ R(j, T+1 → T+21) ]
                      for all j in the universe at date T
```

Equal-weighted universe **median** — not the mean, not SPY, not sector-adjusted. Rationale: the question is whether APEX ranks winners inside its own investable universe, and the median is robust to the small number of extreme winners that distort a cross-sectional mean.

*Technical note:* this benchmark is a single cross-sectional constant at each date. Subtracting a constant does not change the rank ordering of returns, so the IC in H1 and the top-minus-bottom spread in H2 are **numerically identical** whether computed on raw or excess returns. The definition is locked for reporting consistency and for interpreting absolute figures, not because it alters either test.

Direction is specified in advance. A significant *negative* IC is a failed experiment, not a discovered reversal signal.

---

## 3. Universe Definition

**Base:** All US common stocks listed on NYSE, NASDAQ, or NYSE American.

**Inclusion filters, applied at each formation date using only data available at that date:**

| Filter | Threshold |
|---|---|
| Market capitalization | ≥ $1B |
| 60-day average daily dollar volume | ≥ $10M |
| Closing price | ≥ $5 |
| Trading history | ≥ 252 trading days |

**Exclusions:** ETFs, closed-end funds, REITs, SPACs, ADRs, units, warrants, preferred shares, and any security with fewer than 200 trading days in the prior 252.

**Survivorship treatment:** The universe must include securities that were later delisted, acquired, or removed from indices. Delisted securities remain in the universe until their delisting date. Where a delisting return is unavailable and the delisting is performance-related (bankruptcy, exchange rule violation), apply a terminal return of **−30%**. Where the delisting is a merger or acquisition, use the final traded price.

A universe constructed from a current list of tickers is invalid and must not be used, even provisionally.

---

## 4. Data Specification

**Required:**
- Daily OHLCV, split- and dividend-adjusted and unadjusted, for all listed and delisted securities
- Corporate actions: splits, dividends, spin-offs, delisting dates and reasons
- Shares outstanding (for market cap), historical as-reported
- Sector classification

**Primary source:** Norgate Data (US Equities incl. delisted). Secondary/cross-check: Polygon or Tiingo.

**Point-in-time rules:**
- No restated data. Prices as they printed, adjusted only for splits and dividends occurring on or before the formation date.
- Market cap computed from shares outstanding as known at formation date, not current shares.
- **Known limitation:** sector classification is not truly point-in-time in most affordable datasets. Reclassifications are infrequent and this is accepted as a minor contamination. It must be disclosed in the results and not silently ignored.

**Cleaning:** Records with zero volume, negative prices, or split-adjustment discontinuities > 50% not matched to a corporate action are flagged and excluded for that security-date. Exclusion counts are reported.

**Timing convention (lookahead firewall):**
- Features computed from data through the **close of day T**
- Portfolio formed at the **close of day T+1**
- Forward return measured **close T+1 → close T+21**

Any calculation that references a price at or after T+1 in the feature set is a lookahead violation and voids the run.

---

## 5. Feature Specification

Four categories, defined exactly. No additions, no substitutions.

**F1 — Momentum**
- 126-day total return, excluding the most recent 5 trading days
- 63-day total return, excluding the most recent 5 trading days
- Both expressed as excess over the equal-weighted universe return for the same window

**F2 — Trend Strength**
- (Close ÷ 200-day SMA) − 1
- Fraction of the prior 63 trading days on which Close > 50-day SMA

**F3 — Volatility Structure**
- Ratio of 20-day realized volatility to 100-day realized volatility (values < 1 indicate compression)
- ATR(14) ÷ Close

**F4 — Relative Strength**
- 63-day return minus the equal-weighted 63-day return of the security's sector
- 63-day return minus the 63-day return of the S&P 500

**Composite construction:**
1. Winsorize each raw feature cross-sectionally at the 1st and 99th percentiles
2. Convert to cross-sectional z-scores
3. Average the z-scores within each category → four category scores
4. **Equal-weight the four category scores** (0.25 each)
5. Rank cross-sectionally and map to percentile 0–100 = **APEX Score**

The equal weighting is a pre-registered prior, not an estimate. It is deliberately not optimized. Weight optimization is exploratory research and is out of scope for this experiment.

Sign convention for F3 must be fixed in advance and stated in code comments: compression (lower ratio) is hypothesized favorable.

---

## 6. Model Specification

**No machine learning.** The model is the deterministic linear composite in §5.

Rationale: an ML ranker introduces hyperparameters, feature interactions, and fitting decisions that cannot be pre-registered honestly at this stage. If a fixed linear composite of four well-understood price factors carries no information, an ML model fitted on the same features is far more likely to be fitting noise than to be recovering signal. ML ranking is a candidate for a future experiment **only if** Experiment #001 succeeds.

---

## 7. Research Design

**Splits:**

| Period | Dates | Use |
|---|---|---|
| In-sample | 2005-01-01 → 2017-12-31 | Implementation verification, pipeline debugging, sanity checks |
| Validation | 2018-01-01 → 2021-12-31 | One evaluation. Failure here ends the experiment. |
| **Locked holdout** | 2022-01-01 → 2026-06-30 | **One evaluation, once, ever** |

The in-sample period is for confirming the pipeline is correct — no lookahead, no survivorship, features computing as specified. It is *not* for judging whether the signal works, and in-sample performance must not influence any specification decision.

The holdout is not opened until validation has passed. If validation fails, the holdout remains untouched and available for a future experiment.

**Sampling and independence:**
- **Primary test:** cross-sectional IC computed daily; the resulting IC time series is tested with Newey-West HAC standard errors at lag 25 to correct for the autocorrelation induced by overlapping 20-day forward windows
- **Robustness test:** non-overlapping 20-day formation dates (~12.6/year), simple t-test

Both are reported. If they disagree in sign or materially in significance, the experiment is treated as inconclusive, not as a pass.

**Holdout power limitation, acknowledged in advance:** the holdout contains roughly 58 non-overlapping periods across a single broad market environment (rate normalization, AI-led concentration). It can detect a moderate-to-large effect and cannot resolve a small one. A pass on this holdout establishes robustness against recent unseen conditions only.

---

## 8. Cost Model

Fixed before results. Applied to all reported net figures.

| Component | Assumption |
|---|---|
| Commission | $0 |
| Half-spread | 5 bps per side |
| Slippage / impact | 5 bps per side |
| **Total round-trip** | **20 bps** |

At full turnover every 20 trading days (~12.6 round trips/year), this is approximately **2.5% annualized drag per leg**.

**Sensitivity:** all headline results are also reported at 2× cost (40 bps round trip). A result that passes at 1× and fails at 2× is reported as fragile and does not qualify for promotion.

**Tax:** pre-tax returns are primary, since this is a signal test. After-tax figures are reported for context at a 35% short-term marginal rate. 20-day holds generate exclusively short-term gains; this is disclosed, not optimized around, in this experiment.

---

## 9. Evaluation Metrics

**Primary:**
- Mean cross-sectional Spearman rank IC
- Newey-West t-statistic of the IC series
- IC information ratio (mean IC ÷ std dev of IC)

**Secondary:**
- Decile spread, gross and net, annualized
- Decile monotonicity (are D1→D10 mean returns ordered?)
- Hit rate: fraction of periods with positive top-minus-bottom spread
- Sharpe ratio of the equal-weighted top decile, net
- Maximum drawdown of the top decile
- Annualized turnover
- Breakdown by year and by market regime (bull / bear / high-vol)

**Portfolio simulation rule (evaluation construct only):**

The decile figures are produced by a mechanical rule, fixed here so that "the score works" has one unambiguous meaning:

- Hold every name in the top decile, equal-weighted
- Rebalance every 20 trading days; no intra-period trading
- A name that leaves the universe mid-period (delisting, merger, filter breach) is closed at its last valid price and the proceeds held in cash to the rebalance
- No leverage, no shorting, no stops, no position cap beyond equal allocation
- Long-only for reporting; the bottom decile is computed for the spread but never traded

*This is a measurement instrument, not a portfolio.* The top decile of a ~1,000–1,300 name universe is roughly 100–130 concurrent positions, which is not implementable in a personal account. Whether a concentrated, tradeable subset retains the signal is a **separate experiment** and must not be inferred from a pass here.

**Attribution reporting (required with every result):**
- Return contribution by sector
- Contribution of the top 5 individual winners
- Contribution of the top 5 individual losers
- Result recomputed with the single largest-contributing sector excluded

This exists to answer one specific question: did APEX find a cross-sectional signal, or did it find "own semiconductors during 2023–2025"? Both are informative; they are not the same discovery.

**Benchmark context (reported, not a criterion):**
Top decile net return compared against SPY, the equal-weighted universe, and a public momentum benchmark (e.g. MTUM). These provide interpretive context only. Beating or trailing a benchmark does **not** move the pass/fail decision in §10, which is determined solely by the pre-registered thresholds.

**Formation schedule (locked):** Every 20th trading day, beginning with the first date on which all features are computable (i.e. 200 trading days after the start of available data). The schedule is generated mechanically from that anchor and is never shifted, aligned to month-ends, or adjusted for holidays, earnings, or any market condition. Entry-date selection is not a free parameter.

**Missing data (locked):** No imputation, no forward-filling of feature inputs. Any security missing a required input for any of the four features at a formation date is excluded from that formation date only, and remains eligible at subsequent dates. Exclusion counts and reasons are reported.

**Per-rebalance reporting (required):** every formation date logs eligible universe count, count excluded by each filter, count excluded for missing data, top-decile count, and bottom-decile count. A sudden change in universe size is a data bug until proven otherwise.

Metrics are computed identically on validation and holdout. No metric is added after seeing results.

---

## 10. Promotion / Failure Criteria

Decided now. Not negotiable after results are visible.

**PASS — proceed to the next experiment:**
- Mean IC ≥ 0.015 **and** Newey-West t ≥ 2.5
- Non-overlapping robustness test agrees in sign and is significant at t ≥ 2.0
- Net decile spread ≥ 4% annualized at 1× costs
- Positive net decile spread in ≥ 55% of periods
- Result holds at 2× costs (spread ≥ 2% annualized)
- Decile ordering is broadly monotonic (top 3 deciles > bottom 3 deciles)

**INCONCLUSIVE — no further capital or effort; return to exploratory research:**
- Correct sign but failing significance or cost thresholds
- Primary and robustness tests disagree
- Result driven by a single year or a single sector (>60% of spread from one year or one sector)

**FAIL — hypothesis rejected:**
- Mean IC ≤ 0, or significantly negative

**On failure or inconclusive:** the experiment is closed and documented. The specification is **not** adjusted and re-run. A modified specification is a new hypothesis requiring a new pre-registration and consuming another unit of research budget. This is the single rule most likely to be violated and most important to hold.

**On pass:** the next experiment is a separate pre-registration. Candidates include the 60-day horizon, sector-neutral construction, or a fundamental feature block. Passing #001 does not authorize live capital.

---

## 11. Post-Promotion Monitoring

Applicable only if a signal eventually reaches live deployment. Written now, before any attachment exists.

**Retirement triggers:**
- **Decay:** rolling 100-trade realized IC falls below 50% of the holdout estimate
- **Calibration drift:** predicted vs. realized decile ordering breaks down over a statistically meaningful sample
- **Drawdown breach:** realized drawdown exceeds 1.5× the holdout maximum
- **Structural change:** documented change in market microstructure, regulation, or evidence of crowding

**Action on trigger:** pause new entries, hold existing positions to their defined exits, and require an explicit written review before reactivation. Reactivation is a decision with a date and a rationale, not a drift back into trading.

**Ongoing record:** every live trade records the signal value, the score decile, the forward return, and whether it matched the holdout expectation. This is the calibration dataset.

---

## 12. What This Experiment Does NOT Prove

A successful Experiment #001 establishes exactly one thing: **a fixed four-factor price composite carried measurable cross-sectional information in US equities over 2022–2026, under the stated universe, horizon, and cost assumptions.**

It does not prove:
- That the signal will persist in future regimes
- That any particular CAGR is achievable
- That the signal survives at larger position sizes or worse liquidity
- That options would amplify it
- That an ML model would improve it
- That LLM agents add anything
- That execution, slippage, or tax drag are solved
- That a portfolio built on it would be investable

Each of those is a separate question requiring a separate experiment. Success here purchases the right to ask the next question, and nothing more.

---

## Amendment Log

| Date | Change | Reason | Made before/after seeing results |
|---|---|---|---|
| | | | |
