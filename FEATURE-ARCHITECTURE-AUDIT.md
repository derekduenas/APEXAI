# APEX Feature / Alpha Architecture Audit

**Date:** 2026-08-12
**Scope:** inventory, redundancy, gaps, research directions
**Credits consumed:** zero · **Registry modified:** no · **Screens run:** none
**Evidence:** `results/feature_library_audit.txt`, in-sample only (2005-01-01 →
2017-12-31), feature-to-feature correlations, no forward returns anywhere

APEX-002's validation result was not consulted in producing this document.

---

## 0. The premise needs correcting first

The brief assumed a rich feature library — "if you've got 40 features but 15
are basically different transformations of momentum". The actual library is:

```
APEX-001 components   8   ALL derived from price/volume
APEX-002 features     1   nsi (share count)
TOTAL implemented     9
```

There is no valuation feature, no profitability feature, no growth feature, no
quality feature, no liquidity feature, no accrual feature, and no
attention/positioning feature in the codebase. The `SF1` table carries roughly
100 fundamental fields; **one** of them (`sharesbas`) is used by anything.

The concern behind the brief was right, but it understated the case: it is not
that some features duplicate each other. It is that eight of the nine come from
one data series.

## 1. Feature inventory

Coverage is on the §3-eligible cross-section, 198,944 security-dates,
164 formation dates.

