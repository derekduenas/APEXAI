# EXP-002 — BOUNDED CHALLENGER TOURNAMENT, EXECUTABLE SPECIFICATION (v5, qualification revision 2)

> **Revision 2 was designed after observing the failed revision-1 battery.** Revision 1
> (`results/exp002_synthetic_qualification.json`) remains **NOT QUALIFIED**; its failure is
> not retroactively removed and its 25 fits stay in the cumulative record. Changes: a strong
> linear world is the blocking linear check and the weak one is kept unchanged as a
> diagnostic; the baseline-replacement verdict is removed and selection rests on the matched
> `C − L` comparison alone; the bootstrap p-value estimator is declared as `(k+1)/(B+1)`.

**Implemented for synthetic qualification only.** Historical fitting and admission
remain closed. EXP-001B is unchanged and preserved as a completed NO_SIGNAL result.
The registered constants live in `apex/world_model/exp002/registration.py`, whose
hash is the registration hash; this document describes them and must not drift.

This tests a **forecasting component**. Option-price comparison and payoff
economics are separate later stages. The options-only objective is untouched.

---

## 1. WHAT EXP-001B TESTED

Information set `ret_1, ret_5, rv_30` from `[t-30min, t]`; target
`log(close[t+15min]/close[t])`; M0 zero-mean Gaussian with `sd = rv_30·k`; M1
linear-mean Gaussian, same sd; DM-HAC lag 14, threshold 2.0. Result `t = 0.7525`,
NO_SIGNAL, n = 165,958. It tested only a linear conditional mean against zero, with
variance model and family fixed.

---

## 2. ARMS — AS IMPLEMENTED

| arm | mean | family | dispersion | code |
|---|---|---|---|---|
| M0 | zero | Gaussian | registered `k` | `exp001b.models`, imported unchanged |
| M1 | linear | Gaussian | registered `k` | `exp001b.models`, imported unchanged |
| S | zero | Student-t | shared `(s*, ν*)` | `exp002.models` |
| L | linear (SVD, centred/scaled basis) | Student-t | shared `(s*, ν*)` | `exp002.models` |
| C | quadratic (SVD, centred/scaled basis) | Student-t | shared `(s*, ν*)` | `exp002.models` |

**Shared reference, one estimation.** `e = y − μ_L(x)` on the fit split, `z = e/rv_30`,
`(s*, ν*) = argmax Σ log t_ν(z; scale s)`. S, L and C use `scale = rv_30·s*` with the
same `ν*`. Within the t-family only the mean varies.

**Variance is not matched across families.** `k` and `s*` are different estimators
on different quantities. `C−L` and `L−S` isolate the mean; `C−M1`, `C−M0`, `S−M0` are
**compound** and are never described as isolating anything.

**Standard deviation versus scale.** `implied sd = scale · sqrt(ν/(ν−2))`. The
`total_uncertainty` field carries the implied sd; the scale and ν travel in the
sealed `calibration_metadata`.

---

## 3. ESTIMATION — COMPLETE

| item | rule |
|---|---|
| least squares | `numpy.linalg.lstsq` (SVD), `rcond = 1e-12`; rank `< p` → **REFUSED** `RANK_DEFICIENT` |
| basis conditioning | non-intercept columns centred and scaled by **fit-split** mean and sd; affine, span unchanged, no hyperparameter |
| zero-variance column | **REFUSED** `ZERO_VARIANCE_FEATURE` |
| registered baselines | fitted by the registered `_ols2`, **without** centring; their own refusal surfaces as `REGISTERED_BASELINE_REFUSED` |
| `(s*, ν*)` | two-parameter ML, **Nelder-Mead** on `(log s, log ν)`, coefficients α=1, γ=2, ρ=0.5, σ=0.5 |
| initialisation | `ν₀ = 6`, `s₀ = std(z)·sqrt((ν₀−2)/ν₀)`, simplex steps 0.1 |
| stopping | `max|fᵢ − f_best| < 1e-8` and simplex diameter `< 1e-8`; else 500 iterations → **REFUSED** `OPTIMIZER_NO_CONVERGENCE` |
| ν bounds | `[2.1, 50]`, enforced as infinite walls |
| ν at **upper** bound | **legitimate** near-Gaussian outcome; `nu_at_upper_bound = true`; run proceeds |
| ν at **lower** bound | **REFUSED** — a declared model-domain policy. Variance is finite at 2.1; the dispersion comparison is degenerate that close to 2. |
| zero volatility | rows with `rv_30 < 1e-9` refused **at admission for every arm**, so pairing is preserved; count reported |
| numerical failure | `INVALID_INPUT` for the tournament; nothing clamped, substituted or dropped |

**Train-only, enumerated:** `k`, `s*`, `ν*`, all coefficients, and the centring and
scaling constants come from the fit split alone.

---

## 4. SCORING

