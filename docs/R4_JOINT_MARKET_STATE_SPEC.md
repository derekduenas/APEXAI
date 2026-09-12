# R4 — Joint market-state forecasting: the CLOSED implementation contract (nothing implemented, nothing fitted)

Status: `SPECIFICATION_CLOSED_V1` on branch `frontier-build`. The reviewer accepted the Draft 3.1 review patch
(applied at `24b055e`, file blob `a11a0cee…` by SHA-256) and the two design choices it settles: the retained
block-sequential sampler with its COMPOUND attribution scope, and the selected-only economic veto. This closeout
commit fixes the four documentation findings that survived the patch, reconciles the per-block record fields and
synchronizes the status table and manifest. Chain: `24b055e` ← `e8c6a53` ← `4d84548` ← `f848163` ← `65834d0` ←
`cf4155f`.

**What "closed" means.** This file, at the blob recorded as `r4.spec_pin.blob` in `docs/frontier_build_manifest.json`,
is the IMPLEMENTATION CONTRACT for R4. Implementation may now proceed against it under the holds below. Any later
change to the contract is a numbered amendment with its own review; code may not silently diverge from this text,
and a divergence found during implementation is reported as a finding against the contract rather than fixed by
editing the contract after the fact.

**What closing does NOT authorize.** No dataset is opened, no model is fitted, no service starts, no maintenance
block is lifted, no limit or admission changes, no backtest runs, no order is placed. A fitting run still requires
its own authorization (§1.3); prospective paper trading still requires live-feed and fee commissioning.

"Executable" means every requirement names the record it produces, the refusal code it raises, or the test that
pins it. Acceptance is exact identities and deterministic fixtures (§6.1) ONLY. Every statistical quantity is a
reported frequency with its uncertainty (§6.2) and gates nothing. §10 is the equation-to-test checklist.

**Default policy, verified in code at `2011f03`:** `--pilot-selection-policy` defaults to `PILOT_RULE_V1`
(`scripts/options_paper_session.py:341`; `apex/pulse_options/sources.py:38,181,197`;
`apex/options_pilot/entrypoint.py:53`). The deterministic pilot rule is and remains the operational default.
`FULL_FUNNEL_V1` is selection-by-name; `JOINT_FUNNEL_V1` will be too.

**Operator decisions, approved in principle (Draft 2 review), unchanged here.** State family; constants as
PROVISIONAL ENGINEERING CONSTANTS; collector-first fitting direction; the eight-run production estimation budget;
selection-by-name with no promotion rule. Implementation and fitting remain HELD.

**Amendment A — the five issues from the Draft 3 review.**

| # | Issue | Amendment | Where | Test |
|---|---|---|---|---|
| A1 | The permutation control assumed away the EXP-002 problem: row permutation also destroys time structure, `A = 0` constrains only the conditional mean, and equality of population problems does not imply equality of two particular fitted models' expected scores | `C_PERM` is SYNTHETIC-ONLY and removed from the historical comparator table; the generator's independence/exchangeability assumptions, the permutation UNIT (whole sessions), independent evaluation samples and the exact expectation that is zero are all stated; `JOINT − C_DIAG` is retained as the cross-block dependence contrast because permuting predictors does not remove residual cross-block correlation | §4.2, §6.2 | frequency report only |
| A2 | The endpoint is an approximate measurement, not the minute-15 state; and `A(t)` admitted quotes from BEFORE the target, so `δ = 0` could coexist with a nearly 120 s-stale quote | per-quote SIGNED offset from the target, receipt lag and slice dispersion recorded; a symmetric permissible-offset window replaces the one-sided delay; the tighter sensitivity uses the ACTUAL offsets; the estimand is renamed and labelled a delayed/stale-quote PROXY | §1.4 | **T32** |
| A3 | Restricted residuals define a TEST of zero, not a confidence interval for a possibly non-zero coefficient; and restricting every equation imposes more than the hypothesis under test | one construction only: confidence interval BY TEST INVERSION, with the inversion algorithm specified; exactly ONE coefficient in ONE equation is restricted and the other equations are untouched; same-seed reproduction is labelled reproducibility, not inferential correctness | §2.3 | **T33** |
| A4 | `E_sel = min(E[S1], E[S2])` is a minimum of two ESTIMATED means with no stated standard error, and near-ties carry selection uncertainty | paired path-level samples retained for both scenarios; the WAIT gate requires SIMULTANEOUS lower confidence limits above zero for BOTH scenarios over the candidate × scenario family; the runner-up comparison is explicitly a HEURISTIC SCREEN with no confidence claim; `E[min(S1,S2)]` is forbidden as a substitute | §3.1, §5.3 | **T34** |
| A5 | The block-sequential construction changes execution-block marginal tails as well as coupling; size penalties must not rerank | Retain the sampler, label its contrast COMPOUND_COUPLING_LAW_CONTRAST, preserve IV-block draws, and select without size before a selected-only risk/economic veto; spread ranking influence disclosed | §2.4, §2.1, §5.3 | **T35, T36** |

**Corrections in Draft 3** (each from the Draft 2.1 review; all are corrections to the existing design, no new
capability): §2.5 the pricing map is anchored at the frozen strike `K_atm` so it reproduces the stored ATM IV
exactly, and the log-IV sign claim is replaced by range guards; §1.4 one endpoint-selection algorithm shared by
training, the simulation target and scoring, with the timing error recorded; §3.2 time-to-expiry recomputed at the
extension endpoint and all randomness pre-generated per scan so candidate ordering cannot change any path;
§3.1/§4.4/§5.1 the "bounds" and "cannot flatter" claims are withdrawn and replaced by named accounting SCENARIOS
with an order-free selection value, and every forecast-quality result is labelled population-conditional whenever
any exclusion occurs; §6.2 the null control becomes a predictor-permutation comparator whose population contrast is
exactly zero, the zero-dynamics identity is split into a compatible-states and a matched-policy variant, and the
finite-ensemble rank reference is specified; §2.3/§1.5 only complete four-output rows enter the joint fit, the
missingness-ceiling claim is corrected, and the exclude-versus-refuse contradiction is resolved; §2.3/§7 the wild
cluster bootstrap is fully specified, its cross-session limitation stated, and the inference-resampling budget
separated from the production estimation budget; §1.3 every R4 read requires explicit R4 authorization, inheriting
nothing from EXP-001B, with role approval separated from run authorization.

---

## Review patch to e8c6a53 — APPLIED AND ACCEPTED (`24b055e`)

The specification-only patch retained the sampler's equations and corrected its marginal-preservation claim: the
coupling contrast is COMPOUND and isolated dependence attribution remains unestablished. It reconciled
per-scenario uncertainty, no-size ranking and selected-only veto accounting, the bootstrap null construction and
its numerical search limits, and the synthetic averaged-null report. The matrix transpose corrected the documented
orientation, not the intended regression. The reviewer verified that the commit changes only this file and that
its blob matches the supplied revision, and accepted both the compound-attribution scope and the selected-only
economic veto as design choices.

**Closeout after acceptance (this commit).** Four documentation findings survived the patch and are fixed here,
none of them a model change: the stale claim in §6.2 that `JOINT − C_DIAG` answers cross-block residual dependence
(it does not — §2.4 makes that contrast compound); the status line's branch and lifecycle wording (above); the
per-block truncation fields in the §7 record schema (§7); and the disclosure that the execution-block attribution
term now bundles the size-veto policy (§4.3). The repeated-gate coverage disclosure is added at §5.3.

## 0. Objective, horizon, non-goals

At decision instant `t_d`, estimate how the underlying price, the ATM implied volatility, the slice skew, the
relative spread and the available size evolve JOINTLY over `H = 900 s`; reprice each eligible expression inside
every simulated future state; compare expressions against WAIT on after-cost economics; act only when the ranking
is decision-relevant under the declared uncertainty rules; record everything so each probability, selection and
paper order is attributable to information recorded before its outcome.

**What the joint model is.** A CONDITIONAL model of option-state change given the SAME-WINDOW underlying path
statistics. It does not forecast the underlying: the underlying path comes from the existing GARCH-t engine and the
option state is drawn conditional on that path. This determines the estimator (§2.3).

**Non-goals (V1).** Multi-leg expressions; intraday refitting; jumps; feedback from option state to the underlying
within the horizon; time-of-day parameter buckets; contract-specific executable conditions; any claim of
calibration, fill probability or positive expectancy.

**Governance constants unchanged.** Kernel limits ($500 trade, $1,500 aggregate, $600 same underlying, $1,000
family, $1,000 drawdown halt); envelope `min(ref ask × 1.1, $5.00)`; `EXIT_AT_HORIZON_15M_V1` (due +900 s, window
120 s, ≤ 5 attempts); maintenance block; collector observation-only; fees SYNTHETIC / UNVERIFIED; no broker orders;
no promotion rule.

---

## 1. Information available at decision time

### 1.1 Input contract

