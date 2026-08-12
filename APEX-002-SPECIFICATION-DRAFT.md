# APEX Experiment #002 — Net Share Issuance
## Research Specification (DRAFT — unsigned, unregistered)

**Status:** awaiting approval. Not a pre-registration until signed and hash-pinned.
**Credit:** would be 2 of 5. **Not spent.** Holdout sealed. No predictive analysis performed.

---

## 1. Economic hypothesis

Companies that reduce share count through net repurchases outperform companies
that aggressively issue equity, because net share issuance carries information
about managerial capital allocation, financing need, valuation, and future
dilution.

**Direction (fixed):** lower net share issuance → higher expected subsequent
return. A significant *negative* result is a FAILED experiment, not a
discovered reversal.

## 2. Exact economic definition

The quantity is: **the proportional change in the number of common equity claims
outstanding attributable to deliberate corporate financing activity** —
issuance, secondary offerings, option exercise and stock compensation on one
side; open-market and tender repurchases on the other.

It excludes changes in the share count that create or extinguish no claim on the
same underlying business: splits, reverse splits, stock dividends, spin-offs,
merger consideration, acquisitions for stock, share-class conversions, and
recapitalisations.

## 3. Accounting identity, and the decisive measurement fact

    S_adj(t) = S_filed(t) x K(t)

where `K(t)` is Sharadar's cumulative split-rebasing factor.

**[MEASURED 2026-08-11] `sharesbas` is retroactively rebased to the CURRENT
split basis.** AAPL's 2013-06-29 ARQ row reports 25,437,916,000 shares — the
~900M actually filed, multiplied by the subsequent 7:1 (2014) and 4:1 (2020)
splits. No jump appears at either split; the series declines smoothly at the
buyback rate. `sharefactor` is 1 throughout and does NOT carry the adjustment.

Two consequences, and they point in opposite directions:

**(a) It solves the split problem exactly.** Because the entire history is on one
basis, `K` is constant across any window and cancels in a ratio:

    S_adj(t)/S_adj(t-w) = [S_filed(t) K] / [S_filed(t-w) K] = S_filed(t)/S_filed(t-w)

Splits and reverse splits need NO ACTIONS-based neutralisation. The vendor has
already removed them, more reliably than a hand-rolled adjustment would.

**(b) It forbids any level-based measure.** `K(t)` embeds splits that occur
AFTER the formation date. The stored LEVEL is therefore contaminated by future
information. A signal using share-count levels, or shares scaled by anything not
on the same rebased basis, would be a lookahead violation.

**Therefore the measure MUST be a pure ratio of two rebased share counts.** This
is not a stylistic preference; it is the only form the data permits.

## 4. Share-count variable

Available: `sharesbas`, `shareswa`, `shareswadil`, `sharefactor`.
(`sharewa` does NOT exist on this API; `shareswa` is the weighted-average field.)

**Selected: `sharesbas`.**

`sharesbas` is the count of shares outstanding as of the filing. It measures
claims outstanding, which is the economic object. `shareswa` and `shareswadil`
are period-average and diluted EPS denominators: they smooth across the period,
lag the actual count, and `shareswadil` further contaminates the measure with
option-dilution accounting that is not an issuance event. The literature on the
issuance anomaly (Pontiff & Woodgate 2008; Daniel & Titman 2006; Fama & French
2008) measures shares outstanding, not the EPS denominator.

Quality: 99.97% non-null, **100.00% integer-valued**, 770 zero/negative to
exclude, 488,635 ARQ rows, 13,126 tickers, 2004-01-02..2026-06-30.

## 5. Point-in-time construction

1. Restrict to `dimension == "ARQ"` (as-reported quarterly).
2. **For each `(ticker, reportperiod)`, the AS-FILED observation is the row with
   the EARLIEST `date`.** 3.45% of pairs carry multiple ARQ rows because Sharadar
   RETAINS revisions rather than overwriting. A `last()` or `max(date)` selects
   the RESTATED figure and is PROHIBITED.
3. Admit an observation into the information set only where `date <= T`, the
   formation date. `date` is the filing date — verified across all 488,635 ARQ
   rows: `date - reportperiod` p1=23, p50=41, p90=83 days.
4. Discard the 17 rows (0.0035%) where `date <= reportperiod`; a filing cannot
   precede its own period end.
5. Resolve `ticker -> permaticker` DATE-AWARE via `TICKERS.firstpricedate` /
   `lastpricedate`, the same join already used for SEP and DAILY. SF1 is keyed
   by ticker and tickers are recycled.