Gaussian arms are scored by the **untouched** `apex.world_model.grader`. Student-t
arms are scored by `exp002.scoring` in the same `Grade` shape, using
`exp002.studentt`, a self-contained density, CDF (regularised incomplete beta by
continued fraction, with the complement formed exactly so the CDF is not flat around
the median) and quantile. Tests anchor it to the closed-form Cauchy and ν=2 CDFs,
to the normal in the large-ν limit **via the known first-order expansion**
`(x⁴−2x²−1)/(4ν)`, and to the grader in the Gaussian limit.

**A log-likelihood gain is a distributional-score improvement.** Calibration is a
separate claim: PIT mean, sd and 10-bin histogram, and empirical coverage at 0.05,
0.50, 0.95, are reported for every arm regardless of any verdict.

---

## 5. INFERENCE — BOTH REQUIRED

**Primary:** Diebold-Mariano, Bartlett HAC, lag 14 (overlap-motivated, not proof of
bounded dependence), one-sided `t > 2.0`.

**Secondary:** stationary bootstrap over **whole sessions**, geometric block length
with **expected length 5 sessions** (a declared research choice, not optimality);
sessions resampled whole and their row-level differentials concatenated, so each
contributes in proportion to its rows; **centred**, one-sided `p < 0.0228`;
10,000 resamples; seed 20260909. **p-value estimator, declared before the revision-2 run: `(k+1)/(B+1)`**, with `k` the centred exceedances and `B` the replicates; zero observed exceedances is reported as `k = 0`, `p = 1/(B+1)`, never as zero probability. Sensitivity at expected lengths **1 and 10**,
reported; a gate passing only at one length is flagged, and selection never
switches to whichever passes.

**Disagreement** between HAC and the 5-session bootstrap on the primary gate is
**`NOT_SELECTED_INFERENCE_DISAGREEMENT`** — an unresolved inference, not a broken
experiment and not evidence of no information.

---

## 6. GATE, VERDICTS, MULTIPLICITY — REVISION 2

**One gate carries selection authority: `G1 = C − L`**, matched, with shared dispersion
and tail parameters unchanged, required under **both** predeclared inferences.

| verdict | condition | meaning |
|---|---|---|
| `MATCHED_IMPROVEMENT` | G1 passes both inferences | a candidate for later confirmation of incremental predictive information; **not validated alpha** |
| `NOT_SELECTED` | G1 fails under both | this quadratic specification did not demonstrate improvement over the matched linear Student-t |
| `NOT_SELECTED_INFERENCE_DISAGREEMENT` | the two inferences disagree on G1 | unresolved |
| `INVALID_NULL_CONTROL` | a required matched null assertion fails | void |

**Removed:** `BASELINE_REPLACEMENT_CANDIDATE` and `MATCHED_IMPROVEMENT_ONLY`. Revision 1
showed the compound comparisons `C−M1` and `C−M0` pass in every world including the null,
because the registered scale law is a mean-absolute-deviation ratio used as a standard
deviation (about 0.80 of the truth for Gaussian data), so they added little
discrimination. They are now **reported context without selection authority**, alongside
`L−S`, `L−M1`, `S−M0`, `M1−M0`, with Holm correction across the six. No comparator family
is added now; a later baseline-replacement study can specify stronger dispersion
comparators explicitly. The registered models and EXP-001B's result are untouched.

**Multiplicity.** With a single gate there is no conjunction to control. The six reported
comparisons form a separate family under Holm. This does not erase prior search and does
not make 2019 confirmatory.

## 7. NULL CONTROL — A STRESS TRANSFORMATION ON MATCHED PAIRS

**What is permuted:** the outcome sequence `y`, in blocks of 20 consecutive
evaluation rows, block order shuffled with the run seed.
**What is fixed:** every forecast — models are **not** refitted and forecasts are
**not** recomputed differently; the state sequence including `rv_30`.
**What is broken:** the row-level pairing of outcome with state, hence the
conditional-mean **and** conditional-variance structure.
**What survives:** the marginal outcome distribution and the state sequence.

Every arm is therefore mis-scaled in the same way, which is why assertions are made
**only** on matched pairs:

| pair | required under N0 |
|---|---|
| `C − L` | NO_SIGNAL |
| `L − S` | NO_SIGNAL |
| `M1 − M0` | NO_SIGNAL |
| `C−M1`, `C−M0`, `S−M0` | **no assertion** (compound); `S−M0` reported |

---

## 8. SYNTHETIC CONTROL WORLDS — COMPLETE GENERATOR

Rows are generated directly in the shape the tournament consumes.

| element | specification |
|---|---|
| sessions | 750 fit + 250 development, 330 rows each; state reset per session |
| features | `z1, z5` independent AR(1), `φ = 0.3`, innovations scaled to unit marginal variance; `ret_1 = 3e-4·z1`, `ret_5 = 6.7e-4·z5` |
| volatility | `rv_30 = exp(ℓ)`, `ℓ` AR(1) with `φ = 0.9` around `log(3e-4)`, marginal sd 0.3 |
| noise | `ε_t = (1/√15)·Σ_{j=0..14} u_{t+j}` — an MA(14) of iid shocks with unit variance, mimicking the 15-minute overlap |
| outcome | `y = rv_30 · (β·g + ε)` |
| signal-to-noise | `R² = β²/(β²+1)`, so `β = sqrt(R²/(1−R²))` with `Var(g) = 1` |
| orthogonality | `g = z1·z5` is uncorrelated with `z1` and `z5` by construction |

