# EXP-004 — OHLCV pressure proxy: does body–volume alignment add forecasting information?

**Specification for independent review. Design only.** No historical reads, no
fitting, no scoring, no registration, no implementation, no sealed-data opening.
Supersedes `EXP004_METAORDER_STATE_PROPOSAL.md`, whose feature algebra and
comparator structure were wrong.

Business objective is unchanged and options-only. This brick proposes **one
candidate forecasting input**, not a regime engine, not a trading system.

---

## 1. Observations, hypotheses, and what this dataset can reach

**Working description: an OHLCV pressure proxy.** Not order flow, not
participation rate, not metaorder detection, not a regime.

Two things the data cannot support, stated before anything else:

- **Aggregate volume is not a participant's share of market volume.** We observe total volume in a minute. We cannot observe any participant's rate.
- **Candle geometry does not reveal which side initiated trades.** A close near the high is consistent with buy-initiated pressure, with a seller withdrawing, and with an unrelated path through the minute. Order-book studies find signed order-flow imbalance more informative than volume alone; we have neither.

The mechanism literature is real but does not transfer for free. Studies using
**identified** metaorders find impact during execution and relaxation after it.
That such orders exist and behave that way does **not** establish that minute
bars identify them.

Three separable achievements, and which are in reach:

| Achievement | Reachable here? |
|---|---|
| The feature improves a forecast | **Yes** — this is what the design tests |
| The evidence is consistent with the proposed mechanism | **Limited** — the ablations constrain which simpler explanations survive; consistency is not confirmation |
| The mechanism is causally identified | **No.** Not promised, not attempted |

Competing explanations that this design cannot exclude: continued execution
(momentum rather than reversion), informed trading with permanent impact,
volatility clustering expressed through the same signature, and time-of-day
effects.

---

## 2. Feature algebra, resolved

### 2.1 The prior definition collapsed

The previous proposal defined `flow_W = ΣBᵢVᵢ/ΣVᵢ`, `pressure_W = ΣVᵢ/ΣV̄ᵢ`,
`S = pressure·|flow|`. The `ΣVᵢ` cancels:

    S = |Σ BᵢVᵢ| / Σ V̄ᵢ

and the signed predictor `d·S` is simply `Σ BᵢVᵢ / Σ V̄ᵢ`.

**What survives:** a single aggregate — baseline-normalised signed body-volume.
**What disappears:** every claim that *both* ingredients must be individually
strong. High volume compensates for weak direction, and one dominant bar
reproduces any value that ten consistent bars produce. The product form created
no conjunction.

### 2.2 Consequent decision on persistence

The hypothesis is hereby declared to concern **aggregate signed activity and its
alignment with volume**, not persistence. **All persistence claims are removed.**
The chosen construction cannot support them, and inventing a persistence
statistic now would add a second feature and a second hypothesis to a brick that
should test one. Persistence across bars is recorded as a distinct future
question, not smuggled into this one.

### 2.3 What is actually incremental

Write `W` bars, `B̄ = (1/W)ΣBᵢ`, `P = ΣVᵢ/ΣV̄ᵢ`, `F = ΣBᵢVᵢ/ΣV̄ᵢ`. With the
covariance taken over the window with **divisor `W`** (not `W−1`),
`Cov_W(B,V) = (1/W)Σ(Bᵢ−B̄)(Vᵢ−V̄ᵂ)`, exactly:

    F = U + K,    U = B̄·P,    K = W·Cov_W(B, V) / Σ V̄ᵢ

So `F` decomposes into (i) the **product** `U` of the two ingredients and (ii) a
normalised within-window **covariance** `K` between body direction and volume —
whether the volume sits on the consistently-signed bars. An additive model in
`B̄` and `P` can express neither; a model with `U` present can express the
product but not `K`. The design's object of study is therefore the
**incremental signed-activity information carried by `F` beyond `U`**. Because
the fixed clipping (§2.4) is applied to `B̄`, `P` and `F` separately, it breaks
the raw identity in the clipped tail, so the comparison is *not* claimed as an
exact covariance-only attribution.

### 2.4 Final feature definitions — one construction, no menu

