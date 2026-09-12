# R4 amendment DRAFT — T11a / T11b as a declared limit identity (PROPOSAL ONLY, NOT APPLIED)

Status: `AMENDMENT_DRAFT_FOR_REVIEW`. **This document changes nothing.** The closed contract remains
`docs/R4_JOINT_MARKET_STATE_SPEC.md` at commit `0ce431afe4ac9e3873397b25832a372f3ff22373`, blob
`902256e3c3c5025a450a4bb607410933bb0c4b25`, sha256
`66cba7095bce903d0b3cd474631b90ea962fda97325d70d1abf9670cee49ce50`. The repair branch does not touch the contract
file or its hash; this draft is carried beside it for the reviewer to accept, amend or reject.

## The conflict

Two clauses of the closed contract cannot both hold.

| Clause | Text | Consequence |
|---|---|---|
| §6.1 T11a | "`A ≡ 0`, `Σ ≡ 0`, and every eligible contract starting with `sz ≥ 1` → `JOINT` and `MATCHED_FROZEN` produce bitwise-identical paths, candidate tables and proposals" | requires a residual covariance of exactly zero |
| §6.1 T11b | "`A ≡ 0`, `Σ ≡ 0`, `JOINT` against a frozen comparator with the SAME `MODELLED` size policy → identical for ANY starting size" | same |
| §2.4 | "Require positive definiteness before Cholesky operations" | a zero matrix is not positive definite |
| §2.3 | `COVARIANCE_NOT_PD` refusal; `DEGENERATE_STATE` refusal on a constant outcome column | a zero-variance world cannot be fitted either |

Reproduction (in `tests/test_joint_wb.py::test_T11_contract_conflict_sigma_exactly_zero_is_unreachable`, and in
`docs/evidence/r4_repair_reproductions.json` as `F12_T11_conflict_open`):

```python
SMP.pregenerate(sigma=np.zeros((4, 4)), n_paths=4, seed=1)
# SamplerRefused: COVARIANCE_NOT_PD:S11

MDL.fit(rows_whose_outcomes_never_move, cutoff_epoch=...)
# ModelRefusedR4: DEGENERATE_STATE
```

**No degenerate production path was added.** Weakening the positive-definiteness refusal to satisfy a test would
trade a real safety property for a green tick, and the refusal is load-bearing: it is what stops a rank-deficient
or collapsed covariance reaching the Cholesky and the simulator.

## Proposed replacement text (§6.1, rows T11a and T11b)

> | **T11a** | zero-dynamics identity, COMPATIBLE STATES, DECLARED LIMIT: with `A ≡ 0` and `Σ = ε I` for
> `ε ∈ {1e-10, 1e-14}`, every eligible contract starting with `sz ≥ 1`, and one fixed `scan_id`, the per-candidate
> `E_sel` of `JOINT` and `MATCHED_FROZEN` agree within `τ(ε)` and the gap is MONOTONE DECREASING in `ε`. Declared
> tolerance `τ(ε) = 1e-3` at `ε = 1e-14`. Exact bitwise equality at `Σ ≡ 0` is NOT required and NOT reachable:
> §2.3/§2.4 refuse a non-positive-definite covariance, and that refusal takes precedence (see T11c). |
> | **T11b** | zero-dynamics identity, MATCHED SIZE POLICY, DECLARED LIMIT: the same construction comparing `JOINT`
> against a frozen comparator carrying the SAME `MODELLED` size policy agrees within `τ(ε)` for ANY starting size,
> including `sz < 1` — the case a cross-policy identity cannot cover. |
> | **T11c** (NEW) | degeneracy refusal: `Σ = 0` raises `COVARIANCE_NOT_PD`, and a world whose outcomes never move
> raises `DEGENERATE_STATE`. The refusals are the contract's behaviour at the limit point; no fixture-only
> degenerate sampler path exists. |

## Why a limit identity, and what it does and does not establish

- **What it establishes.** That the option-state contribution is the ONLY thing separating the comparators: as the
  residual law collapses, their candidate values converge, and the convergence is monotone in the collapsing
  parameter. A construction that mixed some other difference in would not converge.
- **What it does not establish.** It is not a bitwise identity, so it cannot catch a difference smaller than
  `τ(ε)`. It is weaker than the original text in exactly that respect, and the weakening is the price of keeping
  the positive-definiteness refusal.
- **Tolerance discipline.** `τ` is declared in the contract, not chosen per run, and the MONOTONICITY requirement
  is what prevents a loose `τ` from hiding a real difference: a genuine discrepancy does not shrink with `ε`.

## Alternative the reviewer may prefer instead

Add a **declared fixture-only degenerate mode** to the sampler: `pregenerate(..., allow_degenerate=True)` returning
exactly zero innovations when `Σ = 0`, usable ONLY from the test fixtures and refused in any production path by an
explicit flag check. That restores the bitwise identity at the cost of a second code path whose only purpose is a
test, and it puts a bypass next to a safety refusal. I did not adopt it and do not recommend it, but it is the
honest alternative and the choice is yours.

## Implementation status while the amendment is pending

The repair branch implements the limit form under the ORIGINAL test names, and records this conflict in
`docs/R4_IMPLEMENTATION_R1.md` and in the reproduction evidence. If you accept this draft, the contract gains
T11a/T11b as above plus T11c, the pin changes, and the tests are renamed to match. If you reject it, the
alternative above is the remaining route, and the implementation would change rather than the contract.
