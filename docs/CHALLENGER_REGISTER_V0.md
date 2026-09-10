# CHALLENGER REGISTER V0

A register of advanced methods as **challengers** to the simplest
comparator, each with its falsification test, negative control,
incremental-value criterion and activation gate. Listing here is not
permission to implement. Each row is activated only by a registered
experiment that names it, after its dependency row is at least "tested".

> **SUPERSESSION NOTE — 2026-09-09 (applies to the common rule below and to every
> per-row "N0" / "must return NO_SIGNAL" entry).** The general assertion that a
> permutation control "must return NO_SIGNAL" is **withdrawn as a universal
> correctness requirement**. `docs/EXP002_N0_CLOSURE.md` established that
> permutation alone does not justify a required NO_SIGNAL for a matched
> location comparison: the expected score differential depends on centering and
> scale assumptions the transformation does not enforce, and repetition does not
> supply an invariance argument. Going forward, any randomisation control given
> invalidation authority must state its null hypothesis, why the transformation
> represents it, and the assumptions required, and must be reviewed on that basis
> before registration. **Historical registrations that used this rule
> (EXP-001B, EXP-002) are not rewritten**; their records stand as executed, and
> EXP-002's `INVALID_NULL_CONTROL` verdict stands. The per-arm descriptive
> register is `docs/CHALLENGER_REGISTER.md`.

Common rules: fit on permitted training information only; dependence-aware
statistics; incremental value is measured against the simpler comparator
on the *same* sealed data with the *same* costs; a negative control (N0
permutation or an equivalent that destroys the mechanism) must return
NO_SIGNAL; promotion is a human decision on repeated, registered evidence.

| # | Method | 1. Information / mechanism captured | 2. Architecture location | 3. Required data and causal limitations | 4. Simpler comparator | 5. Falsification test and negative control | 6. Incremental-value criterion | 7. Compute / maintenance | 8. Build dependency → activation gate |
|---|---|---|---|---|---|---|---|---|---|
| C1 | State-space models, HMMs, particle filters | latent regime / state persistence; time-varying conditional moments | World Model (conditional distribution) | admitted bars; regimes are latent — labels are inferred not observed; look-ahead in smoothing (use filtered, not smoothed, estimates for forecasts) | M1 conditional Gaussian (EXP-001) | OOS log-likelihood DM-HAC vs comparator; N0 block permutation; regime-shuffled control (state sequence permuted) | ΔLL > 2.0 HAC-t on validation AND after-cost economic readout non-negative | low–moderate; refit cadence declared | after EXP-001 adjudicated → registered EXP naming C1 |
| C2 | Hawkes / order-flow models | self-excitation of trades/quotes; short-horizon intensity | World Model (intraday); Execution simulator (fill/queue) | trade prints or L2 — **not on box** (bars only); cannot be fit on OHLCV | rv_30 volatility scaling | intensity forecast vs realized count, Poisson comparator; N0 shuffle of inter-arrival times | ΔLL vs Poisson/ACD; economic only via execution cost reduction | moderate; needs tick capture and storage | data acquisition + admission → gated |
| C3 | Jump diffusion, stochastic volatility | fat tails, vol clustering, event jumps | Multiverse (path generation); World Model tails | admitted bars; event timestamps for jump conditioning; parameters estimated on train only | Gaussian with rv scaling (M0) | tail calibration (PIT, coverage at 5/95), CRPS vs comparator; N0: shuffle outcomes; N1: remove event conditioning | pinball loss at 0.05/0.95 improves with HAC-t > 2; coverage within tolerance | moderate | Multiverse real-data path generator NOT_IMPLEMENTED → after first daily-horizon experiment registered |
| C4 | Graph-based shock propagation | cross-asset / cross-entity transmission of a shock | Twin (edges) + World Model (transmission hypotheses) | sourced relationships with effective time and availability; risk of double-counting one evidence through several paths | single-factor (index beta) transmission | conditional response at neighbor vs beta-only; negative control: edges randomly rewired (degree-preserving) must show no gain | ΔLL or Δ after-cost on the neighbor's forecast, HAC-t > 2 | moderate; relationship data maintenance is the burden | Twin relationship interface NOT_IMPLEMENTED → after event corpus admitted |
| C5 | Tail-risk and dependence models (EVT, copulas) | joint tails, dependence under stress | Multiverse (stress branches); Risk (certification stress) | admitted multi-asset bars; tail estimates are sample-starved; dependence non-stationary | historical covariance + empirical tails | tail coverage on sealed period; stress branches unweighted; N0: independence copula must not outperform | coverage at 1/99 within tolerance and certified-loss exceedance frequency ≤ declared | low–moderate | after Multiverse V0 |
| C6 | Distribution-distance methods (KL, Wasserstein, CRPS decomposition) | size and shape of physical-vs-implied disagreement | Market-implied comparison | option chains with per-row publication time (on box for 6 underlyings); risk-premium adjustment required | expected-return difference after cost | disagreement → realized-outcome association vs sign-only; N0: implied distribution shuffled across dates | after-cost return of expressions selected by distance beats sign-only, HAC-t > 2 | low | option-implied estimator NOT_IMPLEMENTED at needed horizon → first daily-horizon experiment |
| C7 | Information-theoretic incremental-value tests (conditional MI, transfer entropy) | whether a feature adds information beyond the comparator's | Experience / research budget | dependence-adjusted estimation; small-sample bias; multiple testing | nested-model likelihood-ratio with HAC | permutation-based null distribution of the statistic; N0: feature permuted within blocks | CMI significantly > 0 AND nested LL gain agrees | low | usable now on EXP-001 outputs (engineering) → registered use |
| C8 | Robust decision control (distributionally robust selection, ambiguity sets) | acting under model uncertainty rather than point forecasts | PRIME (selection) | requires calibrated uncertainty from World Model; ambiguity radius is a chosen parameter (search burden) | PRIME_RULES_V0 thresholds | after-cost selection outcome vs rules; negative control: random ambiguity radius | after-cost mean and drawdown not worse, with fewer certified-loss exceedances | low | after first economic readout on real data |
| C9 | Robust / fractional Kelly (downstream of validation) | growth-optimal sizing under estimated edge and calibration | Arena (sizing), gated by calibration evidence | prospective calibration on ≥ 20 independent sessions (REPORTING_SUFFICIENCY_PRIOR); edge estimates are noisy — fractional only | fixed-fraction sizing at declared 1R | geometric growth on sealed period vs fixed-fraction; N0: edge estimate shuffled → sizing must not add growth | growth improves without exceeding survival constraints under stress branches | low | prospective calibration evidence → never before |
| C14 | Forecast fusion / model combination (stacking, pooling, mixtures) | whether combining inputs carries information none carries alone | **Downstream of the World Model only** — it consumes forecasts, it never originates them | two or more component inputs on the same sealed data with the same costs. **Components need NOT each prove standalone alpha first**: an input that is worthless alone may still contribute in combination. Combination weights are fitted parameters and inherit the components' overfitting risk | **the strongest baseline available**, not the average of components and not the weakest | DM-HAC of the combination against that strongest baseline; N0 block permutation; component-shuffle control (weights fitted to shuffled components must return NO_SIGNAL); **ablations removing each input in turn** | ΔLL > 2.0 HAC-t against the STRONGEST baseline, with ablations showing what each input contributes; beating an average is not evidence | low compute, high maintenance: a decayed component silently degrades the combination | **two or more component inputs available on the same sealed data**, plus a defensible strongest baseline to beat → registered experiment naming C14. Downstream only; recorded 2026-09-08, criterion corrected 2026-09-08. |

