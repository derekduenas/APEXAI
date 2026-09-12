# R4 — Joint market-state forecasting: executable specification, DRAFT 2 (FOR REVIEW; nothing implemented, nothing fitted)

Status: `SPECIFICATION_DRAFT_2` on branch `frontier-build`. Supersedes Draft 1 (`cf4155f`) after the independent
review of that draft. This document authorizes NOTHING: no code under `apex/` changes with it, no historical data is
opened, no model is fitted, no service, limit, maintenance block, backtest hold, promotion rule or real-money
authority changes. Implementation begins only after review of THIS text; historical fitting only under a separately
authorized study contract.

"Executable" means every requirement names the record it produces, the refusal code it raises, or the test that pins
it. Correctness requirements are ALGEBRAIC IDENTITIES or deterministic fixtures. Statistical behaviour is REPORTED as
frequencies with uncertainty, never asserted as a single-sample pass/fail.

**Default policy, verified in code at `2011f03`:** `--pilot-selection-policy` default is `PILOT_RULE_V1`
(`scripts/options_paper_session.py:341`), and `TwinSources` / `ProductionSources` default to `PILOT_RULE_V1`
(`apex/pulse_options/sources.py:38,181,197`, `apex/options_pilot/entrypoint.py:53`). The deterministic pilot rule is
and remains the operational default. Draft 1 §0 misstated this by calling the funnel baseline "the default";
`docs/FUNNEL_INTEGRATION.md` line 5 already states the setting correctly and needed no change. `FULL_FUNNEL_V1` is
selection-by-name, and `JOINT_FUNNEL_V1` will be too.

**Changes from Draft 1** (each is the reviewer's numbered point): §2.2/§2.3 one coherent estimator with no
contemporaneous endogeneity and an exactly specified truncation; §1.4 three separated clocks and frozen contract
identity, plus dataset-and-role permissions; §3 complete path accounting with two bounds and candidate refusal;
§4 two distinct baselines, explicit size policy, `C_DIAG` renamed and narrowed, an exactly additive decomposition;
§6 identity-based acceptance with separated frequency reports; §5 frozen scoring and uncertainty contracts including
the unresolved-outcome estimand and multiplicity; §7 fit accounting with time-of-day buckets removed.

---

## 0. Objective, horizon, non-goals

At decision instant `t_d`, estimate how the underlying price, the ATM implied volatility, the slice skew, the
relative spread and the available size evolve JOINTLY over `H = 900 s`; reprice each eligible expression inside every
simulated future state; compare expressions against WAIT on after-cost economics; act only when the ranking is
decision-relevant under the declared uncertainty rules; record everything so each probability, selection and paper
order is attributable to information recorded before its outcome.

**What the joint model is.** A CONDITIONAL model of option-state change given the SAME-WINDOW underlying path
statistics. It does not forecast the underlying: the underlying path comes from the existing GARCH-t engine, and the
option state is drawn conditional on that path. This is stated here because it determines the estimator (§2.3).

**Non-goals (V1).** Multi-leg expressions; intraday refitting; jumps; feedback from option state to the underlying
within the horizon; time-of-day parameter buckets (removed from V1); any claim of calibration or positive expectancy.

**Governance constants unchanged by this brick.** Kernel limits ($500 trade, $1,500 aggregate, $600 same underlying,
$1,000 family, $1,000 drawdown halt); envelope `min(ref ask × 1.1, $5.00)`; exit policy `EXIT_AT_HORIZON_15M_V1`
(due `+900 s`, window `120 s`, ≤ 5 attempts); maintenance block; collector observation-only; fees SYNTHETIC /
UNVERIFIED; no broker orders; no promotion rule.

---

## 1. Information available at decision time

### 1.1 Input contract

Every input carries `event_time`, `available_time`, `source`, `revision_policy`, `max_age_s`, `quality`, or it is
refused `INPUT_CONTRACT_MISSING:<field>`. Table as in Draft 1 §1.1 (unchanged, restated in the implementation doc):
bars (event = bar start, available = bar complete + receipt lag, revisions visible only if `available ≤ t_d`, max age
120 s); underlying NBBO (15 s); option quotes (indicative 120 s, execution 15 s at the boundary); chain membership
(a contract absent from the latest snapshot is INELIGIBLE, never carried forward); open interest (feature only, never
a size proxy); fee schedule; calendar; fitted parameters.

Refusals: `FUTURE_INPUT:<name>` for `available_time > t_d` (a firewall violation, not staleness);
`INPUT_STALE:<name>`. Tests: §6.1 T1–T3.

### 1.2 Asynchronous underlying and option quotes

Unchanged from Draft 1 §1.2 and restated: `t_d` is the boundary clock reading; `S_0` is the last completed bar close
with `available ≤ t_d`; the NBBO mid, when VALID, is recorded as `S_nbbo` and `spot_async_gap = log(S_nbbo/S_0)` must
satisfy `|gap| < 0.002` else `SPOT_ASYNC_GAP_EXCEEDED` → WAIT; implied vol is inverted with the underlying reference
at the option quote's OWN time (corpus `underlying_ref` when `moneyness_status == CAUSAL`, else the latest underlying
observation with `event_time ≤ quote.event_time` and gap ≤ 5 s, else `IV_UNUSABLE: NO_CONTEMPORANEOUS_UNDERLYING` —
the quote may still price as an execution quote but can supply no IV or skew); slice quantities require all quotes
inside a 30 s coherence window else `SLICE_INCOHERENT` and skew is MISSING; every quote passes `sanitize_quote`
before any use (r3 rule).

