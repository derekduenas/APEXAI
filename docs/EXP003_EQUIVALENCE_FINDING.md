# EXP-003 orthogonalised increment — equivalence finding

**Conclusion: the proposed predictor is the same predictor as EXP-002's C arm.**
Orthogonalisation is withdrawn as a forecasting capability. EXP-003 is recorded
as a proposed **testing-protocol revision**, not a model advance, and the same
historical comparison must not be re-run merely because its invalidation rule
changed. No historical access was used to establish this.

## 1. The algebra (Frisch–Waugh–Lovell)

Let `X` hold the intercept and linear features and `Q` the quadratic features,
`M_X = I − X(XᵀX)⁻¹Xᵀ`, `Q⊥ = M_X Q`, `A = (XᵀX)⁻¹XᵀQ` the training projection.

Because `Q⊥ ⟂ X` and `span[X, Q] = span[X, Q⊥]`, the projection splits:
`P_[X,Q] = P_X + P_{Q⊥}`. So the in-sample fitted values agree exactly.

Out of sample the two are the same **function**, not merely equal on the
training rows. FWL gives the joint coefficient relation `b_X = β_L − Aγ`, hence
for any new row `x`:

    f_joint(x) = x_X b_X + x_Q γ = x_X(β_L − Aγ) + x_Q γ
               = x_X β_L + (x_Q − x_X A) γ = f_two-step(x)

provided the training projection `A` is carried forward, which the proposal
specified.

**Standardisation.** EXP-002 standardises the joint `[linear, quadratic]` block
by fit-split mean and sd and prepends an intercept. Column-wise affine
transforms with an intercept present leave the column span unchanged, so the
projection — and therefore both the fitted values and the out-of-sample
function — are invariant to which block is standardised how. The registered code
refuses zero-variance columns, so the transform is always invertible.

**Rank.** If `[X, Q]` were rank-deficient the minimum-norm `lstsq` solutions
could differ off the training column space. The registered code **refuses**
rank deficiency (`RANK_DEFICIENT`), so this case never reaches prediction.

**Shared tail estimator.** `fit_arms` fits `(s, ν)` to the **linear**-mean
residuals. `L` is identical in both designs, so `(s, ν)` is identical, so the
scale and shape are identical. Same location function + same scale + same shape
= identical predictive distributions.

## 2. Numerical check against the shipped code path

`scripts/exp003_equivalence_check.py`, deterministic, synthetic, seed 4242,
3,000 fit rows and 500 out-of-sample rows. The C arm is built with the **real**
`_fit_lstsq` / `_mean_of`; the two-step is built as the proposal described.
Record: `results/exp003_equivalence_check.json`.

| Quantity | Value |
|---|---|
| max abs difference, fit rows | 4.34e-19 |
| max abs difference, **out-of-sample** rows | 3.25e-19 |
| max relative difference, out-of-sample | **4.28e-16** |
| size of the quadratic increment itself (C − L, out-of-sample) | 5.47e-4 |
| predictor scale, out-of-sample | 7.61e-4 |
| ranks: C design / projection / increment | 6 / 3 / 3 |
| rank-deficient input | REFUSED: `RANK_DEFICIENT: C design rank 3 < 6` |

The difference is at floating-point level while the increment being tested is
72% of the predictor's own scale — the check would have detected a real
difference.

## 3. Consequences, as the reviewer stated them

- **Zero fit-split mean of the increment is not a new advantage.** The full OLS model already has that projection property; residualising only re-parameterises it.
- **It does not guarantee zero marginal contribution on another period.** Fit-split orthogonality says nothing about 2019 or any later block.
- **Removing the unjustified permutation veto changes the decision rule, not the model.** That is a protocol change and must be described as one.
- **The exposure cannot be undone.** EXP-002's development differential (G1 C−L `t = −2.312`, negative) is a disclosed observation about *this same predictor*, even though the registered result was invalidated. A development screen of an equivalent predictor is **not** a fresh opportunity and must not be presented as one.

## 4. Corrections to the EXP-003 proposal document

1. **"Known-absence" fixtures are not a size estimate.** A handful of seeded fixtures gives realised outcomes, not a false-positive rate. Estimating one requires many independent realisations with reported uncertainty, and exchangeability must be argued for the generator — "synthetic" does not supply it. The proposal's size claim is withdrawn.
2. **Implementation checks can invalidate historical evidence after the fact.** I wrote that they "carry no authority to invalidate a historical scientific result". That is wrong: a genuine numerical or provenance defect discovered later does undermine the scientific use of an artifact already produced. Corrected position: preserve the artifact always, and never promise that a later-discovered defect cannot invalidate its scientific use.
3. **No automatic confirmation opening.** A development threshold cannot itself grant sealed-period access. Any confirmation requires a separately reviewed, explicitly authorised admission. The proposal's "opened once if development passes" is withdrawn as an automatic rule.

## 5. Exposure ledger, corrected

| Period | Status |
|---|---|
| 2016-01-04 → 2018-12-31 | fit split; used by EXP-001B and EXP-002 |
| 2019 | development; **exposed** — including a negative C−L differential for the predictor EXP-003 proposed to re-test |
| 2020-01-01 → 2021-12-31 | **exposed** — reported as EXP-002's secondary period |
| evaluation 2022-01-01 → 2024-12-31 | sealed, with one disclosed exception: **EVALUATION-READ INCIDENT 001** — 60 bytes of metadata (0.058%) from the first evaluation session `SPY_2022-01-03.json` were read once on 2026-09-08, no values exposed; recorded in `docs/EVALUATION_READ_INCIDENT_001.md` and carried forward here so the set is never described as completely untouched |
| reserve | sealed, never opened |
