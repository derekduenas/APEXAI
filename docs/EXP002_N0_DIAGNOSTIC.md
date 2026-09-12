# EXP-002 N0 diagnostic — derivation and frozen prediction

The verdict of run `20260909T193814Z-exp002-ca450243` stands: `INVALID_NULL_CONTROL`,
no model selected. Nothing here reopens it. No refitting, no rescoring, no
alternate permutation, no subgroup search, no threshold change.

## 1. What N0 actually does

From the registration: the outcome sequence `y` is permuted in blocks of 20
consecutive evaluation rows, block order shuffled; **forecasts are not
recomputed**, the state sequence including `rv_30` is fixed; what is destroyed
is "the row-level pairing of outcome with state"; what survives is "the marginal
outcome distribution; the state sequence". Asserted `NO_SIGNAL`: C−L, L−S, M1−M0.

In code (`run.py`), the null pass calls `_block_permute(ys, seed, N0["block"])`,
then rescores the SAME rows against the permuted outcomes, and applies the same
one-sided rule: SIGNAL requires `mean > 0` **and** `t > 2.0`.

## 2. The L−S score differential

L and S share scale `σ_i = rv_30,i · s*` and shape `ν`; they differ only in the
mean (`m_i` vs `0`). With `logpdf(y,μ,σ,ν) = c − log σ − ((ν+1)/2)·log1p(z²/ν)`,
`z=(y−μ)/σ`, the `−log σ` terms cancel exactly:

```
d_i = −((ν+1)/2)·[ log(1 + (z_i − a_i)²/ν) − log(1 + z_i²/ν) ],
      z_i = y_i/σ_i,  a_i = m_i/σ_i
```

Expanding in the (small) standardised mean `a`:

```
d ≈ a·ψ(z) − (a²/2)·ψ′(z),    ψ(z) = (ν+1)z/(ν+z²),   ψ′(z) = (ν+1)(ν−z²)/(ν+z²)²
E[d] ≈ E[a·ψ(z)] − ½·E[a²·ψ′(z)]
```

**The assumptions that would justify the asserted `NO_SIGNAL`:**

1. `E[a·ψ(z)] = 0` — requires the permuted outcome to be independent of the
   row's mean *and* the standardised outcome to be symmetric. L keeps its fitted
   **intercept**, so `E[a] ≠ 0`; any asymmetry in `ψ(z)` then leaves a residual term.
2. `E[a²·ψ′(z)] ≥ 0` — requires `ψ′(z) ≥ 0` on average, i.e. `z² < ν` typically.
   `ψ′(z) < 0` for `|z| > √ν` (here √ν = 2.527). In that region the log-density
   is locally **convex** in μ, so *any* nonzero mean scores better than zero.
3. That the permutation leaves the standardised outcome properly scaled.

Assumption 3 is the one N0 itself breaks. Permutation moves `y` from its own
volatility regime onto a different row's `σ_i`, so `z_i = y_i/σ_i` is no longer
standardised: high-volatility outcomes land on low-volatility rows and produce
`|z| ≫ √ν`. Every such row contributes `ψ′ < 0`, i.e. a **positive** expected
`L−S` with **zero conditional information**. This is marginal-location fit under
scale mismatch, not signal.

Separating the four channels the reviewer named:
- **conditional information** — destroyed by the permutation, as intended;
- **marginal-location fit** — *survives*: the fitted intercept and spread of `m_i` still fit the marginal outcome distribution better or worse than zero;
- **volatility mismatch** — *created* by the permutation; the mechanism above;
- **dependence** — blocks of 20 keep within-block adjacency, and `m_i` is serially correlated, so the HAC standard error, not the point estimate, is what absorbs this.

## 3. Why L−S and M1−M0 need not behave alike

M0/M1 are **Gaussian** with shared `σ_i = k·rv_30,i`. There:

```
d = −[(y−μ)² − y²]/(2σ²) = a·z − a²/2,   so  ψ(z) = z,  ψ′(z) ≡ 1
E[d] = E[a·z] − ½E[a²]  ≤ 0  whenever E[a·z] = 0
```

`ψ′` is a **constant 1** for the Gaussian: there is no tail region where the sign
flips, so a nonzero mean is always penalised against an independent outcome. The
Student-t's `ψ′` changes sign at `|z| = √ν`. So the two pairs have different
score sensitivities *by family*, and a differing null statistic between them is
expected, **not by itself evidence of a bug**. Observed: L−S `t = +2.823`
(failed), M1−M0 `t = +0.893` (passed), C−L `t = −4.118` (passed) — C−L compares
two arms that *both* carry fitted means of similar magnitude, so the second-order
term largely cancels.

## 4. Frozen synthetic test (construction and prediction registered before execution)

Purpose: test the null's **logical claim**, not to find a control that passes.
`scripts/exp002_n0_diagnostic.py`, purely synthetic, no market data, no fitting.
Fixed from the sealed record: `ν = 6.384478029123821`, `s* = 3.287952250006828`,
`k = 2.932453397662227`, block 20, seed 20260909, n = 100,000. Rows carry
`rv_30` lognormally spread with parameter `τ ∈ {0.0, 0.3, 0.6, 0.9}`; outcomes
are drawn `t_ν` **correctly coupled** to their own row's scale; the mean `m_i`
is a fixed intercept plus a fixed slope on a synthetic predictor. The real
`_block_permute` is then applied and the real HAC statistic computed.

**Predictions, registered now:**

- **A.** With volatility heterogeneity (`τ ≥ 0.6`), permuted `L−S` gives `mean > 0` and `t > 2` — the asserted `NO_SIGNAL` is false by construction, with zero conditional information present.
- **B.** With `τ = 0` (homoskedastic), permuted `L−S` gives `mean ≤ 0`.
- **C.** The Gaussian analogue gives `mean < 0` at every `τ`.
- **D.** The effect grows with the permuted-sample fraction of `|z| > √ν`, and `E[ψ′(z)]` turns negative as that fraction grows.

If A fails, the hypothesis is wrong and will be reported as wrong.

---

## 5. Result — prediction A is REFUTED by this test

Run in the contained slice, 6 s. Vectorised log-density agrees with the shipped
scalar `studentt.logpdf` to `0.0` max absolute difference over the sampled rows.
Means below in units of 1e-6.

| τ | L−S intact | L−S **permuted** | Gaussian intact | Gaussian **permuted** | frac \|z\|>√ν | E[ψ′] |
|---|---|---|---|---|---|---|
| 0.0 | −1241.6 (t=−8.21) | −1101.4 (**t=−7.25**) | −1942.9 (t=−7.51) | −1776.7 (t=−6.85) | 0.043 | 0.787 |
| 0.3 | −1592.9 (t=−9.26) | −1039.0 (**t=−5.61**) | −2570.1 (t=−8.76) | −1876.9 (t=−4.43) | 0.074 | 0.770 |
| 0.6 | −2777.2 (t=−10.67) | −1631.6 (**t=−5.54**) | −4566.8 (t=−10.21) | −3978.9 (t=−2.35) | 0.135 | 0.739 |
| 0.9 | −12361.7 (t=−23.59) | −4075.2 (**t=−7.51**) | −21134.1 (t=−21.68) | −7982.5 (t=−0.49) | 0.190 | 0.710 |

**Scored against the frozen predictions:**

- **A — FAILED.** Permuted `L−S` was negative at every τ, including 0.9. The asserted `NO_SIGNAL` held in all four worlds with a wide margin. My proposed mechanism does not produce a positive `L−S` at these heterogeneity levels.
- **B — held.** τ=0 permuted `L−S` mean < 0.
- **C — held.** The Gaussian analogue was negative at every τ.
- **D — FAILED.** The tail fraction did rise as predicted (0.043 → 0.190), but `E[ψ′(z)]` stayed **positive** throughout (0.787 → 0.710). The bulk of the distribution continues to dominate the average; the sign never flips.

