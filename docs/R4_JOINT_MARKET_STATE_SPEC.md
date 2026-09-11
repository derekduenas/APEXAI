# R4 — Joint market-state forecasting: executable specification (FOR REVIEW; nothing implemented, nothing fitted)

Status: `SPECIFICATION_DRAFT_1` on branch `frontier-build`. This document authorizes NOTHING. No code under
`apex/` changes with it; no historical data is opened; no model is fitted; no service, limit, maintenance block,
backtest hold or real-money authority changes. Implementation begins only after independent review of this text,
and historical fitting only under a separately declared and authorized study contract.

"Executable" means: every requirement below names the record it produces, the refusal code it raises, or the test
that pins it. A requirement without one of those is not a requirement and must be removed before implementation.

## 0. Objective, horizon, non-goals

**Objective.** At a decision instant `t_d`, estimate how the underlying price `S`, the ATM implied volatility
`iv`, the slice skew `sk`, the ATM relative spread `sp` and the available size `sz` evolve JOINTLY over the existing
15-minute horizon `H = 900 s`; reprice each eligible expression inside every simulated future state; compare the
expressions against WAIT on after-cost economics; act only when the ranking is decision-relevant under the declared
uncertainty rules; record everything so that each probability, selection and paper order is attributable to
information recorded before its outcome.

**Baseline preserved.** The current engine (`FULL_FUNNEL_V1`: GARCH-t underlying paths, `IV_FIXED`,
`SPREAD_FIXED`, size unmodelled) stays as `BASELINE` and remains the default selection policy. R4 adds a
selection policy `JOINT_FUNNEL_V1` that must be selected by name.

**Non-goals (V1).** Multi-leg expressions; intraday re-fitting; jumps; feedback from option state to the
underlying path within the horizon; options on anything but the pilot symbols; any claim of calibration or
positive expectancy (both are separate evidence classes, §7).

**Governance constants (unchanged by this brick).** Kernel limits (`$500` per trade, `$1,500` aggregate, `$600` same
underlying, `$1,000` family, `$1,000` drawdown halt); envelope `min(ref ask × 1.1, $5.00)`; period policy (exposed
≤ 2021-12-31; 2022+ SEALED); maintenance block on `apex-options-paper.service`; collector observation-only; fee
schedule SYNTHETIC / UNVERIFIED; no broker orders.

## 1. Information available at decision time

### 1.1 Input contract

Every input the joint model or the pricing model reads carries the same six fields, or it is refused
(`INPUT_CONTRACT_MISSING:<field>`): `event_time` (when the fact was true in the market), `available_time` (when this
process could first have read it), `source` (provider id + endpoint or corpus file + row), `revision_policy`,
`max_age_s` (at `t_d`), `quality` (VALID | STALE | MISSING | REJECTED with reason).

| Input | Event time | Availability | Source (live / corpus) | Revision policy | Max age at `t_d` |
|---|---|---|---|---|---|
| Underlying 1-min bar | bar START (UTC) | `bar_complete + receipt lag` (BarStore) | Alpaca v2 bars / corpus `underlying_*.json.gz` | revisions accepted only if `available ≤ t_d`; the earlier version is retained and served for any `as_of` before the revision (existing BarStore semantics) | 120 s (last bar age) |
| Underlying NBBO (bid, ask, sizes) | provider quote timestamp | receipt time | Alpaca `quotes/latest` (`AlpacaBarsAdapter.nbbo`) / corpus `underlying_ref` on the option row | no revisions; a newer quote supersedes, older ones are retained in the collection record | 15 s |
| Option quote (bid, ask, sizes) per contract | provider timestamp (ThetaData ET-naive → localized) | receipt time | ThetaData v3 snapshot (`ThetaChainAdapter.parse_chain`) / corpus `quotes_*.csv.gz` | no revisions; superseded by newer receipt | indicative 120 s; execution 15 s (boundary, unchanged) |
| Option chain membership (expirations, strikes) | receipt time | receipt time | ThetaData expirations + chain / corpus | daily; a contract absent from the latest snapshot is INELIGIBLE, never carried forward | 1 session |
| Open interest | previous close | receipt time | ThetaData / corpus `oi_*.csv.gz` | daily | 1 session (feature only; never a size proxy) |
| Fee schedule | schedule hash | static | `fees.py` | version-hashed; changes are a new schedule id | n/a |
| Calendar (expiry instant) | — | static | `expiration + 16:00 America/New_York` | n/a | n/a |
| Fitted model parameters | fit cutoff epoch | fit completion | walk-forward fit (§2.5) | a refit replaces parameters only for decisions with `t_d > fit_completion` | one session (refit each session day) |

