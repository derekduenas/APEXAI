# CONVENTIONS.md
## Binding Resolutions — APEX Research Protocol v1.0, Experiment #001

**Status:** Signed / frozen
**Date:** 2026-08-07
**Author:** Derek Duenas
**Governs:** `APEX-Research-Protocol-v1.0-Experiment-001.md`, SHA-256 `8f3396f70cf426a750a3ca2c557cedd5dd6b0877800885319b99768932a76bb6`

This document resolves every specification gap identified in the Stage-0 review. It has the same force as the protocol itself. Nothing here may change after data is first loaded, except by dated amendment recorded in §7 below.

**No amendment to the protocol is required.** The vendor decision below allows §3 and §4 to execute as originally written. This document specifies; it does not modify.

---

## 1. Data Vendor (resolves A1, A2)

> **Amended 2026-08-09 (A-002). See §7.** Sharadar is confirmed **primary and
> authoritative for every universe filter**. Norgate is admitted as an
> **optional secondary source for prices and cross-checking only**, and may
> never be authoritative for a universe filter, for shares outstanding, for
> market capitalisation, or for security identity. Where the two disagree on a
> price, Sharadar governs and the disagreement is reported. A security-date that
> cannot be established point-in-time from Sharadar is **excluded and reported** —
> never filled from Norgate, from today's shares, from today's market cap, from
> a current ticker mapping, or from a later-revised fundamental.

**Primary source: Sharadar, via Nasdaq Data Link.**

| Table | Use |
|---|---|
| `SEP` | Daily OHLCV, unadjusted and adjusted, survivorship-free incl. delisted |
| `DAILY` | Point-in-time market capitalization at each date |
| `TICKERS` | Security metadata, exchange, security type, sector, `isdelisted`, first/last price date |
| `ACTIONS` | Splits, dividends, delisting and corporate-action events |

`SF1` (fundamentals) is **not** used **for Experiment #001**. Experiment #001 has no fundamental features, and pulling it now creates the temptation to peek.

> **Amended 2026-08-11 (A-005). See §7.** `SF1` is permitted **for APEX-002 ONLY**,
> and **solely** as a source of as-filed shares outstanding (`sharesbas` /
> `sharewa`) keyed on `datekey`. It may **not** be used for Experiment #001,
> which is closed, and it does **not** open the wider fundamental field set to
> any experiment. The restriction's original purpose — removing the temptation
> to peek at fundamentals — is preserved by limiting the permission to a single
> named quantity for a single named experiment.

Rationale: Sharadar supplies survivorship-free point-in-time market cap, which Norgate does not, allowing §3's ≥$1B filter and §4's "shares outstanding as known at formation date" to execute literally. It is a plain HTTP/CSV API, which also resolves A2 — no Windows VM, no Norgate Data Updater.

**Two items to verify empirically before Stage 4 begins, and to report the findings of:**

1. **Delisting reason coverage.** §3's −30% convention applies only to *performance-related* delistings; M&A delistings use the final traded price. Confirm whether `ACTIONS` and `TICKERS` together permit a reliable performance-vs-M&A classification. If they do not, the fallback rule is: **treat any delisting not affirmatively identifiable as M&A or voluntary as performance-related** and apply −30%. This is the conservative direction and is hereby pre-registered as the fallback.
2. **Sector taxonomy.** Sharadar's `TICKERS.sector` is its own classification scheme, not GICS. C3 below is amended accordingly. Confirm bucket count and stability.

---

## 2. Rulings on Blocking Ambiguities (B1–B6)

**B1 — F3 sign convention.** **Both components are negated.** Lower ATR(14)÷Close is hypothesized favorable, as is a lower 20d/100d volatility ratio. F3 is therefore a low-volatility category, and this is accepted rather than worked around. Rationale: the low-volatility anomaly is well documented and directionally consistent with the compression hypothesis; leaving ATR un-negated would cause the two components to partially cancel and contribute noise.

