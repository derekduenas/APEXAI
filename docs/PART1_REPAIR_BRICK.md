# Part 1 repair brick — one fee identity, unknown is never zero, exact sale-principal fees (2026-09-12)

Candidate branch `trace-replay-001`. No historical reads, no fitting, no provider contact, no service activation,
no orders. The Part 1 ledger and trace are preserved unchanged as burned, quarantined replay evidence; the
correction is a new record beside them. **Part 2 not started.**

## 0. Quantification before repair (the table the brick asked for first)

| # | Defect | $ on the Part 1 trade | Worst case at the $500 cap | Path |
|---|---|---|---|---|
| **F3** | reserved capital counts an unknown envelope debit as **zero** (`book.py:122`, and `:143` in `risk_inputs`, the second site the review did not name) | **500.00** of exposure invisible to the kernel | **1,500.00** — at the aggregate cap, three positions admissible against an apparent 0 reserved | **RISK GATE** |
| **F1** | the authority gates on its own fee schedule, not the one sealed on the intent | 0.10 (the fees the record could not state) | 0.10 per round trip, but the real consequence is admitting an intent whose own record says the cost is unknown | **RISK GATE** |
| **F2** | Book computes net P&L through `(fee or 0.0)` while `fees_known` is `False` two lines above | 0.10 | 0.10 per round trip | report |
| **F5** | the −36.00 / −36.10 inconsistency | 0.10 | 0.10 | report |
| **F4** | SEC fee as a fixed per-contract constant instead of sale principal | **0.01** (overstated) | 0.01 within the cap; understates by 0.01 above $5.00 premium | report |
| **F6** | the `or 0` idiom as a **class**: 12 occurrences found, of which 4 on risk paths | — | — | mixed |
| **F7** | strict JSON vs NaN/Infinity | — | — | **already satisfied**: `records.canonical_json` used `allow_nan=False` before this brick |

The ranking is confirmed: one defect is worth 500 to 1,500 dollars of hidden exposure in a gate, four are worth ten
cents in a report, and one is worth a cent and was already declared and conservative. Effort was allocated that way.

Reproducers: `scripts/part1_repair_probes.py` → `docs/evidence/part1_repair_reproductions.json` (7/7 reproduced,
with the two extra sites) and `docs/evidence/part1_repair_after.json` (**0/7**).

## A. One fee-schedule identity (blocker) — done

The boundary owns the schedule for the run. `CertifiedRiskAuthority.fee_identity_problem()` now verifies the
identity **carried on the intent** — `schedule_id`, `schedule_hash`, `provenance`, `known`, plus the full policy in
`fee_identity()` — against the authority's own schedule, **before** the certificate, the kernel, or any quote.
Missing, incomplete or mismatched refuses. The identity is sealed on every approval
(`fee_identity`, `fee_identity_verified_against_intent`), carried into the intent record, and **re-checked**
at fill (`Boundary.fee_identity_problem`, inside the eligibility step before the quote call) and at recovery
(`record_outcome`, against the fill's own `fees_entry` identity, so an exit is never priced under a schedule the
entry did not use). The session's pre-selection risk call carries the same block.

Tests (`tests/test_part1_repairs.py::TestOneFeeScheduleIdentity`): boundary-verified/authority-unverified refuses;
**authority-verified/record-unverified refuses (the exact Part 1 defect)**; two different known schedules refuse;
tampered hash refuses; missing and incomplete fee blocks refuse; matching identity proceeds and seals the identity;
**no quote is requested on a mismatch** (asserted through the real session with a counting quote function); a
schedule swapped under an open intent refuses at fill.

## B. Unknown is never zero — the class, risk path first (blocker) — done

**B1, the risk path, first.** An unknown envelope debit no longer becomes zero reserved capital. `Book.reserved` is
`None` with `reserved_unknown = True` and a named `RESERVATION_ENVELOPE_UNKNOWN` integrity problem;
`risk_inputs.planned()` returns `None` for any family containing an unknown reservation, so `open_risk`,
`same_underlying_risk` and `same_family_risk` are unknown rather than understated, and the kernel refuses on an
unknown input instead of sizing against a smaller number. `available_capital` is likewise `None` when either term
is unknown. An unknown beta family now yields `None` rather than `0.0`.