Tests: `test_r4_inputs_missing_contract_field_refused`, `test_r4_input_available_after_decision_refused`
(every input type; the composing function must raise `FUTURE_INPUT:<name>` for `available_time > t_d`),
`test_r4_bar_revision_after_decision_is_invisible` (existing BarStore semantics re-asserted through the new state
composer).

### 1.2 Asynchronous underlying and option quotes

Underlying and option quotes never share a timestamp. Rules, in order:

1. **Decision instant.** `t_d` is the boundary clock reading at the start of the scan. All ages are `t_d − event_time`.
2. **Spot for path simulation.** `S_0` = last completed bar close whose `available ≤ t_d` (age ≤ 120 s); if the NBBO
   mid is VALID (age ≤ 15 s) it is recorded alongside as `S_nbbo`; the simulation uses `S_0` and the difference
   `log(S_nbbo/S_0)` is recorded as `spot_async_gap` and must be `< 0.002` (`SPOT_ASYNC_GAP_EXCEEDED` → WAIT).
3. **Underlying reference for each option quote.** Implied vol is inverted with the underlying reference AT THE
   OPTION QUOTE'S OWN TIME: the corpus row's `underlying_ref` (when `moneyness_status == CAUSAL`), or the latest
   underlying NBBO mid / bar close with `event_time ≤ quote.event_time` and `quote.event_time − event_time ≤ 5 s`.
   No such reference → the quote is `IV_UNUSABLE: NO_CONTEMPORANEOUS_UNDERLYING` (still usable as an execution
   quote for ranking at its own price; never for IV or skew).
4. **Slice coherence window.** Skew and the SVI slice are computed only from quotes whose event times all fall
   inside a 30-second window ending at the newest quote (`SLICE_COHERENCE_S = 30`). Otherwise the slice is
   `INCOHERENT`, skew is MISSING (declared), and any comparator that needs skew degrades to its declared fallback (§2.4).
5. **Ordering.** A quote with `event_time > t_d` or `available_time > t_d` is a firewall violation (`FUTURE_INPUT`),
   not a stale quote.
6. **Validation before use.** Every quote passes `sanitize_quote` (finite typed timestamp, sides, sizes,
   consistency, age) BEFORE IV inversion, skew, features or ranking (r3 rule, unchanged).

Tests: `test_r4_iv_uses_contemporaneous_underlying_only`, `test_r4_incoherent_slice_makes_skew_missing`,
`test_r4_spot_async_gap_refuses`, `test_r4_future_quote_is_firewall_not_staleness`.

### 1.3 The `MarketState` record (kind `market_state`, persisted with every joint decision)

```
{ symbol, t_d, S_0 {value, event_time, available_time, source, age_s, quality}, S_nbbo {...}, spot_async_gap,
  expiry {expiration, expiry_epoch, T_entry_years, T_exit_years},
  iv_atm {value, method: "BSM mid inversion, EUROPEAN_APPROX, contemporaneous underlying", quotes_used: [contract ids], event_time_span_s, quality},
  skew {value (§2.1 definition), slice: {coherent, n_quotes, window_s, svi: {params, fit_ok, rmse, butterfly} | null}, quality},
  spread_rel_atm {value, quality}, size_atm {value = min(bid_size, ask_size) at ATM, quality},
  prefix_returns {n, first_event_time, last_event_time},
  state_hash (canonical hash of everything above) }
```

`state_hash` is the value the joint forecast and the trace reference; a decision whose `market_state` does not
verify against its hash is `REFUSE` at the boundary (same mechanism as the twin `state_hash`).

## 2. The minimal joint model and its comparators

### 2.1 State variables (V1)

| Symbol | Definition at time t | Unit |
|---|---|---|
| `r` | log return of the underlying over the horizon (sum of 1-minute log returns) | log |
| `x_iv` | `log(iv_atm)` where `iv_atm` = mean of CALL and PUT ATM BSM implied vols (contemporaneous underlying) | log |
| `x_sk` | `skew` = `iv(K_−) − iv(K_+)` for the strikes nearest `S·e^{−0.02}` and `S·e^{+0.02}` at the same expiry (when the SVI slice is `fit_ok`, the same quantity evaluated from the slice; source recorded) | vol points |
| `x_sp` | `log(spread_rel_atm)` = log((ask − bid)/mid) at ATM | log |
| `x_sz` | `log(1 + size_atm)` | log |

