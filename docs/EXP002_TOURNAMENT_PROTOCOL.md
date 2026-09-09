# EXP-002 — BOUNDED CHALLENGER TOURNAMENT, PROTOCOL v2

**Revision for review. Nothing fitted, no admission requested, no historical data
touched.** Supersedes v1 at `13f5c9b`.

This tests a **forecasting component**. Option-price comparison and executable
payoff economics are separate later stages. The options-only business objective is
unchanged and untouched by this document.

---

## 1. WHAT EXP-001B TESTED, AND WHAT IT DID NOT

| | |
|---|---|
| information set | `ret_1`, `ret_5`, `rv_30` from bars in `[t-30min, t]`, 30-minute warmup |
| target | `log(close[t+15min] / close[t])`, elapsed, exact bar required, no imputation |
| M0 | zero mean, `sd = rv_30 · k`, Gaussian |
| M1 | mean `a + b1·ret_1 + b5·ret_5` (OLS on train), same sd, Gaussian |
| statistic | Diebold-Mariano, Bartlett HAC, lag 14, threshold `t > 2.0` |
| result | `t = 0.7525`, **NO_SIGNAL**, n = 165,958 |

It tested **only** whether a linear conditional mean beats a zero mean, with the
variance model and distribution family held fixed. It is preserved as a completed
NO_SIGNAL result and is not revisited.

---

## 2. THE ARMS — FIVE, WITH SCALE AND TAIL SHARED WHERE IT MATTERS

v1 had four arms and could not isolate nonlinearity: quadratic-t against
linear-Gaussian differs in **two** ways at once. A matched linear-t arm is added.

| arm | mean | family | scale / tail parameters |
|---|---|---|---|
| **M0** | zero | Gaussian | `k` on fit split |
| **M1** | linear | Gaussian | `k` on fit split |
| **S** | **zero** | Student-t | **shared** `(k*, ν*)` |
| **L** | **linear** | Student-t | **shared** `(k*, ν*)` |
| **C** | **quadratic** | Student-t | **shared** `(k*, ν*)` |

`C`'s mean is `a + b1·ret_1 + b5·ret_5 + b11·ret_1² + b55·ret_5² + b15·ret_1·ret_5`.

### Shared parameters, and why

In v1, `S` and `C` each estimated their own `ν` from their own residuals, so `C − S`
mixed a mean change with a shape change. **`(k*, ν*)` are now estimated once**, on
the fitting split, from the **linear-mean** residuals, and the identical values are
used by `S`, `L` and `C`. The only thing that varies across those three arms is the
mean specification.

### Scale versus standard deviation

`rv_30 · k` defines the **standard deviation**, as it does for the Gaussian arms.
The Student-t **scale** is derived as `sd · sqrt((ν − 2) / ν)`, so the second moment
is matched across every arm. Without this the comparison would confound shape with
variance.

### The primary question

**`C − L`: does a quadratic mean improve forecasts when scale, tail and information
set are held fixed?** That is the experiment. Everything else is context.

---

## 3. PROMOTION RULE — NAMED PAIRWISE COMPARISONS

`max(M0, M1)` is withdrawn: it was ambiguous between a per-row winner and a best
average comparator. Every comparison is now an explicitly named pair.

**Gates. All three must pass on the development split.**

| gate | comparison | what it establishes |
|---|---|---|
| G1 **primary** | `C − L` | the quadratic mean adds information, holding scale and tail fixed |
| G2 | `C − M1` | it also beats the registered linear Gaussian challenger |
| G3 | `C − M0` | it also beats the registered baseline |

Each at `DM-HAC t > 2.0`, one-sided, in favour of `C`.

**Reported, with no promotion authority:** `L − M1`, `S − M0`, `L − S`, `M1 − M0`.
**`S − M0` is expected to be large and is not a finding.**

### Multiplicity

The three gates form a **conjunction**, evaluated as an intersection-union test.
Requiring all three to pass at level α controls the type-I rate at **no more than
α**; a conjunction cannot inflate it, so no correction is applied and none is
needed. This is stated because applying one here would be wrong, not merely
unnecessary.

The four reported comparisons form a separate family and carry **Holm-Bonferroni**
correction across the four. They are exploratory, they cannot promote anything, and
their corrected and uncorrected values are both reported.