6. At formation date T, a security's information set is the set of as-filed
   observations with `date <= T`. The most recent such observation is current;
   it is superseded only when a later filing's `date` passes T.

## 6. Corporate-action treatment (deterministic)

| Action | Economic issuance? | Moves observed shares? | Treatment |
|---|---|---|---|
| split, reverse split, adrratiosplit | No | **No** — already rebased | None required (verified §3) |
| stock dividend | No | No — rebased identically | None required |
| spinoff / spunofffrom / spinoffdividend | No | Yes | **EXCLUDE** security for any window spanning the action date |
| acquisitionby / acquisitionof | No | Yes | **EXCLUDE** for any window spanning the action date |
| mergerto / mergerfrom | No | Yes | **EXCLUDE** for any window spanning the action date |
| conversion / recapitalisation | No | Yes | **EXCLUDE** for any window spanning the action date |
| ambiguous or unclassified action | Unknown | Unknown | **EXCLUDE** — never assume benign |

Rule: if any ACTIONS record of an excluding type falls in `(T-w, T]` for the
security, the signal is NOT computed for that security at T. Exclusion, never
adjustment — a share exchange has no defensible issuance interpretation, and
inventing one would be exactly the convenient proxy this specification forbids.

Measurement support: 22,161 contaminating records; all nine types present in
ACTIONS. Independently, 1.77% of quarter-on-quarter `sharesbas` changes exceed
|50%|, consistent with mechanical events surviving the split rebasing.

## 7. Measurement window

**Exactly twelve months: four consecutive quarterly ARQ observations.**

Justified on: the annual horizon is the literature standard (Pontiff & Woodgate;
Daniel & Titman; Fama & French use annual issuance); it matches the reporting
cadence with four observations; buyback and issuance programmes are authorised
and executed over multi-quarter horizons, so an annual window captures policy
rather than quarter-end noise; and a longer window loses PIT-eligible securities
while a shorter one is dominated by option-exercise seasonality.

Requirement: an as-filed observation at T and another with `reportperiod`
approximately 12 months earlier, both with `date <= T`, the earlier one being the
nearest available in `[T-15mo, T-9mo]`. If either is unavailable, the security is
excluded at T. No interpolation, no forward-fill across the boundary.

## 8. Exact formula

    NSI(i, T) = ln( S(i, q0) / S(i, q-4) )

where `S(i, q)` is `sharesbas` from the AS-FILED ARQ observation, `q0` is the
most recent reportperiod whose filing `date <= T`, and `q-4` is the observation
nearest 12 months earlier within `[T-15mo, T-9mo]` and also filed by `T`.

* Numerator / denominator: rebased share counts, same basis, factor cancels
* Units: dimensionless log ratio. **No annualisation** (the window is already 12mo)
* Scaled, not absolute — required by §3(b)
* Negative NSI = net repurchase; positive = net issuance; zero = unchanged
* **Extreme values: retained, not clipped.** No winsorisation. A genuine 300%
  issuance is information, not an outlier, and clipping after inspecting the
  distribution is the fitting behaviour this project exists to prevent.
* Log form chosen so repurchase and issuance of equal proportional size are
  symmetric; a simple percentage is bounded below at -100% and unbounded above.

## 9. Ranking

* Signal direction: **ascending** — lowest NSI (largest net repurchase) = rank 1
  = top decile. This encodes the pre-registered direction.
* Cross-sectional, per formation date, over the eligible universe at T only
* Ties: `method='first'` after a deterministic sort on `security_id` (C10)
* Missing: excluded from the cross-section at that date; never imputed
* Minimum 30 eligible names for a ranked date (existing `min_names_for_ic`)
* **No winsorisation, no clipping, no sector-neutralisation, no size-neutralisation**
* Deciles: equal-count, 1..10 (existing machinery)
* Rebalance: every 20 trading days on the existing locked grid
* Formation T, entry T+1, exit T+21 — unchanged from the frozen timing firewall

## 10. Universe interaction

**The frozen §3 universe is UNCHANGED.** Exchange, security type, REIT
exclusion, $1B market cap, $10M ADDV, $5 close, 252-day history, level filters
on unadjusted prices, survivorship — all as already implemented and audited.

**The signal is computed AFTER §3 eligibility**, on the eligible cross-section
only. NSI is an additional ranking variable, not a universe definition. A
security failing §3 is absent regardless of its NSI; a security lacking a
computable NSI is absent from the ranking at that date but remains eligible at
later dates (the existing `missing_feature` path).

## 11. Missing and ambiguous observations

Excluded at the formation date, never imputed:

* `sharesbas` missing, zero, or negative (770 rows)
* fewer than the two required as-filed observations within the window
* `date <= reportperiod` (17 rows — impossible filings)
* an excluding ACTIONS record within `(T-w, T]`, or any ambiguous action
* `ticker -> permaticker` resolving to zero or to more than one security
* conflicting as-filed rows sharing an identical earliest `date` for one
  `(ticker, reportperiod)` — unresolvable, therefore excluded

Exclusion counts are reported per formation date alongside the existing §9 log.

## 12. Information-set transition (worked)

Given FY2020 filed 2021-03-15 and FY2021 filed 2022-03-15:

| Formation date | Most recent as-filed observation available |
|---|---|
| 2020-12-31 | FY2019 (FY2020 not yet filed) |
| 2021-02-28 | FY2019 |
| 2021-03-31 | **FY2020** (filed 03-15, now public) |
| 2021-12-31 | FY2020 |
| 2022-03-31 | **FY2021** |

The fiscal-period label never determines availability. `date` does. On
2021-02-28 the FY2020 figure exists in the vendor table and is invisible to the
experiment.

## 13. Success / failure / invalidity

**SUCCESS** — mean IC positive, Newey-West t (Bartlett-25) ≥ the one-sided
α = 1% critical value from the simulated null at that period's length
(≈2.92 validation, ≈2.88 holdout), and the non-overlapping robustness test
agrees in sign.

**FAILURE** — measurable and complete, but the threshold is not met, or the
result is directionally negative. Experiment closed; specification NOT adjusted
and re-run.

**INVALID (0 credits)** — the hypothesis cannot be validly tested: PIT
information unestablishable, corporate-action contamination unresolvable, the
accounting identity inadequate, precision inadequate, identity unestablishable,
or observations unconstructible without lookahead.

## 14. Alternatives considered and rejected

| Alternative | Rejected because |
|---|---|
| `shareswa` / `shareswadil` | EPS denominators. Period-averaged, lag the actual count, and dilution accounting is not an issuance event. |
| Simple % change `(S0-S-4)/S-4` | Asymmetric: bounded at -100%, unbounded above. Log form treats equal proportional issuance and repurchase symmetrically. |
| Share-count LEVEL or level-scaled measure | **Prohibited by §3(b)** — the rebasing factor embeds future splits. Lookahead. |
| Issuance scaled by market cap | Mixes a rebased share count with a price-based denominator on a different basis; reintroduces the level problem and adds valuation, which is a different hypothesis. |
| Change vs *average* shares over the window | No accounting identity advantage; adds a smoothing parameter with no theoretical basis. |
| Quarterly (3-month) window | Dominated by option-exercise and compensation seasonality; measures timing noise rather than capital-allocation policy. |
| Multi-year (3-5yr) window | Literature-supported, but loses PIT-eligible securities and blends distinct policy regimes. One window must be chosen ex ante; 12 months is the modal choice in the cited literature. |

Selection made on accounting identity, economic meaning, academic precedent, PIT
integrity, measurement error and corporate-action treatment. **No formulation was
compared empirically.**

## 15. Pre-registration language

> Experiment #002 tests whether the cross-sectional rank of twelve-month net
> share issuance, measured as the natural log ratio of as-filed basic shares
> outstanding (`SF1.ARQ.sharesbas`, earliest filing `date` per ticker and
> reportperiod, admitted only where `date <= T`), predicts forward 20-trading-day
> excess returns among securities eligible under the frozen §3 universe.
> Securities experiencing a spin-off, merger, acquisition, conversion or
> recapitalisation within the measurement window, or any ambiguous corporate
> action, are excluded. Securities are ranked ascending, so the largest net
> repurchasers occupy the top decile. No winsorisation is applied. The
> hypothesis is directional: lower net issuance predicts higher subsequent
> return. The experiment succeeds only if the mean daily cross-sectional
> Spearman IC is positive with a Newey-West (Bartlett, lag 25) t-statistic at or
> above the one-sided α = 1% critical value derived from the simulated null at
> the evaluation period's observation count, and the non-overlapping robustness
> test agrees in sign. All other protocol elements — timing firewall, universe,
> cost model, evaluation machinery — are inherited unchanged from APEX Research
> Protocol v1.0.

---

## VERDICT

**READY TO PRE-REGISTER**

with one constraint recorded above as binding rather than advisory: the measure
must be a ratio of two rebased share counts. `sharesbas` is retroactively
split-rebased, so any level-based construction embeds post-formation splits and
is a lookahead violation. The ratio form is not a preference — it is the only
construction the data admits.