### 1.3 Dataset-and-role permissions (replaces the absolute date rule)

The period policy is a property of a DATASET and a ROLE, not of the calendar. The registry (`apex/joint_wb/
permissions.py`, to be written) is the single authority; any read of an unregistered dataset refuses
`DATASET_NOT_REGISTERED`.

| Dataset | Path | Role | Permitted uses | Authorization |
|---|---|---|---|---|
| `HIST-A-OPTIONS` 2016–2019 | `/apex-data/history-a/options_history` | TRAIN | fitting, development replay | existing (EXP-001B) |
| `HIST-A-OPTIONS` 2020–2021 | same | VALIDATION | development replay; fitting only under a named contract | existing |
| `HIST-A-OPTIONS` 2022–2024 | same | EVALUATION_SEALED | none | sealed |
| `HIST-A-OPTIONS` 2025 → 2026-08-28 | same | RESERVE_SEALED | none | sealed |
| `PILOT-COLLECTION` (2026-09-11 →) | `/apex-data/pilot_collection/` | PROSPECTIVE_OBSERVATION | fitting and calibration reporting | operator decision §8.3 |
| `PILOT-LEDGER` | `/apex-data/core/…` live options ledger | PROSPECTIVE_DECISION | outcome evidence only, never fitting | untouched |

The 2022+ seal is a property of `HIST-A-OPTIONS`. `PILOT-COLLECTION` is a different dataset, created after the pilot
began, whose rows are prospective relative to every model they would inform; its calendar dates being 2026 does not
make it sealed. Draft 1's "2022+ SEALED" line contradicted its own data path; this table replaces it. Fitting on
`PILOT-COLLECTION` still requires the operator's explicit decision (§8.3), and fitting on `HIST-A-OPTIONS` requires
contract `R4-FIT-001` in addition.

### 1.4 Three clocks for a training pair, and frozen contract identity

A training pair is `(START, END)` for one scan and one frozen contract set.

| Clock | Definition | Rule |
|---|---|---|
| `t_d` | decision instant | START-state inputs must have `available_time ≤ t_d`. No exception. |
| Endpoint window | `[t_d + H, t_d + H + W_end]`, `W_end = 120 s` (matches `EXIT_AT_HORIZON_15M_V1.window_s`) | the END observation is the FIRST quote set inside the window whose slice is coherent; nothing outside the window is used |
| Availability deadline | `t_d + H + W_end + 60 s` | every END input must have `available_time ≤` this; a later arrival does not rescue the row |
| Fit eligibility | fit start instant `t_fit` | every row used must satisfy `availability deadline ≤ t_fit`; `Model.fit`'s existing firewall enforces `available ≤ cutoff` |

**Frozen identity within a pair.** At `t_d` the pair fixes, and the END measurement re-uses without re-selection:
the expiration `E*` (first with DTE ≥ 21 at `t_d`); the ATM strike `K_atm` (minimizing `|K − S_0|`, ties → lower
strike); the skew strikes `K_−, K_+` (nearest available to `S_0·e^{∓0.02}`, ties → lower; must be distinct from each
other, else skew MISSING); the right-aggregation rule. Re-selecting any of these at the endpoint would measure
contract re-selection instead of market evolution (`IDENTITY_NOT_FROZEN` is a construction bug, pinned by test T6).

**Right aggregation.** `iv_atm = ½(iv_CALL + iv_PUT)` when both are usable; if exactly one is usable, use it and set
`iv_source ∈ {BOTH, CALL_ONLY, PUT_ONLY}`; if neither, the row is INCOMPLETE. The END measurement must use the SAME
`iv_source` as the START; a change of source makes the row INCOMPLETE (`IV_SOURCE_CHANGED`), because a call-to-put
switch is not a market move.