Horizon changes are `Δx = x(t_d + H) − x(t_d)`. Skew, spread and size are measured at the SAME expiry the pilot
rule selects (first expiry with DTE ≥ 21), so the state is the state of the traded slice.

### 2.2 Dynamics (JOINT-V1, one declared form)

Underlying: unchanged — 1-minute GARCH-t (or declared EWMA fallback) with the regime mixture and the truncated-t
innovations of r3, producing `r` per path.

Option state, conditional on the path's `r` and its realized path variance `q = Σ e_t²` (both from the same path):

```
Δx_iv = a_iv + b_iv · r + c_iv · (log q − log E[q])       + σ_iv · ε_iv
Δx_sk = a_sk + b_sk · r                                     + σ_sk · ε_sk
Δx_sp = a_sp + b_sp · |r| / sqrt(E[q]) + c_sp · Δx_iv      + σ_sp · ε_sp
Δx_sz = a_sz + b_sz · |r| / sqrt(E[q]) + c_sz · Δx_sp      + σ_sz · ε_sz
(ε_iv, ε_sk, ε_sp, ε_sz) ~ N(0, R), R a correlation matrix, each ε truncated at ±6 sd and renormalized (declared)
```

Dependence assumptions (declared, each with a test that they hold in the implementation): the option state
depends on the underlying only through `(r, q)` of the same path (common random numbers); no feedback from option
state to the underlying within the horizon; parameters are regime-independent in V1; the option-state innovations
are jointly Gaussian given `(r, q)`. Time-of-day effects: `a_·` may carry one declared time-of-day bucket (open /
mid / close) if the estimation window supports it; otherwise a single intercept (recorded).

Forecast vs pricing model (kept distinct, both recorded):

- **Forecast model** = the dynamics above: it produces future STATES `(S_H, iv_H, sk_H, sp_H, sz_H)` per path.
- **Pricing model inside a state** = the slice model that turns a state into a contract's mid:
  `iv_K(state) = iv_H + slope(sk_H) · log(K/S_H)` with `slope` the linear map implied by the skew definition
  (two-point), then BSM European at `(S_H, K, T_exit, iv_K)`; `exit_bid = mid − ½ · sp_H · mid`; if `sz_H < 1`
  the exit is `NOT_ACHIEVABLE` on that path (§4.3). This is the same pricing model in every comparator; only the
  forecast of the state differs.

### 2.3 Comparators (predetermined; identical populations, contracts and underlying paths)

| Id | Δx_iv | Δx_sk | Δx_sp | Δx_sz | Correlation R |
|---|---|---|---|---|---|
| `BASELINE` (current engine) | 0 | 0 | 0 | ∞ (unmodelled) | — |
| `C_IV` | modelled | 0 | 0 | ∞ | — |
| `C_IV_SK` | modelled | modelled | 0 | ∞ | R restricted to (iv, sk) |
| `C_EXEC` | 0 | 0 | modelled | modelled | R restricted to (sp, sz) |
| `C_INDEP` | modelled | modelled | modelled | modelled | R = I |
| `JOINT` | modelled | modelled | modelled | modelled | R estimated |

Every comparator prices with the same pricing model, the same fees, the same underlying paths (same seed), the
same eligible contracts and the same decision rule (§4). No comparator is added, removed or re-parameterized after
the first decision population is evaluated (search budget 0 for comparator design; recorded in the study contract).

### 2.4 Declared fallbacks (labelled on every trace)

| Condition | Fallback |
|---|---|
| Skew MISSING (incoherent slice or < 2 usable strikes) | `C_IV_SK`, `C_INDEP`, `JOINT` evaluate with `Δx_sk = 0` and are labelled `SKEW_DEGRADED`; attribution tests exclude degraded rows from skew comparisons and count them |
| Size MISSING | `sz` treated as MISSING → any comparator that models size labels `SIZE_DEGRADED` and applies the `NOT_ACHIEVABLE` rule with `P = P(sz_H < 1)` unknown → WAIT for those comparators (declared: no trade without a size model when size is a modelled input) |
| Joint fit REFUSED (§2.6) | `JOINT_FUNNEL_V1` returns WAIT with the refusal; `BASELINE` remains available and is what the trace records as the alternative — never an automatic switch of policy |

### 2.5 Estimation (walk-forward; authorized separately)

