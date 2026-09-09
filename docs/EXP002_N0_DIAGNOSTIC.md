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