Every input carries `event_time`, `available_time`, `source`, `revision_policy`, `max_age_s`, `quality`, or it is
refused `INPUT_CONTRACT_MISSING:<field>`. Bars (event = bar start; available = bar complete + receipt lag;
revisions visible only if `available ≤ t_d`; max age 120 s); underlying NBBO (15 s); option quotes (indicative
120 s; execution 15 s at the boundary); chain membership (a contract absent from the latest snapshot is INELIGIBLE,
never carried forward); open interest (feature only, never a size proxy); fee schedule; calendar; fitted
parameters. Refusals: `FUTURE_INPUT:<name>` for `available_time > t_d` (a firewall violation, not staleness);
`INPUT_STALE:<name>`.

### 1.2 Asynchronous underlying and option quotes

`t_d` is the boundary clock reading. `S_0` is the last completed bar close with `available ≤ t_d`; the NBBO mid,
when VALID, is recorded as `S_nbbo` with `spot_async_gap = log(S_nbbo/S_0)`, which must satisfy `|gap| < 0.002`
else `SPOT_ASYNC_GAP_EXCEEDED` → WAIT. Implied vol is inverted with the underlying reference at the option quote's
OWN time (corpus `underlying_ref` when `moneyness_status == CAUSAL`, else the latest underlying observation with
`event_time ≤ quote.event_time` and gap ≤ 5 s, else `IV_UNUSABLE: NO_CONTEMPORANEOUS_UNDERLYING` — such a quote may
still price as an execution quote but supplies no IV or skew). Slice quantities require joint coherence (§1.4).
Every quote passes `sanitize_quote` before any use (r3 rule).

### 1.3 Dataset-and-role permissions, and R4 authorization (nothing is inherited)

The period policy is a property of a DATASET and a ROLE, not of the calendar. The registry
(`apex/joint_wb/permissions.py`, to be written) is the single authority; a read of an unregistered dataset refuses
`DATASET_NOT_REGISTERED`. **No prior experiment's admission authorizes anything here.** EXP-001B registered a
different study with a different target; it confers no R4 permission. Every R4 read requires an explicit R4
authorization artefact, named below.

| Dataset | Path | Role | R4 permitted uses | R4 authorization required |
|---|---|---|---|---|
| `HIST-A-OPTIONS` 2016–2019 | `/apex-data/history-a/options_history` | TRAIN | fitting; development replay | `R4-FIT-001` (not yet requested) |
| `HIST-A-OPTIONS` 2020–2021 | same | VALIDATION | development replay; fitting only if `R4-FIT-001` names this role | `R4-FIT-001` |
| `HIST-A-OPTIONS` 2022–2024 | same | EVALUATION_SEALED | none | none obtainable in this brick |
| `HIST-A-OPTIONS` 2025 → 2026-08-28 | same | RESERVE_SEALED | none | none obtainable in this brick |
| `PILOT-COLLECTION` | `/apex-data/pilot_collection/` | PROSPECTIVE_OBSERVATION | fitting; calibration reporting | ROLE approved in principle (operator, Draft 2 review) **plus** a separate run authorization `R4-FIT-002` naming the session range, the fit cutoff and the evaluation population |
| `PILOT-LEDGER` | live options ledger | PROSPECTIVE_DECISION | outcome evidence only; never fitting | n/a (never fitted) |

Two statements required by the review:

1. **Role approval is not run authorization.** Approving `PILOT-COLLECTION` as a fittable role does not authorize
   any particular fitting run. Each run needs `R4-FIT-002` with its own cutoff and population, recorded and hashed
   before the run starts.
2. **Prospective collection is not out-of-sample status.** That observations were gathered after the pilot began
   establishes WHEN they were recorded. It does not make a later evaluation out-of-sample. Out-of-sample status is
   a property of the fit/evaluation split (§1.6) and is checked there, per decision.

### 1.4 Clocks, the single endpoint-selection algorithm, and frozen contract identity

**Frozen identity.** At `t_d` the pair fixes, and nothing re-selects later: expiration `E*` (first with DTE ≥ 21 at
`t_d`); `K_atm` (minimizes `|K − S_0|`, ties → LOWER strike); skew strikes `K_∓` (nearest to `S_0·e^{∓0.02}`, ties →
LOWER, must be distinct); the right-aggregation source (`BOTH | CALL_ONLY | PUT_ONLY`). A change of aggregation
source at the endpoint makes the row INCOMPLETE (`IV_SOURCE_CHANGED`): a call-to-put switch is not a market move.

**`ENDPOINT_SELECTION_V1` — one algorithm, used by training, by the simulation target and by scoring.** Let the
frozen keys be `R = {(E*, K_atm, CALL), (E*, K_atm, PUT), (E*, K_−, ·), (E*, K_+, ·)}`, and let `A(t)` be the
quotes with `event_time ≤ t`, `available_time ≤ t`, each passing `sanitize_quote`.

```
t_e = min { t ∈ [t_d + H , t_d + H + δ_max] :  the ATM keys of R are present in A(t)
                                               AND all quotes used for R at t have event times
                                               within SLICE_COHERENCE_S = 30 s of each other
                                               AND every used quote j satisfies |o_j| ≤ o_max }
δ   = t_e − (t_d + H)                      selection delay,      δ_max = 60 s
o_j = event_time_j − (t_d + H)             SIGNED per-quote offset from the TARGET (negative = stale)
                                           o_max = 60 s, symmetric
```

**A2 — the selection delay is not the measurement error.** `A(t)` admits any quote with `event_time ≤ t`, so
Draft 3 allowed `δ = 0` alongside a quote whose event time was nearly 120 s before the target: reporting only `δ`
hid that. Every row therefore records, per selected quote: the signed offset `o_j`, the receipt lag
(`available_time_j − event_time_j`) and the slice dispersion (`max_j event_time_j − min_j event_time_j`), plus the
row summaries `max_j |o_j|` and `mean_j o_j`. The permissible-offset window is now symmetric and binding: a quote
with `|o_j| > o_max` cannot be used at all, so a stale quote can no longer enter under `δ = 0`. The declared
tighter sensitivity re-runs the estimation on rows with `max_j |o_j| ≤ 15 s` — the ACTUAL offsets, not `δ`.

The selection is JOINT: one instant `t_e` for the whole key set, then per-key lookup AT that instant (§1.5). Draft
2.1's per-contract "earliest quote" rule could return a set that never jointly existed; it is replaced. If no such
`t_e` exists the row is EXCLUDED (`ENDPOINT_NOT_COHERENT`) and counted.

**One selection rule for all three uses, and an honestly named estimand.** Training, the simulation target and
scoring use this one algorithm. But a shared rule does not remove measurement bias, and a minute-16 (or
minute-14) observation is not the minute-15 state. The estimand is therefore named and labelled everywhere it is
reported:

> `TARGET_PROXY_V1` — a 15-minute-ahead forecast ASSESSED AGAINST A DELAYED-OR-STALE QUOTE PROXY: the realized
> quantity is measured from quotes whose event times lie within ±60 s of `t_d + H`, with the per-quote offsets,
> receipt lags and slice dispersion recorded. No observation model corrects the discrepancy in V1; until one does
> (§9), every CRPS, rank, Brier and attribution number is a statement about this proxy, not about the state at
> exactly `t_d + H`.

The `δ` and `|o_j|` distributions are reported with every fit. Rows with no admissible `t_e` are excluded and
counted. **Scoring uses the same proxy:** CRPS and rank scores compare the simulated distribution of the exit bid
at `t_d + H` against the realized bid measured under `TARGET_PROXY_V1`. The execution extension (§3.2) is a
different object, an execution mechanism rather than a second forecast target.

| Clock | Definition | Rule |
|---|---|---|
| `t_d` | decision instant | every START input: `available_time ≤ t_d`. No exception |
| `t_e` | endpoint measurement instant | `ENDPOINT_SELECTION_V1`, `δ ≤ 60 s`, recorded per row |
| Availability deadline | `t_e + 60 s` | every END input `available_time ≤` this; a later arrival does not rescue the row |
| Fit eligibility | fit start `t_fit` | every used row: availability deadline `≤ t_fit`; the `Model.fit` firewall enforces it |
| Execution extension | `t_d + H + W_end`, `W_end = 120 s` | §3.2 only; never a state-forecast target |

**Missing endpoints.** A row with no `t_e` is EXCLUDED with its reason and counted. Above a 10 % exclusion rate the
fit refuses `ENDPOINT_MISSINGNESS_EXCESSIVE`. **This ceiling is an engineering refusal threshold only.** It does
NOT establish that complete-case estimates below it are unbiased: if missingness is informative (illiquid or fast
states) a complete-case fit is biased at any rate, and that limitation is recorded with the census. No imputation
in V1.

### 1.5 Per-key lookup at the selected instant: deterministic tie-breaking and missing data

Lookup is by EXACT key at `t_e`; no nearest-strike or nearest-expiry substitution (a substitution measures contract
re-selection, not market evolution).