Per bar `i`, with `H > L` required for a defined body:

    Bᵢ = (closeᵢ − openᵢ) / (highᵢ − lowᵢ)        signed body-to-range measure, ∈ [−1, 1]

**Named honestly:** this is a *signed body-to-range* measure. It is **not** the
conventional close-location value `(2·close − high − low)/(high − low)`, and the
two are not substituted for one another anywhere in this design.

    V̄(m) = fit-split median volume at exchange-local session minute m
    P     = Σ Vᵢ / Σ V̄(mᵢ)                      relative volume intensity, ≥ 0, dimensionless
    B̄     = (1/W) Σ Bᵢ                           mean signed body, ∈ [−1, 1], dimensionless
    F     = Σ Bᵢ Vᵢ / Σ V̄(mᵢ)                    signed body-volume, dimensionless

Fixed window **W = 10** completed bars. One value, declared now, not searched.

**One fixed transformation: winsorisation at fit-split quantiles.** For each of
`B̄`, `P`, `F`, one constant — the fit-split 99th percentile of the absolute
value — estimated once and frozen:

    x̃ = clip(x, −q_x, +q_x)     (P is one-sided: clip(P, 0, q_P))

Behaviour: **at zero**, `x̃ = 0`, and `F = 0` means either no net signed body or
no volume. **At ordinary values** (≈99% of fit rows) the transform is the
identity, so the §2.3 decomposition holds exactly in the bulk. **At extremes**
the value is capped, bounding single-bar leverage; the count and share of
clipped rows is reported per period. No `g()`, no scale constant, no window
alternatives, no thresholds are left open.

---

## 3. Arms, comparators, and the primary comparison

**L is a legacy reference, not the established strongest model.** My earlier
claim that "L is the strongest thing we have" is withdrawn: its advantage over
M1 conflated the mean with a *dispersion-family* difference (Student-t vs
Gaussian), and every one of those comparisons came from the invalidated,
exposed EXP-002 development pass.

Nuisance terms: **none are used.** If review wants session-time controls they
must be added identically to every arm; the design does not include them, so no
arm has them.

| Arm | Mean specification |
|---|---|
| **L** (legacy context) | `ret_1`, `ret_5` |
| **A** (additive) | `ret_1`, `ret_5`, `B̄̃`, `P̃` |
| **A×** (product comparator — **primary**) | A + `B̄̃·P̃` |
| **C** (challenger) | **A× + `F̃`** |

The arms are strictly nested: `L ⊂ A ⊂ A× ⊂ C`. The earlier version had
`C = A + F̃`, which **replaced** the product with `F` rather than adding `F` while
retaining it; `A×` could fit a coefficient on `U` while `C` tied `U` and `K` to
one coefficient — different restrictions, not a matched removal. Corrected.

All arms: intercept plus the standardised basis, ordinary least squares on the
fit split, identical treatment of shared coefficients — every arm re-estimates
all of its own coefficients, so no arm inherits another's fit. Scale and tail
law shared (§5).

**Frozen comparisons:**

| # | Comparison | Role | What it isolates |
|---|---|---|---|
| **P1** | **C vs A×** | **primary scientific** | whether `F` adds forecast value **after the ingredients and their product are available** — incremental signed-activity information beyond the specified product comparator |
| S1 | A× vs A | secondary | the product component alone |
| S2 | A vs L | secondary | whether the ingredients add anything beyond price features |
| S3 | C vs A | secondary, contextual | the combined product-plus-`F` increment (not an isolation of either) |

**P1 is the scientific comparison. C vs L is contextual only** and carries no
authority. Ingredient attribution is by these **matched feature-removal**
comparisons — the previous fixed-sign "A4" arm is removed, since it was not a
clean test that magnitude is volatility.

**Joint value is not inferred from separate failures.** If S2 and S3 each fail
significance, that is *not* evidence that the combination works; only P1 speaks
to P1's question. Secondary comparisons form one declared family, Holm-adjusted,
with no authority.

---

## 4. Deterministic implementation checks — representational novelty

