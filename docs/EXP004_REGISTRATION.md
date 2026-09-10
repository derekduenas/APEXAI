# EXP-004 REGISTRATION — OHLCV pressure proxy — FROZEN

**Status: FROZEN 2026-09-09.** Machine-readable form:
`apex/world_model/exp004/registration.py`, **registration hash
`9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9`** (sha256 of the module bytes; the module is
authoritative where prose and module could differ). Implementation and
historical admission are subsequent bricks. Nothing here has been fitted, scored, or read
from historical data. The design rationale is in
`EXP004_OHLCV_PRESSURE_PROXY.md`; this document is the executable contract.

---

## R1. Question

Does the clipped signed body-volume feature `F̃` improve the distributional score
of a 15-minute-ahead SPY log-return forecast **after** the legacy price features,
the two ingredients `B̄̃`, `P̃`, and their product `B̄̃·P̃` are already available in
the location forecast, with scale and tail shape held fixed?

## R2. Data, periods, exposure

| Role | Range | Status |
|---|---|---|
| fit | 2016-01-04 → 2018-12-31 | training material |
| development pool | 2019-01-01 → 2021-12-31 | **exposed** (EXP-002 development and observed) |
| evaluation | 2022-01-01 → 2024-12-31 | **sealed**; one disclosed 60-byte metadata read (`EVALUATION_READ_INCIDENT_001`) |
| reserve | 2025-01-01 → 2026-08-28 | sealed |

Instrument SPY; source family `alpaca_sip_raw_1m`; fields `open, high, low,
close, volume, event_time_utc`.

**Inherited definitions, pinned by source and value** (recording chosen
behaviour, not changing it):

| Definition | Source | Value |
|---|---|---|
| target | `exp001b.registration.TARGET` | `log(close[bar at t+15min] / close[bar at t])`; the t+15min bar must exist; nothing forward-filled |
| horizon | `exp001b.registration.HORIZON_MINUTES` | 15 |
| bar length | `exp001b.registration.BAR_SECONDS` | 60 s |
| availability clock | `exp001b.registration.AVAILABILITY_BASIS`; `bars.session_from_doc` | `ASSUMED_BAR_CLOSE`: `bar_complete = assumed_available = event_time + 60 s`; `known_from` = the feature bar's `assumed_available`; no publication timestamp in the corpus |
| warm-up | `exp001b.registration.WARMUP_MINUTES` | 30 min |
| embargo | `exp001b.registration.EMBARGO_MINUTES` | 15 min — rows whose `t+15+15 min` reaches the close are excluded |
| calendar | `exp001b.registration.CALENDAR_VERSION`; `exchange_calendar.session_bounds(require_verified=True)` | `NYSE_REGULAR_SESSION_CALENDAR_V0_2016_2026` |
| legacy features | `exp001b.bars.observable_rows`, `EXP001B_OBSERVABLE_FEATURES_V0` | `ret_1, ret_5, rv_30` |
| `RV_FLOOR` | `exp002.registration.RV_FLOOR` | `1e-9`; below-floor rows refused for all arms |
| HAC | `apex.world_model.inference` | Bartlett, lag `14 = H−1` |
| bootstrap constants | `exp002.registration.BOOT_*` | block 5 (sens. 1, 10), `B = 10,000`, seed `20260909`, `p̂ < 0.0228`, `(k+1)/(B+1)` |
| DM threshold | `exp002.registration.DM_THRESHOLD` | 2.0 |

**EXP-004 requires its own signed admission**;
no prior admission extends to it. A development result is a candidate screen and
grants no sealed access.

## R3. Feature equations (per forecast row, all quantities from completed bars only)

Session minute `m(i)` from the verified exchange calendar. Window `W = 10`
completed bars ending at the feature bar. `V̄(m)` = fit-split median volume at
session minute `m`, requiring ≥ 100 fit sessions with a present bar at `m`.

    Bᵢ  = (closeᵢ − openᵢ)/(highᵢ − lowᵢ)   if highᵢ > lowᵢ, else 0        signed body-to-range, ∈ [−1,1]
    B̄   = (1/W) Σᵢ Bᵢ
    P   = Σᵢ Vᵢ / Σᵢ V̄(m(i))
    F   = Σᵢ Bᵢ Vᵢ / Σᵢ V̄(m(i))
    Cov_W(B,V) = (1/W) Σᵢ (Bᵢ − B̄)(Vᵢ − V̄ᵂ),   V̄ᵂ = (1/W)ΣᵢVᵢ         (divisor W)
    F   = B̄·P + W·Cov_W(B,V)/Σᵢ V̄(m(i))                                   (identity, raw features)