**Missing endpoints.** A row with no coherent END observation inside the window is EXCLUDED with a reason and
counted. The exclusion census is part of the fit record. If the exclusion rate exceeds 10 %, the fit refuses
`ENDPOINT_MISSINGNESS_EXCESSIVE`: at that level the missingness is plausibly informative (illiquid or fast states)
and a complete-case fit would be biased. No imputation in V1.

---

## 2. State, dynamics and estimator

### 2.1 State variables (positivity built in)

| Symbol | Definition at time `t` | Why this parameterization |
|---|---|---|
| `r` | log underlying return over the horizon | unchanged |
| `q` | realized path variance `Σ e_t²` over the horizon | conditioning variable, same path |
| `x_iv` | `log iv_atm(E*, K_atm)` | `iv = exp(x_iv) > 0` by construction |
| `x_sk` | slope `g` of `log iv` in log-moneyness: `g = [log iv(K_−) − log iv(K_+)] / [log(K_−/S) − log(K_+/S)]`, dimensionless | the slice map is `log iv_K = x_iv + g·log(K/S)`, so EVERY strike's IV is positive for every finite state — Draft 1's additive-vol-points skew could produce non-positive strike IV |
| `x_sp` | `log max(sp_obs, sp_floor)`, `sp` = (ask − bid)/mid at `(E*, K_atm)`, `sp_floor = 1e-4` | a locked market (`sp = 0`) is representable; floored observations are counted (`sp_floored_n`) and a fit with > 5 % floored refuses `SPREAD_FLOOR_EXCESSIVE` |
| `x_sz` | `log(1 + sz)`, `sz = min(bid_size, ask_size)` at `(E*, K_atm)`, `x_sz ≥ 0` by construction; simulated states are floored at 0 and the floor count recorded | `sz = exp(x_sz) − 1 ≥ 0` always |

`Δx = x(END) − x(START)` for each of the four option-state coordinates.

**ATM size is a declared PROXY.** `sz` is measured at `K_atm` and is not the displayed size of any other strike.
Policy `SIZE_PROXY_V1`: the size state may only GATE (reduce value or force WAIT, §3.3/§5.3); it may never increase a
candidate's expected value or promote one candidate over another. Any modelled availability number is labelled
`MODEL_CONDITIONAL_AVAILABILITY`, never a fill probability. Contract-specific executable conditions are out of scope
for V1 and are named as the next capability (§9).

### 2.2 Dynamics (JOINT-V1)

Underlying: unchanged (GARCH-t or declared EWMA fallback, regime mixture, truncated-t innovations of r3), producing
`(r, q)` per path.

Option state, conditional on the SAME path's `(r, q)` — **no contemporaneous option-state variable appears on any
right-hand side**:

```
Δx = A z + ε ,  where
z  = ( 1 ,  r ,  |r| / sqrt(v̂) ,  log q − log v̂ )'          (common to all four equations; v̂ = E[q] at t_d
                                                              from the GARCH integrated-variance forecast, a
                                                              t_d-measurable scaling constant)
Δx = ( Δx_iv , Δx_sk , Δx_sp , Δx_sz )'                      A is 4×4 of coefficients
ε  ~ TMVN( 0 , Σ ; c )                                       zero-mean multivariate normal, elliptically truncated
                                                              and renormalized (§2.4)
```

Draft 1 put `Δx_iv` on the spread equation's right-hand side and `Δx_sp` on the size equation's, while letting the
same innovations correlate: the regressors were then correlated with their own equation's error, so
equation-by-equation OLS would not recover the declared structural coefficients. Draft 2 removes every
contemporaneous option-state regressor. The co-movement those terms were meant to capture now lives entirely in `Σ`,
which is exactly what a residual covariance is for. No recursive contemporaneous effects are claimed in V1; if a
later version wants them, it must state an identification argument and an estimator that matches it (§9).

**Declared assumptions, each with a recorded diagnostic:** (a) `E[ε | r, q] = 0` — conditional mean independence of
the option-state innovation from the same-window underlying statistics; diagnostic: correlation of each residual with
`r`, `|r|`, `r²`, reported with HC-robust SEs, RECORDED (a flag, not a refusal, in V1). (b) Linearity in `z`.
(c) Parameters constant across regimes and across the session (no time-of-day buckets in V1). (d) Gaussian residuals
before truncation; diagnostic: Jarque–Bera per equation, RECORDED as `RESIDUAL_NONGAUSSIAN_FLAG`. (e) No feedback
from option state to the underlying within the horizon.

### 2.3 Estimator (one coherent formulation)

Multivariate linear regression with a COMMON design matrix `Z` (n×4) and four outcomes `Y` (n×4):