| Situation | Rule | Record |
|---|---|---|
| Key absent at `t_e` | quantity MISSING | `ENDPOINT_KEY_ABSENT:<key>` |
| Several quotes for the key at `t_e` | latest `event_time ≤ t_e`; ties → earliest `available_time`; ties → lowest `source` id (lexicographic); still tied → `ENDPOINT_AMBIGUOUS:<key>`, row INCOMPLETE | census |
| Quote present but fails `sanitize_quote` | MISSING with the validator's reason (never silently used) | census |
| ATM key missing | row INCOMPLETE (the ATM leg defines three of the four coordinates) | census |
| A skew strike missing | skew MISSING → **row INCOMPLETE for the joint fit** (§2.3); at DECISION time the comparators needing skew are labelled `SKEW_DEGRADED` | census |

Every tie-break is deterministic and total; no lookup depends on container or file ordering (T22 shuffles the input
and asserts an identical result).

### 1.6 Walk-forward conditions on any fitting source

1. A decision at `t_d` may use only parameters whose `fit_cutoff` precedes the start of that session day and whose
   every training row satisfies `availability deadline ≤ fit_cutoff`.
2. No observation may appear in both the fitting set and the evaluation set of the same decision; the attribution
   population is checked against every contributing fit's row index and an intersection refuses `FIT_EVAL_OVERLAP`
   with the offending row ids. This check — not the collection date — establishes out-of-sample status.
3. A recorded forecast is immutable: a later fit produces parameters for FUTURE decisions only and never revises,
   re-scores or re-labels a forecast already on disk (T23).
4. Identical for `PILOT-COLLECTION` and, when authorized, for `HIST-A-OPTIONS`.

---

## 2. State, dynamics and estimator

### 2.1 State variables (positivity by construction)

| Symbol | Definition | Note |
|---|---|---|
| `r` | log underlying return over the horizon | from the GARCH-t path |
| `q` | realized path variance `Σ e_t²` over the horizon | same path; conditioning variable |
| `x_iv` | `log iv(E*, K_atm)` — log IV at the FROZEN strike | `iv = exp(x_iv) > 0`; `x_iv` itself is negative whenever IV < 1, which is normal |
| `x_sk` | `g = [log iv(K_−) − log iv(K_+)] / log(K_− / K_+)`, dimensionless | anchor-free: the denominator is the same for any reference point |
| `x_sp` | `log max(sp_obs, sp_floor)`, `sp = (ask − bid)/mid` at `(E*, K_atm)`, `sp_floor = 1e-4` | floored count recorded; > 5 % floored refuses `SPREAD_FLOOR_EXCESSIVE` |
| `x_sz` | `log(1 + sz)`, `sz = min(bid_size, ask_size)` at `(E*, K_atm)` | `sz = exp(x_sz) − 1 ≥ 0`; simulated states floored at 0, floor count recorded |

`Δx = x(t_e) − x(t_d)` per coordinate, measured on the FROZEN keys.

**ATM size is a declared PROXY — `SIZE_PROXY_V2: SELECT_THEN_VETO` (A5).** Draft 3 promised the size proxy could
"never promote one candidate over another" while also letting it reduce candidate values; those cannot both hold,
because lowering one candidate's value can hand the top rank to another. V1 resolves it by SEQUENCE, not by claim:

1. **Rank without size.** `E_sel` and the ranking are computed under `ASSUME_AVAILABLE` (the size state plays no
   part), so no candidate can be promoted by another's size penalty.
2. **Veto the selected candidate only.** The size model is then applied to `c*` alone: if its
   `MODEL_CONDITIONAL_AVAILABILITY` failure rate exceeds the §5.3 rule-4 threshold, the decision is WAIT. There is
   NO substitution with the runner-up — a veto ends the scan's trade, it does not choose a different trade.
3. **Selected-only economic veto.** Retain the selected identity and no-size ranking. Re-evaluate c* under
   modelled size on the SAME paths and apply §5.3 rule 4. These values can veto to WAIT, never choose a substitute.
   Numerical failure or unavailable size also yields WAIT. Report ranking and veto values separately.
   This additional economic veto is a proposed conservative policy choice, not a validated threshold.

The alternative — permitting re-ranking and disclosing that the proxy carries selection authority — remains
available but is NOT adopted in V1. `MODEL_CONDITIONAL_AVAILABILITY` is a model-conditional figure, not a fill
probability.

**The spread state is also an ATM proxy, and it DOES affect ranking.** `x_sp` is measured at `K_atm` and applied
to every candidate in §2.5. Unlike size it enters the value used for ranking, so it can re-rank candidates. That
influence is DISCLOSED here rather than claimed away; contract-specific spreads are named in §9.

### 2.2 Dynamics (JOINT-V1)

Underlying: unchanged (GARCH-t or declared EWMA fallback, regime mixture, truncated-t innovations of r3) producing
`(r, q)` per path. Option state, conditional on the SAME path's `(r, q)`, with NO contemporaneous option-state
variable on any right-hand side:

```
Δx = A z + ε
z  = ( 1 , r , |r| / sqrt(v̂) , log q − log v̂ )'     v̂ = E[q] at t_d (GARCH integrated variance), t_d-measurable
Δx = ( Δx_iv , Δx_sk , Δx_sp , Δx_sz )'             A is 4×4
ε  ~ BLOCK_SEQUENTIAL_V1(Σ, c)                     §2.4; not a single four-dimensional TMVN
```

**Predictor domain (checked BEFORE any `log` or `sqrt`).** `v̂ ≤ 0` or non-finite → the whole decision refuses
`SCALE_VARIANCE_INVALID` → WAIT, before any path is simulated. A path with `q ≤ 0` or non-finite → that path is
`PREDICTOR_INVALID` and the CANDIDATE is refused `REJECTED: PREDICTOR_INVALID_PATH_PRESENT` with the count and the
first offending path index (no silent dropping, §3).

**Training-row validity: the exclude-versus-refuse split** (Draft 2.1 contradiction resolved).

- A ROW containing a non-finite or out-of-domain value in `z` or `Δx`, or lacking any of the four outcomes, is
  EXCLUDED during row construction and counted in the census (subject to the §1.4 ceiling).
- After exclusions, a non-finite value ANYWHERE in the assembled `Z` or `Y` is an implementation fault, not data:
  the fit refuses `NONFINITE_INPUT` (T15, T26).

**Declared assumptions, each with a recorded diagnostic:** `E[ε | r, q] = 0` (residual correlations with `r`,
`|r|`, `r²` reported; a flag, not a refusal); linearity in `z`; parameters constant across regimes and across the
session; Gaussian residuals before truncation (Jarque–Bera per equation, `RESIDUAL_NONGAUSSIAN_FLAG`); no feedback
from option state to the underlying within the horizon.

### 2.3 Estimator and inference

**Estimator.** Common design `Z` (n×4), complete outcomes `Y` (n×4):

```
B̂ = (Z'Z)^{-1} Z'Y        Â = B̂'        Ê = Y − Z B̂        Σ̂ = Ê'Ê / (n − k),  k = 4
```

Rows of B̂ index predictors and columns index outcomes; Â = B̂' has outcome rows for Δx = Â z + ε.
The transpose matters even though both matrices happen to be 4×4.

With identical regressors in every equation, SUR collapses to equation-wise OLS (Zellner), which is why a common
design is chosen. **Only COMPLETE four-output rows enter the fit**: a row missing skew (or any coordinate) cannot
contribute to a common-design estimate or to a cross-equation covariance, so it is excluded and counted, never
partially used. Draft 2.1's "retained for the other three coordinates" is withdrawn.

Refusals: `COVARIANCE_NOT_PD`; `DESIGN_RANK_DEFICIENT` (`cond(Z'Z) > 1e10`); `INSUFFICIENT_HISTORY` (n < 200);
`DEGENERATE_STATE` (any outcome column constant); `COEFFICIENT_OUT_OF_BOUNDS` (declared bounds; refused, never
clipped); `NONFINITE_INPUT` (assembled matrices).

**Inference.** Rows are serially dependent: volatility and liquidity cluster within a session, and the endpoint
measurement at `t_e` can fall inside the next scan's start window (`ACKNOWLEDGED_OVERLAP`; on a finer grid rows
overlap by construction).

| Quantity | Estimator | Use |
|---|---|---|
| Coefficient covariance | CR1 cluster-robust, cluster = calendar SESSION | default reported SE |
| Coefficient interval (primary) | wild cluster bootstrap-t, specified below | every interval supporting a claim |
| HC1 | as computed | DESCRIPTIVE ONLY, labelled, never supports a claim |
| Attribution contrasts | session-block bootstrap (§5.1) | all reported contrasts |

**`WILD_CLUSTER_BOOTSTRAP_CI_BY_INVERSION_V1` — ONE construction (A3).** Draft 3 mixed two things: restricted
residuals impose `H₀: a_ij = 0`, which defines a TEST OF ZERO, not a confidence interval for a possibly non-zero
coefficient; and "re-estimating without that regressor" restricted every equation, imposing far more than the
hypothesis under test. Both are replaced by confidence intervals BY TEST INVERSION.

*Scope of one interval.* An interval is for exactly ONE coefficient `a_ij` in exactly ONE equation `i`. Because
the design is common and estimation is equation-wise, the CR1 covariance of equation `i`'s coefficients depends
only on equation `i`'s residuals: the other three equations are UNTOUCHED and play no part. (Cross-equation joint
hypotheses are not in V1; if ever added, the per-cluster weight draw is shared across equations for exactly those
statistics — that is the only reason weight sharing would be needed.)