Clipping constants, fit split only, frozen: `q_B = Q₀.₉₉(|B̄|)`, `q_P = Q₀.₉₉(P)`,
`q_F = Q₀.₉₉(|F|)` — the 0.99 quantile as the `⌈0.99·n⌉`-th order statistic.

    B̄̃ = clip(B̄, −q_B, q_B)     P̃ = clip(P, 0, q_P)     F̃ = clip(F, −q_F, q_F)

Clipping is applied per feature and breaks the raw identity in the clipped tail;
no covariance-only attribution is claimed. Legacy features `ret_1`, `ret_5`,
`rv_30` exactly as registered in EXP-001B.

## R4. Arms (location forecasts)

All arms: intercept + standardised basis (fit-split mean/sd per column), OLS via
SVD `lstsq` with `rcond = 1e-12`, every coefficient re-estimated per arm.

| Arm | Basis columns |
|---|---|
| L | `ret_1, ret_5` |
| A | `ret_1, ret_5, B̄̃, P̃` |
| **A×** | `ret_1, ret_5, B̄̃, P̃, B̄̃·P̃` — **primary comparator** |
| **C** | `ret_1, ret_5, B̄̃, P̃, B̄̃·P̃, F̃` — **challenger** |

Design spaces are nested `L ⊆ A ⊆ A× ⊆ C`. Strict enlargement depends on
non-redundant columns on the actual fit data and is **not guaranteed**; a
rank-deficient design is **refused** (`RANK_DEFICIENT`), never repaired. A
zero-variance column is refused (`ZERO_VARIANCE_FEATURE`).

The coefficient `θ` on `F̃` in C is a **partial association holding the other
regressors fixed**. Because C re-estimates every coefficient, the forecast
difference `μ_C − μ_A×` is **not** `θ·F̃` in general and is never reported as such.

## R5. Dispersion — objectives as equations

Reference residuals, on the common eligible fit rows (§R7):

    zᵢ = (yᵢ − μ_A×(xᵢ)) / rv_30,ᵢ

Let `t_ν(·)` be the unit-scale Student-t density. With `n` residuals:

    D0:  J₀(log s₀, log ν)  = Σᵢ [ log s₀ − log t_ν(zᵢ / s₀) ]                 minimise over (log s₀, log ν)
    D1:  aᵢ = log s₁ + λ·P̃ᵢ
         J₁(log s₁, λ)      = Σᵢ [ aᵢ − log t_ν₀(zᵢ · e^(−aᵢ)) ]                minimise over (log s₁, λ), ν ≡ ν₀ from D0

The omitted `Σ log rv_30,ᵢ` is constant within each fit. **Full forecast scoring
uses the complete scale:** `scaleᵢ = rv_30,ᵢ·s₀` (D0) or `rv_30,ᵢ·s₁·e^(λP̃ᵢ)` (D1),
and the scored log-density includes `−log scaleᵢ`.

**Required identity check (implementation, before any fit is accepted):**
`J₁(log s₀, 0)` evaluated with `ν₀` must equal `J₀(log s₀, log ν₀)` to relative
tolerance `1e-9` on the same residual vector. This checks the computation, not
the labels.

**Optimiser** (both): the shipped Nelder–Mead (`studentt.fit_scale_nu` form) —
reflection 1.0, expansion 2.0, contraction 0.5, shrink 0.5; initial simplex
steps 0.1; `max_iter = 500`; convergence when objective spread `< 1e-8` **and**
simplex diameter `< 1e-8`. D0 init `ν₀ = 6`, `s₀ = sd(z)·√((ν₀−2)/ν₀)`. D1 init
`s₁ = s₀ (from D0)`, `λ = 0`. Bounds as infinite walls: `ν ∈ [2.1, 50]`,
`λ ∈ [−2, 2]`, `s > 0`.

Sharing: `(s₀, ν₀)` used identically by L, A, A×, C under D0; `(s₁, λ, ν₀)`
identically under D1. The OLS locations do not depend on the dispersion
specification, so the four fitted locations are scored under both — one
estimation each, reused.

## R6. Refusal semantics (acceptance contract)