| Feature | Definition | Source | PIT | Timing | Interpretation | Direction | Coverage |
|---|---|---|---|---|---|---|---|
| `f1_mom_126` | 126d skip-adjusted return − universe mean | SEP `closeadj` | yes, prices are as-traded | close T, skip 5d | medium-horizon momentum | higher better (#001) | 100.00% |
| `f1_mom_63` | 63d skip-adjusted return − universe mean | SEP `closeadj` | yes | close T, skip 5d | short-horizon momentum | higher better | 100.00% |
| `f2_close_over_sma200` | close ÷ SMA200 | SEP `closeadj` | yes | close T | trend position | higher better | 100.00% |
| `f2_frac_above_sma50` | fraction of last 63d closed above SMA50 | SEP `closeadj` | yes | close T | trend persistence | higher better | 100.00% |
| `f3_vol_ratio` | 20d vol ÷ 100d vol | SEP `closeadj` | yes | close T | volatility compression | **lower** better (negated, B1) | 100.00% |
| `f3_atr_over_close` | Wilder ATR(14) ÷ close | SEP `high/low/close` | yes, requires adj factor | close T | volatility level | **lower** better (negated) | 100.00% |
| `f4_vs_sector` | 63d skip return − sector mean (ex-self, ≥10 names) | SEP + TICKERS `sector` | yes | close T, skip 5d | sector-relative strength | higher better | 100.00% |
| `f4_vs_market` | 63d skip return − SPY total return | SEP + SFP | yes | close T, skip 5d | market-relative strength | higher better | 100.00% |
| `nsi` | ln(S_t ÷ S_t−4q) on as-filed `sharesbas` | SF1 ARQ | **yes, by filing date** | filing ≤ T | net share issuance | **lower** better (#002 §9) | 97.69% |

**Transformations already applied.** All eight #001 components are winsorized
at 1%/99%, z-scored, and percentile-ranked by `composite.build_scores`; `f3`'s
two components are sign-negated (CONVENTIONS B1). `nsi` receives **none** of
these — #002 forbids them — and is percentile-ranked only.

## 2. Redundancy — the material finding

### `f1_mom_63` and `f4_vs_market` are the same feature

Measured cross-sectional Spearman correlation: **+1.000**, and it is +1.000
*by construction*, not by coincidence:

```
f1_mom_63   = raw_63 − universe_mean(raw_63)     ← per-date scalar
f4_vs_market = raw_63 − benchmark_return          ← per-date scalar
```

Both start from the same 63-day skip-5 adjusted return (`f1.windows: [126, 63]`,
`skip_days: 5`; `f4.window: 63`, `skip_days: 5`). Subtracting a **per-date
scalar** cannot change a cross-sectional ranking, and every downstream step in
#001 is cross-sectional. The two components are rank-identical on every date.

`f4_vs_sector` is not identical — sector demeaning is not a global scalar — but
sits at **+0.920** with both.

**Consequence for #001, which is CLOSED and stays closed.** Its composite
weighted four categories at 0.25 each. The 63-day momentum series entered
through `f1` (0.125 of the composite) *and again* through `f4` (0.125), with
`f4_vs_sector` a near-copy at 0.92. The "four-factor" composite was
substantially fewer than four factors. This does not reopen APEX-001, does not
change its recorded INCONCLUSIVE verdict, and is recorded here only because any
future multi-signal work would inherit the same components.

### The price block collapses to roughly two dimensions

| Pair | ρ |
|---|---|
| f1_mom_63 ↔ f4_vs_market | **+1.000** |
| f4_vs_market ↔ f4_vs_sector | +0.920 |
| f1_mom_63 ↔ f4_vs_sector | +0.920 |
| f1_mom_126 ↔ f2_close_over_sma200 | +0.887 |
| f2_frac_above_sma50 ↔ f4_vs_market | +0.779 |
| f2_close_over_sma200 ↔ f2_frac_above_sma50 | +0.719 |
| f1_mom_126 ↔ f1_mom_63 | +0.664 |

Six of the eight #001 components — `f1_mom_126`, `f1_mom_63`,
`f2_close_over_sma200`, `f2_frac_above_sma50`, `f4_vs_sector`, `f4_vs_market` —
form one correlated block (ρ 0.62 to 1.00). They are trend/momentum measured at
different lookbacks and against different baselines.

The two `f3` components sit apart (|ρ| ≤ 0.18 against the block) and apart from
each other (+0.18). Volatility level and volatility *change* are close to
independent inputs.

### `nsi` is genuinely distinct

| | ρ with nsi |
|---|---|
| f1_mom_126 | +0.049 |
| f1_mom_63 | +0.014 |
| f2_close_over_sma200 | +0.042 |
| f2_frac_above_sma50 | −0.012 |
| f3_vol_ratio | −0.008 |
| f4_vs_market | +0.014 |
| f4_vs_sector | +0.018 |
| **f3_atr_over_close** | **+0.287** |

Largest absolute correlation with any #001 component: **0.287**, against
ATR/close. Higher-volatility names issue more equity — economically
unsurprising, and worth remembering as the one place #002's input overlaps
#001's. Against the entire momentum/trend block, `nsi` is orthogonal to three
decimal places.

**This is a statement about inputs, not about predictive power.** It says the
two experiments asked different questions. It says nothing about whether either
question has a useful answer.

## 3. Effective dimensionality of the current library

| Block | Members | Distinct information |
|---|---|---|
| Trend / momentum | 6 components | ~1, possibly 2 (short vs medium lookback, ρ 0.66) |
| Volatility | f3_vol_ratio, f3_atr_over_close | ~2 (mutually ρ +0.18) |
| Corporate capital allocation | nsi | 1 |

**Nine implemented features carry roughly four independent dimensions**, and
three of the four come from the price series.

## 4. Alpha-family map — implemented versus available

| Family | Implemented | Data present in the snapshot | Status |
|---|---|---|---|
| Momentum / price behaviour | 6 components | SEP | **over-represented, heavily redundant** |
| Volatility / risk | 2 components | SEP high/low/close | present, thin |
| Corporate actions / capital allocation | nsi | SF1 `sharesbas`, `ncfcommon`, `ncfdiv`, `sbcomp`; ACTIONS (487k dividends, 8.8k splits, 5.7k acquisitions, 468 spinoffs) | **1 of many** |
| Valuation | **none** | SF1 `pb pe ps evebit evebitda`, DAILY same | **empty** |
| Profitability / quality | **none** | SF1 `gp roa roe roic netmargin grossmargin ebitdamargin` | **empty** |
| Growth | **none** | SF1 `revenue assets equity capex rnd` (as-filed, differenced) | **empty** |
| Fundamental change / accruals | **none** | SF1 `netinc`, `ncfo`, `receivables`, `inventory`, `payables`, `depamor` | **empty** |
| Liquidity | **none** | SEP `volume` × price, `sharesbas` for turnover | **empty** |
| Investor behaviour / attention | **none** | **no short interest, no 13F, no options, no analyst estimates, no news** | **not constructible** |
| Leverage / solvency | **none** | SF1 `debt de currentratio workingcapital` | **empty** |

## 5. Gaps

**Gap 1 — the library is one data series.** Eight of nine features derive from
`closeadj`. Any multi-signal model built today would be a momentum model with
two volatility terms and one share-count term.

**Gap 2 — no fundamental valuation, quality, growth or accrual feature
exists.** These are the best-documented non-price return regularities in the
published literature, the data is present and PIT-capable, and none is
implemented.

**Gap 3 — attention and positioning are not constructible from this vendor.**
No short interest, no institutional holdings, no options, no analyst estimates,
no news or search volume. Volume-derived proxies (turnover, Amihud illiquidity,
volume shocks) are the only members of that family the snapshot can support,
and they are proxies for attention, not measures of it.

**Gap 4 — earnings *announcement* dates are absent.** SF1 carries the filing
date, which #002 correctly used as the knowledge date. A 10-Q filing typically
*follows* the earnings press release, so any post-earnings-announcement-drift
construction here would be measuring drift from the wrong event, later than it
occurred. This is a real constraint on the whole underreaction family.

**Gap 5 — the redundancy discovered above is not detected by anything.**
Nothing in the codebase would have flagged that two registered components are
rank-identical. A future composite could re-introduce the same duplication.

**Gap 6 — no feature-level PIT audit exists.** #002's PIT correctness is
measured (`known_from_out`); #001's price features are PIT by construction but
unmeasured; any fundamental feature would need the same as-filed discipline
`nsi` established, and that machinery is currently specific to `nsi`.

## 6. Research directions

Directions, not candidate experiments. None is a proposal, none has been
screened, and none is ranked by any performance expectation.

**D1 — Feature independence as infrastructure, not as an experiment.**
Make redundancy detectable. A registered feature that is rank-identical to
another should be impossible to add silently. This costs no credit, is not a
hypothesis, and is a precondition for any honest multi-signal work.

**D2 — Fundamental valuation as an independent family.** The largest empty
cell with the strongest published support and fully PIT-capable data. Its
independence from the existing library is an empirical question answerable
in-sample without a credit.

**D3 — Profitability / quality as an independent family.** Same argument.
`gp/assets` in particular is computable from as-filed SF1.

**D4 — Accruals and fundamental change.** `netinc − ncfo` scaled by assets;
asset growth; net operating assets. All differenced from as-filed data, all
requiring the earliest-filing discipline `nsi` already implements.

**D5 — Liquidity and turnover.** Constructible from SEP volume and `sharesbas`.
Note the audit found breadth-related structure in #002's post-mortem; that
observation must **not** be the justification for this direction, or it becomes
a post-hoc modification of #002 (see §7).

**D6 — Capital allocation beyond share count.** Dividends, buybacks via
`ncfcommon`, stock-based compensation, capex intensity. Adjacent to #002 and
therefore the direction most at risk of being a #002 variant rather than a new
question.

**D7 — Volatility as its own family rather than a composite ingredient.** The
two `f3` components are the least redundant things in the current library and
have never been tested standalone.

**D8 — Combining independent families.** The eventual objective, and the one
that must come last. It is only meaningful once at least two families have
independently demonstrated something, and it multiplies the multiple-comparisons
problem by the number of combinations considered. Not reachable with the
current library, because the current library is one family with two
appendages.

## 7. Post-hoc contamination risk

Any direction justified by something learned from APEX-002's result inherits
#002's degrees of freedom. Specifically:

- **D5 (liquidity/breadth) is contaminated if motivated by the post-mortem.**
  The post-mortem found IC concentrated in high-breadth dates. Using that to
  motivate a breadth-conditioned hypothesis is #002's failed result selecting
  the next question. If the direction is worth pursuing it must be justified
  from economics and prior literature, independently.
- **D6 (capital allocation) is the closest neighbour to #002.** A dividend or
  buyback signal is a different mechanism from share-count change, but the line
  is thin, and a registration would need to state explicitly why it is a new
  hypothesis rather than NSI with a different numerator.
- **D1, D2, D3, D4, D7 carry no #002 contamination.** They were identifiable
  from the data schema alone, before any result existed.

## 8. What this audit did not do

Rank features by performance. Search for a combination. Optimise a parameter.
Consult APEX-002's validation result. Access validation or holdout data.
Compute a forward return. Create, propose, or screen APEX-003. Consume a
credit.
