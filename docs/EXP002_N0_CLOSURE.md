# EXP-002 N0 — analytical closure

EXP-002 stays invalidated: run `20260909T193814Z-exp002-ca450243`,
`INVALID_NULL_CONTROL`, no model selected. Nothing here reopens it, and no
historical access, fitting, alternate seed or retrospective change was performed.
This document corrects the derivation in `EXP002_N0_DIAGNOSTIC.md`. The frozen
predictions and their failed outcomes in that document are preserved unchanged.

## 1. The exact score difference, and what actually decides its sign

For a matched pair sharing scale `σ_i` and shape, differing only in location
(`μ_i` vs `0`), write `a_i = μ_i/σ_i`, `z_i = y_i/σ_i`. The `−log σ` terms
cancel exactly.

**Student-t:**

    d_i = ((ν+1)/2) · log( (ν + z_i²) / (ν + (z_i − a_i)²) )

**Gaussian:**

    d_i = a_i·z_i − a_i²/2

Both are exactly positive under the *same* elementary condition:

    d_i > 0  ⟺  (z_i − a_i)² < z_i²  ⟺  a_i·(2z_i − a_i) > 0

That is pure geometry — the forecast location moved toward the outcome and did
not overshoot by more than twice the distance. It involves **no curvature term
and no family-specific property**. The families differ only in how each row's
displacement is *weighted* into the total, not in when a row favours one arm.

My previous framing put the second-order term `−½E[a²ψ′(z)]` at the centre of
the sign question. That expansion is a local approximation around `a = 0`; the
first-order term, the sign and size of `a`, and the remainder all matter, and
`ψ′(z) < 0` on some rows does **not** establish a positive expected differential.
I withdraw that framing.

I also substituted `E[ψ′(z)]` for `E[a²ψ′(z)]`. That substitution is valid only
when `a ⟂ z`, which held **by construction in my synthetic fixture** and does
**not** hold in the experiment: `a_i = m_i/σ_i` and `z_i = y_i/σ_i` share `σ_i`,
so they remain dependent even after the outcome is permuted. The reported
`E[ψ′]` values therefore describe the fixture, not the run.

## 2. The Gaussian claim was false — the counterexample

I claimed the Gaussian pair "cannot go positive under an independent outcome".
That is wrong. Exactly:

    E[d] = E[a·z] − ½·E[a²]

Independence of the outcome from the predictors gives `E[a·z] = E[a]·E[z]`, not
zero, and `E[z] = E[y]/σ`. So the inequality `E[d] ≤ 0` requires

    E[a·z] ≤ ½·E[a²]

which independence alone does not supply.