- **No filtering of residuals.** The residual vector is formed on the common eligible fit rows exactly. If **any** residual is non-finite the fit is **refused** (`NONFINITE_RESIDUALS`); if the count is `< 100` it is refused (`INSUFFICIENT_RESIDUALS`). Invalid observations are never dropped to reach either condition.
- **Bound contact.** The fitter *reports* contact; a new component `apex/world_model/exp004/dispersion.py` (`fit_d0`, `fit_d1`) *enforces* the policy. Detection tolerance for both `ν` and `λ`: `|param − bound| ≤ 1e-3`. `ν` at the lower bound → refused; `ν` at the upper bound → accepted and recorded (as registered in EXP-002). `λ` at either bound → **refused**. A bound-contacting `λ` is a constrained estimate; refusing it is a **declared model-domain policy**, not a claim that it is not an estimate.
- **Finiteness at acceptance.** Accepted parameters must give a finite objective and a finite, strictly positive `scaleᵢ` on every fit row and, at scoring, on every eligible development row. Any violation refuses the run (`INVALID_INPUT_OR_FAILURE`). No overflow-driven row dropping, no fallback values.
- **Optimiser non-convergence** → refused (`OPTIMIZER_NO_CONVERGENCE`).

## R7. Common row population

A development row is **eligible** iff it satisfies the requirements of **every**
arm: legacy warm-up and target availability (as in EXP-001B/002), `rv_30 ≥
RV_FLOOR`, and the pressure-window requirements — 10 completed bars within the
same session, none missing (`MISSING_PRESSURE_BARS` otherwise), all OHLC valid
(`high ≥ low`, `open, close ∈ [low, high]`, finite, `volume ≥ 0`; else
`INVALID_OHLC`), every window minute with baseline support, and
`Σ V̄(m(i)) > 0`. Zero volume in a present bar is valid. Zero-range bars give
`B = 0` and are counted.

Eligibility is computed **once** per row, and every comparison — P1, S1–S3,
C-vs-L — is scored on the identical key set `(session_date, event_time)`. A
pressure refusal removes the row from L as well. Eligible counts and refusal
counts by category are reported per year.

**The same rule governs training.** All four location fits, the clipping
constants and both dispersion fits use **one identical eligible fit-row
population** under the same requirements; there is no arm-specific filtering at
any stage. Preprocessing order, fixed:

1. valid fit bars (calendar-verified sessions; malformed or impossible bars refused by name)
2. minute-of-session volume baselines `V̄(m)` from those bars (median; support ≥ 100 sessions)
3. eligible raw feature rows on the fit split under this rule (legacy + pressure requirements)
4. clipping constants `q_B, q_P, q_F` from the step-3 rows
5. standardised design matrices per arm (fit-split column mean/sd) from the step-3 rows with step-4 clipping
6. location fits L, A, A×, C on the identical step-3 rows
7. dispersion fits D0, then D1, on A× residuals over the identical step-3 rows

For development, steps 2, 4 and the step-5 standardisation statistics are frozen
from the fit; development rows pass this rule once; features use only completed
bars available by each forecast time.

Fit-split rows are training material; baselines and clipping constants derived
from the whole fit window are not forecasts available at earlier fit timestamps.

## R8. Inference

Per-row differential `dᵢ = log p_X(yᵢ) − log p_Y(yᵢ)` for comparison `X vs Y`;
positive means `X` scored better. Null `E[d] ≤ 0`.

**DM-HAC.** Bartlett kernel, lag `L = 14 = H − 1`. This is a **fixed inference
choice motivated by the 15-bar target overlap**, not a claim that dependence
ends after fourteen rows. Pass iff `mean > 0` and `t > 2.0`. One-sided normal
p-value `Φ̄(t)` is reported and enters Holm for secondaries.

**Session stationary bootstrap** (`exp002.bootstrap.session_stationary_bootstrap`,
unchanged). With per-session differential sums `D_j` and eligible-row counts
`N_j`, each replicate draws `S` sessions as consecutive runs in session order
(wrapping; run length geometric, `p = 1/5`, expected block 5 sessions; fresh
random start per run) and forms

    m̂* = Σⱼ D_{Iⱼ} / Σⱼ N_{Iⱼ}

The resampled quantity is the **pooled per-row mean as a ratio of session sums to
session counts**. Its justification concerns the **joint sequence of session
(sum, count) pairs** — counts vary with early closes and missing bars — being
approximately stationary with dependence covered by the geometric run lengths;
it is not a claim that sessions are exchangeable. `B = 10,000`; seed
`20260909`; centred exceedances `k`; `p̂ = (k+1)/(B+1)`; pass iff `mean > 0` and
`p̂ < 0.0228`. Sensitivities with expected block 1 and 10 are reported without
authority.

**Intervals, frozen.** HAC: `mean ± 1.96·se_HAC`. Bootstrap: the two-sided 95%
**percentile interval** of the raw replicate means `m̂*`, lower bound the
`⌈0.025·B⌉`-th and upper bound the `⌈0.975·B⌉`-th order statistic
(1-indexed, no interpolation). `boot_se` is reported but is **not** converted
into a normal interval and called a bootstrap interval. The percentile
interval is descriptive; `p̂` decides. Both intervals are reported for every
comparison.

