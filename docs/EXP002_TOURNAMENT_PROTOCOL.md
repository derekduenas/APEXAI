# EXP-002 — BOUNDED CHALLENGER TOURNAMENT, PROTOCOL v3

**Revision for review. Nothing fitted, no admission requested, no historical data
touched. EXP-001B is unchanged.** Supersedes v2 at `ea1eb4c`.

A small nonlinear forecasting experiment. It tests a **forecasting component**;
option-price comparison and executable payoff economics are separate later stages,
and the options-only objective is untouched here.

---

## 1. WHAT EXP-001B TESTED

Information set `ret_1, ret_5, rv_30` from `[t-30min, t]`. Target
`log(close[t+15min]/close[t])`. **M0**: zero mean, `sd = rv_30 · k`, Gaussian.
**M1**: mean `a + b1·ret_1 + b5·ret_5` (OLS), same sd, Gaussian. DM-HAC lag 14,
threshold 2.0. Result `t = 0.7525`, **NO_SIGNAL**, n = 165,958.

It tested only whether a linear conditional mean beats a zero mean, with variance
model and distribution family fixed. It is preserved and not revisited.

---

## 2. ARMS

| arm | mean | family | scale / tail |
|---|---|---|---|
| **M0** | zero | Gaussian | registered `k` — **unchanged from EXP-001B** |
| **M1** | linear | Gaussian | registered `k` — **unchanged** |
| **S** | zero | Student-t | shared `(s*, ν*)` |
| **L** | linear | Student-t | shared `(s*, ν*)` |
| **C** | quadratic | Student-t | shared `(s*, ν*)` |

`C`'s mean is `a + b1·ret_1 + b5·ret_5 + b11·ret_1² + b55·ret_5² + b15·ret_1·ret_5`.

### The `k*` contradiction in v2, resolved

v2 said the shared reference came from **linear-mean residuals** but then defined
`k*` as `mean(|y|)/mean(rv_30)`, which uses **raw outcomes**. Those are different
estimators and the document asserted both. Resolved as follows.

`(s*, ν*)` are obtained by **one two-parameter maximum-likelihood fit** on the
fit-split **linear-mean residuals**, standardised by `rv_30`:

```
e = y − μ_L(x)          μ_L from the linear OLS fit on the fit split
z = e / rv_30
(s*, ν*) = argmax  Σ log t_ν( z ; scale = s )
```

`S`, `L` and `C` then use `scale = rv_30 · s*` with the same `ν*`. One estimation,
one pair of parameters, all three arms identical outside the mean.

**M0 and M1 keep the registered `k` from `mean(|y|)/mean(rv_30)`, untouched.** They
are the registered baselines and are not re-specified to suit this tournament.

### Variance is NOT matched across families — correction

v2 claimed second moments were "matched across every arm". **That was wrong.**
Matching a Student-t's implied standard deviation to its own scale says nothing
about whether it equals the Gaussian arms' standard deviation, and it does not,
because `k` and `s*` come from different estimators on different quantities.

The honest position:

- **Within the t-family** (`S`, `L`, `C`) scale and tail are **identical**, so
  `C − L` and `L − S` isolate the mean specification exactly. This is where the
  experiment's claim lives.
- **Across families** (`C − M1`, `C − M0`, `S − M0`) the comparison is **compound**:
  mean, distribution family and fitted dispersion all differ. Those are reported as
  compound comparisons and are never described as isolating anything.

---

## 3. GATES AND MULTIPLICITY

**Primary, matched:** `G1 = C − L`. Does the quadratic mean improve on the linear
mean with scale, tail and information set held fixed?

**Secondary, compound, also required:** `G2 = C − M1`, `G3 = C − M0`.

Each one-sided in favour of `C`, at the thresholds in §4, and **all three must pass
under both inference methods**.

**Reported, no promotion authority:** `L − S`, `L − M1`, `S − M0`, `M1 − M0`, with
Holm correction across those four, uncorrected values shown alongside.

### Multiplicity, stated correctly

v2 said applying a correction to the conjunction "would be wrong". **That
overstated it.** The intersection-union argument is appropriate for a fixed
conjunction of valid component tests, and requiring all three to pass controls the
type-I rate at no more than α. An additional correction would be **conservative,
not mathematically incorrect**. None is applied.

Two things this does **not** do, stated because they are easy to assume. It does
not erase the search already conducted across this research programme. And it does
not make 2019 confirmatory evidence: 2019 is development data with prior exposure,
and a pass there is candidate selection.

---

## 4. INFERENCE — BOTH REQUIRED, DISAGREEMENT IS ITS OWN VERDICT

**Primary:** Diebold-Mariano, Bartlett HAC, lag 14, one-sided `t > 2.0`. The lag is
**overlap-motivated**, not a demonstration that dependence is bounded there.

**Secondary, specified before any result:** stationary bootstrap (Politis–Romano)
over whole trading sessions.