Search burden: the rows are enumerated before any result; each activation is
one registered experiment; results are reported for every activated row,
including failures. No row is installed by this register.

## Addendum A entries (added at `2af98967`; none implemented)

Same rules as C1–C9: listing is not permission; each row activates only
through a registered experiment naming it, after its dependency is at least
"tested"; results are reported for every activated row, failures included.

| # | Method | 1. Information / mechanism captured | 2. Architecture location | 3. Required data and causal limitations | 4. Simpler comparator | 5. Falsification test and negative control | 6. Incremental-value criterion | 7. Compute / maintenance | 8. Build dependency → activation gate |
|---|---|---|---|---|---|---|---|---|
| C10 | Lyapunov-style / dynamical predictability measures | how fast nearby states diverge, i.e. an intrinsic horizon beyond which skill is not available | Predictability map (A3), as a *challenger* to measured skill | needs long, stationary-ish series; estimates are sensitive to embedding choice and noise; a divergence rate is not itself a forecast | the measured out-of-sample skill curve by horizon | does the divergence estimate predict where measured skill dies, out of sample? Negative control: phase-randomised surrogate series must show no relationship | the estimate must anticipate the skill cliff better than the measured curve's own extrapolation | low–moderate | after the predictability map has ≥ 2 registered experiments' worth of cells |
| C11 | Sequential latent-state estimation (particle / Kalman family) for `LATENT_STATE_ESTIMATE_V0` | latent liquidity / regime / positioning state behind the observations | World Model (A1) | observation model must be justified, not assumed; filtered (not smoothed) estimates only for forecasting; positioning proxies are inferences, never facts | the observable feature set used directly (EXP-001B's `ret_1, ret_5, rv_30`) | OOS log-likelihood DM-HAC vs the direct-feature model; N0 block permutation; **state-shuffled control** (state path permuted) must show no gain | ΔLL > 2.0 HAC-t on validation **and** a non-negative after-cost readout | moderate; refit cadence declared | overlaps C1 — C11 is C1 *bound to the A1 interface*; activate at most one, and record which |
| C12 | Correlation-adjusted ensemble weighting | how much independent information an ensemble actually contains | Multiverse / World Model weight ownership (A2) | member overlap must be measured, not assumed; equal weights over correlated members fabricate confidence | single best model by validation score | does the adjusted ensemble beat the single model OOS? Negative control: duplicate one member N times — the adjusted weighting must not change, the naive one will | improvement in OOS score **and** a stable `effective_independent_members` | low | needs ≥ 2 genuinely different models to exist |
| C13 | Decision-value-of-information scoring | whether an observation would change a decision, not merely reduce variance | PULSE acquisition (A4) | requires a decision model and a cost model; both are assumptions and are recorded as such | "acquire if information gain > 0" | retrospective: did acquisitions ranked high by decision value change decisions more often than those ranked high by information gain alone? | measurably better decision-change rate per unit cost | low | after ≥ 10 recorded acquisition outcomes exist to score |

Search burden: thirteen enumerated rows, none installed. C11 and C1 overlap
by construction and are counted once when either activates.