*The test at a candidate value.* For `H₀: a_ij = a₀`, impose the SINGLE restriction in equation `i` only: regress
the offset outcome `y_i − a₀ · z_j` on the remaining regressors of `z`, take the restricted residuals `ẽ_i`, and
add back the offset to define mu0_i = a₀ z_j + Z_{-j} beta0_{-j}, set ẽ_i = y_i − mu0_i, and
form B = 2,000 replicates y*_{i,g} = mu0_{i,g} + w_g · ẽ_{i,g} with Rademacher `w_g` drawn once per cluster
`g` (seed 11). Each replicate's statistic is `(â*_ij − a₀)` studentized by the CR1 cluster-robust SE computed
within that replicate. The bootstrap p-value is (1+k)/(1+B_valid), with k valid absolute statistics at least as large as the
observed one. Generate and retain one B-by-G weight array per equation/fit and reuse it at every a₀.
Fixed-design rank is checked before resampling; a replicate cannot change Z's rank.

*Numerical inversion and its limits.* Let b be the unrestricted estimate and se its positive finite CR1
standard error; otherwise refuse the interval. Evaluate 25 equally spaced points on [b−4se,b+4se].
Accept a tested value when p(a₀)>0.05. If an endpoint is accepted, double its distance from b at most three
times and evaluate 25 equally spaced points in each newly added segment. Cache every evaluation.
Bisect every adjacent tested accepted/rejected pair until width <=1e-4 se, at most 30 iterations per pair.
Return sampled acceptance components and their convex hull, with all tested points and p-values.
Detected separated components receive CI_NONCONVEX_ACCEPTANCE. An accepted outer endpoint after the search
cap or unresolved bisection receives INVERSION_SEARCH_UNRESOLVED; do not issue a finite endpoint on that side.
A finite search cannot prove unboundedness or exclude unsampled acceptance islands. Even a finite returned
hull is labelled NUMERIC_TEST_INVERSION_APPROXIMATION. No exact acceptance-set claim is made.

*Stability and honesty.* `G` = session clusters is recorded beside every interval, with the `t_{G−1}` reference
noted when `G < 30`. A replicate with non-finite or non-positive coefficient-specific CR1 variance is DISCARDED
and counted; above 1 % discarded the interval refuses `BOOTSTRAP_UNSTABLE`. A same-seed reproduction test (T33)
establishes REPRODUCIBILITY only — not inferential correctness, whose only evidence here is the coverage FREQUENCY
report of §6.2, which gates nothing.

**Declared limitation.** Session clustering — and the session-block bootstrap — assumes independence ACROSS
clusters. Dependence BETWEEN sessions (multi-day volatility regimes, weekly effects) is NOT addressed by either.
Every interval is valid only under that assumption, which is stated wherever it is reported; §9 names the remedy.

### 2.4 Block-sequential law: retained construction, corrected attribution

Retain Draft 3.1's sampler. This amendment corrects its interpretation and does not introduce a new copula.
Partition Σ̂ into IV/skew block 1 and spread/size block 2, each dimension 2:
M = Σ̂₂₁ Σ̂₁₁⁻¹; C = Σ̂₂₂ − M Σ̂₁₂. Require positive definiteness before Cholesky operations.

Independently generate standard two-dimensional vectors w1,w2 by radial rejection of N(0,I2) at
c²=chi2_quantile(2,0.9999), dividing accepted draws by sqrt(kappa).
kappa=F_chi2_4(c²)/F_chi2_2(c²); their population covariances are I2.
Pre-generate named base vectors per path, block and horizon before candidate evaluation.

    e1       = chol(Σ̂₁₁) w1
    e2_joint = M e1 + chol(C) w2
    e2_diag  = chol(Σ̂₂₂) w2

JOINT uses (e1,e2_joint); C_DIAG uses (e1,e2_diag); C_IVSK uses e1;
C_IV takes e1's FIRST COORDINATE, never a separately truncated 1-D draw;
C_EXEC uses e2_diag. Inactive state changes are zero. Independent extension base vectors use the same law.

Exact POPULATION moment identities:
Cov(e2_joint)=M Σ̂₁₁ M' + C=Σ̂₂₂; Cov(e1,e2_joint)=Σ̂₁₂;
Cov(e2_diag)=Σ̂₂₂ and Cov(e1,e2_diag)=0.
These identities do not assert exact sample covariance.

The entire execution-block marginal law generally DIFFERS: JOINT sums two bounded random vectors;
C_DIAG transforms one. BOTH the conditional mean and conditional residual covariance change.
Equal covariance does not guarantee equal tail shape.
JOINT − C_DIAG is therefore COMPOUND_COUPLING_LAW_CONTRAST, never an isolated correlation effect.
Carry that scope on each reported contrast and trace. Marginal-preserving dependence attribution is outside V1.

T35 verifies shared block-1 draws, the C_IV projection, the matrix moment identities and different conditional
covariances for nonzero M. A bounded scalar fourth-moment fixture demonstrates unequal marginal laws despite
equal variance. Empirical covariance and tail measurements are statistical reports only.

### 2.5 Pricing model inside a simulated state (anchored at the frozen strike)

Given a path state `(S_H, x_iv, x_sk, x_sp, x_sz)`, a contract `(K, E*)` and an evaluation instant `t_eval`:

```
log iv_K  = x_iv + x_sk · log( K / K_atm )                 ← ANCHORED AT THE FROZEN STRIKE
T(t_eval) = (expiry_epoch − t_eval) / (365 · 86400)        ← recomputed at EVERY evaluation instant
mid       = BSM( S_H, K, T(t_eval), iv_K, r=q=0, right )
sp_H      = exp(x_sp) ;  sz_H = max(0, exp(x_sz) − 1)
bid_H     = mid · (1 − sp_H / 2)                           may be ≤ 0 when sp_H ≥ 2 → §3
```

**Anchor correction (Draft 2.1 defect).** `x_iv` is log IV at the FIXED strike `K_atm`, at both ends of the pair, so
the slice must be anchored there. Draft 2.1's `log iv_K = x_iv + g·log(K/S_H)` returned `x_iv + g·log(K_atm/S_H)` at
`K = K_atm`, which differs from the stored `x_iv` whenever `S_H ≠ K_atm` and `g ≠ 0`. The anchored form satisfies
`iv_{K_atm} = exp(x_iv)` for every state (T27). Redefining `x_iv` as a moving-ATM intercept is a DIFFERENT state
variable and is not adopted in V1.