```
Â = (Z'Z)^{-1} Z'Y                      (equivalently the GLS/SUR estimator: with identical regressors in every
                                         equation, SUR collapses to equation-wise OLS — Zellner's identity, which
                                         is why a common design is chosen)
Ê = Y − Z Â
Σ̂ = Ê'Ê / (n − k)                       k = 4 (columns of Z); Σ̂ is the residual covariance across equations
```

Reported per coefficient: HC1-robust standard errors (heteroskedasticity only; no cross-equation correction needed
because the estimator is equation-wise consistent under the common design). Reported for `Σ̂`: the correlation
matrix, its eigenvalues, and its condition number. Refusals: `COVARIANCE_NOT_PD` (min eigenvalue ≤ 0 — no shrinkage
repair in V1), `DESIGN_RANK_DEFICIENT` (`Z'Z` condition number > 1e10), `INSUFFICIENT_HISTORY` (n < 200),
`DEGENERATE_STATE` (any outcome column constant), `COEFFICIENT_OUT_OF_BOUNDS` (declared sanity bounds; refused, never
clipped), `NONFINITE_INPUT`.

Test T7 pins the identity: on a deterministic fixture, the implementation's `Â` equals the closed-form
`(Z'Z)^{-1}Z'Y` to 1e-12, and `Σ̂` equals `Ê'Ê/(n−k)` to 1e-12. That is an algebraic identity, not a statistical claim.

### 2.4 Truncation of correlated innovations (exact, and exactly testable)

Coordinate-wise clipping of correlated normals distorts the dependence in a way that is not analytically tracked.
V1 therefore uses ELLIPTICAL (Mahalanobis) rejection with an analytic renormalization:

```
draw u ~ N(0, Σ̂);  accept iff  d² = u' Σ̂^{-1} u  ≤  c²        (c² = χ²_{4,0.9999} quantile, declared)
ε = u / sqrt(κ(c, 4)),      κ(c, d) = P(χ²_{d+2} ≤ c²) / P(χ²_d ≤ c²)
```

`κ` is the exact variance-deflation factor of an elliptically truncated multivariate normal, so `Cov(ε) = Σ̂`
exactly, and the truncation preserves the correlation structure (the truncation region is an ellipsoid of `Σ̂`, so
every coordinate is treated alike). The accepted mass, `c`, `κ` and the rejection count are recorded on every
simulation. Test T8 pins two identities: (i) `κ` computed by the implementation equals the chi-square ratio to
1e-12; (ii) on a large deterministic sample the realized covariance matches `Σ̂` within stated Monte Carlo error, and
the realized correlation matches `Corr(Σ̂)` — with the tolerance derived from the sample size, and the check reported
as a coverage frequency over seeds, not a single pass. Sensitivity to `c` is part of the adverse-scenario set (§5.3).

The underlying's univariate truncated-t innovations (r3, cap 8 sd) are unchanged and remain a separate declared
assumption.

### 2.5 Pricing model inside a simulated state (distinct from the forecast model)

Given a path's end state `(S_H, x_iv, x_sk, x_sp, x_sz)` and a contract `(K, E*)`:

```
log iv_K = x_iv + x_sk · log(K / S_H)                    (positive IV by construction)
mid      = BSM(S_H, K, T_exit, iv_K, r=q=0, right)        T_exit = (expiry_epoch − (t_d + H)) / (365·86400)
sp_H     = exp(x_sp) ;  sz_H = max(0, exp(x_sz) − 1)
bid_H    = mid · (1 − sp_H / 2)                           may be ≤ 0 when sp_H ≥ 2 → see §3
```

The same pricing model is used by EVERY comparator, including the matched frozen baseline, so a contrast measures
the forecast of the state and nothing else. Test T9: applied to a KNOWN state, the pricing model reproduces the
analytic BSM value to 1e-10, with no forecast involved.

---

## 3. Complete path accounting (every path gets a defined number, or the candidate is refused)

Policy `PATH_ACCOUNTING_V1`. For one candidate, one path, entry at the validated ask `a` (100 multiplier, fees
`f_in + f_out`), the exit is evaluated at `t_d + H`; if not achievable there, the state is advanced by the declared
exit window (`W_end = 120 s`, one additional simulation step block under the same dynamics, recorded) and evaluated
once more. Then exactly one of:

| Case | Condition | Net on that path |
|---|---|---|
| ACHIEVED | `bid_H > 0` and `sz_H ≥ 1` | `100 (bid_H − a) − f_in − f_out` |
| NOT_ACHIEVABLE | `bid_H ≤ 0` (includes `sp_H ≥ 2`) or `sz_H < 1`, at both evaluations | **conservative:** `−100 a − f_in` (premium written off, no exit fee); **optimistic:** `100 (mid_H − a) − f_in − f_out` |
| UNPRICEABLE | BSM inputs invalid (non-finite, `T_exit ≤ 0`, `iv_K` non-finite) | no number is assigned — see below |