Before any historical access. These use constructed bar histories and establish
**representational** differences only: that the feature can distinguish states
the legacy inputs cannot. They establish **neither predictive value nor
statistical independence** from the legacy features on real data.

| Check | Construction | Establishes |
|---|---|---|
| N1 | Two valid histories with **identical close paths** (hence identical `ret_1`, `ret_5`, `rv_30` at the forecast row) but different opens/highs/lows/volumes | `F` varies where every legacy input is fixed |
| N2 | Two histories with identical `B̄` and identical `P` but different `F` | the alignment content is not recoverable from the additive ingredients |
| N3 | Two histories with identical `F`, one from a single dominant bar and one from ten uniform bars | documents what `F` does **not** distinguish, supporting the removal of persistence claims |
| N4 | Availability: recompute every feature at each forecast time from only prior completed bars | no future bar enters a feature |
| N5 | Equivalence: is the challenger's fitted predictor distinct from the comparator's, out of sample, via the FWL check already built | avoids repeating the EXP-003 error |

A handful of successful fixtures **does not** estimate false-positive frequency
or general detection power, and no size or power claim is made from them.

---

## 5. State-dependent dispersion

Pressure may forecast **volatility** without forecasting direction, and a
density-score gain can come from a better-specified scale rather than a better
mean. One bounded robustness comparison, both scale specifications declared now:

    D0 (registered):        scaleᵢ = rv_30,ᵢ · s₀
    D1 (state-dependent):   scaleᵢ = rv_30,ᵢ · s₁ · exp(λ · P̃ᵢ)        with ν FROZEN at D0's value

**Why ν is frozen.** If D1 re-estimated `ν`, a D1-vs-D0 improvement could come
from a changed tail shape even if pressure contributed nothing — the same
mean/dispersion confounding EXP-002 suffered. So D1 changes the **scale
specification only**, with location and tail shape fixed.

**Estimation contract, declared before implementation:**

| | D0 | D1 |
|---|---|---|
| Reference residuals | `zᵢ = (yᵢ − μ_A×(xᵢ)) / rv_30,ᵢ` on the fit split — the **product comparator's** residuals, one declared reference | the same `zᵢ` |
| Free parameters | `(log s₀, log ν)` | `(log s₁, λ)`; `ν ≡ ν₀` from D0 |
| Objective | negative Student-t log-likelihood of `z/s` | negative Student-t log-likelihood of `zᵢ / (s₁·exp(λP̃ᵢ))`, including the `−Σ log(s₁·exp(λP̃ᵢ))` Jacobian |
| Optimiser | the shipped Nelder–Mead (`studentt.fit_scale_nu`): reflection 1.0, expansion 2.0, contraction 0.5, shrink 0.5 | the same Nelder–Mead, same coefficients |
| Initialisation | `ν₀ = 6`, `s₀ = sd(z)·√((ν₀−2)/ν₀)`, simplex steps 0.1 | `s₁ = s₀`, `λ = 0`, simplex steps 0.1 |
| Bounds | `ν ∈ [2.1, 50]`, infinite walls | `λ ∈ [−2, 2]`, `s₁ > 0`, infinite walls |
| Convergence | `max_iter = 500`, `tol = 1e-8` on both objective spread and simplex diameter | identical |
| Refusals | `< 100` finite residuals; zero spread; no convergence; **`ν` at the lower bound refused** (upper bound accepted and recorded, as registered) | the same, plus **`λ` at either bound refused**, since a bound-riding `λ` is not an estimate |
| Reuse across arms | `(s₀, ν₀)` shared identically by L, A, A×, C | `(s₁, λ, ν₀)` shared identically by L, A, A×, C |

No other scale family, no hyperparameter search. **GARCH is deliberately not
here**: D1 is a pressure-conditioned scale, not a recursively evolving variance,
and testing GARCH against the `rv_30` baseline is its own bounded volatility
comparison to be proposed separately once these comparisons are sound.

Three quantities reported separately, never merged:

1. **Incremental location contribution under matched dispersion** — P1 evaluated under D0, and again under D1. Scale *and* tail shape are identical on both sides of each comparison, so any difference comes from the location forecast.
2. **Dispersion improvement** — arm A× under D1 vs arm A× under D0. Same location and same `ν` on both sides, so the difference comes from the scale specification alone.
3. **Unresolved sensitivity to the scale specification** — whether P1's sign or pass status changes between D0 and D1. If it does, the location result is reported as *specification-sensitive* and no location claim is made.

---

## 6. Outcomes — three outputs kept separate

The score differential is `dᵢ = log p_C(yᵢ) − log p_A×(yᵢ)`. **Negative `d`
means the challenger scored worse.** It says nothing about market direction,
continuation, momentum, or whether price moved with the signature. Three outputs
are reported separately and are never allowed to stand in for one another:

| Output | What it is | What it is not |
|---|---|---|
| **Score differential** (P1) | which forecast performed better, as a distributional score | evidence about direction or mechanism |
| **Fitted coefficient** `θ` on `F̃` in C | the model's signed association: positive `θ` associates positive signed activity with a **higher forecast location**, negative `θ` with a lower one | a causal mechanism; a "reversion" or "continuation" finding |
| **Mechanism interpretation** | what, if anything, the sign of `θ` is *consistent with* | identification of temporary impact, informed trading, or anything else |

**Decision table for P1** (see §8 for the executable rule):

| P1 under D0 and D1 | Reported as |
|---|---|
| Passes under both | **A better distributional score obtained by changing the location forecast while holding scale and shape fixed**, beyond the product comparator, robust to the two declared scale specs. An exposed-data candidate screen. Then, separately: the sign of `θ` and what it is consistent with |
| Passes under one spec only | Specification-sensitive; **no location claim**. Both results reported |
| Fails under both | No detectable incremental score improvement from `F` at this horizon with these proxies and this comparator. Does **not** refute market impact or the mechanism — the proxies may be too weak, the comparator may already carry the information |

**On the coefficient, whatever P1 does:** positive `θ` does not establish
temporary impact; negative `θ` does not refute market impact generally; either
sign is *consistent with* more than one mechanism, and consistency is reported
as such. **On the score:** a Student-t log-score improvement from changing the
location is **not** automatically evidence of a better conditional-mean estimate
under misspecification; the defensible claim is the narrower one stated in the
first row. Dispersion result (2) is reported whatever P1 does, and a
dispersion-only improvement is **not** a location finding.

---

## 7. Availability, timing and data hygiene

- **Session indexing:** exchange-local session minute from the verified exchange calendar (`require_verified`), which carries daylight-saving transitions and early closes. Baselines `V̄(m)` are indexed by that session minute, so an early-close session's minute 200 is the same index as a full session's minute 200; **early-close sessions contribute to a baseline only for minutes they actually contain**.
- **Window:** exactly 10 **completed** bars ending at the same bar as the existing features. The forecast is issued at that bar's completion, `assumed_available = t + 60s`, identical to the registered clock.
- **No session crossing:** the window must lie entirely within one session; rows too early in a session are refused, as warm-up rows already are.
- **No bridging:** if any of the 10 minutes is absent, the row is **refused** (`MISSING_PRESSURE_BARS`), matching the existing missing-bar discipline. Gaps are never interpolated.
- **Zero vs missing volume:** a present bar with `volume = 0` is **valid** and contributes 0 to both sums. An absent bar is missing and refuses the row. The two are never conflated.
- **Zero-range bars:** `high = low` gives an undefined body; `B = 0` by declaration, and the count and share of such bars is reported per period.
- **Impossible OHLC:** `high < low`, `close` or `open` outside `[low, high]`, negative volume, non-finite values — the row is **refused** under a named refusal, never repaired.
- **Baseline support:** a session minute needs at least **100** fit-split sessions with a present bar, else every row whose window touches it is refused. `Σ V̄(mᵢ) = 0` refuses the row.
- **Frozen transformations:** `V̄(·)` and the three winsorisation constants are estimated on the **fit split only** and frozen. Development features use only frozen transformations and observations available by each forecast time. **Fit-period preprocessing is training material, not a forecast:** a baseline or clipping constant computed from the whole fit window was not available at earlier fit-window timestamps, and fit-split rows are never described as forecasts issued at their own times. This is legitimate for training and is stated so it cannot be read otherwise.
- **Structural volume change after the fit window** (venue mix, tick-size or ETF-share changes, 2020 volume regime) is a **known limitation**, not something adapted to. A baseline-drift diagnostic — realised `P` distribution by year against the fit-split baseline — is reported alongside results, and is descriptive only.
- **Admission:** EXP-004 requires **its own admission**. That the fields already exist in the corpus does **not** extend EXP-002's admission, and no historical byte is read before a separate reviewed decision.

