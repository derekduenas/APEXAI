# ALPHA-EXP-001 — qualifications (additive; nothing above is erased)

## 1. The positive-control fixture was changed after failures. That is test development, and it is recorded as such.

The engineering suite's "planted signal" tests failed twice before they
passed. The sequence, verbatim from the runs:

| Attempt | Fixture | Validation n | mean loglik gain | HAC SE | iid SE | t | Verdict | N0 t |
|---|---|---|---|---|---|---|---|---|
| 1 | AR(1) φ=0.35, 8 sessions | 662 | — | — | — | — | NO_SIGNAL | — |
| 2 | AR(1) φ=0.60, 12 sessions | 993 | — | — | — | — | NO_SIGNAL | — |
| diagnostic | φ=0.00, 16 sessions | 1324 | −0.00153 | 0.00396 | 0.00152 | −0.39 | NO_SIGNAL | +0.87 |
| diagnostic | φ=0.60, 16 sessions | 1324 | −0.00660 | 0.01283 | 0.00799 | −0.51 | NO_SIGNAL | −2.25 |
| 3 (final) | AR(1) φ=0.90, 16 sessions | 1324 | +0.11461 | 0.05498 | 0.02450 | **+2.08** | SIGNAL_DETECTED | −4.43 |

Attempts 1 and 2 recorded no statistic in the test output because my first
diagnostic printed the wrong dictionary keys and showed `nan`; the diagnostic
row for φ=0.60 is the same configuration re-read by its real keys.

**What the final PASS proves:** that the pipeline detects an AR(1) structure
with coefficient 0.9 in one-minute returns, at ~1,300 validation rows, and
that the N0 block-permutation control then correctly returns NO_SIGNAL.

**What it does not prove:** sensitivity to any plausible market effect. A
one-minute AR(1) of 0.9 is far outside anything expected in SPY. The fixture
was strengthened *until the harness could see it*; it was not chosen to
resemble a market. The moderate fixture (φ=0.60) produced a *negative*
likelihood gain — the OLS-fitted mean costs out-of-sample likelihood when the
true effect is weak — which is itself a property of M1 that real data will
also exhibit, and which pushes small effects toward NO_SIGNAL.

The original fixtures, the parameter changes, and the diagnostics are
preserved above and in the commit history of `tests/test_exp001_engineering.py`.

## 2. "Realistic SPY predictability would produce t ≈ 0.3" — withdrawn as stated, and replaced with the calculation

The earlier sentence gave a number without its assumptions. Writing the
assumptions down shows the number was wrong by about an order of magnitude.
This section is labelled **ILLUSTRATIVE**: the quantities are assumptions,
and the only measured anchors are the fixture rows above.

**Setup.** Two Gaussian forecasts with the same σ; M1's mean carries the
predictable component δ_t, M0's mean is zero. Per-sample log-likelihood
differential d_t = logL_M1 − logL_M0.

**Effect size.** Define R² as the fraction of target variance explained by
δ_t. Then, in the large-sample limit where M1's fit is close to the truth:

- E[d] ≈ R² / 2 nats per sample (for small R²)
- SD[d] ≈ √R² per sample

**Sample.** Validation 2020–2021, regular session, ~170,000 usable rows
(assumption: ~505 sessions × ~340 rows after warm-up and embargo).

**Dependence.** Adjacent 15-step targets share 14 of 15 increments. The
Bartlett-HAC standard error with L = 14 was **measured at 2.2× iid** on the
fixture; the theoretical inflation for a random-walk sum is ≈ 3.2×. Both are
used below as bounds.

**Statistic.** t_HAC ≈ ( E[d] / (SD[d]/√n) ) / inflation = √(n·R²) / (2·inflation).

| Assumed R² | √(n·R²) | t at 2.2× (measured) | t at 3.2× (theory) | Expectation |
|---|---|---|---|---|
| 0.0001 (0.01%) | 4.1 | **0.9** | 0.6 | NO_SIGNAL likely |
| 0.001 (0.1%) | 13.0 | **3.0** | 2.0 | borderline — genuinely uncertain |
| 0.01 (1%) | 41.2 | 9.4 | 6.4 | detectable |

**Correction.** The earlier "t ≈ 0.3" corresponds to no coherent assumption
in this table; the nearest defensible statement is that at R² ≈ 0.01% the
expected t is below 1. At R² ≈ 0.1% the experiment sits *near its threshold*.

**Consequence for the registration.** NO_SIGNAL is a reasonable
*expectation* if the effect is at the low end of what the literature
suggests. It is **not a predetermined verdict**: at R² ≈ 0.1% the registered
design has meaningful power, and the estimation-cost effect seen on the φ=0.60
fixture cuts the other way. The verdict will be whatever the sealed statistic
says.

**Check against the fixture.** For φ=0.9 the predictable fraction is roughly
R² ≈ 0.18, predicting E[d] ≈ 0.09 nats; measured 0.115. The measured SD[d]
(0.0245 × √1324 ≈ 0.89) is about twice √0.18 ≈ 0.42, because the AR structure
inflates the target's variance beyond the σ the models use. So the formula
is right in kind and rough in scale — which is why it is labelled
illustrative.

## 3. Three things the admission document ran together, now separated

**(i) The synthetic laboratory's prohibition on real data.**
`WORLD_MODEL_SOURCE_BOUNDARY_V0`: real-evidence roots refused by resolved
path, permitted classes limited to fixtures, no override. This is a property
of the *laboratory package*, and its purpose is to keep the synthetic lab
uncontaminated by labels, outcomes, book P&L and execution results. **It must
remain intact.** It is not a finding about any dataset.

**(ii) The eligibility of the historical datasets.** A property of the
*data*, assessed per source, field and cutoff in `EXP001_ELIGIBILITY.md`.
The SPY continuous corpus is `ELIGIBLE_WITH_EXPLICIT_LIMITATIONS`. That
finding stands on its own and is not answered by (i) in either direction.

**(iii) Whether an eligible dataset may enter a separately governed
real-data research path.** This is the decision the reviewer owns, and it
is a *new* authority with its own boundary, manifest and record — not an
exemption carved into (i).

**Consequence for the options I offered earlier.** Option A (extend the
laboratory's boundary with a real class) would weaken (i) and is withdrawn as
a recommendation. Option B (mirror real bars into the fixture root with a
provenance manifest) keeps (i) textually intact but makes real bars *look
like* fixtures, which is a workaround, not governance; it is retained only as
a documented expedient. The recommendation is now **(iii) as its own
boundary**: a real-data research contract that admits datasets by an explicit
eligibility record and manifest, forbids the same labels/outcomes/P&L
categories, and through which `exp001.run` executes unchanged. EXP-001's
loader takes the boundary as a parameter for exactly this reason.

**The exact blocker, restated.** Real-data execution of EXP-001 is BLOCKED
because (iii) does not exist and (i) correctly refuses. It is not blocked by
(ii): the dataset is eligible with recorded limitations.

## 4. Registration timing

`EXP001_REGISTRATION_V0` was written and its hash
(`1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c`)
committed at `7f26e938` **before any real row was read**, and no real row has
been read since. The primary statistic is `DEPENDENCE_AWARE_DM_HAC_V0`,
threshold 2.0, L = 14, n ≥ 60, orientation d = logL_M1 − logL_M0, one-sided.
The fixture parameters in the engineering tests are not part of the
registration and their change does not alter it.