**Numerical guards (replacing Draft 2.1's wrong sign claim).** `iv_K = exp(log iv_K) > 0` for every finite
exponent, but `log iv_K` itself may be negative and carries no sign guarantee. Guard by RANGE: require
`log iv_K ∈ [log 1e-4, log 50]`, `T(t_eval) > 0`, `S_H` finite and positive. Any violation makes that path
`UNPRICEABLE` (→ candidate refused, §3.1), so `exp` can neither overflow nor underflow.

The same pricing model is used by EVERY comparator, so a contrast measures the state forecast and nothing else.

---

## 3. Complete path accounting

### 3.1 Cases and the two accounting scenarios

Policy `PATH_ACCOUNTING_V1`. For one candidate and one path, entry at the validated ask `a` (100 multiplier, fees
`f_in + f_out`), evaluated at the PRIMARY endpoint `t_d + H` and, if not achievable, once at the EXTENSION endpoint
`t_d + H + W_end` (§3.2):

| Case | Condition | Net on that path |
|---|---|---|
| ACHIEVED | `bid > 0` and `sz ≥ 1` at the evaluated endpoint | `100 (bid − a) − f_in − f_out` |
| NOT_ACHIEVABLE | `bid ≤ 0` (includes `sp ≥ 2`) or `sz < 1` at both evaluations | scenario-dependent, below |
| UNPRICEABLE | any §2.5 guard violated | no number exists → candidate `REJECTED: UNPRICEABLE_PATH_PRESENT` (stage recorded) |
| PREDICTOR_INVALID | `q ≤ 0` or non-finite (§2.2) | candidate `REJECTED: PREDICTOR_INVALID_PATH_PRESENT` |

**Accounting scenarios, not bounds.** Draft 2.1 called these "conservative" and "optimistic" bounds. They are not
bounds: a modelled midpoint is not an upper bound on eventual liquidation value, and the two are not even ordered —
their difference is `100·mid_last − f_out`, negative whenever `mid_last < f_out/100`. They are therefore named
SCENARIOS and the selection is made order-free:

```
S1  SCENARIO_WRITE_OFF        NOT_ACHIEVABLE path → net = −100 a − f_in
S2  SCENARIO_MID_LIQUIDATION  NOT_ACHIEVABLE path → net = 100 (mid_last − a) − f_in − f_out
E_sel = min( E[S1] , E[S2] )                  ← the only value used for selection and ranking
U     = | E[S1] − E[S2] |  ≥ 0                ← accounting-scenario spread, non-negative by construction
```

Because `E_sel` is a minimum and `U` an absolute difference, the §5.3 rule-4 gate cannot pass through an inverted
ordering (T28 plants `mid_last < f_out/100` and asserts both properties).

**A4 — `E_sel` is a minimum of two ESTIMATED means and carries no `sd/√N` standard error.** The path-level PAIRED
samples `{net_k^{S1}}` and `{net_k^{S2}}` (identical on ACHIEVED paths, differing only on NOT_ACHIEVABLE ones) are
RETAINED for every candidate, together with their paired differences against WAIT and against the runner-up. Which
scenario is the smaller is itself uncertain near a tie, so no single scenario's standard error is used as if it
were the standard error of the minimum; §5.3 rule 1 instead requires a SIMULTANEOUS statement over both scenarios.
`E_sel` is a RANKING value (a declared choice rule), not an estimate carrying a confidence claim.
**`E[min(S1, S2)]` — the path-by-path minimum — is FORBIDDEN as a substitute: it is a different economic quantity,
and T34 asserts the two differ on a fixture so the substitution cannot creep in.**

PATH_ACCOUNTING_V1 takes an explicit size_policy. ASSUME_AVAILABLE ignores size in the achievable predicate;
MODELLED_SIZE requires sz>=1. Retain separate scenario arrays, means and U values for ranking and selected-only
veto. The model-conditional availability failure rate never changes the recorded ranking.

### 3.2 Execution extension (exact)

`H = 900 s` = 15 one-minute bars; `W_end = 120 s` = 2 further bars, matching `EXIT_AT_HORIZON_15M_V1.window_s`.

**All randomness is pre-generated per scan, before any candidate is evaluated.** For each of the `N` paths the scan
draws, in one deterministic block indexed by path and keyed by the single recorded seed: 17 underlying bars
(15 + 2), the horizon option-state innovation, and the extension option-state innovation. Candidate evaluation is
then a PURE FUNCTION of that block. Draft 2.1's "continue the RNG stream when an extension is needed" made later
paths depend on which candidates happened to need extensions, so candidate ordering could change the paths; that is
removed. T29 permutes candidate order and asserts every underlying path, every option-state draw and the entire
candidate table are bitwise unchanged.

**Extension dynamics** (`EXTENSION_SCALING_V1`, a declared assumption, not an estimate):

```
v̂_ext  = v̂ · (2/15)
z_ext  = ( 1 , r_ext , |r_ext| / sqrt(v̂_ext) , log q_ext − log v̂_ext )
Δx_ext = (2/15) · A z_ext  +  sqrt(2/15) · ε_ext           ε_ext from the pre-generated block
T_ext  = (expiry_epoch − (t_d + H + W_end)) / (365 · 86400)  ← recomputed; Draft 2.1 reused T at t_d + H
```

Linear-in-time drift and square-root-of-time innovation scaling are assumptions, recorded on every simulation, with
the innovation scale ×1.5 in the adverse set (§5.3 rule 3).

| Situation | Outcome |
|---|---|
| PRIMARY priceable and achievable | ACHIEVED at primary; extension not evaluated (still pre-generated) |
| PRIMARY priceable, not achievable; EXTENSION priceable and achievable | ACHIEVED at extension; delay recorded |
| PRIMARY priceable, not achievable; EXTENSION priceable, not achievable | NOT_ACHIEVABLE; `mid_last` = extension mid; `scenarios_from: EXTENSION` |
| PRIMARY priceable, not achievable; EXTENSION predictor invalid (`q_ext ≤ 0` / non-finite) | NOT_ACHIEVABLE; `mid_last` = primary mid; `scenarios_from: PRIMARY`; `extension_undefined_n` incremented; the path is valued, never dropped |
| PRIMARY UNPRICEABLE | candidate REJECTED (`stage: PRIMARY`); no extension attempted |
| EXTENSION UNPRICEABLE | candidate REJECTED (`stage: EXTENSION`) |

Counters (`achieved_primary_n`, `achieved_extension_n`, `not_achievable_n`, `extension_undefined_n`,
`unpriceable_n` by stage) are on the `joint_forecast` record.

---

## 4. Baselines, comparators, decomposition, refusals

### 4.1 Two distinct reference objects

| Object | What it is | Role |
|---|---|---|
| `OPERATIONAL_REFERENCE` | the FROZEN r3 policy `FULL_FUNNEL_V1` at pin `525340c`, with its own pricing map, accounting and decision rule | the "what runs today" line; reported alongside, never the attribution baseline |
| `MATCHED_FROZEN` | R4's pricing map (§2.5), accounting (§3) and decision rule (§5.3), with `Δx ≡ 0` | the attribution baseline: identical machinery, frozen state |

### 4.2 Comparator table

| Id | IV block | Exec block | Residual covariance | Size policy |
|---|---|---|---|---|
| `MATCHED_FROZEN` | 0 | 0 | — | `ASSUME_AVAILABLE` |
| `C_IV` | `Δx_iv` only | 0 | first coordinate of shared e1 | `ASSUME_AVAILABLE` |
| `C_IVSK` | both | 0 | 2×2 | `ASSUME_AVAILABLE` |
| `C_EXEC` | 0 | both | e2_diag | rank without size; selected-only veto |
| `C_DIAG` | both | both | e1,e2_diag | rank without size; selected-only veto |
| `JOINT` | both | both | e1,e2_joint | rank without size; selected-only veto |

`C_PERM` is NOT in this table (A1): it is a SYNTHETIC-ONLY diagnostic defined in §6.2 and is never run on
historical or prospective data, never enters an attribution report, and never appears in a decision path.
`JOINT − C_DIAG` is retained as COMPOUND_COUPLING_LAW_CONTRAST (§2.4). The synthetic predictor-permutation
diagnostic answers a separate question; neither isolates residual dependence in this version.

C_DIAG has independent residual blocks conditional on the underlying path. Output coordinates can still be
dependent through that path. Contrasting JOINT also changes execution-block marginal tails, as §2.4 states.

### 4.3 Exactly additive decomposition

With `V(·)` a functional on one fixed population:

```
Sh(F1) = ½[V(C_IVSK) − V(MATCHED_FROZEN)] + ½[V(C_DIAG) − V(C_EXEC)]     F1 = IV block
Sh(F2) = ½[V(C_EXEC) − V(MATCHED_FROZEN)] + ½[V(C_DIAG) − V(C_IVSK)]     F2 = exec block
D      = V(JOINT) − V(C_DIAG)                                            compound coupling-law change (§2.4)
J      = V(JOINT) − V(MATCHED_FROZEN)
IDENTITY:  J ≡ Sh(F1) + Sh(F2) + D      (exact, order-independent; T10 asserts to 1e-12)
```

`C_IV` is a descriptive contrast only and is not part of the decomposition.

**Scope disclosure on the execution-block term.** `C_EXEC`, `C_DIAG` and `JOINT` carry the selected-only economic
veto of §5.3 rule 4, while `MATCHED_FROZEN`, `C_IV` and `C_IVSK` do not. On the DECISION-ECONOMICS functional the
`Sh(F2)` term therefore bundles two things — the spread and size DYNAMICS and the VETO POLICY that only the
size-modelling comparators face — and `D` inherits the same bundling. `Sh(F2)` on the FORECAST-QUALITY functional
is unaffected, because scoring a predictive distribution does not invoke the decision rule. Every reported
economic `Sh(F2)` and `D` carries the label `INCLUDES_SIZE_VETO_POLICY`; separating the policy from the dynamics
would need a veto-free size-modelling comparator, which is named in §9 and is not in V1.

### 4.4 When a comparator refuses a candidate

A refusal removes a CANDIDATE for one comparator; it must never silently remove a row from the population.

- **Decision economics.** The refusing comparator selects among its remaining eligible candidates, or WAITs at
  value 0 (§5.3 rule 0). The scan stays in the common population for every comparator. **Claims withdrawn:** Draft
  2.1 said refusal "costs it the trade" and that these devices "never flatter" a comparator. Both are false. WAIT
  can legitimately IMPROVE a comparator's economics by avoiding losing trades; a refusal changes the action set and
  its effect, positive or negative, is MEASURED rather than assumed. The refusal census by (comparator, reason) is
  reported with every economic result.
- **Forecast quality (CRPS / rank).** A refusing comparator produced no distribution, so the CONTRACT leaves the
  scored population for ALL comparators, keeping it common. **Every forecast-quality result carries
  `SCORED_POPULATION_CONDITIONAL` whenever ANY exclusion occurred** — not only above 5 % — together with the scored
  coverage (fraction of eligible contracts scored) and the full exclusion-reason census. **Claim withdrawn:**
  restricting every comparator to the same subset does NOT eliminate selection bias, because the subset is chosen
  by an outcome-correlated event.
- **`EXCLUSION_SENSITIVITY_OBSERVED_WORST`.** Assigning each excluded contract the worst score that comparator
  achieved on the scored population is reported as a SENSITIVITY and is explicitly NOT a bound: an unobserved score
  can exceed every observed one. Draft 2.1's "worst-case bound" name is withdrawn.

---

## 5. Scoring, uncertainty, decision rule

### 5.1 Scoring contracts

- **CRPS** against the realized exit bid at `t_e`, exactly from the simulated sample:
  `CRPS = (1/N)Σ|x_i − y| − (1/(2N²))ΣΣ|x_i − x_j|`. No kernel, no bandwidth.
- **Rank / PIT with an explicit finite-ensemble reference.** For `N` simulated values and one realization the
  reference is the RANK of the realization among the `N + 1` values, whose null distribution is DISCRETE UNIFORM on
  `{1, …, N + 1}` under exchangeability — not continuous uniform. Uniformity is assessed by a chi-square
  goodness-of-fit on the rank histogram with declared equal-width bins (`min(20, N+1)` bins; any remainder assigned
  to the lowest bins; the rule recorded); ties broken by mid-rank randomization with a recorded seed. Draft 2.1's
  continuous-uniform KS expectation was wrong; nominal rejection rates in §6.2 refer to this discrete reference.
- **Realized endpoint missing** (no `t_e`) → the contract is CENSORED from CRPS and rank scoring and counted; the
  scan stays in the economic population, where a comparator that traded it takes the unresolved value below.
- **Realized endpoint present but unexecutable** (`bid = 0`, or `size < 1` at a positive bid) → the CRPS/rank
  target is the OBSERVED bid as quoted (0 when there is no bid), carrying `executable: false`; a sensitivity
  excluding these rows is reported beside the headline. CRPS therefore scores the PRICE forecast only.
- **Executability scored separately** by a Brier score of `MODEL_CONDITIONAL_AVAILABILITY` against the realized
  executability indicator, same weighting and bootstrap. It is a forecast score, not a fill probability.
- **Weighting.** Contract scores averaged equally WITHIN a scan; scans weighted equally; bootstrap block = session.
- **Bootstrap.** Session-block, 2,000 draws, seed 11, percentile interval, sessions resampled with replacement to
  the original count; same cross-session-independence limitation as §2.3.
- **Decision economics (primary estimand).** Per SCAN on the common population: resolved TRADE = realized net;
  WAIT = 0; **unresolved TRADE = `−100 a − f_in`** (the obligation the boundary carries until discharged).
  Secondary, labelled: (i) unresolved EXCLUDED (resolved-subset estimand), (ii) unresolved at the `S2` value.

### 5.2 Monte Carlo uncertainty

N=4,000 (provisional). Retain S1,S2 arrays under each named size policy. Report each scenario's mean and
SE=sample_sd(ddof=1)/sqrt(N). Paired comparisons use the sample SD of pathwise differences.
E_sel=min(mean(S1),mean(S2)) has NO single sd/sqrt(N) standard error.
Normal-quantile lower limits are approximate Monte Carlo intervals conditional on fitted parameters and the
simulator. Bonferroni controls multiplicity only to the extent individual coverage assumptions hold; it supplies
neither finite-sample exactness nor model/parameter uncertainty.

### 5.3 Decision rule `JOINT_DECISION_RULE_V1`

m counts all eligible, envelope-feasible candidates entering the no-size ranking; keep it fixed for the veto.
c* and c2 are selected using ASSUME_AVAILABLE E_sel. No veto-stage re-ranking is permitted.

0. **`m = 0`** → WAIT, `NO_ELIGIBLE_CANDIDATE`, with the per-reason census (envelope, quote validation, refusal,
   absent key). The scan is recorded at value 0; no rule below is evaluated.
1. **Versus WAIT — SIMULTANEOUS over both accounting scenarios (A4).** Using the retained paired samples, require
   for EACH scenario `s ∈ {S1, S2}`:
   `Ê[S_s](c*) − z_{1−α/(2·2m)} · SE_paired(S_s(c*) − WAIT) > 0`, `α = 0.05`, the Bonferroni family being the
   `m` competing candidates × 2 scenarios. BOTH lower limits must exceed zero; this avoids needing the sampling
   distribution of a minimum and is conservative when the two scenario means are close. Any naive 2-SE figures are recorded per SCENARIO, never attached to E_sel. Failure →
   `MC_NOT_DISTINGUISHED_FROM_WAIT:<scenario>`.
2. **Versus runner-up — a HEURISTIC SCREEN, no confidence claim (A4).** `m = 1` → VACUOUS, recorded
   `SOLE_CANDIDATE`. Else require, in BOTH scenarios, `Ê[S_s](c*) − Ê[S_s](c₂) > 1 · SE_paired` on the shared
   paths; failure → `RANK_UNCERTAIN` → WAIT; `|Δ| < 1e-12` → `RANK_TIED` → WAIT. This comparison is made AFTER
   selecting `c*` by the same data, so it is labelled `HEURISTIC_SCREEN_NO_CONFIDENCE_CLAIM` on every trace and is
   never reported as a confidence statement.
3. **Adverse-scenario robustness (ablations are NOT gates).** `E_sel > 0` must survive: truncation `c²` at the
   0.999 and 0.99999 quantiles; spread innovations ×1.5; extension innovation scale ×1.5; `a_iv` shifted by −1
   cluster-robust SE against the position; selected-only size-veto sensitivity with the floor removed (negative implied size means unavailable, never
   negative executable size). Failure → `NOT_ROBUST_TO_ASSUMPTIONS:<scenario>`.
   Component ablations (`Δx_iv ≡ 0`, `Δx_sk ≡ 0`, diagonal `Σ`) are RECORDED for attribution, never gates.
4. **Accounting and selected-only veto.** Require U_rank<=0.25|E_sel_rank|.
   For C_EXEC, C_DIAG and JOINT only, evaluate c* under MODELLED_SIZE using the same paths.
   Require BOTH scenario lower limits >0 with the same quantile and original 2m family as rule 1;
   U_veto<=0.25|E_sel_veto|; and availability-failure rate<=0.05.
   Failures are respectively SIZE_VETO_NOT_DISTINGUISHED_FROM_WAIT:<scenario>,
   EXIT_ACCOUNTING_UNCERTAIN, and EXIT_LIQUIDITY_RISK. Each yields WAIT without substitution.
   A numerical failure or undefined selected-only result also yields WAIT, not candidate removal/re-ranking.
   Record rank and veto numbers separately. Other comparators retain ASSUME_AVAILABLE.
   The selected-only economic recheck is an explicit proposed conservative policy choice, not a validated threshold.
5. **PRIME supervision ACT** (unchanged r3 policy).

**Repeated-gate disclosure.** Rules 1 and 4 apply Bonferroni-adjusted lower limits over the same `2m` family to
the same simulated paths, under two different size policies. Because every gate must pass, the rules form an
INTERSECTION: adding rule 4 can only shrink the set of scans that trade, so the procedure is conservative for the
TRADE decision. It does NOT deliver simultaneous interval coverage across both gate families — the collection of
intervals reported is not a calibrated simultaneous confidence set over their union, and no coverage statement
about the pair is made or implied. Every trace carries `GATES_INTERSECTION_NOT_SIMULTANEOUS_COVERAGE`.

Carried on every trace: passing this rule establishes that the MODEL-CONDITIONAL ranking is decision-relevant under
the declared uncertainty. It establishes neither calibration, nor fill probability, nor positive expectancy.

### 5.4 Constants sensitivity and the no-retune rule

`constants_sensitivity` reports the decision census and the attribution contrasts under `N ∈ {1,000, 4,000,
16,000}` and each gate constant moved one declared step each way (rank separation 0.5/1/2 SE; accounting spread
15/25/40 %; availability failure 2/5/10 %; multiplicity naive/Bonferroni), computed on SYNTHETIC worlds before any
outcome is seen. Constants are frozen in the study-contract hash before the first evaluated population; changing
one afterwards requires a NEW contract, counts against the search budget, and the prior result stands beside it.

---

## 6. Synthetic acceptance

### 6.1 Correctness identities and deterministic fixtures (the ONLY acceptance gates)

| Id | Assertion |
|---|---|
| T1 | `available_time > t_d` on any input → `FUTURE_INPUT:<name>`; no partial state composed |
| T2 | a bar revision arriving after `t_d` is invisible (byte-identical `market_state`) |
| T3 | quotes failing `sanitize_quote` never reach IV inversion, skew, the slice, the candidate set or pricing (every call recorded) |
| T4 | IV uses the contemporaneous underlying; a 30 s-old reference → `NO_CONTEMPORANEOUS_UNDERLYING` |
| T5 | `ENDPOINT_SELECTION_V1`: `t_e` is the earliest instant with a JOINTLY coherent ATM key set; a fixture whose per-key earliest quotes never coexist selects a later `t_e` or excludes the row — never a set that did not coexist |
| T6 | frozen identity: when "first expiry ≥ 21 DTE" changes between `t_d` and `t_e`, the endpoint still measures `E*` chosen at `t_d` |
| T7 | estimator identity: `B̂ = (Z'Z)^{-1}Z'Y`, `Â = B̂'`, `Σ̂ = Ê'Ê/(n−k)` to 1e-12; rows lacking any outcome are absent from `Z`, `Y` and present in the census |
| T8 | truncation identity: `κ = P(χ²_{d+2} ≤ c²)/P(χ²_d ≤ c²)` to 1e-12 |
| T9 | pricing identity: a KNOWN state reproduces analytic BSM to 1e-10; `T(t_eval)` matches timestamp arithmetic exactly at BOTH endpoints; range guards fire for `log iv_K` outside `[log 1e-4, log 50]`, `T ≤ 0`, non-finite `S_H` |
| **T27** | **anchor identity**: with `x_sk ≠ 0` and `S_H ≠ K_atm`, pricing at `K = K_atm` returns exactly `exp(x_iv)`; the Draft 2.1 form fails this fixture |
| T10 | decomposition identity `J ≡ Sh(F1) + Sh(F2) + D` to 1e-12 |
| **T11a** | zero-dynamics identity, COMPATIBLE STATES: `A ≡ 0`, `Σ ≡ 0`, every eligible contract starting with `sz ≥ 1` → `JOINT` and `MATCHED_FROZEN` give bitwise-identical paths, candidate tables and proposals |
| **T11b** | zero-dynamics identity, MATCHED POLICY: `A ≡ 0`, `Σ ≡ 0`, `JOINT` against a frozen comparator with the SAME `MODELLED` size policy → identical for ANY starting size including `sz < 1`. Draft 2.1's single identity conflated the two and would have failed correct code whenever `sz_0 < 1` |
| T12 | shared randomness: all comparators on one scan use the identical pre-generated underlying paths |
| **T29** | **candidate-order permutation**: permuting candidate order leaves every underlying path, every option-state draw and the whole candidate table bitwise unchanged |
| T13 | accounting completeness: on a world producing `bid ≤ 0`, `sz < 1` and `sp ≥ 2`, every path receives both scenario values; `E_sel` matches a hand-computed 10-path fixture |
| **T28** | **scenario ordering**: with `mid_last < f_out/100`, `S2 < S1`; `E_sel = min` picks `S2`, `U = |S1 − S2| ≥ 0`, and the rule-4 gate cannot pass via an inverted ordering |
| T24 | exit-window mechanics: all six resolution rows, including `extension_undefined` valued from the PRIMARY evaluation; `T_ext` differs from `T_primary` by exactly `W_end/(365·86400)` |
| T14 | `UNPRICEABLE` → candidate REJECTED with stage, count and first failing input; never dropped |
| T25 | refusal attribution: the scan stays in the economic population at the comparator's next-best or WAIT value; the contract leaves the scored population for ALL comparators; both censuses written; the result carries `SCORED_POPULATION_CONDITIONAL` |
| T26 | predictor domain: `v̂ ≤ 0` refuses before any path is simulated; one path with `q ≤ 0` refuses the candidate with its index; a training row with non-finite `z` is EXCLUDED and counted, while a non-finite in the ASSEMBLED matrices refuses `NONFINITE_INPUT` |
| T15 | numerical refusals: non-PD `Σ̂`, rank-deficient `Z`, constant outcome column, out-of-bounds coefficient, > 10 % missing endpoints, > 5 % floored spreads — each named, no parameters written |
| **T30** | One coefficient in one equation restricted; fitted null adds the offset back; other equations untouched; reused weight matrix; fixed rank checked once; invalid coefficient-SE replicates counted; >1% discarded refuses. Reproducibility is separate from statistical coverage. |
| T16 | firewall: one training row with `available > cutoff` → `FIREWALL`, no fallback |
| T23 | immutability: revising or re-scoring a persisted forecast after a later fit is refused |
| T17 | deterministic reconstruction: same `market_state` + parameters + seed → byte-identical trace digest and proposal |
| T18 | decision-rule cases: `m = 0` → `NO_ELIGIBLE_CANDIDATE` with census; `m = 1` → `SOLE_CANDIDATE`; exact tie → `RANK_TIED`; naive and Bonferroni numbers both recorded |
| T19 | unconditional boundary path: `JOINT_FUNNEL_V1` FULL mode → real engine selects → persisted `market_state` + funnel → digest-bound intent with certified reservation → FILLED → RESOLVED exit → book closed clean |
| T20 | mandatory WAIT: one fixture per §5.3 failure mode, each WAITing with its named reason and no intent |
| T21 | every `joint_forecast` and funnel `joint` block carries the §7 separation entry with both digests present and distinct; a record missing it is refused |
| T22 | per-key lookup (§1.5): each table row, including an unbreakable tie; shuffled input → identical result |
| **T31** | **budget separation**: a production decision performs zero bootstrap solves; the production counter and the inference-resampling counter are distinct and both written |
| **T32** | **endpoint offsets (A2)**: a fixture with `δ = 0` but a 119 s-stale ATM quote is REFUSED by the `|o_j| ≤ o_max` rule (Draft 3 would have accepted it); every row records per-quote signed offsets, receipt lags and slice dispersion; the tighter sensitivity selects on `max_j|o_j| ≤ 15 s`, not on `δ`; every artefact carries the `TARGET_PROXY_V1` label |
| **T33** | Specified grid/widening/bisection reproduced; capped accepted endpoint gives INVERSION_SEARCH_UNRESOLVED, not proof of unboundedness; detected gaps recorded; a narrow unsampled island demonstrates finite-grid limitations. |
| **T34** | **scenario inference (A4)**: paired per-path samples for `S1` and `S2` are retained and identical on ACHIEVED paths; the WAIT gate uses simultaneous lower limits over the `2m` family and a near-tie fixture where one scenario's limit is ≤ 0 produces WAIT even though `E_sel > 0`; the runner-up check carries `HEURISTIC_SCREEN_NO_CONFIDENCE_CLAIM`; a fixture asserts `E[min(S1,S2)] ≠ min(E[S1], E[S2])` and that the pathwise minimum is never used |
| **T35** | Shared e1 draws and C_IV coordinate projection; Schur-complement moment identities; conditional covariance difference; scalar fourth-moment counterexample; required COMPOUND_COUPLING_LAW_CONTRAST label. Empirical moments are diagnostics. |
| **T36** | Ranking invariant to size; selected candidate can veto only to WAIT, never substitute. Positive no-size value with <5% catastrophic illiquidity and negative size-modelled mean must WAIT. Spread influence on ranking disclosed. |

### 6.2 Statistical behaviour: reported frequencies, gating nothing

Over `S = 200` seeds per world, each with a binomial CI. **No quantity here gates acceptance**; a deviation from
nominal is a FINDING for review, recorded with the seeds that produced it.

- **Recovery coverage.** True `A`, `Σ` known; coverage frequency of each coefficient's 95 % wild cluster
  bootstrap-t interval at `n ∈ {200, 480, 2000}`.
- **Null control `C_PERM` — SYNTHETIC ONLY, with its invariance argument stated (A1).** Draft 3 claimed that
  permutation "preserves both marginals and destroys only their dependence", so the contrast was exactly zero.
  That is the assumption error of EXP-002 in another form and is withdrawn. Arbitrary row permutation also
  destroys TIME structure, and `A = 0` constrains only the conditional MEAN — predictors may still carry
  distributional information. Permutation inference needs an INVARIANCE argument under its null, not a
  marginal-preservation claim.

  What is declared instead:
  1. **Generator assumption (synthetic only).** The null world generates SESSIONS that are independent and
     identically distributed, and within a session `H₀`: the option-state change block is INDEPENDENT of that
     session's predictor block (not merely mean-independent). Under `H₀` the joint law is invariant to permuting
     session labels between the two blocks — that invariance, not marginal preservation, is what licenses the
     control.
  2. **Permutation unit = the whole SESSION** (predictor block against outcome block). Rows are never permuted
     individually, which is what would destroy within-session time structure.
  3. **Independent evaluation sample.** Fit on a training draw, permute, and score on a SEPARATE evaluation draw
     from the same generator, so no score comparison is contaminated by in-sample fitting.
  4. **Averaged expectation and its uncertainty.** Under (1), use fixed equal-length synthetic sessions
     with identical row grids and fitting/evaluation rules. No output-dependent filtering or model-dependent
     evaluation censoring is permitted. A refusal is reported and makes this null report unavailable rather
     than selecting a successful subset.
     E_training,permutation,evaluation[score(JOINT)-score(C_PERM)]=0 under this generator.
     Produce S=200 independent training/permutation/evaluation triples, one paired mean difference D_s each.
     Report ONE grand mean, across-triple SE and a 95% t_(S-1) interval as Monte Carlo uncertainty.
     Individual fitted-pair intervals are descriptive; their rejection fraction is not a nominal false-positive
     rate. A rejection frequency of grand-mean intervals requires another outer repetition budget, absent in V1.
  5. **Scope.** `C_PERM` never touches historical or prospective data, never enters the comparator table (§4.2),
     never enters an attribution report and never appears in a decision path. Its conclusion is limited to this
     synthetic generator and fitted model class. **Cross-block residual dependence is NOT isolated by any V1
     contrast.** `JOINT − C_DIAG` is the `COMPOUND_COUPLING_LAW_CONTRAST` of §2.4 — it moves the conditional mean,
     the conditional residual covariance and the execution-block marginal law together — and permutation cannot
     isolate it either, because permuting predictors does not remove residual cross-block correlation. The two
     diagnostics answer different questions and NEITHER is an isolated dependence estimate; a
     marginal-preserving dependence contrast is named in §9 as outside V1.
- **Planted effects.** For b_iv in {-0.2,-0.6}, report the same 200-triple grand-mean contrast and interval,
  not an undefined rejection frequency of one grand mean. Coupling settings {0.3,0.6} are reported as compound
  JOINT-versus-C_DIAG sensitivity, not isolated correlation detection. Recovery/calibration reports stay separate.
- **Calibration frequency.** Well-specified world: rejection frequency of the rank chi-square against the DISCRETE
  uniform reference (§5.1), expected ≈ α. Misspecified world (jumps): DETECTION frequency of the rank test and of
  `RESIDUAL_NONGAUSSIAN_FLAG`; no claim that either fires in every sample.
- **Seed stability.** Over `K = 50` seeds on identical inputs: how often the selected candidate changes and how
  often the decision flips between TRADE and WAIT. Determinism is asserted only GIVEN a seed (T17); a different
  seed may legitimately change the ranking, and rule 2 is the control for that.

None of §6.2 transfers to markets.

---

## 7. Records, budgets, separation

**Records.** `market_state`; `joint_fit` (design summary, `Â`, CR1 SEs with `G`, wild cluster bootstrap-t intervals
with the discarded-replicate count, HC1 marked DESCRIPTIVE, `Σ̂` with eigenvalues, exclusion and censoring censuses,
the `δ` distribution, floor counts, diagnostics, refusals, dataset ids and roles, authorization artefact id,
`fit_cutoff`, training row ids for the §1.6 overlap check); `joint_forecast` (parameter digest, seed, `N`,
PER-BLOCK truncation fields — for block 1, block 2 and the extension draws separately: `c²(d_b)`, `κ(c, d_b)`,
accepted mass and rejection count, matching the block-sequential law of §2.4 rather than a single four-dimensional
figure — plus the pre-generation block digest, the Schur-complement matrices `M` and `C` with their positive-definiteness
checks, per-comparator moments, availability rates, `E[S1]`, `E[S2]`, `E_sel`, `U`, the separate RANKING and
selected-only VETO values of §5.3 rule 4, and all §3.2 counters); the funnel trace's `joint` block (comparator table, the six
decision-rule checks with their numbers, adverse-scenario table, ablation table, degraded labels, censuses).