---

## 8. Inference and authority

- **Primary estimand:** the mean per-row difference in log predictive density, `C − A×`, over the **common eligible rows** of the development pool. Orientation: **positive means the challenger scored better**.
- **Statistical null for P1:** `E[d] ≤ 0`.
- **Effect size:** reported always — mean log-score difference per row with the HAC interval and the bootstrap interval, not only a pass/fail.

**Common row population.** Every paired comparison — P1, S1–S3, and the
contextual C-vs-L — is evaluated on **one identical set of row keys**
`(session_date, event_time)`: the rows that satisfy the feature requirements of
**every** arm, including the pressure-window requirements of §7. Pressure-related
refusals therefore remove a row from *all* arms, including L; no arm is ever
scored on a different population from its comparator. The eligible-row count
and each refusal category's count are reported per period.

**Executable decision rule for P1, frozen** (inherited from the EXP-002
registration where noted):

| Element | Value |
|---|---|
| DM-HAC | Bartlett kernel; lag `L = H − 1 = 14`, derived from the 15-minute horizon (`inference.py`, refuses any other lag); pass iff `mean > 0` **and** `t > 2.0` |
| Session stationary bootstrap | as implemented in `exp002.bootstrap.session_stationary_bootstrap`: per-session sums and counts; each replicate draws `S` sessions as **consecutive runs in session order, wrapping circularly, run length geometric with expected block 5 sessions** (`p = 1/5`), a fresh random start per run; replicate mean = total/count; `B = 10,000`; seed `20260909`; centred exceedances `k`; `p̂ = (k+1)/(B+1)`; pass iff `mean > 0` **and** `p̂ < 0.0228` |
| Bootstrap sensitivities | expected block 1 and 10 sessions, **reported**, no authority |
| Per-specification pass | both methods pass under that dispersion specification |
| **Selection** | P1 passes both methods under **both D0 and D1** |
| Any other pattern | `NOT_SELECTED`, with the specific pattern named: `INFERENCE_DISAGREEMENT` (methods split under a spec), `SPECIFICATION_SENSITIVE` (passes under one spec only), or plain fail |
| Reporting | **every** cell — 2 methods × 2 specifications × (P1, S1, S2, S3, C-vs-L) — is reported; no specification is chosen after the fact |

**Method assumptions, tied to the implementation.** HAC assumes stationarity
and weak dependence of the per-row differential and depends on the derived lag
truncation. The bootstrap resamples **consecutive session blocks** to preserve
local (session-to-session) dependence; its justification is that the sequence
of per-session mean differentials is approximately stationary and that
dependence dies out over a span the geometric run lengths can cover — **not**
merely that individual sessions are exchangeable. Neither assumption is
established for 2019–2021, which spans a volatility regime change; this is a
declared limitation of the inference, not a solved problem.
- **Disagreement handling, frozen now:** as in the table — no claim is made, and nothing is resolved case-by-case afterwards.
- **Secondary family:** S1–S3, Holm-adjusted within that family, no authority, declared before execution.
- **No permutation control with invalidation authority.** "Every permuted comparison must be insignificant" is not reinstated, for the reasons in `EXP002_N0_CLOSURE.md`.
- **Integrity controls with invalidation authority** (each a direct measurement, none a statistical test): source and code identity, sealed-period exclusion, fit-budget spies, numerical validity, forecast-hash reconstruction. Implementation checks, provenance checks and statistical inference are kept in separate sections of the record and never combined into one verdict. Per the correction now on record, a defect discovered later **can** invalidate the scientific use of an artifact already produced; the artifact is preserved regardless.