Two bounds are carried for every candidate: `E_lower` (NOT_ACHIEVABLE paths at the conservative value) and `E_upper`
(at the optimistic value). **Selection uses `E_lower` only.** `E_upper − E_lower` is the accounting uncertainty and
is recorded; §5.3 rule 4 uses it. Dropping hard paths is therefore impossible: they are valued, conservatively, and
they can only reduce the number that authorizes a trade.

`UNPRICEABLE` paths cannot be valued. If any path is UNPRICEABLE the candidate is `REJECTED:
UNPRICEABLE_PATH_PRESENT` with the count and the first failing input recorded. Draft 1's "> 1 % tolerance" is
removed: a distribution that cannot be constructed is not a distribution.

`NOT_ACHIEVABLE` frequency is reported as `MODEL_CONDITIONAL_AVAILABILITY`, explicitly not a fill probability, and
its only authority is to reduce `E_lower` and to trigger the §5.3 gate.

---

## 4. Baselines, comparators and an exactly additive decomposition

### 4.1 Two distinct reference objects

| Object | What it is | Role |
|---|---|---|
| `OPERATIONAL_REFERENCE` | the FROZEN r3 policy `FULL_FUNNEL_V1` at pin `525340c`, its own pricing map (additive-vol skew absent, `IV_FIXED`, `SPREAD_FIXED`), its own decision rule | the "what the system does today" line; reported alongside, never used as the attribution baseline |
| `MATCHED_FROZEN` | R4's pricing map (§2.5), R4's path accounting (§3), R4's decision rule (§5.3), with `Δx ≡ 0` | the attribution baseline: identical machinery, frozen state |

A contrast against `MATCHED_FROZEN` isolates the state forecast. A contrast against `OPERATIONAL_REFERENCE` mixes in
the pricing map, the accounting and the decision rule, and is reported as such. Draft 1 conflated the two.

### 4.2 Comparator table (explicit size policy; no `∞`)

| Id | IV block (`Δx_iv`, `Δx_sk`) | Exec block (`Δx_sp`, `Δx_sz`) | Residual covariance | Size policy |
|---|---|---|---|---|
| `MATCHED_FROZEN` | 0 | 0 | — | `ASSUME_AVAILABLE` (no size gate; `sz_H ≡ ∞` is replaced by this named policy) |
| `C_IV` | `Δx_iv` modelled, `Δx_sk = 0` | 0 | 1×1 | `ASSUME_AVAILABLE` |
| `C_IVSK` | both modelled | 0 | 2×2 block | `ASSUME_AVAILABLE` |
| `C_EXEC` | 0 | both modelled | 2×2 block | `MODELLED` (gate only, §2.1) |
| `C_DIAG` | both modelled | both modelled | block-diagonal (IV block ⊥ exec block; within-block correlation retained) | `MODELLED` |
| `JOINT` | both modelled | both modelled | full `Σ̂` | `MODELLED` |

`C_DIAG` is NOT an independence model: all comparators share the same underlying paths (common random numbers) and
every equation conditions on `(r, q)`, so option-state coordinates remain dependent through the underlying even with
a diagonal `Σ`. Its name and its claim are narrowed accordingly: it isolates CROSS-BLOCK RESIDUAL correlation only.

### 4.3 Exactly additive decomposition (no ambiguous residual)

Let `V(·)` be a functional of a configuration (§5.1: CRPS of the exit value, or per-scan economics), evaluated on
one fixed population. Two binary factors plus one dependence term, over the lattice
`{MATCHED_FROZEN, C_IVSK, C_EXEC, C_DIAG, JOINT}`:

```
F1 = IV block on,  F2 = exec block on
Sh(F1) = ½ [ V(C_IVSK) − V(MATCHED_FROZEN) ] + ½ [ V(C_DIAG) − V(C_EXEC) ]
Sh(F2) = ½ [ V(C_EXEC) − V(MATCHED_FROZEN) ] + ½ [ V(C_DIAG) − V(C_IVSK) ]
D      = V(JOINT) − V(C_DIAG)                        (cross-block residual correlation)
J      = V(JOINT) − V(MATCHED_FROZEN)
IDENTITY:  J  ≡  Sh(F1) + Sh(F2) + D                 (exact, order-independent; test T10 asserts it to 1e-12)
```

`C_IV` is retained as a descriptive contrast (`V(C_IV) − V(MATCHED_FROZEN)`, IV level without skew) and is NOT part
of the decomposition, so no double counting arises. Draft 1's "subtract the components" residual is replaced by this
identity. Every term is reported with its session-block bootstrap interval (§5.2).