- **Training rows.** One row per (session, decision minute on the 15-minute grid) with `(r, q, Δx_iv, Δx_sk,
  Δx_sp, Δx_sz)` computed from data whose `available_time ≤` the row's `t_d + H` and, for fitting, whose
  `t_d + H ≤ fit_cutoff`. The `Model.fit` firewall (`available ≤ cutoff`) applies to every row.
- **Window.** Trailing 20 completed sessions (≈ 480 rows); minimum 200 rows else `INSUFFICIENT_HISTORY`.
- **Cadence and budget.** One joint fit per session day, on sessions strictly before the day; the underlying GARCH
  and regime fits are unchanged. Fit budget for the brick: 3 fits per session day (GARCH, regime, joint); an
  exhausted budget refuses (`FIT_BUDGET_EXHAUSTED`).
- **Estimator.** Equation-by-equation OLS for `(a, b, c)` with HC-robust standard errors recorded; `σ` from
  residuals; `R` from standardized residuals; no regularization in V1 (declared).
- **Data that may be used, and when.** (i) The prospective collector observations (`/apex-data/pilot_collection/`)
  once ≥ 20 sessions exist — these are PROSPECTIVE and require no period-policy exception; (ii) the exposed corpus
  (≤ 2021-12-31) only under a declared `HistoricalStudyContract` (R4-FIT-001) that the operator authorizes
  separately; (iii) the sealed periods: never. This specification authorizes none of these.

### 2.6 Numerical refusals (each a test)

`INSUFFICIENT_HISTORY` (< 200 rows); `NONFINITE_INPUT`; `DEGENERATE_STATE` (any `σ_· = 0` or any state series
constant); `COVARIANCE_NOT_PD` (R not positive definite after estimation; no shrinkage repair in V1);
`COEFFICIENT_OUT_OF_BOUNDS` (`|b_iv| > 20`, `|b_sk| > 5`, `|b_sp| > 10`, `|c_·| > 10` — declared sanity bounds;
a fit outside them is refused, not clipped); `RESIDUAL_NONGAUSSIAN_FLAG` (Jarque–Bera p < 0.001 is RECORDED as a
flag, not a refusal, in V1); `SIMULATION_STATE_INVALID` (`iv_H ≤ 0`, `sp_H < 0`, non-finite); `PRICING_REFUSED`
(BSM inputs invalid on a path → that path is `UNPRICEABLE` and counted; > 1 % unpriceable paths → the candidate is
`REJECTED: UNPRICEABLE_PATHS`).

## 3. Layer attribution (predetermined comparisons)

**Population.** The same decision population for every comparator: every scan where `BASELINE` reached the
expression war (fit READY, valid quotes, eligible expiry). Rows where skew or size is degraded are counted and, for
the comparisons that isolate skew or execution, excluded from BOTH sides.

**Two estimands per comparator, each on identical rows:**

1. **Forecast quality of the exit value** — the quantity a trader needs: for each eligible contract on each scan,
   the comparator's predictive distribution of `exit_bid` is scored against the realized exit bid at `t_d + H`
   (log score under the simulated empirical distribution with a declared kernel bandwidth; CRPS; PIT). Paired
   differences vs `BASELINE`, session-block bootstrap CI. This is the primary attribution estimand because it does
   not depend on the decision rule.
2. **Decision economics** — per-scan after-cost outcome of the comparator's decision (resolved TRADE = net, WAIT = 0,
   unresolved excluded and counted; the r2 `paired_per_scan` estimand), paired vs `BASELINE` and vs WAIT.

**Isolation and joint contribution.** `C_IV − BASELINE` isolates IV dynamics; `C_IV_SK − C_IV` isolates skew;
`C_EXEC − BASELINE` isolates execution conditions; `JOINT − C_INDEP` isolates dependence (correlation);
`JOINT − BASELINE` is the joint contribution, reported on its own — it is NEVER inferred as the sum of the isolated
parts, and the interaction `JOINT − BASELINE − Σ(components)` is reported explicitly.

**Pre-registration.** All of the above, with the bootstrap method, seed, and the fixed comparator table, live in
`R4-ATTR-001` (a `HistoricalStudyContract` or its prospective equivalent) declared and hashed before any decision
population is scored. Search budget: 0 additional comparisons.

## 4. Decision uncertainty

### 4.1 Monte Carlo uncertainty (every candidate, every scan)

Per candidate: `E[net]`, `SE_mc(E[net]) = sd(net)/√N`; per pair (candidate vs WAIT, candidate vs runner-up):
paired SE on common paths. `N = 4,000` paths in V1 (declared; the SE is what is checked, not N).

### 4.2 Assumption sensitivity (every selected candidate)