**Two further risk-path sites the review did not name, both fixed:** `risk_inputs` (`book.py:143`) carried the same
idiom per symbol and family; and `risk_certificate.planned_loss_at_stop` treated an unknown exit friction as
frictionless, **understating the planned loss at the stop** — it now returns `NOT_ESTIMABLE` and a caller must pass
`0.0` explicitly to declare a frictionless exit.

**B2.** The arithmetic now honours the flag the Book already computes. **B3/B4.** An unknown entry fee makes the
cashflow amount unknown; an unknown fee on either side makes the closed position `net_status:
NOT_ESTIMABLE_FEES`, `realized_pnl: null`, with `gross_pnl`, debit, credit and the missing-fee reason retained. A
record that *claims* a net while a fee is unknown is an integrity problem. **B5.** `Book.cash` is `None` when any
cashflow is unknown and `gross_cash` always reconciles. **B6.** Already satisfied.

**B7, the actual repair.** `test_b7_structural_ban_on_unknown_to_zero_coercions` greps the whole pilot and decision
path for `or 0`, `or 0.0`, `else 0`, `else 0.0` and **fails the build** on any occurrence without an explicit
`UNKNOWN_TO_ZERO_EXEMPT` comment. It found seven sites beyond the named ones; four were repaired, three carry
reviewed exemptions (a counter increment; a branch already unreachable for a validated quote; two reporting sums
whose unknowns are flagged elsewhere). Also repaired: `decision_wb/experience.py` classified an unknown P&L as a
non-negative outcome (`NO_ERROR`); it now returns `UNSCORABLE_UNKNOWN_PNL`.

## C. Exact sale-principal fees (not a blocker) — done, and the schedule returns to candidate

`FeeSchedule.exit(contracts, sale_principal=…)` computes each component under its own rule: CAT and FINRA TAF per
contract, then the SEC fee at $20.60 per $1,000,000 of **actual sale principal**, rounded up to the cent, before
totalling. Missing principal returns `NOT_ESTIMABLE`; non-finite, negative or boolean refuses. The boundary passes
the actual principal at exit; the Book recomputes independently from the principal the record carries; the
intent-time estimate uses the **reference bid** as a declared assumed principal, consistent with the toll formula's
existing equal-half-spread assumption.

Exit fee by premium: $2.00 → 0.05, $4.54 → 0.05, $5.00 → 0.06, $10.00 → 0.07 (SEC component 0.01/0.01/0.02/0.03).

**The schedule's computation changed, so `ROBINHOOD_RHF_2026` is version `2026-09-12b`, its authorization is marked
`SUPERSEDED_BY_COMPUTATION_CHANGE`, and `LIVE_DEFAULT_FEES` has reverted to `UNVERIFIED_FEES` pending operator
review.** A changed cost model is not an authorized one. This reverses part of the Stage 1 entry: the live default
is unverified again until you review the new arithmetic.

## D. Quarantine and correction — done

The burned ledger is unchanged. `docs/evidence/trace_replay/part1_correction.json` records the status
(`REPLAY`, `QUARANTINED`, `NOT_PROSPECTIVE_EVIDENCE`, `NOT_A_MODEL_PERFORMANCE_RESULT`,
`NOT_ELIGIBLE_FOR_LEARNING_OR_PROMOTION`) and the correction:

| Figure | Value |
|---|---|
| gross | **−36.00** |
| entry fee / exit fee (exact) | 0.04 / **0.05** (sale principal 454.00, SEC component 0.01) |
| **corrected realized** | **−36.09** (of the CORRECTED FIXTURE, not of the burned trade) |
| basis | **NET_ESTIMABLE**, both sides known |

**−36.09 belongs to the corrected fixture, not to the burned trade.** The burned record still reads −36.10 and is
unchanged; −36.09 is what the same quotes produce under the repaired arithmetic, computed on a separate fixture.