---

## 5. Scoring, uncertainty and the decision rule (all constants frozen here)

### 5.1 Scoring contracts

- **Exit-value forecast quality.** CRPS against the realized exit bid, computed EXACTLY from the simulated sample
  (`CRPS = (1/N)Σ|x_i − y| − (1/(2N²))ΣΣ|x_i − x_j|`). No kernel density, no bandwidth: Draft 1's KDE log score is
  removed because the bandwidth was an unfrozen degree of freedom.
- **PIT.** `u = (1/N)·#{x_i < y} + U·(1/N)·#{x_i = y}`, `U ~ Uniform(0,1)` from a recorded seed (mid-rank
  randomization for ties). PIT is reported as a histogram, a KS statistic and a rejection FREQUENCY over seeds
  (§6.2), never as a single pass/fail gate.
- **Weighting.** Contract-level scores are averaged with equal weight WITHIN a scan; scans are then equally weighted;
  the bootstrap block is the calendar session. Stated once, applied everywhere.
- **Bootstrap.** Session-block, 2,000 draws, seed 11, percentile interval, sessions resampled with replacement to the
  original session count. Identical for every reported interval.
- **Decision economics estimand (primary).** Per SCAN, on the common population: resolved TRADE = realized net;
  WAIT = 0; **unresolved TRADE = the conservative value `−100 a − f_in`** (the obligation the boundary actually
  carries until discharged). Two secondary estimands are reported beside it and labelled: (i) unresolved EXCLUDED
  (the resolved-subset estimand — what Draft 1 wrongly made primary), (ii) unresolved at the optimistic bound. A
  headline can therefore never be improved by dropping hard rows.

### 5.2 Monte Carlo uncertainty

`N = 4,000` paths (provisional engineering setting, not validated sufficiency — the SE is what is checked). Per
candidate: `E_lower`, `SE_mc = sd/√N`. Per pair on COMMON paths: paired SE. Reported with every decision.

### 5.3 Decision rule `JOINT_DECISION_RULE_V1`

Let `m` = number of ELIGIBLE, envelope-feasible candidates; `c*` = argmax `E_lower`; `c₂` = runner-up.

1. **Versus WAIT, with multiplicity.** `E_lower(c*) − z_{1−α/(2m)} · SE_paired(c* − WAIT) > 0`, `α = 0.05`,
   Bonferroni over the `m` candidates that competed. The naive 2-SE number is ALSO recorded, labelled
   non-simultaneous. Failure → `MC_NOT_DISTINGUISHED_FROM_WAIT`. Draft 1's plain 2 SE is replaced because the maximum
   of `m` estimates is selected, not a pre-chosen one.
2. **Versus the runner-up.** If `m = 1`: rule VACUOUS, recorded as `SOLE_CANDIDATE`. Else require
   `E_lower(c*) − E_lower(c₂) > 1 · SE_paired(c* − c₂)`; failure → `RANK_UNCERTAIN` → WAIT (no coin flip). Exact ties
   (`|Δ| < 1e-12`) are `RANK_TIED` → WAIT.
3. **Adverse-scenario robustness** (ABLATIONS ARE NOT GATES). `E_lower > 0` must survive every ADVERSE PLAUSIBLE
   scenario: tail cap `c²` at the 0.999 quantile (tighter) and at the 0.99999 (looser); spread innovations scaled
   ×1.5; the IV drift `a_iv` shifted by `−1` robust SE (against the position); size floor removed. Failure →
   `NOT_ROBUST_TO_ASSUMPTIONS:<scenario>`. The component ABLATIONS (`Δx_iv ≡ 0`, `Δx_sk ≡ 0`, `Σ` diagonal) are
   computed and RECORDED for attribution but are NOT gates: Draft 1's `Δx_iv = 0` gate would have forbidden exactly
   the trades whose legitimate modelled advantage is an IV forecast.
4. **Accounting uncertainty.** `E_upper(c*) − E_lower(c*) ≤ U_max = 0.25 · |E_lower(c*)|` and
   `MODEL_CONDITIONAL_AVAILABILITY` failure rate ≤ 0.05; failure → `EXIT_ACCOUNTING_UNCERTAIN` /
   `EXIT_LIQUIDITY_RISK`.
5. **PRIME supervision ACT** (unchanged r3 policy).

Carried on every trace: passing this rule establishes that the MODEL-CONDITIONAL ranking is decision-relevant under
the declared uncertainty. It does not establish positive expectancy, calibration, or an executable fill.

---

## 6. Synthetic acceptance: identities first, frequencies reported separately

All worlds come from a declared generator with a known mechanism. Every test is deterministic given its seed.