**B2 — IC sampling.** Confirmed as read. **Daily cross-sectional IC is the primary test**, with Newey-West HAC standard errors at lag 25. **Every-20th-trading-day is the non-overlapping robustness subset and the portfolio rebalance schedule.** The two are distinct tests with distinct N.

**B3 — F4 skip.** **F4 applies the same 5-trading-day skip as F1.** Rationale: without it, F4 absorbs short-term reversal in the opposite direction from F1 and the two partially cancel.

*Consequence, logged and accepted:* with the skip applied, F1b (63-day excess vs. universe) and F4b (63-day vs. S&P 500) become near-duplicates, differing only in benchmark. This is a genuine weakness in the pre-registered feature set. It is **implemented as specified and not corrected.** Feature-set redundancy is a candidate hypothesis for a future experiment, not a mid-flight repair.

**B4 — Delisting return compounding.** **Reading (b), the Shumway (1997) convention:**

```
R = (P_last / P_entry) × 0.70 − 1
```

The −30% is applied to the terminal value on top of the realized partial-period return, not as the total window return.

**B5 — Regime definitions.** Defined blind, before any results exist:

- **Bull / Bear:** S&P 500 close at the formation date above / below its 200-day simple moving average
- **High-volatility:** VIX close at the formation date in the **top tercile of its trailing 1,260-trading-day distribution**

The trailing window is mandatory. A full-sample percentile would be lookahead and would silently contaminate every regime-conditioned result.

**B6 — Sector-exclusion attribution.** **Full re-rank.** Remove the sector from the universe at each formation date and recompute winsorization, cross-sectional z-scores, category scores, ranking, and deciles from scratch. Removing names from the P&L while holding the original ranking fixed is the weaker test and is not what §9 requires.

---

## 3. Conventions (C1–C11)

Approved as proposed, with **C3 and C4 amended**:

| # | Convention |
|---|---|
| C1 | F1's universe benchmark = cross-sectional **mean** of individual window returns, over the eligible universe as constituted at T (fixed membership, measured backwards) |
| C2 | F4a sector benchmark **excludes self**; requires ≥10 eligible names in the sector, else the security is excluded at that date |
| C3 | **AMENDED:** Sector taxonomy = **Sharadar `TICKERS.sector`**, not GICS. Non-point-in-time contamination disclosed per §4 of the protocol. Bucket count reported. |
| C4 | **AMENDED:** F4b benchmark = **S&P 500 total return** (SPXTR, or SPY total return if unavailable) — **not** the price index. Rationale: F1 and the securities' own returns are total-return based; subtracting a price-return benchmark would build in a systematic tilt toward high-dividend names. Both sides of every comparison must use the same return basis. |
| C5 | Realized volatility = standard deviation of **daily log returns**, `ddof=1`, not annualized (cancels in the ratio) |
| C6 | ATR(14) = **Wilder's smoothing**, standard true range |
| C7 | Data lake loads from 2004-01-01; first formation date 2005-01-03. §9's "200 trading days after start of available data" refers to the **data lake**, not the in-sample period |
| C8 | Costs = 10 bps per side applied to **realized one-way turnover**, on **both legs** of the spread |
| C9 | Annualization = **geometric**, 12.6 periods/year |
| C10 | Deciles = equal-count by rank, `method='first'` on ties, after a deterministic secondary sort on `security_id` |
| C11 | Excess-return median computed over the **post-filter, post-missing-data eligible** universe at T |

---

## 4. Observations Acknowledged, Implemented As Written

Recorded so that none is later mistaken for a bug or used as post-hoc justification.

