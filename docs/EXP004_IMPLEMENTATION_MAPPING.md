# EXP-004 implementation → registration mapping (candidate `32c82b2c`)

Registration hash preserved: `9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9`
(`apex/world_model/exp004/registration.py` unchanged; verified by sha256 on the
host after the candidate commit). Synthetic only; no historical data was read.

| Registration | Implementation | Test |
|---|---|---|
| R3 features `B, B̄, P, F`, `W=10`, `V̄` median with support ≥100 | `features.body`, `pressure_from_window`, `fit_baselines` | N1, N2 (identity, divisor `W`), N3, `test_feature_refusals_and_valid_cases` |
| R3 clipping: `⌈0.99n⌉`-th order statistic, exact | `features.order_statistic(num, den)` — **exact integer arithmetic** (`(num·n+den−1)//den`); floating `ceil(q·n)` was found to round up | `test_feature_refusals_and_valid_cases` |
| R4 arms `L ⊆ A ⊆ A× ⊆ C`, OLS/SVD `rcond 1e-12`, refusals | `models.COLUMNS`, `fit_arm`, `fit_all` (4 fits) | N5; `ZERO_VARIANCE_FEATURE`, `RANK_DEFICIENT` |
| R4 constant-column refusal | `fit_arm` checks `max−min == 0` **in addition to** `sd > 0`: `np.std` of a constant column can be ~1e-17 | N5 (this is what first surfaced it) |
| R5 `J₀`, `J₁`, full scoring scale, identity check 1e-9 | `dispersion.J0`, `J1`, `identity_check`, `scales`, `logpdf` | N6 (passes; teeth shown with `λ=0.5` and a sign-flipped Jacobian) |
| R5 optimiser contract, `ν` frozen for D1 | `dispersion._nelder_mead` (same coefficients as `studentt.fit_scale_nu`), `fit_d0`, `fit_d1(nu0=…)` | N6 asserts `D1.nu0 == D0.nu0` |
| R6 refusals: no filtering, `<100`, bound contact `1e-3`, `λ` bounds, finiteness, non-convergence | `dispersion._validate_residuals`, `fit_d0`, `fit_d1`, `check_scales` (`np.errstate` so overflow → `inf` → refused, never dropped) | `test_dispersion_refusals` (9 cases incl. `λ` at ±bound within tolerance and an accepted interior `λ=1.5`) |
| R7 common rows, one population for fit and dev, preprocessing order | `features.eligible_rows(_many)`; `run.prepare_fit` steps 1–7; `run.score` | N7 (pressure-only refusals remove rows from **every** arm; `n_rows` identical across all comparisons) |
| R8 HAC lag 14, `mean>0 ∧ t>2`, `±1.96·se` | `inference.hac_decision` (uses `apex.world_model.inference`) | end-to-end |
| R8 bootstrap estimand, `p̂=(k+1)/(B+1)`, percentile interval, exact indices | `bootstrap_adapter.session_stationary_bootstrap_ext`, `order_stat(num, den)` | N8 (exact equivalence to the original over 3 seeds × 3 blocks); interval test (indices 1/39 at `B=40`, 250/9750 at `B=10,000`; unequal session counts) |
| R9 classification, independent flags, integrity precedence | `inference.classify` | all 16 combinations; co-occurring flags; integrity precedence |
| R10 six-hypothesis Holm per method | `inference.secondary_family` | manual Holm comparison; method families do not mix |
| R11 budget: 10 estimations | `run.prepare_fit["estimations"]` | end-to-end asserts `{1,3,4,2,total 10}` |
| R12 N1–N8 | `tests/test_exp004_implementation.py` | 14 tests, all pass |

## Results at candidate `32c82b2c`

- `tests/test_exp004_implementation.py`: **14 passed** (19 s, contained MemoryMax=1400M).
- Regression untouched by this brick: tournament, revision2, studentt, controls, real_data_boundary, research_activation, activation_verifier_review — **188 passed** (257 s).
- Representative records (`results/exp004_synthetic_records/`): successful `NOT_SELECTED` with all three flags false on the null-ish fixture (2,630 development rows, `θ ≈ −1.9e-5`); refused `INTEGRITY_FAILURE` / `INSUFFICIENT_DEVELOPMENT_ROWS: 0 eligible` with no statistical classification.

## Observations recorded, not acted on

1. `exp002/models.py:36` uses the same `sd <= 0` constant-column test that EXP-004 found insufficient. EXP-002 is qualified and invalidated code; **not changed**. Noted for any future registration that reuses it.
2. Fixtures use 110 synthetic sessions so the registered baseline support of 100 is met without overriding it; the support rule is also tested to yield **no** baselines at 5 sessions.

These tests establish implementation behaviour. They do not establish market
signal, statistical size, or power.

---

## Contract repair — candidate `6061f3ba` (supersedes `32c82b2c`)