**Forecast-versus-pricing separation, required in every record** (T21):

```
separation = { forecast_model: {id, parameters_digest, fit_cutoff, produces: "future STATES"},
               pricing_model:  {id, digest, produces: "price of a contract GIVEN a state"},
               statement: "a model-conditioned value ranking is not a calibrated probability, not a fill
                           probability, and not evidence of positive expectancy" }
```

**Two separate budgets, two separate counters** (Draft 2.1 conflated them):

| Budget | Scope | Ceiling | Counter |
|---|---|---|---|
| `PARAMETER_ESTIMATION_BUDGET` | production path, per session day: GARCH (1 + ≤ 1 Nelder–Mead polish + 1 second start), EWMA fallback ≤ 1, regime 1, joint design solve 1, joint covariance 1 | 8 estimation runs; a refusing run still counts; no retries for the joint fit; no time-of-day variants | `estimation_runs` |
| `INFERENCE_RESAMPLING_BUDGET` | reporting and attribution jobs ONLY: wild cluster bootstrap replicates, session-block bootstrap draws, permutation controls | declared per job (e.g. `B = 2,000` × equations), never inside a live decision | `resampling_solves` |

A production decision performs ZERO resampling solves (T31). The eight-run ceiling governs parameter estimation
only; it never had to accommodate thousands of bootstrap solves.