1. **The true cost hurdle.** 20 bps round trip at full turnover is ~2.5% annualized per leg; the decile spread carries two legs, so ~5% at 1× and ~10% at 2×. §10's PASS criteria therefore require roughly **9% gross annualized spread at 1×** and **~12% gross** to clear the 2× fragility check. Realized turnover below 100% lowers this — a realistic hurdle is **7–8% gross**. This is a demanding bar for a four-factor price composite, and it is acknowledged **before** results exist.
2. **−30% understates NASDAQ delistings.** Shumway (1997) estimates ~−30% for NYSE/AMEX; Shumway & Warther (1999) estimate roughly −55% for NASDAQ. The protocol specifies a flat −30%. Implemented as written; the direction of the resulting bias (understating losses on NASDAQ delistings, i.e. flattering results) is disclosed with every result.
3. **Category equal-weighting is not equal risk-weighting.** The variance of a two-z-score average depends on the correlation between its components, so F1 (two highly correlated momentum windows) receives more effective weight than 0.25. Implemented literally as specified.
4. **Adjustment factors and level filters.** Cumulative split/dividend adjustment factors do not create lookahead in *returns* (the factor cancels in any within-window ratio) but do in *level* quantities. The $5 price filter and the $1B market cap filter must therefore use **as-of-date unadjusted** prices. The lookahead auditor enforces this specifically.

---

## 5. Expected Outcome, Stated Before Results

The most probable outcome of Experiment #001 is **INCONCLUSIVE** — a small but real information coefficient, with a decile spread insufficient to clear the cost hurdle in §4.1 above.

This is recorded now so that, if it happens, the §10 routing is followed rather than relitigated. **The cost model in §8 is not reopened after results are seen.** Any argument that costs were set too conservatively, made after the numbers are visible, is motivated reasoning and is pre-emptively rejected here.

---

## 6. Repository

`~/apex-equities`. `~/apex` is an unrelated project and is not to be modified.

Both the protocol and this document are committed and SHA-256 pinned before the first data load. The pinned hashes are recorded in the header of each results run.

---

## 8. Experiment #002 Registration (added 2026-08-11)

**APEX-002 — Net Share Issuance.** SIGNED and FROZEN 2026-08-11, Author Derek Duenas.

**Governs:** `APEX-002-Protocol-Net-Share-Issuance.md`, SHA-256 `63703d1020893a59a4b43ed9698c4920ccb392e7f76bc77030ef019693ea9bda`

APEX Research Protocol v1.0 is inherited unchanged for the timing firewall, the
§3 universe, the cost model and the evaluation machinery. #002 adds one
cross-sectional ranking variable and nothing else. Experiment #001 is closed and
is not affected by this registration.

---

## 9. Experiment #003 Registration (added 2026-08-13)

**APEX-003 — Gross Profitability.** SIGNED and FROZEN 2026-08-13, Author Derek Duenas.

**Governs:** `APEX-003-Protocol-Gross-Profitability.md`, SHA-256 `6d3bebedf911cc4dfa8ebeb35394762cba8758af91aa1b430b76ff136b34697c`

Inherited unchanged: timing firewall, §3 universe, cost model, evaluation
machinery, §13 success criteria (t >= 2.92 validation / 2.88 holdout, read from
config). #003 adds one HIGHER-is-better ranking variable
(`prof_gross_profitability` = gp/assets, as-filed ARQ) and nothing else.
Experiments #001 and #002 are closed and are not affected.

Binding constraint carried from the specification: the twelve-month measurement
window and the corporate-action exclusion rule **may not be altered after any
predictive result is observed**.

The measurement-coverage gate that preceded freezing established measurability
only — 3.04% excluded by corporate actions, 88.7% with four-quarter PIT history,
3,743–5,107 securities per year. It tested no predictive power. #002's
hypothesis is entirely untested.

---

## 10. Experiment #004 Registration (added 2026-08-13)

**APEX-004 — Small-Cap Gross Profitability.** SIGNED and FROZEN 2026-08-13, Author Derek Duenas.

**Governs:** `APEX-004-Protocol-Smallcap.md`, SHA-256 `13eb9f8b30033f287696d72457fdc62b17cbe444ec6270b0d2a5e4383f08639b`