Recorded expected net P&L under: tail cap ∈ {6, 8, 12} sd; `Δx_iv` forced to 0; `Δx_sp` doubled; `R = I`;
`sz` floor at 1 (no NOT_ACHIEVABLE). The selection is `ROBUST_POSITIVE` only if `E[net] > 0` under every scenario.

### 4.3 From uncertain rankings to WAIT (declared rule, `JOINT_DECISION_RULE_V1`)

A candidate `c*` (max `E[net]` among ELIGIBLE, envelope-feasible candidates) becomes a proposal only if ALL hold;
otherwise the decision is WAIT with the FIRST failing reason recorded:

1. `E[net](c*) − 2 · SE_paired(c* − WAIT) > 0` — else `MC_NOT_DISTINGUISHED_FROM_WAIT`;
2. `E[net](c*) − E[net](c₂) > 1 · SE_paired(c* − c₂)` for the runner-up `c₂` — else `RANK_UNCERTAIN` (the two best
   expressions are not separated; no coin-flip between them);
3. `ROBUST_POSITIVE` under §4.2 — else `NOT_ROBUST_TO_ASSUMPTIONS:<first failing scenario>`;
4. `P(exit NOT_ACHIEVABLE) ≤ 0.05` on `c*`'s paths — else `EXIT_LIQUIDITY_RISK`;
5. PRIME supervision ACT (unchanged r3 policy: staleness, disagreement, regime, book, affordability).

Statement carried on every trace: passing this rule establishes that the MODEL-CONDITIONAL ranking is
decision-relevant under the declared uncertainty; it does NOT establish positive expectancy, which is a separate
prospective evidence class (§7).

## 5. Synthetic acceptance (implementation correctness first; power and calibration separately)

All synthetic worlds are generated by a declared generator (`apex/…/r4_synthetic_world.py`, TO BE WRITTEN) whose
mechanism is known exactly, so recovery can be asserted numerically. Every test is deterministic given its seed.

### 5.1 Implementation correctness (small n, exact assertions)

| Test | World | Assertion |
|---|---|---|
| `test_r4_known_mechanism_recovery` | `b_iv = −0.6`, `b_sp = +0.4`, `R[iv,sk] = 0.5`, others 0; 1,000 rows | fitted `(b_iv, b_sp, R[iv,sk])` within 3 robust SE of truth; every other coefficient within 3 SE of 0 |
| `test_r4_absent_mechanism_no_false_attribution` | all option-state dynamics 0, `R = I` | `JOINT` and `BASELINE` exit-value forecasts agree within MC error on every row; the attribution report shows every isolated contribution's CI covering 0 |
| `test_r4_stale_inputs_degrade_by_declaration` | option quotes 1000 s old / underlying reference missing / slice spread over 60 s | quotes rejected before use; skew MISSING → `SKEW_DEGRADED` label; IV unusable → WAIT `PREREQUISITE_MISSING`; no pricing call sees a rejected quote (recorded, as in r3) |
| `test_r4_asynchronous_pairing` | option quote at `t`, underlying at `t − 3 s` and `t − 30 s` | IV inverted with the 3-s reference; the 30-s one refused `NO_CONTEMPORANEOUS_UNDERLYING` |
| `test_r4_adverse_liquidity` | `b_sz` strongly negative so `P(sz_H < 1) = 0.3` on up-moves; wide spreads | exits `NOT_ACHIEVABLE` counted per path; rule 4 → WAIT `EXIT_LIQUIDITY_RISK`; with size floored, TRADE — showing the rule binds |
| `test_r4_numerical_failures` | non-PD R; constant state; `b_iv = 50`; nonfinite row; > 1 % unpriceable paths | each named refusal; no parameters written; the engine WAITs with the refusal on the trace; budget not consumed by input refusals |
| `test_r4_deterministic_reconstruction` | any world | same recorded `market_state` + parameters + seed → byte-identical trace digest and proposal; a changed seed changes only the simulation section |
| `test_r4_forecast_vs_pricing_separation` | any world | the pricing model applied to a KNOWN future state reproduces the analytic BSM value (no forecast involved); the forecast model produces states without touching pricing |
| `test_r4_common_random_numbers` | any world | all comparators on one scan share identical underlying paths (`S` arrays equal), differ only in option state |
| `test_r4_unconditional_boundary_path` | synthetic twin with the planted mechanism | `JOINT_FUNNEL_V1` FULL mode → real joint engine selects → persisted `market_state` + funnel → digest-bound intent with certified reservation → FILLED → RESOLVED exit → book closed clean; asserted unconditionally (the r3 acceptance pattern) |
| `test_r4_mandatory_wait_cases` | one world per rule in §4.3 | each rule produces WAIT with its named reason; the corresponding intent never exists |
| `test_r4_firewall_on_fit` | rows with one `available > cutoff` | `FIREWALL` refusal; no fallback |