Registration unchanged; hash `9155024f…45bf9` re-verified after the commit.
Focused suite **19 passed** (50 s); regression on untouched suites **188 passed**.

| Reviewer finding | Repair | Test |
|---|---|---|
| 1. Non-finite scores became an ordinary `NOT_SELECTED` | `dispersion.require_finite` applied to targets, `rv_30`, `P̃`, every arm's means, reference residuals, every log-density (`logpdf` now refuses its own non-finite output), every pairwise differential, HAC inputs and statistics (`inference.InferenceRefused`), bootstrap replicates and summary values; `run.strict_json` uses `allow_nan=False` and runs before any record is returned | `test_nonfinite_values_are_integrity_refusals_never_not_selected`: the exact probes (`logpdf([1e308,…])`, `hac_decision([nan]*60)`) now raise; a poisoned mean for arm C ends as `INTEGRITY_FAILURE` with no `development` block; `strict_json` refuses NaN and Infinity |
| 2. Duplicate session objects fabricated baseline support | `features.validate_sessions`: refuses `NO_SESSIONS`, `SESSION_WITHOUT_IDENTITY`, `SYMBOL_MISMATCH`, `DUPLICATE_SESSION`, `NON_CHRONOLOGICAL_SESSIONS`; `fit_baselines` calls it and counts **unique** dates | 100 copies now refused by name; five unique sessions give no baseline; a duplicated fit session ends the run as `INTEGRITY_FAILURE` |
| 3. Session order assumed, never validated | `validate_sessions` (strictly increasing dates) at both fit and development; `run._check_row_order` refuses `ROWS_OUT_OF_ORDER` / `INTERLEAVED_SESSIONS` on the row keys before any statistic | reversed development list refused before inference; out-of-order and interleaved key sequences refused |
| 4. Reporting did not satisfy the frozen contract | `run._year_cell`: fixed cells `2019, 2020, 2021` always present; each carries `n_rows`, per-year refusal counts, every comparison (P1, S1–S3, C-vs-L) under both specs with HAC (interval) and bootstrap (percentile interval + sensitivities 1/10), and dispersion improvement; a year below 60 rows or with no sessions is an explicit `NOT_AVAILABLE` cell; years outside the registered set are listed separately | three-year fixture asserts all cells `REPORTED` with full contents and per-year refusals (INVALID_OHLC = 10 in 2019, 0 in 2020); two-year fixture asserts a `NOT_AVAILABLE` 2021 cell |
| 5. Malformed fit bars excluded rather than refused | `features.validate_fit_bars` (step 1) refuses `INVALID_FIT_BAR: <date> minute <m>: <why>`; `fit_baselines` re-checks; the `invalid_bars_excluded` counter is gone | one impossible bar among ~43,000 refuses the fit by name; run ends `INTEGRITY_FAILURE` with no `fit` block |
| N8 compared aggregates, not the replicate sequence | tracing `random.Random` injected into both modules: the **full RNG draw sequence** (method, value) is identical, length > 1,000; the exposed replicate means reproduce the original's `boot_se` and exceedances | `test_n8_adapter_preserves_the_exact_rng_draw_sequence` |
| `identical_across_all_comparisons` hard-coded | computed from a sha256 of each comparison cell's row keys and the cell sizes; a mismatch is a refusal (`ROW_POPULATION_MISMATCH`) | end-to-end asserts `key_sets == 1` |
| Budget reported, not enforced | `run.FitAccounting`: counting wrappers around the **real** `fit_baselines`, `order_statistic`, `fit_arm`, `fit_d0`, `fit_d1` for the duration of `prepare_fit`; a call beyond the registered count raises `BUDGET_EXCEEDED`; the final tally must equal the registered budget or the fit is refused; the call log is recorded | tally `{1,3,4,2}` = 10 with the ordered log; an injected fifth location fit ends as `INTEGRITY_FAILURE: BUDGET_EXCEEDED: location_fits call 5 > 4` |
| False comment about `ceil(0.025*40)` | corrected in `bootstrap_adapter.order_stat`: `0.025*40 == 1.0` in Python; the integer form is kept because it is exact for every `B` and tail, not because of that example | — |

Representative records regenerated on the three-year fixture:
`NOT_SELECTED` with all flags false over 3,950 rows, `θ ≈ −1.9e-5`; refused
`INTEGRITY_FAILURE` / `INSUFFICIENT_DEVELOPMENT_ROWS: 0 eligible`.

This brick remains implementation evidence. It does not establish market
alpha, options profitability, GARCH value, regime skill, or a working time
machine.

---

## Second contract patch — candidate `PENDING` (supersedes `6061f3ba`)

Registration unchanged. Focused suite **23 passed** (70 s).