The ONE experimental change vs #003 is the §3 universe: market cap in
[$100M, $2B) (ceiling exclusive), 60-day ADDV >= $1M, close >= $2. The signal,
timing, estimator and evaluation machinery are #003's, via the SAME certified
execution path (`apex.experiments.apex003`). The §13 bar is the STRICTER
legacy t >= 2.92 (true size 0.872% under the §8a-derived null; the exact-1%
bar was 2.85 and the operator chose 2.92 on the record). Provenance:
descendant-of-failure CONTESTED, RULED ADMISSIBLE 2026-08-13
(`SMALL-CAP-JUSTIFICATION.md`); the disclosure is retained, not erased.
Experiments #001–#003 are closed and are not affected.

---

## 7. Amendment Log

| Date | Item | Change | Reason | Before/after results |
|---|---|---|---|---|
| 2026-08-15 | A-009 — segmented holdout capacity | Holdout capacity expanded via independence classes (II segment ρ̄-floor 0.50 / III geo 0.20 / IV asset 0.20 / V period 0.30, currently empty), priced by N_eff(k,ρ̄)=k/(1+(k−1)ρ̄) with charge floor 0.25 and ρ̄=0.7 unmeasurable default; budget 5→8 with AUTOMATIC in-code reversion to 5 if pricing is inoperative; sum-of-charges governs budget, N_eff governs multiplicity, both always together; verdicts carry class+ρ̄+ΔN_eff inline; ρ̄ measurement leak-suppressed; naming irrevocable; burn programme-wide. **Composition sentence added at signing**: an experiment costs its A-003 credit including its named holdout; §3 pricing governs additional holdout evaluations of the same validated strategy, k per-strategy. Full text: `CONVENTIONS-AMENDMENT-A-009.md`. | Idea supply is unbounded; confirmation capacity was one. Fresh out-of-sample draws exist but are not equally independent; counting a correlated segment as an independent confirmation would manufacture the fake precision §34.7 prohibits. | **BEFORE** any Class II–V holdout is defined or priced. |
| 2026-08-15 | A-010 — standalone #004 holdout | APEX-004's holdout evaluation (Class I primary, US small-cap 2022-01-01→2026-06-30) is conducted STANDALONE before any full-stack registration. Already purchased under A-003 (audit 1.1); no new credit. Frozen protocol exactly as written, bar t ≥ 2.88 unchanged; pre-flight (pin, chain, auditor) aborts before the token; result recorded whatever it is; holdout burns programme-wide on completion. Full text: `CONVENTIONS-AMENDMENT-A-010.md`. A-009 (segmented capacity) remains UNSIGNED pending its §3.1 composition sentence; identifier reserved. | Attribution requires a confirmed signal-level anchor; holdout-hoarding is named as a governance failure mode — an unopened holdout is an option, not evidence. | **BEFORE** any full-stack experiment registration. |
| 2026-08-13 | A-008 — §10, #004 registration | APEX-004 pre-registration SIGNED (Registered 2026-08-13, Author Derek Duenas) and FROZEN; SHA-256 `13eb9f8b…` pinned in the new §10. Universe flipped in config to the registered small-cap band; §13 bar kept at the STRICTER 2.92 after the §8a derivation produced 2.85. Gate ruling and dry-run certification (digest 3daebc37…, twice bit-for-bit) both PRECEDED registration. Experiments #001–#003 and their closed results untouched. | A pre-registration must be signed and pinned to be one; the descendant-of-failure ruling had to be on the record before the signature, not after. | **BEFORE** any #004 predictive result. |
| 2026-08-13 | A-007 — §9, #003 registration | APEX-003 pre-registration SIGNED (Registered 2026-08-13, Author Derek Duenas) and FROZEN; its SHA-256 pinned in the new §9. Dry run PASSED twice bit-for-bit (digest 18b2dee8…) BEFORE registration. Experiments #001/#002 and their closed results untouched. | A pre-registration must be signed and pinned to be one; certification preceded registration per the INCIDENT-001 lesson. | **BEFORE** any #003 predictive result. |
| 2026-08-11 | A-006 — §8, #002 registration | APEX-002 pre-registration SIGNED and FROZEN; its SHA-256 `63703d1020893a59…` pinned in the new §8. Experiment #001, its protocol and its closed result are untouched. | A pre-registration must be signed and pinned to be one. Recorded before implementation begins and before any #002 predictive analysis. | **BEFORE** any #002 result. |
| 2026-08-11 | A-005 — §1, SF1 scope | `SF1` permitted for **APEX-002 only**, and only for as-filed shares outstanding (`sharesbas`/`sharewa`) keyed on `datekey`. Experiment #001 is closed and unaffected. No other fundamental field is unlocked for any experiment. | The #002 measurement audit established that `DAILY.marketcap` carries no vintage — 100% of rows were rewritten after their own date, median 1,246 days — so a share-count DIFFERENCE derived from it may embed restatements. Restatements concentrate in firms with accounting problems, which is plausibly correlated with subsequent returns, making this a lookahead channel pointed at the dependent variable. §4 requires shares "as known at formation date". SF1's `datekey` is the filing date and is the only as-filed source available. | **BEFORE** #002 is registered, and before any #002 predictive analysis of any kind. |
| 2026-08-11 | A-004 — signature + re-pin | Pre-registration SIGNED (Registered 2026-08-11, Author Derek Duenas). Signing edits the protocol file, so its SHA-256 necessarily changes; the CONVENTIONS pin is updated from `a569c718b39b9cac…` to `8f3396f70cf426a7…`. **No clause, threshold, feature, filter or statistical rule was altered — only the two signature fields.** | A pre-registration must be signed to be one, and the pin must track the signed document. | **BEFORE** any validation or holdout result. |
| 2026-08-09 | A-001 — §2 B2, evaluation | None to the protocol or to this document. Recorded for completeness: the pre-registered Newey-West Bartlett lag-25 estimator was measured to be over-dispersed on the MA(19) autocorrelation that overlapping 20-day windows produce (Bartlett weight at lag 19 is 0.27, discarding ~73% of the relevant autocovariance). sd(t) ≈ 1.21 and the pre-registered `t ≥ 2.5` hurdle carries a **true one-sided size of ~1.9%** against 0.621% nominal. **The protocol is NOT amended**: Bartlett-25 and t ≥ 2.5 both stand exactly as written. The true size is a **disclosed property** reported with every result, and a simulation-calibrated reference distribution is used for **test-harness calibration and for interpretation only** — never as a pass/fail criterion. | Ruling: do not repair a pre-registered statistic after measuring its properties. Disclosure preserves both integrity and interpretability; retroactive correction would destroy the first to buy the second. | **BEFORE** any result. Holdout unopened; validation unopened. |
| 2026-08-09 | A-002 — §1, data vendor | Sharadar **confirmed primary and authoritative for all universe filters**. Norgate admitted as **optional secondary for prices and cross-check only**, never authoritative for a universe filter, shares outstanding, market cap, or identity. An earlier working design that made Norgate the identity spine is **withdrawn**. | Point-in-time market cap is non-negotiable for §3's ≥$1B filter, and Norgate does not supply it. A clean PIT implementation outranks convenience or prior preference. | **BEFORE** any result and before any data load. |
| 2026-08-09 | A-003 — §7 holdout usage | Clarification, not a change. Protocol §7 stands: **one holdout evaluation per experiment, never reused.** The "five" figure is a budget of **five separate pre-registered experiments**, each with its own validation pass and one and only one holdout evaluation. There is **no shared holdout reuse across hypotheses.** Family-wise error inflation across the programme is tracked in the research ledger, not absorbed by re-looking at the same holdout. | Separates experiment validity (governed by the protocol) from programme-level inference (governed by the ledger). | **BEFORE** any result. |