**Counterexample** (the reviewer's, restated): let the outcome have marginal mean
`m ≠ 0`, let L predict `m` on every row and S predict `0`, with constant scale
`σ`. Then `a ≡ m/σ`, `E[z] = m/σ`, and

    E[d] = (m/σ)·(m/σ) − ½·(m/σ)² = m²/(2σ²) > 0

There is no conditional predictive information anywhere in this construction —
only a better **marginal** location — and permutation leaves it entirely intact,
because permutation preserves the marginal outcome distribution *including its
mean*. The Gaussian pair is exposed to exactly the channel I claimed protected it.

Consequence for §3 of the diagnostic: the L−S / M1−M0 contrast is **not** the
structural family difference I asserted. Both pairs can go positive under a
permuted outcome. What remains true is narrower: the two pairs weight the same
per-row condition differently, so their null statistics need not agree, and a
disagreement between them is still not by itself evidence of a bug. That M1−M0
passed on the historical data (`t = 0.893`) is an empirical fact about that data —
plausibly because the marginal mean of 15-minute log returns is small relative to
`σ` — not a guarantee from the Gaussian form.

## 3. Sufficient assumptions for a nonpositive expected differential

Family-free statement. Under the permuted law, write the comparison as expected
log-score of location `μ(X)` against location `0`, at the arm's own scale:

    E[d] ≤ 0  ⟺  E[ log p(Y; μ(X), σ(X)) ] ≤ E[ log p(Y; 0, σ(X)) ]

A sufficient set of assumptions:

1. **Independence.** `Y ⟂ X` under the transformation, so no conditional information survives.
2. **Pseudo-true centering.** For (almost) every scale value `σ`, location `0` maximises `μ ↦ E[log p(Y; μ, σ)]` over the locations the challenger actually uses — i.e. zero is the KL-optimal location for the *marginal* outcome law under the assumed family and that scale.
3. **No scale–location coupling.** The permuted outcome's best-fitting location does not vary systematically with `σ(X)` in a way correlated with `μ(X)`.

For the Gaussian, assumption 2 reduces to `E[Y] = 0`; then `E[a·z] = 0` and
`E[d] = −½E[a²] ≤ 0`, with equality only if the location is identically zero.
For the Student-t, assumption 2 is the pseudo-true (M-estimator) location being
zero, which is *not* implied by `E[Y] = 0` when the outcome law is not the
assumed `t_ν(σ)` law.

**What N0 establishes:** the row-level pairing of outcome with state is
destroyed, so (1) holds up to the within-block dependence the block permutation
deliberately retains; forecasts are not recomputed; the marginal outcome
distribution and the state sequence survive.

**What N0 does not establish:** assumptions (2) and (3). Nothing in the
permutation forces the marginal outcome's pseudo-true location to be zero, and
the L arm retains a fitted **intercept**, which is precisely a marginal-location
term that survives the transformation. The asserted `NO_SIGNAL` for `L−S` is
therefore **conditional on assumptions the control itself does not supply** —
for either family.

## 4. Why matching forecast scales does not create a zero-information null

Matching scale and shape across a pair *isolates* the location channel: it
removes scale fit as a confound, which is why the pair is called matched.
Isolation is not neutralisation. After permutation the outcome keeps its
marginal law, and a location forecast that sits closer to that marginal law's
pseudo-true location scores better — with no conditional information at all.
Matching removes one channel and leaves the other fully open. A genuinely
zero-information comparison would additionally require the two arms' locations to
be equally good against the permuted marginal law, which is the content of
assumption (2) above, not a consequence of matching.

## 5. Corrections to the chance and precision statements

- **Chance.** I wrote that the simulated values make a chance rejection "less comfortable" than the p-value suggests. **Withdrawn.** Four realised statistics from one generator under fixed seeds are not a reference distribution for the historical statistic. Any statement about the plausibility of chance requires a justified reference distribution for that statistic under the market null, which I do not have.
- **Precision vs expected disadvantage.** I described heterogeneity as "eroding the negative margin" using the Gaussian t-statistic moving −6.85 → −0.49. In the same fixture its **mean became more negative** (−1943 → −21134, in 1e-6 units). Those measure different things: the mean is the expected score disadvantage, the t-statistic is that mean divided by a HAC standard error that grew faster. What the fixture shows is deteriorating statistical **precision** under heterogeneity, not erosion of the expected disadvantage. I conflated them.

## 6. The refutation, narrowed to what was tested

Supported conclusion, and no more:

> The proposed scale-heterogeneity mechanism did not produce a positive
> Student-t differential in the four tested configurations
> (τ ∈ {0.0, 0.3, 0.6, 0.9}, outcomes drawn from exactly the assumed `t_ν(σ)`
> law, `a ⟂ z` by construction, one seed).

It does **not** establish that volatility mismatch cannot contribute under other
outcome distributions — in particular under the misspecification that the
fixture excluded by construction, since it generated outcomes from the very law
the arms assume. The frozen predictions stand as recorded: A and D failed, B and
C held.

## 7. Where this leaves the historical failure

Two things must stay separate.

- **Established here:** N0's `NO_SIGNAL` assertion for a matched location pair is not justified by permutation alone. It rests on a centering assumption the transformation does not enforce, and this applies to the Gaussian pair as well as the Student-t pair. The control tests less than it was taken to test.
- **Unresolved:** whether that gap explains the observed `L−S t = +2.823` on the development period. It could equally be misspecification of the tails given `σ`, the retained intercept, HAC understatement under block permutation, chance, or a combination. Nothing here measures which.

## 8. Proposed disposition for the next registration

For decision, not for action now. EXP-002's verdict and records are unchanged.

1. **State the assertion conditionally.** Record N0's matched-pair claims together with the centering assumption they require, so a failure is read as "the assumption or the model failed", not "the model failed".
2. **Close the marginal-location channel** in whichever way the next registration prefers — for example holding the intercept common across a matched pair so the compared arms differ only in the conditional component, or centering the outcome before permutation. Either changes what the control tests and must be declared in advance.
3. **Replace the fixed threshold with the transformation's own reference distribution.** Computing the statistic over many permutations gives a valid reference for exactly the transformation performed, instead of assuming a null expectation of zero. This costs compute and would need its own budget declaration.
4. **Do not** change N0, the threshold, or the model retrospectively, and do not re-run EXP-002 under a modified control. The invalidated result stands on the record as it is.

I am not recommending one of these over the others; that is a registration
decision. My only recommendation is that whichever is chosen be declared before
any further historical access.

---

## 9. Corrections to this closure (applied; investigation closed after these)

**9.1 Permutation does not establish independence.** §3 said N0 establishes
assumption (1) "up to the within-block dependence the block permutation
deliberately retains". That is still an overclaim. Block permutation **disrupts
the original row-level pairing**; it does not establish independence between the
permuted outcome and the state. Retained time structure, block positions,
nonstationarity across 2016–2021, and accidental alignment of a permuted block
with a similar state stretch can all leave dependence. Corrected statement:

> N0 establishes that the original pairing was disrupted. It does **not**
> establish assumption (1), (2) or (3). All three remain assumptions.

**9.2 Independence gives factorization, not substitution.** Under independence of
the *standardized* variables, `E[a²ψ′(z)] = E[a²]·E[ψ′(z)]` — the non-negative
multiplier `E[a²]` remains, so independence licenses reading the **sign** from
`E[ψ′(z)]`, never the magnitude. Independence is sufficient for that
factorization, not necessary. And my claim that `a` and `z` "remain dependent"
in the experiment because both contain `σ` was too strong: a shared denominator
is a potential dependence channel, not a proof of dependence in every
construction. The same care applies to the Gaussian step: `E[az] = E[a]E[z]`
requires independence of the standardized `a` and `z`, not merely of raw
outcomes and predictors, once the scale varies across rows.

**9.3 Repetition does not manufacture a reference distribution.** Disposition
item 3 said computing the statistic over many permutations "gives a valid
reference". It does not. It gives the distribution induced by the chosen
randomization scheme. Treating that as the null distribution requires an
exchangeability or invariance argument appropriate to the hypothesis and to the
time dependence present; more repetitions cannot supply it. Corrected to: *a
permutation reference distribution is a candidate design that requires an
explicit invariance argument, not a default remedy.*

**9.4 Neither centering fix is automatically sufficient.** A common intercept
across a matched pair does not guarantee that the differing conditional
components carry no marginal score advantage after permutation. Arithmetic
centering of the outcome does not generally produce the Student-t pseudo-true
location, especially across varying scales. Both are **candidate designs
requiring justification**, not fixes.

**9.5 Transcription.** §5's precision correction quoted the wrong series. The
Gaussian **permuted** realized sample means accompanying `t` = −6.85 → −0.49 were
approximately **−1777 → −7983** (1e-6 units); the −1943 → −21134 figures are the
**intact** series. All of these are realized sample means from one seeded
fixture, not established expectations. The observation stands in that narrower
form: in this fixture the permuted mean grew more negative while the realized
`t` moved toward zero, consistent with a HAC standard error growing faster than
the mean.

**Status: this investigation is closed.** Established: N0's required `NO_SIGNAL`
is not justified by permutation alone. Unresolved and not further pursued: the
cause of the specific `L−S t = +2.823` failure on the development period.