| | |
|---|---|
| block length | geometric, **expected length 5 sessions** (one trading week) |
| why 5 | volatility dependence persists across days; this is a **declared choice**, not a derivation |
| sensitivity | also reported at expected lengths 1 and 10; a gate passing only at one length is reported as such |
| unequal sessions | sessions are resampled whole and their **row-level** differentials concatenated, so a session contributes in proportion to its row count |
| construction | centred: the bootstrap distribution of `mean* − mean_obs` |
| threshold | one-sided `p < 0.0228`, the normal-theory equivalent of `t > 2.0` |
| resamples | 10,000; seed `20260909` |

**v2 claimed the overnight gap separates sessions. Withdrawn — an overnight gap does
not establish independence between days.** Session blocks are used because
dependence is *concentrated* within sessions, not because days are independent, and
the geometric block length exists precisely to carry dependence across session
boundaries.

**Disagreement rule.** Both must pass. If they disagree the verdict is
**`NOT_SELECTED — INFERENCE_DISAGREEMENT`**, reported with both statistics. That is
neither a broken experiment nor evidence that no information exists; it is an
unresolved inference, and selection does not proceed on it.

---

## 5. NULL CONTROL — MATCHED PAIRS ONLY

N0 block permutation, 20-row blocks. **What it does, precisely:** it permutes
outcome blocks against the state sequence. It **preserves** the marginal
distribution of outcomes and the state sequence including `rv_30`. It **destroys**
every outcome-to-state association — the conditional mean **and** the conditional
variance, since the link between an outcome's magnitude and its row's `rv_30` is
broken.

Consequently every arm is mis-scaled under N0 in the same way, which is harmless for
matched pairs and uninterpretable for unmatched ones.

| differential | matched? | requirement under N0 |
|---|---|---|
| `C − L` | yes, identical scale and tail | **NO_SIGNAL** |
| `L − S` | yes | **NO_SIGNAL** |
| `M1 − M0` | yes, identical `k` and family | **NO_SIGNAL** |
| `C − M1`, `C − M0`, `S − M0` | **no** — mixes mean, family and dispersion | **no requirement**; reported only |

v2's "NO_SIGNAL on the mean channel" for `C − M1` is withdrawn: that differential
mixes mean and distribution changes and the instruction was not executable. Null
assertions are now made **only** on matched comparisons.

Failure of a required NO_SIGNAL invalidates the tournament.

---

## 6. POSITIVE CONTROLS — STANDARDISED, WITH DECLARED SIGNAL-TO-NOISE

v2's coefficients `0.05` and `0.08` did not define signal strength. **On raw
returns, `ret_1 · ret_5` has magnitude around `1e-8`, so the interaction world would
have been effectively empty.** Controls are therefore specified in **standardised**
feature units with a declared signal-to-noise ratio.

**Generator.** Standardised features `z1, z5` with `mean 0, sd 1`, carrying declared
AR(1) serial dependence `φ = 0.3` to mimic overlap. `rv_30` is generated
independently and positive. Outcome `y = β·g(z) + ε` where `g` is the world's signal
and `β` is set so that

```
R² = Var(β·g(z)) / Var(y) = declared value
```

**Orthogonality.** In W2 the signal is `g = z1·z5`. With `z1, z5` independent and
mean-zero, `E[z1²z5] = E[z1z5²] = 0`, so the interaction is **uncorrelated with both
linear features by construction**, and a linear mean cannot absorb it. This is the
property that makes W2 a real test of nonlinear sensitivity.

| world | signal `g` | R² | seed | `C − L` expected | other expectations |
|---|---|---|---|---|---|
| **W1 linear** | `z1` | 0.0010 | 1001 | **NO_SIGNAL** | `M1 − M0` SIGNAL |
| **W2 interaction** | `z1·z5` | 0.0010 | 1002 | **SIGNAL** | `M1 − M0` NO_SIGNAL |
| **W3 heavy tail only** | none; `ε` Student-t, ν = 4 | 0 | 1003 | **NO_SIGNAL** | `S − M0` gain permitted |
| **W4 null** | none; `ε` Gaussian | 0 | 1004 | **NO_SIGNAL** | nothing significant |

**Expected detectability, established before any market-data run.** For each world
the analytic expected statistic is computed as
`E[t] ≈ sqrt(n) · sqrt(R²) / ι`, with `ι` the HAC inflation factor set to **2.46**,
the value observed in EXP-001B, and `n` the control sample size. `R² = 0.0010` and
`n = 80,000` give `E[t] ≈ 3.6`. **The registration records this calculation, and if
the realised control statistic departs from it materially that is reported as an
inconclusive control.** Effect sizes are **not** retuned to produce a pass.

Control runs are on synthetic data and are counted separately from market-data fits.

---

## 7. SPLITS

| span | role |
|---|---|
| 2016-01-04 → 2018-12-31 | **fit** |
| 2019-01-01 → 2019-12-31 | **development data with prior exposure** |
| 2020-01-01 → 2021-12-31 | **OBSERVED** — secondary reporting only, no authority |
| 2022-01-01 → 2024-12-31 | **SEALED** evaluation |
| 2025-01-01 → 2026-08-28 | **SEALED** reserve |

