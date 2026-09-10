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
