# EXP-003 — prospective research-design proposal — **WITHDRAWN IN PART**

> **Superseded by `EXP003_EQUIVALENCE_FINDING.md`.** The proposed
> orthogonalised increment is algebraically the SAME predictor as EXP-002's
> C arm (Frisch-Waugh-Lovell; verified against the shipped code path to
> 4.3e-16 relative out of sample). Orthogonalisation is withdrawn as a
> forecasting capability; what remains here is a proposed testing-protocol
> revision, not a model advance, and the same historical comparison must not
> be re-run because its invalidation rule changed. Three further corrections
> apply: the known-absence 'size check' claim is withdrawn; implementation
> checks CAN invalidate the scientific use of an artifact if a defect is
> found later; and the automatic confirmation opening is withdrawn - sealed
> access requires a separately reviewed admission. The successor modelling
> proposal is `EXP004_METAORDER_STATE_PROPOSAL.md`.

---

For independent review. **Nothing here is implemented, fitted, scored or
registered.** No historical access. EXP-002's verdict
(`INVALID_NULL_CONTROL`, no model selected), its records, and the exposure it
created are preserved unchanged and are inputs to this design.

## 1. Exposure ledger carried forward

| Period | Status entering EXP-003 |
|---|---|
| 2016-01-04 → 2018-12-31 | fit split, used by EXP-001B and EXP-002 |
| 2019 | development, **exposed** — EXP-002 development statistics were computed and read |
| 2020-01-01 → 2021-12-31 | **now exposed** — EXP-002 reported it as a secondary period; it can no longer serve as confirmation |
| evaluation, reserve | **sealed**, never opened by any run to date |

Two failed or invalidated results stand on the record and are not reinterpreted:
EXP-001B `NO_SIGNAL`, EXP-002 `INVALID_NULL_CONTROL`.

## 2. The forecasting question

> Given a linear conditional mean of the 15-minute-ahead SPY log return built
> from `ret_1`, `ret_5`, does adding **curvature and interaction** in those same
> two predictors improve the predictive **density**, at an unchanged scale and
> tail law?

**Comparator.** The linear-mean arm L, unchanged from its registered form.

**Incremental information under test.** Exactly the quadratic increment — the
span of `{ret_1², ret_5², ret_1·ret_5}` after projecting out the linear basis and
the constant. Nothing else differs between the two arms.

This is deliberately the *same substantive question* EXP-002 asked. EXP-002 did
not answer it; the design, not the question, is what changed.

## 3. Design of the comparison

**Nested, orthogonalised increment.** On the fit split only:

1. Fit L: intercept plus `ret_1`, `ret_5` on the standardised basis (as registered).
2. Form the quadratic basis, **residualise it against the linear basis and the constant**, and fit the increment `Δ` to L's fit-split residuals.
3. The challenger is `C = L + Δ`. By construction `Δ` has zero fit-split mean and is fit-split-orthogonal to the constant and to the linear terms.

Why this shape: the pair now differs only in a component with **no fit-split
marginal-location content**. That does not make any control valid by itself —
§5 — but it removes the intercept channel that the closure identified as the
clearest contaminant of a location comparison, and it makes the estimand
("does curvature add anything beyond the linear mean") match the arithmetic.

Scale and tail law are shared and taken **unchanged** from the registered
EXP-002 form (`scale = rv_30·s`, Student-t `ν`), estimated once on the fit split.
Both arms use identical `(s, ν)`. The comparison is therefore purely a location
comparison, and is stated as such.

**Primary statistic.** Paired difference in log predictive density, L vs C, per
admitted row; DM-HAC as registered, plus the session stationary bootstrap, both
required to agree. One gate. No compound gates, no subgroup analysis, no
economics.

## 4. Development versus confirmation

- **Development:** 2019, already exposed. Everything exploratory happens here — inspection, diagnostics, any decision to abandon. A development pass carries **no** scientific claim, only permission to open confirmation.
- **Confirmation:** one contiguous block drawn from the **sealed** evaluation set, declared by date range in the registration, opened **once**, scored **once**, with the same fitted parameters and no refit. Its result is the reported finding, whichever way it falls.
- 2020–2021 is exposed and is used, if at all, only as descriptive context with no authority — its exposure recorded on the face of any report.

If development fails, confirmation is **not** opened and the sealed set stays
sealed. That is the point of separating them.

## 5. Controls — what tests what, and with what authority

The failure mode this design is built to avoid: treating "every permuted
comparison must be insignificant" as a universal correctness check. It is not
one, for the reasons in the closure.