### 5.2 Statistical power (declared, reported, not an acceptance gate for correctness)

For planted effect sizes `b_iv ∈ {−0.2, −0.6}`, `R[iv,sk] ∈ {0.3, 0.6}` at `N ∈ {200, 480, 2,000}` rows: the
probability (over 200 seeds) that the isolated attribution CI excludes 0. Reported as a power table in the evidence
file; a planted effect the design cannot detect at the V1 window is a documented limitation, not a failure.

### 5.3 Calibration (separate evidence class)

On a world where JOINT is the true model: PIT of the exit-value forecast uniform (KS p > 0.05 over the seeds);
on a misspecified world (jumps injected): PIT non-uniform and the `RESIDUAL_NONGAUSSIAN_FLAG` raised. Neither
result transfers to markets; market calibration is prospective evidence only.

## 6. Records, traces and attribution of every number

New record kinds: `market_state` (§1.3), `joint_forecast` (parameters digest, fit cutoff, N, seed, per-comparator
moments, `NOT_ACHIEVABLE` probabilities), and the funnel trace gains `joint` (comparator table, decision-rule
checks 1–5 with their numbers, sensitivity table, degraded labels). The proposal's canonical terms (r3) are
unchanged; the intent binds to the funnel record exactly as before. A decision is attributable when: every input on
the `market_state` has `available_time ≤ t_d` (availability), the parameters' `fit_cutoff < t_d` (no future
observations in the fit), the trace digest reproduces from the persisted inputs and seed (reconstruction), and the
funnel binding verifies (ordering/integrity). These four are separate checks and are reported separately; none
implies calibration or expectancy.

## 7. Evidence classes carried forward (do not conflate)

| Class | What establishes it | Status after this brick, if accepted |
|---|---|---|
| Ordering / integrity | funnel binding, chain, digests | established (synthetic) |
| Availability at `t_d` | per-input firewall tests (§1) | established (synthetic) |
| Leakage-free fitting | fit-cutoff firewall + walk-forward tests | established (synthetic) |
| Implementation correctness | §5.1 | established (synthetic) |
| Statistical power | §5.2 | reported, world-specific |
| Calibration | §5.3 synthetic; prospective PIT on live observations | synthetic only; market: UNESTABLISHED |
| Positive expectancy | prospective paper outcomes under the declared rule, n ≥ the reporting-sufficiency prior | UNESTABLISHED |
| Live commissioning | operator authorization, fee verification, adapter commissioning | UNESTABLISHED |

## 8. Deliverables of the implementation brick (after review)

1. `apex/joint_wb/state.py` (MarketState composer + refusals), `apex/joint_wb/model.py` (JOINT-V1 fit/forecast under
   the `Model` contract), `apex/joint_wb/comparators.py` (the fixed table), `apex/joint_wb/decision_rule.py`
   (§4.3), `apex/joint_wb/attribution.py` (§3 estimands), `apex/joint_wb/r4_synthetic_world.py` (§5 generator).
2. `apex/decision_wb/engine.py`: `JOINT_FUNNEL_V1` selection policy (by name; BASELINE untouched).
3. Study contracts declared and hashed before any data: `R4-FIT-001` (fitting authorization request; NOT executed by
   the brick), `R4-ATTR-001` (attribution pre-registration).
4. Tests of §5.1 plus the power and calibration reports of §5.2–5.3 as evidence files.
5. Docs: this specification promoted to `R4_JOINT_MARKET_STATE.md` with the implemented state, the evidence table of
   §7, and the operator decisions below.

## 9. Operator decisions this specification needs before implementation

1. Approve the state definitions (§2.1: ±2 % moneyness skew; ATM size = min side) or amend.
2. Approve `N = 4,000` paths and the decision-rule constants (2 SE vs WAIT, 1 SE vs runner-up, 5 % exit-liquidity).
3. Confirm the fitting data path: prospective collector sessions first (≥ 20), corpus only under `R4-FIT-001`.
4. Confirm the fit budget (3 per session day) and the window (20 sessions).
5. Confirm that `JOINT_FUNNEL_V1` is selection-by-name only and that no promotion rule is created by this brick.