**No subgroup, regime, session or hour analysis is permitted.** Any such comparison
would be an unregistered additional test and is outside the budget.

---

## 4. DEPENDENCE — TWO INFERENCES, DECIDED IN ADVANCE

HAC at lag 14 is an **overlap-motivated choice**, not a demonstration that all
dependence is handled. Overlapping 15-minute targets guarantee dependence out to 14
lags; they do not bound it there.

- **Primary:** Diebold-Mariano, Bartlett HAC, lag 14.
- **Robustness, specified before any result:** a **session-block** inference. Blocks
  are whole trading sessions, since the overlap is within-session and sessions are
  separated by an overnight gap. Stationary block bootstrap over session blocks,
  10,000 resamples, seed `20260909`.

**Disagreement rule, fixed now:** if the two inferences disagree on any gate, the
gate **fails**. The disagreement is reported with both statistics. Selection never
takes the more favourable of the two.

---

## 5. NULL CONTROL — PER-DIFFERENTIAL, NOT BLANKET

"NO_SIGNAL for every arm" was not a defined test and was wrong. **N0 block
permutation (20-row blocks) destroys the association between state and outcome. It
preserves the marginal distribution of outcomes and the state sequence.**

A Student-t arm therefore beats a Gaussian **legitimately** under N0, because the
outcome's fat tails survive permutation. Requiring NO_SIGNAL there would have
condemned correct behaviour.

| differential | channel destroyed | required under N0 |
|---|---|---|
| `C − L` | conditional mean | **NO_SIGNAL** |
| `C − M1` | conditional mean and shape | **NO_SIGNAL** on the mean channel; a residual shape gain is permitted and reported |
| `M1 − M0` | conditional mean | **NO_SIGNAL** |
| `S − M0` | none — pure shape | **gain PERMITTED**; NO_SIGNAL is not required and not expected |
| `L − S` | conditional mean | **NO_SIGNAL** |

Failure of a required NO_SIGNAL invalidates the tournament.

---

## 6. POSITIVE CONTROLS — FOUR WORLDS, PRE-REGISTERED

A planted linear signal does not establish sensitivity to the **nonlinear**
improvement being tested. Four synthetic worlds, run **before** any market-data fit.
Seeds, effect sizes and expected outcomes are fixed here.

| world | construction | seed | effect | `C − L` expected | other expectations |
|---|---|---|---|---|---|
| **W1 linear** | `y = 0.05·ret_1 + ε`, Gaussian ε | 1001 | small | **NO_SIGNAL** | `M1 − M0` SIGNAL |
| **W2 nonlinear** | `y = 0.08·ret_1·ret_5 + ε`, Gaussian ε | 1002 | small | **SIGNAL** | `M1 − M0` NO_SIGNAL |
| **W3 heavy tail only** | `y = ε`, Student-t ε with ν = 4, no conditioning | 1003 | none | **NO_SIGNAL** | `S − M0` SIGNAL |
| **W4 null world** | `y = ε`, Gaussian ε, no conditioning | 1004 | none | **NO_SIGNAL** | nothing significant anywhere |

**W2 is the control that matters.** It is built so the linear mean cannot capture
it. If `C − L` does not detect W2, the tournament has no demonstrated sensitivity to
its own hypothesis and **stops there**, reporting that.

W3 is the mirror: shape improves with no conditional-mean discovery, and `C − L`
must stay silent.

Effect sizes are chosen so W1 and W2 land in a detectable range at n comparable to
the development split. If an effect proves too small or too large to discriminate,
that is reported as an inconclusive control, and the sizes are **not** retuned to
produce a pass.

---

## 7. SPLITS

| span | role |
|---|---|
| 2016-01-04 → 2018-12-31 | **fit** |
| 2019-01-01 → 2019-12-31 | **development selection**, previously used in training |
| 2020-01-01 → 2021-12-31 | **OBSERVED** — secondary reporting only, no authority |
| 2022-01-01 → 2024-12-31 | **SEALED** evaluation |
| 2025-01-01 → 2026-08-28 | **SEALED** reserve |

**2019 is labelled *previously used in training*, not pristine holdout evidence.**
It sat inside EXP-001B's fitting window, so its outcomes contributed to `k`, `a`,
`b1`, `b5` of a model whose validation outcome is now known.