### 6.1 Correctness identities and deterministic fixtures (pass/fail)

| Id | Assertion (exact) |
|---|---|
| T1 | `available_time > t_d` on ANY input → `FUTURE_INPUT:<name>`; no partial state is composed |
| T2 | a bar revision arriving after `t_d` is invisible to the state at `t_d` (byte-identical `market_state` with and without it) |
| T3 | quotes rejected by `sanitize_quote` never reach IV inversion, skew, the slice fit, the candidate set or pricing (every call recorded, as in r3) |
| T4 | IV uses the contemporaneous underlying reference; a 30 s-old reference is refused `NO_CONTEMPORANEOUS_UNDERLYING` |
| T5 | slice spanning > 30 s → skew MISSING and the affected comparators labelled `SKEW_DEGRADED` |
| T6 | frozen identity: a fixture where the "first expiry ≥ 21 DTE" CHANGES between `t_d` and the endpoint still measures `E*` chosen at `t_d`; a construction that re-selects fails the test |
| T7 | estimator identity: `Â = (Z'Z)^{-1}Z'Y` and `Σ̂ = Ê'Ê/(n−k)` to 1e-12 on a deterministic fixture |
| T8 | truncation identity: `κ = P(χ²_{d+2} ≤ c²)/P(χ²_d ≤ c²)` to 1e-12; realized `Cov(ε)` matches `Σ̂` within stated MC error (reported as coverage over seeds, §6.2) |
| T9 | pricing identity: pricing a KNOWN state reproduces analytic BSM to 1e-10; `log iv_K` positive for every finite state; `T_entry − H/(365·86400) = T_exit` exactly |
| T10 | decomposition identity: `J ≡ Sh(F1) + Sh(F2) + D` to 1e-12 on any evaluated population |
| T11 | zero-dynamics identity: with `A ≡ 0` and `Σ ≡ 0` INJECTED (no fitting), `JOINT` paths and `MATCHED_FROZEN` paths are bitwise identical, and so are their candidate tables and proposals |
| T12 | common random numbers: all comparators on one scan share identical underlying `S` arrays; only the option state differs |
| T13 | path accounting completeness: on a world engineered to produce `bid_H ≤ 0`, `sz_H < 1` and `sp_H ≥ 2`, every path receives a conservative AND an optimistic number; the candidate's `E_lower` equals the hand-computed value on a 10-path fixture |
| T14 | `UNPRICEABLE` path → candidate `REJECTED`, never silently dropped; the count and first failing input are recorded |
| T15 | numerical refusals: non-PD `Σ̂`, rank-deficient `Z`, constant outcome column, out-of-bounds coefficient, non-finite row, > 10 % missing endpoints, > 5 % floored spreads — each raises its named refusal, writes no parameters, and leaves the engine WAITing with the reason |
| T16 | firewall: one training row with `available > cutoff` → `FIREWALL`, no fallback |
| T17 | deterministic reconstruction: same `market_state` + parameters + seed → byte-identical trace digest and proposal |
| T18 | decision-rule cases: `m = 1` → `SOLE_CANDIDATE` recorded and rule 2 vacuous; exact tie → `RANK_TIED` → WAIT; Bonferroni number differs from the naive number when `m > 1` and both are recorded |
| T19 | unconditional boundary path: `JOINT_FUNNEL_V1` FULL mode → real joint engine selects → persisted `market_state` + funnel → digest-bound intent with certified reservation → FILLED → RESOLVED exit → book closed clean (the r3 acceptance pattern) |
| T20 | mandatory WAIT: one fixture per §5.3 failure mode, each producing WAIT with its named reason and no intent |

### 6.2 Statistical behaviour: frequencies with uncertainty (reported, never a single-sample gate)

Over `S = 200` seeds per world, each reported with a binomial CI:

- **Recovery coverage.** True `A` and `Σ` known; report the coverage frequency of each coefficient's 95 % CI at
  `n ∈ {200, 480, 2000}`. Acceptance is a coverage band `[0.90, 0.98]` at `S = 200`, stated as a frequency claim.
  Draft 1's "within 3 SE" single-sample assertion is removed.
- **False-positive frequency (null world).** `A ≡ 0`, `Σ > 0` — note this world legitimately produces `JOINT ≠
  MATCHED_FROZEN` paths, so Draft 1's "forecasts agree on every row" assertion was wrong and is deleted. Report
  instead: the frequency with which each attribution interval excludes 0, expected ≈ α.
- **Detection frequency (power).** Planted `b_iv ∈ {−0.2, −0.6}`, cross-block correlation `∈ {0.3, 0.6}`: report the
  frequency the corresponding interval excludes 0, by `n`. An undetectable planted effect at the V1 window is a
  documented limitation.