**What is therefore demonstrated:**

1. The score-differential derivation in §2 and the family contrast in §3 are correct and confirmed numerically: with `ψ′ ≡ 1` the Gaussian pair cannot go positive under an independent outcome, while the Student-t's `ψ′` is only *locally* negative. A differing null statistic between L−S and M1−M0 is a family property and is **not** evidence of a bug.
2. Scale heterogeneity **erodes** the negative margin — visibly so for the Gaussian pair, whose permuted `t` moves −6.85 → −0.49 as τ grows — but in a **well-specified** world it does not flip the Student-t pair's sign. So volatility mismatch alone is *not* a sufficient explanation of the observed `+2.823`.
3. In a correctly specified world the expected permuted `L−S` is *strongly* negative (t ≈ −5 to −7.5). The observed real-data value is a large departure from that expectation, which makes a pure chance rejection less comfortable as an explanation than the raw p-value alone suggests.

**Remaining candidate explanations, all UNMEASURED hypotheses:**

- **marginal misspecification** — real outcomes may have heavier tails, given `σ_i`, than the fitted `t_ν` law, putting far more mass past `√ν` than any world tested here (my worlds drew outcomes from exactly the fitted law, the best case for the null);
- **the first-order term** `E[a·ψ(z)]` — L keeps its fitted intercept, and real standardised outcomes are skewed; this channel was not isolated here;
- **inference** — the HAC standard error may be understated under a block permutation that preserves within-block dependence and creates block-boundary discontinuities;
- **chance** — one-sided `t = 2.823` alone is not extraordinary.

Distinguishing these requires either rescoring the sealed run or a further synthetic
design with deliberately misspecified tails. Neither was performed; both are
outside this brick.

## 6. Proposed disposition (for review; nothing acted on)

The verdict stands and no model is selected. The diagnostic did **not** identify
the cause. My recommendation is to treat N0's `L−S` assertion as *not yet shown
to be justified* rather than as either sound or broken, and to decide between:

- **(a)** a further bounded synthetic study with misspecified tails and an isolated intercept term, frozen in advance, to separate the two leading hypotheses; or
- **(b)** a permitted re-analysis of the *existing* sealed forecasts — no refit, no new fit budget — to measure the real permuted `z` distribution and the two terms directly; this reads the development period only and would need explicit authorisation because it re-touches admitted data; or
- **(c)** leaving the question open and revisiting the null's construction at the next registration, on the record that the current assertion rests on assumptions that have not been established.

I do not recommend changing N0, the threshold, or the model on the strength of
what is known now.

---

## SUPERSEDED IN PART — see `EXP002_N0_CLOSURE.md`

The frozen predictions above and their outcomes (A and D failed, B and C held)
stand as recorded. Four claims in this document are corrected there:

1. §3's "the Gaussian pair cannot go positive under an independent outcome" is
   **false**; a fixed-mean counterexample gives `E[d] = m²/(2σ²) > 0` with no
   conditional information. The L−S / M1−M0 contrast is not a structural family
   guarantee.
2. The curvature framing is local and not decisive; the exact per-row condition
   is `a(2z − a) > 0`, identical for both families. `E[ψ′(z)]` was substituted
   for `E[a²ψ′(z)]`, valid only under `a ⟂ z` — true in the fixture, false in
   the experiment, where both share `σ`.
3. The claim that the simulated statistics make chance "less comfortable" is
   **withdrawn**: realised statistics from one seeded generator are not a
   reference distribution for the historical statistic.
4. "Heterogeneity erodes the negative margin" conflated the expected disadvantage
   (whose mean grew *more* negative) with statistical precision (whose HAC
   standard error grew faster). Only the latter is shown.

The refutation is narrowed to: the proposed scale-heterogeneity mechanism did not
produce a positive Student-t differential in the four tested configurations, in
which outcomes were drawn from exactly the assumed law.