---

## 9. Exposure and anti-selective-reporting

- **Fit: 2016-01-04 → 2018-12-31.** All of **2019, 2020 and 2021 are exposed** development data.
- **One primary aggregate development analysis** — P1 over the pooled development rows — declared now.
- **Fixed stability summaries, declared now:** the same statistic computed separately for 2019, 2020, 2021, reported **always and together**, as description. They are not decisions, and no year may be selected afterwards.
- **No post-hoc selection** of year, session segment, direction, pressure threshold, window or transformation. All are fixed in this document.
- **A successful development result is a candidate screen only.** It grants **no** confirmation access. Evaluation and reserve remain closed; any opening requires a separate, independently reviewed, explicitly authorised admission.
- **Evaluation exposure disclosed:** `EVALUATION_READ_INCIDENT_001` — 60 metadata bytes (0.058%) of `SPY_2022-01-03.json`, read once on 2026-09-08, no values exposed. The evaluation set is never described as untouched.

### Research budget — every estimation counted

| Item | Count |
|---|---|
| Session-minute volume baselines `V̄(·)` | 1 estimation (≈390 medians) |
| Winsorisation constants | 3 (`B̄`, `P`, `F`) |
| Mean fits | 4 (L, A, A×, C) — OLS, fit split, once each |
| Scale/tail estimates | 2 (D0: `s, ν`; D1: `s, λ, ν`) |
| **Total fit-split estimations** | **10** |
| Refits | 0 |
| Development evaluations | 1 primary + 3 fixed per-year summaries (descriptive, no decisions) |
| Design variants held in reserve for later search | **0** |
| Sealed openings | **0** |
| Economics | none |

**Computational reuse:** the mean fits are OLS and do not depend on the scale
specification, so the same four fitted means are scored under both D0 and D1.
This is reuse of one estimation, not two — it does not double the budget, and it
is why the D0/D1 comparison is a genuine matched-dispersion contrast.

---

## 10. What a pass would mean, and what remains unproven

**A pass on P1 under both scale specs would mean:** on the exposed development
pool, adding the clipped signed body-volume `F̃` to a location forecast that
already contains the legacy price features, both ingredients, and their product
produced **a better distributional score by changing the location forecast
while holding scale and tail shape fixed**, under both declared dispersion
specifications and both inference methods. That is incremental signed-activity
information beyond the specified product comparator. It is an exposed-data
candidate screen.

**It would not mean:** an exact covariance-only attribution (clipping breaks the
raw identity); a better conditional-mean estimate under misspecification; that a
metaorder was detected; that the effect is temporary impact; that the state is
causal; that the result generalises past 2021; or that anything is tradable.

**Unresolved assumptions, listed rather than argued away:**

1. The Student-t scale/tail family is assumed, not tested; D1 probes one alternative, not the family.
2. Stationarity and block-exchangeability required by both inference methods are not established across 2019–2021.
3. `B` and relative volume are crude proxies for order flow; the missing evidence is trade-and-quote data, which the corpus does not contain.
4. The development pool is exposed; there is no clean out-of-sample period below 2022.
5. 15 minutes is inherited from the registered horizon and is not matched to any execution timescale.

### Contribution to the options objective, without tradability claims

A positive result would contribute **evidence about the conditional direction
and magnitude of short-horizon SPY returns in a defined observable state**, and
— via the D1 comparison — separate evidence about conditional **dispersion**.
Both are inputs a later options decision would need.

**Missing economic evidence, none of which this brick provides:** contemporaneous
option prices and quotes, implied-volatility changes in the same state, bid-ask
spreads, executable contract selection, fees and exercise/assignment mechanics,
capacity, and portfolio-level risk. EXP-001B's economics were never run. **No
profit is calculated and no broker path is designed here.**

---

## 11. Requested action

Review of this specification. If accepted in principle, the next bricks in
order: a written registration freezing these definitions; the deterministic
implementation and novelty checks N1–N5; then — separately reviewed — a request
for historical admission covering the development pool only. **Stop for
independent review before implementation or registration.**