| Reviewer finding | Repair | Test |
|---|---|---|
| Dispersion improvement reported only a HAC statistic | `_stat_record` extracted and used for **every** comparison cell, pairwise or not; `_dispersion_record` (`AX@D1 − AX@D0`, authority NONE) now carries HAC with interval, the primary bootstrap with percentile interval, and both sensitivities (1, 10) — **top-level and in every per-year cell** | `test_dispersion_comparison_reports_hac_and_bootstrap_everywhere` checks the full contents at top level and in each `REPORTED` year cell; the end-to-end test also asserts the per-year percentile interval |
| Registered date scope accepted out-of-period sessions | `features._period_refusal` + `validate_sessions(enforce_period=True)`: a date outside the role's registered range is refused `SESSION_OUT_OF_REGISTERED_RANGE`, and a date inside `evaluation` or `reserve` is named `SEALED_PERIOD_SESSION` so the record says exactly what was offered. `tournament` validates **both** lists at a new `period_scope` stage **before any preprocessing** | `test_registered_date_scope_is_enforced_not_merely_reported`: 2018 offered as development, 2019 offered as fit, and evaluation/reserve stubs are all refused; through the runner the record has `stage: period_scope` with no `fit` and no `development` block |
| Fit/development leakage | `features.validate_disjoint`: refuses `FIT_DEVELOPMENT_OVERLAP` (shared session dates) and `FIT_DEVELOPMENT_NOT_SEPARATED` (fit not entirely before development); result recorded as `periods` | `test_fit_development_overlap_is_refused` |
| Row-key hash trusted by construction | tampering tests | `test_row_key_tampering_is_an_integrity_failure`: altering one comparison's `row_keys_sha`, and separately its `n_rows`, each yields `INTEGRITY_FAILURE: ROW_POPULATION_MISMATCH` with no `development` block |

**Second protection found while testing:** sealed-period sessions cannot be
constructed at all — the exchange calendar's independently verified window ends
`2021-12-31`, so `session_bounds(require_verified=True)` refuses 2022+ dates
(`CALENDAR_NOT_VERIFIED`). The scope test asserts that refusal and then
exercises the scope check itself with identity-only stubs.

---

## Fail-closed patch — candidate `PENDING2` (supersedes `84c00bc0`)

Registration unchanged. Focused suite **27 passed**.

| Reviewer finding | Repair | Test |
|---|---|---|
| `BarsRefused` could escape the tournament | Confirmed: `BarsRefused(Exception)` is **not** a `ValueError`, so the old `REFUSALS` tuple missed it. Two layers: `features.eligible_rows` converts it at the module boundary to `FeatureRefused("BARS_REFUSED: …")` (and converts numeric `ValueError`/`ArithmeticError` from the same path to `BARS_NUMERIC`/`BARS_ARITHMETIC`), **and** `run.REFUSALS` now names `BarsRefused` and `ArithmeticError` directly | `test_bars_refused_cannot_escape_the_runner` uses a **real valid-but-extreme** session — every bar finite and positive, flat at 1e-300, one upward jump to 1e300 — so no ratio is zero or negative but `c[t]/c[t−1]` overflows to `inf`, making `rv_30` non-finite. Asserts the raw `BarsRefused("NONFINITE_FEATURE")`, the converted `FeatureRefused`, and a sealed `INTEGRITY_FAILURE` with no `development` block |
| Arithmetic/overflow failures from dispersion fitting uncaught | `fit_d0` catches `(ValueError, ArithmeticError)` → `D0_FITTER: <type>: <msg>`; the D1 optimiser call is wrapped → `D1_ARITHMETIC: <type>: <msg>`; `ArithmeticError` (covering `OverflowError`, `FloatingPointError`, `ZeroDivisionError`) is in `REFUSALS` | `test_arithmetic_failures_in_dispersion_are_named_refusals`: injected `OverflowError`, `ZeroDivisionError` and `FloatingPointError` each become named refusals, the last through the full runner |
| Finiteness checked only after `M.fit_all` | targets **and every feature column** (`ret_1, ret_5, rv_30, B̄̃, P̃, F̃`) are validated **before** the location fits | `test_nonfinite_inputs_are_caught_before_the_location_fits` spies on `M.fit_all` and asserts it **never ran**: `NONFINITE_VALUES: fit feature F_c` |
| Per-year row-key identity not independently verified | `_year_cell` now computes its own `cell_sha`/`cell_n` and requires every comparison **and** the dispersion record in that year to match, else `YEAR_ROW_POPULATION_MISMATCH: <year>`; the cell records its hash. Top level likewise verifies the dispersion record shares the population | `test_per_year_row_key_identity_is_verified_inside_each_cell` tampers a comparison **only inside the 2020 cell** — invisible to the top-level check — and gets `YEAR_ROW_POPULATION_MISMATCH: 2020`; the clean run shows three distinct, individually verified year hashes |