**The four attribution checks stay separate**: ordering/integrity (funnel binding), availability (§1),
leakage-free fitting (§1.6 + firewall), reconstruction (T17). None implies calibration or expectancy.

---

## 8. Operator decisions

Approved in principle at the Draft 2 review and unchanged: the state family (with the clarifications now in §2.2
and §1.5); constants as provisional engineering settings (§5.4); the collector-first fitting direction, now split
into role approval versus run authorization (§1.3); the eight-run PRODUCTION estimation budget, now distinguished
from the inference-resampling budget (§7); selection-by-name with no promotion rule.

**Status of this contract: CLOSED.** The reviewer accepted the patch application at `24b055e` and the two design
choices it settles. Implementation against this contract may proceed. Still outstanding and NOT authorized by the
closeout: any fitting run (§1.3, `R4-FIT-001` / `R4-FIT-002`), historical access, live-feed and fee commissioning,
service activation, admission request and prospective paper trading. Each is a separate authorization.

## 9. Named for later, not V1

A MARGINAL-PRESERVING dependence contrast, which is what would turn `JOINT − C_DIAG` from a compound coupling-law
change into an isolated residual-dependence estimate; a VETO-FREE size-modelling comparator, which is what would
separate the size-veto policy from the spread/size dynamics in the economic `Sh(F2)` term; an OBSERVATION MODEL
resolving the `TARGET_PROXY_V1` discrepancy (the per-quote offsets `o_j` enter the
measurement equation rather than being tolerated), which is what would let a result be stated about the state at
exactly `t_d + H`; cross-equation joint hypotheses with shared per-cluster weights; contract-specific spreads to
replace the ATM spread proxy that currently influences ranking;
cross-session dependence in inference (longer blocks or a dependence-robust alternative); contract-specific
executable conditions replacing the ATM size proxy; recursive contemporaneous effects with a stated identification
argument and a matching estimator; regime-dependent or time-of-day parameters; jumps; multi-leg expressions; an IV
process for the pricing model's own uncertainty.