**v1 called that influence "weak". That was unsupported and is withdrawn.** The
magnitude is **unmeasured**. It will be measured as part of the run: refit `M0` and
`M1` on 2016–2018 alone and report the parameter displacement and the development
log-likelihood difference against the 2016–2019 fit. Until that number exists the
influence is **undescribed**, not small.

**2020–2021 has been observed and can never again be presented as untouched
evidence.**

---

## 8. ESTIMATION — BOUNDS, RULES, AND FAILURE

**Train-only, enumerated.** `k*`, `ν*`, and every regression coefficient come from
the fitting split alone. No standardisation, winsorisation, clipping or scaling uses
any statistic from outside it. Features are per-row and backward-looking by
construction. The quadratic basis uses **raw** features; no scaling is introduced,
and the conditioning check below guards the consequence.

**`k*`**: `mean(|y|) / mean(rv_30)` on the fit split, as registered. Bound `k* > 0`.

**`ν*`**: one-dimensional maximum likelihood on fit-split residuals of the **linear**
mean, over `log ν`, by bounded Brent. Bounds `ν ∈ [2.1, 50]`, tolerance `1e-8`, at
most 200 iterations. The lower bound keeps the variance finite so the
moment-matching in §2 is defined.

**OLS**: closed form via normal equations. If the design matrix condition number
exceeds `1e10`, the arm is **REFUSED**. No ridge or other regularisation is added,
because a penalty strength would be a tuned hyperparameter and the budget is zero.

**Numerical failure behaviour.** If the optimiser fails to converge, or `ν*` lands
on either bound, or a condition-number check trips, the affected arm returns
`INVALID_INPUT` and the tournament reports it. **Nothing is clamped silently, no
fallback estimator is substituted, and no arm is quietly dropped.**

---

## 9. FIT BUDGET, DECLARED IN ADVANCE

| | |
|---|---|
| market-data arms | **5** — M0, M1, S, L, C |
| market-data fits | **5**, one per arm, one pass over the fit split |
| information sets | 1, unchanged from EXP-001B |
| horizons | 1, unchanged |
| tuned hyperparameters | **0** |
| refits after seeing any result | **0** |
| leakage-measurement refits | **2** — M0 and M1 on 2016–2018, per §7, declared |
| **synthetic control fits, counted separately** | **20** — 4 worlds × 5 arms |

Control runs are on synthetic data and are **not** market-data fits. They are
counted here so the two budgets can never be conflated.

---

## 10. WHAT A RESULT WOULD MEAN — NARROWED

**If all three gates pass:** this **selects `C` as a candidate for later
confirmation** on evidence not yet used. It does **not** establish validated alpha,
does not establish economic value, does not open the sealed period, and does not
license anything in options. Development selection on a split previously used in
training is candidate generation, nothing more.

**If any gate fails:** **this particular quadratic specification, on this
information set, at this horizon, did not demonstrate improvement.** It does not
settle nonlinear models in general and says nothing about the value of richer state,
which is a separate question for a separate experiment.

**Better tail calibration is a legitimate distributional improvement.** It is not
evidence of directional information and not evidence of tradable mispricing. Any
gain attributable to `S` is reported as calibration, never as alpha.

---

## 11. FORBIDDEN

- Lowering EXP-001B's threshold, searching its results for winning subsets, or
  rerunning it with tuned parameters.
- Opening the sealed evaluation or reserve periods.
- Presenting 2020–2021 as untouched evidence.
- Retuning control effect sizes to produce a pass.
- Any subgroup, regime, session or hour analysis.
- Computing any economic quantity. This stage is distributional only.

---

## 12. OPEN FOR REVIEW

1. Is the shared `(k*, ν*)` estimated from **linear-mean** residuals the right
   reference, or should it come from the zero-mean residuals?
2. Are the W1 and W2 effect sizes the right magnitudes, given they are fixed now and
   may not be retuned?
3. Is the session-block bootstrap the robustness check you want, and is
   "disagreement fails the gate" the right severity?
4. Should the leakage measurement in §7 gate the tournament, or only be reported
   alongside it?

On approval this becomes a registered experiment with its own hash, and only then
does it need an admission and a fitting run.
