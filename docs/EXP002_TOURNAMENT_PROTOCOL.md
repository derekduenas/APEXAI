# EXP-002 — BOUNDED CHALLENGER TOURNAMENT, PROTOCOL FOR REVIEW

**Nothing has been fitted. No admission is requested by this document.** It is one
protocol, offered for review before any challenger is fitted.

This tournament tests a **forecasting component**. Option-price comparison and
executable payoff economics are separate later stages and are not touched here.

---

## 1. WHAT EXP-001B ACTUALLY TESTED

Stated exactly, because the next step only makes sense against it.

| | |
|---|---|
| information set | `ret_1`, `ret_5`, `rv_30`, built from bars in `[t-30min, t]`; 30-minute warmup |
| target | `log(close[t+15min] / close[t])`, elapsed time, exact bar required, no imputation |
| comparator M0 | zero mean; `sigma = rv_30 · k`, `k` fit on train; **Gaussian** |
| challenger M1 | mean `a + b1·ret_1 + b5·ret_5` by OLS on train; **same sigma**; Gaussian |
| metric | out-of-sample log-likelihood differential, M1 − M0 |
| statistic | Diebold-Mariano with HAC, Bartlett, lag 14, threshold `t > 2.0` |
| negative control | N0 block permutation, 20-row blocks |
| search budget | 2 model families, 1 feature set, **0 hyperparameters tuned**, 1 horizon |
| result | `t = 0.7525`, **NO_SIGNAL**, n = 165,958 |

**So EXP-001B tested exactly one thing: whether a linear conditional mean in two
features beats a zero mean, holding the variance model and the distribution family
fixed.** It did not test nonlinearity, distribution shape, conditional variance
beyond `rv_30` scaling, or any richer state.

The correct reading: **this specification did not demonstrate predictive
improvement over its comparator on the validation period.** It does not reject the
World Model idea and it does not test the options engine.

---

## 2. THE TRAP THIS PROTOCOL HAS TO AVOID

The metric is log-likelihood. **A challenger can win on log-likelihood purely by
fitting fatter tails, while carrying no conditional information whatsoever.**
Fifteen-minute equity returns are strongly leptokurtic, so a Student-t will very
likely beat a Gaussian on density alone. That would look like a discovery and be
nothing of the kind.

The design below separates the two with an explicit ablation. This is the single
most important feature of the protocol.

---

## 3. THE ARMS

Information set and forecast target are **held constant** at EXP-001B's, so the only
thing varying is model flexibility.

| arm | mean | scale | family | purpose |
|---|---|---|---|---|
| **M0** | zero | `rv_30 · k` | Gaussian | registered baseline |
| **M1** | linear in `ret_1, ret_5` | `rv_30 · k` | Gaussian | registered linear challenger |
| **S** (shape control) | **zero** | `rv_30 · k` | **Student-t**, ν on train | isolates gain from tail shape alone |
| **C** (challenger) | quadratic basis in `ret_1, ret_5` | `rv_30 · k` | **Student-t**, ν on train | nonlinear conditional mean + flexible shape |

C's mean is `a + b1·ret_1 + b5·ret_5 + b11·ret_1² + b55·ret_5² + b15·ret_1·ret_5`,
by ordinary least squares on the fitting split. Nonlinear in the features, linear in
the parameters, closed form, **no tuned hyperparameters**. ν is estimated once on
fitting-split residuals by one-dimensional maximum likelihood, identically for S and
C, and is a fitted parameter rather than a searched one.

### The decision rule, fixed before any fit

C is promoted only if **both** hold on the primary development split:

1. `DM-HAC(C − S) > 2.0` — the gain survives removal of the shape advantage, so it
   is **conditional information** rather than better tails.
2. `DM-HAC(C − max(M0, M1)) > 2.0` — it beats the **strongest** registered
   comparator, not the weaker one.

All four differentials are reported regardless: C−M0, C−M1, C−S, S−M0. **S−M0 is
expected to be large and is not a finding.**