## 10. Equation-to-test checklist

| # | Equation / rule | Where | Test |
|---|---|---|---|
| 1 | `Δx = A z + ε`, `z = (1, r, |r|/√v̂, log q − log v̂)` | §2.2 | T7, T26 |
| 2 | `B̂ = (Z'Z)^{-1}Z'Y`, `Â = B̂'`, `Σ̂ = Ê'Ê/(n−k)`, complete rows only | §2.3 | T7 |
| 3 | CR1 clustering; CI by test inversion, single restricted equation | §2.3 | T30, **T33** |
| 4 | Block-sequential law; kappa; compound marginal/coupling scope | §2.4 | T8, **T35** |
| 5 | `log iv_K = x_iv + x_sk·log(K/K_atm)` (anchor) | §2.5 | **T27** |
| 6 | `T(t_eval)` recomputed at each endpoint | §2.5, §3.2 | T9, T24 |
| 7 | Range guards on `log iv_K`, `T`, `S_H` | §2.5 | T9 |
| 8 | `ENDPOINT_SELECTION_V1`; per-quote offsets `|o_j| ≤ 60 s`; `TARGET_PROXY_V1` | §1.4 | T5, T6, **T32** |
| 9 | Per-key lookup and tie-breaks | §1.5 | T22 |
| 10 | Pre-generated randomness; order independence | §3.2 | T12, **T29** |
| 11 | `EXTENSION_SCALING_V1`; six resolution rows | §3.2 | T24 |
| 12 | `E_sel = min(E[S1], E[S2])` (ranking only), `U`, paired scenario samples | §3.1 | T13, **T28, T34** |
| 13 | Refusal handling in both estimands; population labelling | §4.4 | T25 |
| 14 | `J ≡ Sh(F1) + Sh(F2) + D` | §4.3 | T10 |
| 15 | CRPS; discrete-uniform rank reference; censoring; Brier | §5.1 | T13 (values), §6.2 (frequencies) |
| 16 | Decision rule 0–5; simultaneous scenario gate; size veto | §5.3 | T18, T20, **T34, T36** |
| 17 | Zero-dynamics identities (compatible states; matched policy) | §6.1 | **T11a, T11b** |
| 18 | Synthetic permutation invariance; 200 independent triples; one grand-mean interval | §6.2 | reported frequency |
| 19 | Walk-forward, immutability, overlap check | §1.6 | T16, T23 |
| 20 | Separation record in every artefact | §7 | T21 |
| 21 | Budget separation, two counters | §7 | **T31** |
| 22 | `SIZE_PROXY_V2` select-then-veto; spread proxy ranking influence disclosed | §2.1, §5.3 | **T36** |

## 11. Deliverables of the implementation brick (after this draft is accepted)

`apex/joint_wb/{permissions,state,endpoint,model,inference,comparators,accounting,decision_rule,attribution,
synthetic_world}.py`; `JOINT_FUNNEL_V1` in `apex/decision_wb/engine.py` (by name; `PILOT_RULE_V1` and
`FULL_FUNNEL_V1` untouched); authorization artefacts `R4-FIT-001` / `R4-FIT-002` and pre-registration `R4-ATTR-001`
declared and hashed before any read; the §6.1 tests; the §6.2 frequency reports as evidence files; this document
promoted with the implemented state and the evidence table.