**Root cause of the −36.00 / −36.10 discrepancy, not just the figure:** the two runs used *different fee schedules*,
not different arithmetic. Run 1's boundary defaulted to `UNVERIFIED` because the driver passed the authorized
schedule only to the authority (finding A), both fee totals were `None`, and finding B turned them into 0.00, so
−36.00 was the **gross** figure wearing a net label. Run 2's boundary carried the schedule, giving −36.10 under the
fixed SEC constant. Under the repairs run 1 produces **no net figure at all**. Negative test: an unknown fee yields
`realized_pnl: null`, `NOT_ESTIMABLE_FEES`, gross retained — **passes**.

## E. Why the suite missed this — mandatory

| Defect | Which test should have caught it | Why it did not |
|---|---|---|
| F1 fee identity | `test_options_pilot_entrypoint::test_production_risk_authority_refuses_even_if_a_forecast_is_supplied` and the boundary's risk tests | They construct the boundary and the authority **from the same schedule object** in every fixture, so the two could never disagree. The property "these two are the same schedule" was never asserted because no fixture could violate it. *Fixture too clean — the defect is unreachable from the test harness.* |
| F2 P&L via `(fee or 0.0)` | `test_options_pilot_accounting` Book tests | They assert P&L on **known** fees only. There is a `fees_unknown` flag test and a P&L test, and nothing joins them: no test ever asked what the P&L *is* when the flag is true. *Property never asserted at the junction of two properties that are each tested.* |
| F3 reserved capital | the same Book tests and the kernel tests | Every fixture builds a reservation with a real `envelope_debit`, because the envelope is produced by `envelope_for()`, which never returns `None`. The only way to reach the branch is a malformed record, and no test writes one. *No test of that behaviour; the branch was unreachable from valid inputs and therefore untested and wrong.* |
| F4 SEC fee | `tests/test_options_pilot_accounting` fee tests | They assert the fee **matches the schedule's own constant**, which is a tautology: the test and the code share the same wrong model. Nothing compared the schedule to the published rule it claims to implement. *Assertion tests self-consistency, not correctness against the source document.* |
| F5 report inconsistency | none | No test compares two runs' economics under different configurations, and nothing forbids labelling a gross figure as net. *No test of that behaviour.* |

**The pattern.** The hypothesis holds, with the sharpest instance yet: **the Book computed `fees_known: False` and
then discarded it in the next arithmetic line.** The information was not missing; the test suite verified that the
flag is produced, and separately that P&L is produced, and never that the second respects the first. That is the
shape of all five: each component is tested in isolation and the *relationship between components* is not. F1 is
two objects that must be one and were never compared; F2 is a flag and an arithmetic that must agree and were
never joined; F3 is a branch no valid fixture can reach; F4 is a test that shares the code's model of the world.
Three consecutive reviews have found by reading source what 400+ passing tests did not, and in every case the tests
covered the parts and not the joins.

The B7 structural ban is the first test in this repository that fails on a *class* of defect rather than an
instance, and it caught seven sites in its first run. The equivalent for the joins would be a fixture obligation:
every gate must have a test in which its input is unknown, and every pair of objects that must be identical must
have a test in which they differ. Proposed, not built.

## Two regressions my own repairs caused, found by the focused suites and fixed

1. **Refusal precedence changed.** I placed the fill-time fee-identity check *before* `_require_new_fill_eligibility`,
   so a production boundary holding a synthetic intent refused with `FEE_IDENTITY_CHANGED_SINCE_INTENT` instead of
   `RISK_AUTHORITY_INCOMPATIBLE`. Both are correct refusals, but reordering an existing precedence is a behaviour
   change I did not intend. Moved after the eligibility checks, still before the quote call.
2. **The recovery check fired on an unfilled attempt.** A WAIT fill carries no `fees_entry` by construction, and my
   check read its absence as a changed schedule. Now enforced only when `status == "FILLED"`.

Both were caught by existing tests, which is worth recording: the suite does catch changes to behaviour it already
pins. What it does not catch is behaviour nobody ever pinned.