---

## 4. CHRONOLOGICAL SPLITS, AND AN HONEST PROBLEM

| span | role |
|---|---|
| 2016-01-04 → 2018-12-31 | **fit** |
| 2019-01-01 → 2019-12-31 | **primary development split** |
| 2020-01-01 → 2021-12-31 | **OBSERVED** — secondary only |
| 2022-01-01 → 2024-12-31 | **SEALED** evaluation, untouched |
| 2025-01-01 → 2026-08-28 | **SEALED** reserve, untouched |

**2020–2021 has now been observed.** EXP-001B's validation result on it is known, so
it can never again be presented as untouched evidence in model selection. It is
reported here as a secondary check with that status attached, and it carries no
promotion authority.

**2019 is the cleanest split available, and it is not pristine.** It sat inside
EXP-001B's fitting window, so its outcomes influenced parameters of a model whose
validation outcome we now know. The leakage channel is indirect and weak. It is
declared, not claimed absent.

Everything is chronological. No shuffling, no cross-validation across time.

---

## 5. DISCIPLINE

**Train-only transformations.** `k`, ν, and every regression coefficient are
estimated on the fitting split alone. No standardisation, winsorisation or scaling
uses any statistic computed outside it. Feature construction is per-row and
backward-looking by construction.

**Calibration, reported whatever the verdict.** Probability integral transform
histogram, and empirical coverage at the 5th, 50th and 95th percentiles, for every
arm on the development split. A challenger that wins on likelihood while
miscalibrated is reported as such.

**Dependence handling.** Unchanged: Diebold-Mariano with Bartlett HAC at lag 14,
matching the 15-minute horizon's overlap. Reported alongside the naive standard
error so the inflation factor stays visible.

**Negative control.** N0 block permutation, 20-row blocks, state preserved. Must
return NO_SIGNAL for every arm.

**Positive control — blocking, and run first.** On synthetic data with a planted
AR(1) mean signal, the pipeline must return SIGNAL_DETECTED at the registered
threshold. **If it does not, the tournament stops and reports that instead.** This
exists because EXP-001B established no detection power, as recorded in the reporting
corrections.

**Fixed search budget, declared in advance.**

| | |
|---|---|
| model families | 2 new (S, C) plus 2 registered (M0, M1) |
| feature sets | 1, unchanged from EXP-001B |
| hyperparameters tuned | **0** |
| horizons | 1, unchanged |
| total fits | 4, one per arm, one pass |
| refits permitted after seeing any result | **0** |

---

## 6. WHAT IS FORBIDDEN

- Lowering or renegotiating EXP-001B's threshold.
- Searching EXP-001B's results for winning subsets, sessions, regimes or hours.
- Rerunning EXP-001B with tuned parameters.
- Opening the sealed evaluation or reserve periods.
- Presenting 2020–2021 as untouched evidence.
- Computing any economic quantity. This stage is distributional only.

EXP-001B is preserved as a **completed NO_SIGNAL result** and is not revisited.

---

## 7. WHAT A RESULT WOULD AND WOULD NOT MEAN

If C passes both gates: **a nonlinear conditional mean carries information the linear
one missed, on this information set at this horizon.** It would not establish
economic value, would not open the sealed period, and would not license options
deployment.

If C fails: model flexibility on this information set does not help, which points the
next step at **richer state** rather than richer models. That is the intended
sequence — test whether a better model extracts information the first one missed,
then separately test whether richer state adds more.

The most likely outcome remains no signal, and that stays a real result.

---

## 8. WHAT I NEED FROM REVIEW

1. Do you accept 2019 as the primary development split, with its declared imperfection?
2. Do you accept the shape-control ablation as the guard against a tail-fitting win?
3. Do you accept the two-gate promotion rule?
4. Should the positive control be broadened beyond a planted AR(1) mean?

On approval this becomes a registered experiment with its own hash, and only then
does it need an admission and a fitting run.