**Reporting interface.** The existing `session_stationary_bootstrap` returns
`mean`, `boot_se`, `exceedances`, `p_one_sided` and `pass` — **not the replicate
means** the percentile interval needs. EXP-004 therefore requires a reporting
extension or adapter exposing the replicate means. Its acceptance check (N8)
must show that, for the same seed, the extension reproduces the existing
resampling sequence, `p̂` and pass decision **exactly**. "Unchanged" above
describes the statistical calculation, not the current return object.

## R9. Result classification (deterministic)

Precedence 1 — **integrity**: if any integrity control fails (source/code
identity, sealed-period exclusion, fit budget, numerical validity, hash
reconstruction, or any R6 refusal), the outcome is **`INTEGRITY_FAILURE`** (or
the specific refusal), no statistical classification is made, and the artifact
is preserved.

Precedence 2 — **primary**, on the four decisions
`{HAC_D0, BOOT_D0, HAC_D1, BOOT_D1}` for P1:

| Outcome | Rule |
|---|---|
| `SELECTED` | all four pass |
| `NOT_SELECTED` | otherwise |

Recorded alongside `NOT_SELECTED` as **independent boolean flags** (both may be
true; no precedence between them):

- `INFERENCE_DISAGREEMENT_D0` = `HAC_D0 ≠ BOOT_D0`; `INFERENCE_DISAGREEMENT_D1` likewise
- `SPECIFICATION_SENSITIVE` = `(HAC_D0 ∧ BOOT_D0) ≠ (HAC_D1 ∧ BOOT_D1)`

All four raw decisions, both statistics, both intervals and the effect size are
recorded regardless of outcome.

## R10. Reporting family and multiplicity

Primary: P1 = C vs A× — no adjustment, decides selection.

Secondary family: **six hypotheses** — S1 (A× vs A), S2 (A vs L), S3 (C vs A),
each under D0 and D1. Holm adjustment is performed **separately for each
inference method**: once over the six HAC p-values, once over the six bootstrap
`p̂`. All twelve adjusted values are reported. None affects primary selection.

Contextual: C vs L, D1-vs-D0 dispersion improvement (A× under D1 vs A× under D0),
bootstrap sensitivities, per-year (2019, 2020, 2021) recomputation of every
statistic — all reported always, none adjusted, none with authority.

## R11. Budget (corrected)

| Item | Count |
|---|---|
| `V̄(·)` baselines | 1 estimation |
| Clipping constants | 3 |
| Location fits (OLS) | 4 — L, A, A×, C |
| Dispersion fits | 2 — D0 `(s₀, ν₀)`; **D1 `(s₁, λ)` with ν fixed** |
| **Total fit-split estimations** | **10** |
| Refits | 0 |
| Development evaluations | 1 pooled primary + 3 fixed per-year summaries |
| Design variants in reserve | 0 |
| Sealed openings | 0 |
| Economics | none |

## R12. Implementation checks required before any historical admission request

N1 identical close paths ⇒ identical legacy inputs, different `F`; N2 identical
`B̄, P`, different `F`; N3 identical `F` from one dominant bar vs ten uniform
bars; N4 availability recomputation from prior completed bars only; N5 FWL
distinctness of C from A× out of sample; **N6 the R5 identity check**; **N7
common-row-key identity across all comparisons on a synthetic fixture with
induced pressure refusals**; **N8 bootstrap adapter equivalence** (same seed ⇒
same replicate sequence, `p̂`, pass). Fixtures establish representation and computation
only — not predictive value, size, or power.

## R13. What a pass means

`SELECTED` means: on the exposed development pool, adding `F̃` to a location
forecast already containing the legacy features, both ingredients and their
product produced a better distributional score by changing the location forecast
while holding scale and tail shape fixed, under both declared dispersion
specifications and both inference methods. It is an exposed-data candidate
screen. It does not mean a covariance-only attribution, a better conditional
mean under misspecification, a detected metaorder, temporary impact, causation,
generalisation beyond 2021, or tradability.

**Contribution to the options objective, narrowed:** evidence that a defined
OHLCV state changes the **distributional score of the location forecast** for
15-minute SPY returns, and separately (D1 vs D0) whether a pressure-conditioned
scale improves the score. Missing before any options use: contemporaneous option
prices and quotes, implied-volatility changes, spreads, executable contract
selection, fees and exercise mechanics, capacity, portfolio risk. No profit is
computed; no broker path exists.