| world | `g` | R² | seed | noise | role |
|---|---|---|---|---|---|
| W1_LINEAR | `z1` | 0.0010 | 1001 | Gaussian | weak linear **sensitivity diagnostic**, unchanged from revision 1 |
| **W1S_LINEAR** | `z1` | **0.0100** | **1006** | Gaussian | **BLOCKING** basic linear-detection check, added in revision 2, frozen before execution |
| W2_INTERACTION | `z1·z5` | 0.0010 | 1002 | Gaussian | weak interaction **sensitivity diagnostic** |
| W2S_INTERACTION | `z1·z5` | 0.0100 | 1005 | Gaussian | **BLOCKING**: the intended nonlinear mechanism must be detected |
| W3_HEAVY_TAIL | none | 0 | 1003 | Student-t ν=4, unit variance | shape improves with no conditional-mean discovery |
| W4_NULL | none | 0 | 1004 | Gaussian | nothing anywhere |

**Declared expectations (HAC verdicts; blocking SIGNAL must also pass the bootstrap):**

| world | `C−L` | `M1−M0` | `L−S` |
|---|---|---|---|
| W1 (weak) | NO_SIGNAL | *diagnostic* | *diagnostic* |
| **W1S (strong)** | **NO_SIGNAL, blocking** | **SIGNAL, blocking** | SIGNAL |
| W2 (weak) | *diagnostic* | NO_SIGNAL | — |
| W2S (strong) | **SIGNAL, blocking** | NO_SIGNAL | — |
| W3 | **NO_SIGNAL, blocking** | NO_SIGNAL | NO_SIGNAL |
| W4 | **NO_SIGNAL, blocking** | **NO_SIGNAL, blocking** | **NO_SIGNAL, blocking** |

Blocking failures stop the tournament from proceeding to any historical fit. **One
seeded realisation per world establishes behaviour on that fixture, not general
detection power.** The earlier `E[t] ≈ √(nR²)/2.46` calculation is withdrawn: the
inflation factor was specific to EXP-001B's loss differential and cannot be
transferred to a different process.

---

## 9. SPLITS

| span | role |
|---|---|
| 2016-01-04 → 2018-12-31 | fit |
| 2019-01-01 → 2019-12-31 | **development data with prior exposure** — inside EXP-001B's fitting window; never pristine |
| 2020-01-01 → 2021-12-31 | **OBSERVED** — secondary reporting only, no authority |
| 2022-01-01 → 2024-12-31 | SEALED evaluation |
| 2025-01-01 → 2026-08-28 | SEALED reserve |

**Training-window sensitivity** (renamed from "leakage"): `M0`/`M1` fitted here on
2016–2018 are compared with EXP-001B's recorded 2016–2019 parameters. A diagnostic
with **no gate**, reported only if informative, costing **no extra fits**. It cannot
quantify how knowledge of EXP-001B's result shaped this design; that influence is
**not measured and not claimed small**.

---

## 10. BUDGET

| | |
|---|---|
| market-data fits | 5, one per arm, one pass |
| tuned hyperparameters | 0 |
| refits after seeing results | 0 |
| information sets / horizons | 1 / 1 |
| **synthetic control fits, separate budget** | **30** — 6 worlds × 5 arms (revision 2); revision 1's 25 retained; cumulative 55 |

---

## 11. ATTRIBUTABILITY OF THE SYNTHETIC RUN

The qualification script captures, **by the process itself**, the file path and sha256 of
every `apex.*` module it imported, the git head and dirty count of the tree they came
from, interpreter and numpy versions, working directory and `PYTHONPATH`, the
registration hash, and every world's generator parameters and seed; it re-hashes the same
modules at completion and records whether they were unchanged. Outputs are written with a
sidecar hash. Revision 1's provenance limitation stands as recorded.

## 12. MEMORY

No forecast or grade object is retained. Per-arm log-likelihoods and PIT values
are float arrays; forecasts are recomputed for the null pass, which is exact
because every arm is a deterministic function of the row and `creation_time` is
fixed per run. A test asserts the record contains no forecast or grade objects.

---

## 13. WHAT A RESULT MEANS

A pass **selects a candidate for later confirmation** on evidence not yet used. It
is not validated alpha, not economic value, does not open the sealed period, and
licenses nothing in options. A failure means **this particular quadratic
specification did not demonstrate improvement**, settling neither nonlinear models
in general nor the value of richer state. Better tails are a real distributional
improvement and are not evidence of directional information or tradable mispricing.

---

## 14. FORBIDDEN

Lowering EXP-001B's threshold, searching its results, rerunning it tuned. Opening
the sealed periods. Presenting 2020–2021 as untouched. Retuning control effect sizes
to produce a pass. Any subgroup analysis. Any economic quantity.