2019 sat inside EXP-001B's fitting window. It is **development data with prior
exposure**, never pristine holdout evidence, and a pass on it is candidate
selection.

### Training-window sensitivity — renamed, demoted, and no extra fits

v2 proposed measuring "leakage" by refitting `M0`/`M1` without 2019. **That measures
training-window sensitivity. It cannot quantify how knowledge of EXP-001B's result
influenced this design**, which is not recoverable by refitting anything.

It is renamed **training-window sensitivity**, it is a **diagnostic with no gate**,
and it costs **no additional fits**: this tournament already fits `M0` and `M1` on
2016–2018, so the comparison is against EXP-001B's **recorded** 2016–2019
parameters. It is reported only if it is informative.

**The influence of prior knowledge on this design is not measured and is not
claimed to be small.**

---

## 8. ESTIMATION

**Train-only, enumerated.** `s*`, `ν*`, all regression coefficients, and the basis
centring and scaling constants come from the fit split alone.

**Least squares.** Predeclared **SVD** solver (`lstsq`) with `rcond = 1e-12`. Normal
equations are not used. The quadratic basis columns are **centred and scaled by
fit-split mean and standard deviation** before solving. That is an affine
reparameterisation: it improves conditioning, does not change the function space
spanned, and introduces no hyperparameter. **`M0` and `M1` are fitted exactly as
registered, without centring**, so the baselines remain identical to EXP-001B's.

**Student-t parameters.** Two-parameter ML on standardised linear-mean residuals per
§2. Bounds `ν ∈ [2.1, 50]`, `s > 0`. Bounded optimisation on `(log s, log ν)`,
tolerance `1e-8`, at most 500 iterations.

### Boundary outcomes — declared in advance

A Gaussian-like world will legitimately push `ν` to its upper bound. Under v2's
rules that would have invalidated the controls themselves.

| outcome | treatment |
|---|---|
| `ν*` at **upper** bound (50) | **legitimate**, recorded as `nu_at_upper_bound: true`. The t-arm is near-Gaussian by construction and the run proceeds. Expected in W1, W2 and W4. |
| `ν*` at **lower** bound (2.1) | **refusal.** Variance is near-undefined and the dispersion comparison degenerates. |
| optimiser non-convergence | **refusal** |
| SVD rank deficiency at `rcond` | **refusal** |

Reaching a declared bound is not automatically optimiser failure. Refusals return
`INVALID_INPUT` for the affected arm and are reported; nothing is clamped silently,
no fallback estimator is substituted, no arm is quietly dropped.

---

## 9. SCORING AND CALIBRATION — SEPARATED

**A likelihood gain is a distributional-score improvement.** It is **not**
automatically better calibration, and v2's language conflated them.

Calibration is a **separate claim requiring separate evidence**: the probability
integral transform histogram, and empirical coverage at the 5th, 50th and 95th
percentiles, reported for every arm on the development split **whatever the gates
do**. No calibration claim is made without those diagnostics, and a distributional
score gain accompanied by degraded coverage is reported as exactly that.

Neither a score gain nor better calibration is evidence of directional information
or of tradable mispricing.

---

## 10. FIT BUDGET

| | |
|---|---|
| market-data arms | 5 — M0, M1, S, L, C |
| market-data fits | **5**, one pass over the fit split |
| additional leakage fits | **0** — the sensitivity diagnostic reuses these |
| information sets | 1, unchanged |
| horizons | 1, unchanged |
| tuned hyperparameters | **0** |
| refits after seeing any result | **0** |
| **synthetic control fits, separate budget** | **20** — 4 worlds × 5 arms |

---

## 11. WHAT A RESULT MEANS

**All gates pass, both inferences:** `C` is **selected as a candidate for later
confirmation** on evidence not yet used. Not validated alpha, not economic value,
no opening of the sealed period, no options licence.

**Any gate fails:** **this particular quadratic specification, on this information
set, at this horizon, did not demonstrate improvement.** It settles neither
nonlinear models in general nor the value of richer state.

**Inference disagreement:** `NOT_SELECTED — INFERENCE_DISAGREEMENT`. An unresolved
inference, not a finding either way.

---

## 12. FORBIDDEN

Lowering EXP-001B's threshold, searching its results for subsets, or rerunning it
tuned. Opening the sealed periods. Presenting 2020–2021 as untouched. Retuning
control effect sizes to produce a pass. Any subgroup, regime, session or hour
analysis. Computing any economic quantity.

---

## 13. OPEN FOR REVIEW

1. Is `R² = 0.0010` with `φ = 0.3` the right control calibration, given it is fixed
   now and may not be retuned?
2. Is expected block length 5 sessions right, and is reporting 1 and 10 as
   sensitivity sufficient?
3. Should `G2` and `G3`, being compound rather than matched, be **required** gates
   at all, or demoted to reported comparisons with `G1` alone promoting?

Question 3 is the one I would most like an answer to. Requiring compound gates makes
promotion harder, which is safe, but it also means a genuine matched improvement
could be blocked by a dispersion difference that has nothing to do with the
hypothesis.