### 5.1 Synthetic implementation checks — implementation authority only

Run on generated data with known truth, before any historical access. These
verify that the code computes what it claims. **They carry no authority to
invalidate a historical scientific result**, and a historical result is never
withheld or discarded on their account after the fact.

| Check | What it establishes |
|---|---|
| Known-truth recovery | With a curvature term present at declared strength, the whole pipeline detects it at the registered gate |
| Known-absence | With no curvature term and correctly specified scale/tails, the pipeline does not detect one — a **size** check on a generator whose exchangeability holds by construction |
| Score identities | The paired differential equals the exact closed form of §1 of the closure, to floating point |
| Orthogonality | `Δ` is fit-split-orthogonal to the constant and linear basis, and has zero fit-split mean |
| Reconstruction | Recorded forecast hashes rebuild from saved parameters (the existing verifier) |

Known-absence is a size check **for that generator**, and its power and size do
not transfer to historical data, where the assumed law is not the true law.
That limitation is stated in the registration, not discovered afterwards.

### 5.2 Historical controls with invalidation authority

**Proposed: none based on permuting the historical outcome.** The closure shows
such a control's required `NO_SIGNAL` is not justified by permutation alone, and
I am not able to supply the missing invariance argument. Carrying it forward
unjustified is exactly the error this brick exists to avoid.

Retained with invalidation authority, each with its null stated:

| Control | Null hypothesis | Why the transformation represents it | Assumptions required |
|---|---|---|---|
| **Source and code identity** | "The scored forecasts were produced by the admitted code and data" | Recomputed hashes of admitted bytes and imported modules; any mismatch means the artifact is not what it claims | Hash collision resistance; the checked path covers everything that can alter a forecast |
| **Sealed-period exclusion** | "No sealed data entered this run" | The sandbox cannot read them and the run records which files it opened | The sandbox restriction holds for the tested process, as probed |
| **Fit-budget** | "Parameters were estimated once, on the fit split only" | Recording spies on the real fitters count invocations | The spies wrap every path that can fit |
| **Numerical validity** | "Reported statistics are finite and computed on the admitted rows" | Non-finite values or row-count mismatch refuse the run | — |

These are *integrity* nulls: each is a statement about the artifact, and the
transformation that tests it is a direct measurement, not a distributional
argument. None of them is a statistical test, and none is offered as evidence
that the *scientific* claim is correct.

**Consequence, stated plainly.** With no permutation control, this design has
**no internal statistical guard against a spurious development result**. Its
protection against that is structural instead: a single pre-registered gate, a
single-use confirmation split, and the willingness to report a negative
confirmation. That is a weaker guard in exchange for one that is justified.
If review prefers a randomisation control, it needs an explicit exchangeability
or invariance argument for the time dependence present — which should be
supplied and reviewed *before* it is given invalidation authority, not assumed.

## 6. Budget

| Item | Count |
|---|---|
| Fits on historical data | 3 — L, `Δ`, and the shared `(s, ν)`; all on the fit split; once |
| Refits | 0 |
| Development evaluations | 1 |
| Confirmation openings | 1, only if development passes |
| Gates with authority | 1 (L vs C, both inferences must agree) |
| Reported-without-authority comparisons | at most 2, Holm-adjusted, declared in advance |
| Synthetic worlds | ≤ 8, all before historical access |
| Economics | none |

## 7. Limitations, stated in advance

- The scale and tail law are **assumed**, not tested. If `rv_30·s` with Student-t `ν` misspecifies the conditional scale, a location comparison at that scale can be biased in an unknown direction. EXP-002's calibration numbers already suggest the Gaussian law's lower tail was too thin; nothing here establishes that the Student-t law is right.
- 2019 development and a confirmation block from a different era face **nonstationarity**; a disagreement between them is not automatically evidence that the development result was spurious.
- The confirmation split is single-use and small; it supports one yes/no, not a precise effect size.
- Curvature in two predictors is a narrow hypothesis. A negative result closes this question, not "nonlinearity".
- 2019 is already exposed, so the development result is not a clean out-of-sample statement even before confirmation.
- The design produces **no** economic claim; a density improvement need not survive costs, capacity, or execution.

## 8. What I am asking for

Review of this design only. If it is accepted in principle, the next bricks
would be, in order: a written registration with these choices frozen; the
synthetic implementation checks; then — and only after separate review of those
results — a request for historical admission. No fitting, historical rescoring,
or implementation until then.