- **Calibration frequency.** Well-specified world: PIT KS rejection frequency at 5 %, expected ≈ 5 % (a correctly
  calibrated forecast fails a KS test 5 % of the time by construction). Misspecified world (jumps injected): report
  the DETECTION frequency of the PIT test and of `RESIDUAL_NONGAUSSIAN_FLAG` — no claim that either fires in every
  sample.
- **Seed stability.** Over `K = 50` seeds on identical inputs, report how often the selected candidate changes and
  how often the decision changes between TRADE and WAIT. Determinism is asserted only GIVEN a seed (T17); a changed
  seed may legitimately change the ranking, and rule 2 (§5.3) is the control for that. Draft 1's "a changed seed
  changes only the simulation section" assertion is deleted.

None of §6.2 transfers to markets. Market calibration and expectancy remain prospective evidence classes.

---

## 7. Fit accounting, budgets and records

**Estimation runs per session day** (an estimation run = one call to a fitting routine; retries count):

| Routine | Runs | Notes |
|---|---|---|
| GARCH-t | 1, plus at most 1 Nelder–Mead polish and 1 second start | the r3 convergence protocol, already accounted inside `GARCH.fit` |
| EWMA fallback | at most 1 | only when GARCH-t refuses |
| Regime (MarkovSwitching2) | 1 | unchanged |
| Joint (§2.3) | 1 design solve (`Â`, all four equations from one `Z`) + 1 covariance estimate (`Σ̂`) | counted as 2 estimation runs; no retries — a refusal is a refusal |

Budget: `FIT_BUDGET_PER_SESSION_DAY = 8` estimation runs, enumerated above; exceeding it refuses
`FIT_BUDGET_EXHAUSTED`. Time-of-day buckets are REMOVED from V1 (single intercept), eliminating Draft 1's
unspecified branch count. Window: trailing 20 completed sessions (provisional engineering setting, not validated
sufficiency), minimum 200 rows.

**Records.** `market_state` (§1); `joint_fit` (design summary, `Â`, HC1 SEs, `Σ̂`, eigenvalues, exclusion census,
floor counts, diagnostics, refusals, dataset ids and roles, `fit_cutoff`); `joint_forecast` (parameters digest,
seed, `N`, truncation `c`/`κ`/rejections, per-comparator moments, availability failure rates, `E_lower`/`E_upper`);
the funnel trace gains `joint` (comparator table, the five decision-rule checks with their numbers, adverse-scenario
table, ablation table, degraded labels). The r3 canonical proposal and its binding are unchanged.

**The four attribution checks stay separate** (ordering/integrity via the funnel binding; availability via §1;
leakage-free fitting via §1.4 and the firewall; reconstruction via T17). None implies calibration or expectancy.

---

## 8. Operator decisions still needed before implementation

1. **State representation** (§2.1): log-IV slope skew, ATM-proxy size with gate-only authority, spread floor 1e-4.
   (Reviewer holds approval pending this draft.)
2. **Decision constants** (§5.3): Bonferroni over eligible candidates at α = 0.05; 1 SE rank separation; accounting
   uncertainty ≤ 25 %; availability failure ≤ 5 %. Provisional: `N = 4,000`, 20-session window.
3. **Fitting data path** (§1.3): confirm `PILOT-COLLECTION` is fittable as a PROSPECTIVE_OBSERVATION dataset once
   ≥ 20 sessions exist; `HIST-A-OPTIONS` TRAIN/VALIDATION only under `R4-FIT-001`; sealed roles untouched.
4. **Fit budget** (§7): 8 enumerated estimation runs per session day.
5. **Selection by name, no promotion** (already approved): `JOINT_FUNNEL_V1` is selected explicitly;
   `PILOT_RULE_V1` remains the operational default; no automatic activation or promotion is created.

## 9. Named for later, not V1

Contract-specific executable conditions (per-strike displayed size and queue) to replace the ATM size proxy;
recursive contemporaneous effects with a stated identification argument and a matching estimator; regime-dependent or
time-of-day parameters; jumps; multi-leg expressions; an IV process for the pricing model's own uncertainty.

## 10. Deliverables of the implementation brick (after this draft is accepted)

`apex/joint_wb/{permissions,state,model,comparators,accounting,decision_rule,attribution,synthetic_world}.py`;
`JOINT_FUNNEL_V1` in `apex/decision_wb/engine.py` (by name; `FULL_FUNNEL_V1` and `PILOT_RULE_V1` untouched); study
contracts `R4-FIT-001` and `R4-ATTR-001` declared and hashed before any data read; the §6.1 tests; the §6.2 frequency
reports as evidence files; this document promoted with the implemented state and the §7 evidence table.