## Residual gap closed in the same brick: the identity is now CRYPTOGRAPHICALLY complete

The first pass compared the identity the authority holds against the identity the intent carries **at approval
time**. It did not make the identity part of the persisted binding, so an identity altered *after* approval still
verified while `schedule_id` was unchanged. Reproduced on a clean checkout, 7 of 9 alterations undetected
(`docs/evidence/fee_identity_reproductions.json`); **0 of 9 after** (`fee_identity_after.json`).

**The complete canonical fee identity** (`FeeSchedule.identity()`), committed to by `envelope_binding_hash`:

| Field | Meaning |
|---|---|
| `schedule_id` | the schedule's name |
| `schedule_hash` | digest of the full described schedule |
| `provenance` | SYNTHETIC_FIXTURE / PROVIDER_VERIFIED / UNVERIFIED |
| `known` | whether the cost is knowable at all |
| `version` | the schedule's version string |
| `effective_date` | the date the published terms take effect |
| `terms_digest` | digest of the **fee terms alone** — no ids, no provenance — so two schedules with the same id and different arithmetic differ here |

`envelope_binding_hash` now commits to `binding_hash(intent) + max_entry_price + envelope_debit + the complete
identity`, with a missing field represented as `__ABSENT__` and any undeclared key gathered under `__EXTRA__`, so
adding, removing or altering **any** of them changes the binding and a persisted approval stops verifying.
`verify_approval` additionally compares the approval's **own** recorded identity field by field against the
intent's. `CertifiedRiskAuthority.accepts()` compares all seven fields, so an authority with the same `schedule_id`
and different terms no longer honours a stored approval. The boundary seals `identity()` on the intent, refuses an
incomplete block by name (`FEE_IDENTITY_INCOMPLETE_ON_INTENT`, listing the missing fields) and refuses an
over-complete one (`FEE_IDENTITY_HAS_UNDECLARED_FIELDS`), re-reading the persisted intent from disk rather than
trusting a caller object. Recovery compares the complete identity carried on the persisted **fill**.

**Decimal-cent arithmetic** replaces binary floats. Each component is computed in `Decimal` and rounded under its
own published rule *before* the total: commission and ORF/OCC exact per contract; CAT per contract with a sub-cent
charge rounding **down to zero**; FINRA TAF to the **nearest** cent; SEC on the **actual sale principal** rounded
**up**. Every component, its raw value and its rounding decision are persisted (`component_basis`,
`rounding_rules`, `arithmetic: DECIMAL_CENTS`) so a total is reconstructable. A schedule that prices on principal
without declaring its per-contract sell components returns `SELL_COMPONENTS_UNDECLARED` rather than defaulting.

Verified against the published schedule (PDF sha `7f9c86bf…`): ORF+OCC $0.04/contract both sides; CAT $0.0003 →
$0.00 at 1 contract and $0.03 at 100; TAF $0.00329 → $0.00 at 1, $0.01 at 2, $0.03 at 10; SEC at $2.00/$4.54/$5.00/
$10.00 → $0.01/$0.01/$0.02/$0.03.

## Testing and identities

Focused suites: fees, boundary, risk, Book, ledger, session, recovery, plus every suite touching them; 17 files.
Four tests that pinned the morning's `PROVIDER_VERIFIED` live default were updated to assert the revert, which is
the intended new behaviour, not a weakened assertion. Reproducers re-run: **0 of 7 survive**. Two probes were corrected mid-brick because they measured the pre-repair surface (F4
compared against a hardcoded constant; F7 tested the stdlib rather than the record serializer) — stated rather than
quietly amended. Builder-reported throughout; nothing in this brick is independently reproduced.

Environment: Mac (Intel i5-5250U), Python 3.11.9, numpy 2.4.6, single process, `-p no:cacheprovider`.

## Part 2 gating

Part 2 remains **not started**. It resumes after A, B and D pass review. The session's data is already registered
BURNED and remains quarantined observational data; Part 2 will need a new burn declaration naming it again.
