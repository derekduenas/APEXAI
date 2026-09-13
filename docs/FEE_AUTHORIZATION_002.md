# FEE-AUTHORIZATION-002 — source verification is not operator authorization (2026-09-13)

Branch `tradingview-integration-003`. Code pin at entry `35af566`, evidence head `ee63990`.

**Monday's scheduled paper run is HELD. No merge, no deployment, no fee promotion, no paper execution.**

## The finding, reproduced before any repair

`docs/evidence/fee_authorization_002/FINDING_REPRODUCTION_before_repair.txt`

`ROBINHOOD_RHF_2026` v2026-09-12b described itself as an unauthorized candidate while being constructed as
`PROVIDER_VERIFIED`:

| | |
|---|---|
| D1 | the object said **both** CANDIDATE and AUTHORIZED — the source comment said "returns to candidate", the `note` said "AUTHORIZED by the operator 2026-09-12 and the LIVE default from that date" |
| D2 | the **superseded** 2026-09-12 authorization travelled *inside* the schedule, attached to arithmetic it never covered |
| D3 | `IDENTITY_FIELDS` named **no** authorization field, so nothing downstream could detect its absence or supersession |
| D4 | **the explicit-candidate bypass**: `LIVE_DEFAULT_FEES = UNVERIFIED_FEES` refused, but passing the candidate explicitly produced `decision=TRADE, intents=1, fills=1` |
| D5 | the supersession was applied by mutating a dict *inside* a frozen dataclass after construction, and nothing ever read it |

Root cause: `known = provenance != "UNVERIFIED"`. `provenance` carried two different facts — that a **document**
was verified, and that the **computation** was cleared for use — and `known` is what every downstream gate
consulted. A schedule became usable the moment it was transcribed. **No person had to agree to the arithmetic.**

This was my own reporting error too: I demonstrated the bypass in the stand-up audit and read it as proof the gate
worked, when it was proof the gate was a default rather than a control.

## The repair

1. **Two facts, kept apart.** `provenance` now means source verification only (`source_verified`). A new
   immutable `FeeAuthorization` records the operator act.
2. **Authorization evidence** carries `schedule_id`, `version`, `source_document_sha256`, `terms_digest`,
   **`computation_digest`**, `effective_date`, `status`, `authorized_by`, `authorized_utc`, `scope` — each matched
   **exactly**; a near miss is a refusal naming the field that differs.
3. **`computation_digest`** is new and is the field that would have caught this: the *rates* were identical
   between v2026-09-12 and v2026-09-12b; only **how the SEC component is computed** changed. A terms digest alone
   could not distinguish them, which is exactly how the superseded authorization survived.
4. **Bound into the canonical identity** — `authorization_status`, `authorization_digest`, `computation_digest`
   and `source_document_sha256` are in `IDENTITY_FIELDS`, so a persisted approval stops verifying the moment the
   authorization changes, is removed or is superseded.
5. **The control, not the default.** `FeeSchedule.usable` = known **and** authorized. Refusal happens at
   **`Boundary.__init__`** — before any quote request, certificate, kernel check, intent or fill — and again,
   independently, in `CertifiedRiskAuthority.approve()`. `charge()` returns `NOT_AUTHORIZED`, never a number.
6. **Stale records corrected.** The schedule's note now reads `CANDIDATE, NOT AUTHORIZED`; the superseded
   authorization is detached into `ROBINHOOD_RHF_2026_SUPERSEDED_AUTHORIZATION` with
   `applies_to_current_schedule = False`. No object says both.

`SYNTHETIC_FEES` is exempt (`requires_authorization == False`): it is labelled synthetic, can never be a live cost
claim, and authorizing a fixture would be theatre. `UNVERIFIED_FEES` still *constructs* — a session that records
refusals is evidence; one that cannot start is not.

## After the repair

```
LIVE_DEFAULT (UNVERIFIED)  decision=REFUSE   FEE_SCHEDULE_UNKNOWN
explicit ROBINHOOD v-b     BOUNDARY REFUSED  BOUNDARY_REFUSES_UNAUTHORIZED_FEE_SCHEDULE
SYNTHETIC fixture          decision=TRADE    (unaffected)
```

## What is NOT done here

No authorization has been authored or installed. `ROBINHOOD_RHF_2026.authorization is None`. The exact digests and
a proposed payload are in `docs/evidence/fee_authorization_002/PROPOSED_AUTHORIZATION.txt` for review.

No merge, no deployment, no pilot restart, no lifting of the hold, no paper execution.


---

# R1 — two blocking findings from review (2026-09-13)

Base `f3c8cb9`. Both reproduced before repair:
`docs/evidence/fee_authorization_002/R1_FINDING_REPRODUCTION_before_repair.txt`.

## F1 — identity consumers compared an obsolete subset

`accepts()` and `fee_identity_problem()` each carried their **own hand-written tuple of seven fields**. The identity
had grown to twelve. Reproduced: an approval issued under one operator authorization was **honoured** by an
authority running a different one (`accepts() -> None`), and an intent sealed under one **passed the gate** on
another.

This is the same defect family as the fee gate itself: the producer records the right information and the consumer
inspects a hand-written subset of it.

**Repair.** One canonical `fees.identity_problem(mine, theirs, *, what)` comparing against `IDENTITY_FIELDS`
itself, with exact key equality **in both directions** — a missing field refuses (an older record cannot be quietly
accepted by a newer authority) and an **extra** field refuses (an identity carrying something undeclared is not one
this code understands). All consumers call it.

**A structural test greps every module for a hand-written identity tuple — and immediately found a third
consumer neither the review nor I had listed: `risk_gate.FEE_IDENTITY_FIELDS`, its own copy of the seven, feeding
`envelope_binding_hash`.** The envelope binding was therefore also committing to the old seven, so a binding made
under one authorization still verified under another. It now derives from the single definition.

## F2 — `computation_digest` hashed labels, not computation

Reproduced: changing `ROUND_CEILING` to `ROUND_FLOOR` in the executable path changed the charge **0.06 → 0.05**
and left the digest **byte-identical**.

**Repair, non-self-referential:**

- `FeeComputationPolicy` — immutable, declarative, holding the actual bases and rounding modes. **`_side()` reads
  its rounding modes from it**, so the description cannot drift from the behaviour. Changing a policy rounding rule
  now changes the charge (verified: 0.06 → 0.05).
- `implementation_digest` — a canonical AST of `_side`/`entry`/`exit`, docstrings and line numbers stripped,
  carrying no authorization payload data. Computed from `type(self)`, so a subclass overriding the arithmetic
  digests differently. Independently recomputed in tests.
- Both are bound into `FeeAuthorization` and `IDENTITY_FIELDS`.
- **Unreadable source fails closed**: a frozen build or zipimport yields `UNVERIFIABLE_IMPLEMENTATION:…`, which can
  never equal an authorization digest — it refuses rather than raising into the fee path or matching by accident.

## Operational consequence of binding the code

`implementation_digest` binds the authorization to the **current** fee-calculation code. Any later edit to
`_side`/`entry`/`exit` invalidates it and refuses every trade until re-authorized. **Authorize after the code is
frozen for the release you intend to run.** The refusal is loud and safe, not silent.

## Procedural limitation, acknowledged

`FeeAuthorization` records `authorized_by` but does not **authenticate** it. For this paper pilot that is
procedural authorization — acceptable only because the operator authorizes the exact digests, the artifact is
preserved, and Claude does not create it before instruction. For a real-money boundary it must become an
externally signed decision.

---

# R2 — the computation binding made transitive (2026-09-13)

Base `0b71849`. All four findings reproduced before repair:
`docs/evidence/fee_authorization_002/R2_FINDING_REPRODUCTION_before_repair.txt`.

## F1 — a transitive dependency was unbound

`_side()` resolved rounding through the module-level mutable dict `ROUND_MODES`, which was in **neither** digest.
`ROUND_MODES["UP"] = ROUND_FLOOR` — one assignment, no source file touched — moved the charge **0.06 → 0.05** with
both digests byte-identical. The original defect, one level down: the digest covered the functions, not what they
resolved *through*.

**Repair.** The table is deleted. `FeeComputationPolicy.mode()` writes the mapping directly and its own AST is in
`implementation_digest`, which now also resolves against **the policy class actually in use** — so a
`FeeComputationPolicy` subclass overriding `mode()` (the same hole one step over) changes the digest too. A
structural test parses `fees.py` and fails if any fee-calculation function reads a module-level mutable container.

## F2 — the declared basis was not the executed basis

`_side()` dispatched on `sale_principal_rate_per_million`, so `sec_basis` was attested in the digest while the code
consulted something else. `sec_basis="NONSENSE"`, `arithmetic="FLOATS"` and
`component_order=("commission","commission")` all constructed.

**Repair.** `_side()` dispatches on `pol.sec_basis`. `FeeComputationPolicy.__post_init__` rejects unsupported
`sec_basis`, `regulatory_sum`, `arithmetic`, non-bool `cat_sub_cent_to_zero`, and any `component_order` that is not
a duplicate-free permutation of the components. `FeeSchedule.__post_init__` refuses a schedule whose declared basis
and carried terms disagree, in either direction. **Every policy field now controls execution or does not exist.**

## F3 — Book recomputation ignored the authorization

`recompute_fees` compared `schedule_id`, `schedule_hash` and the total. Two schedules with identical **terms** and
different **operator authorizations** share a `schedule_hash` and produce the same number, so an outcome written
under one reconciled clean under another. It now calls `identity_problem()` on the recorded `fee_identity` **before**
numeric agreement is accepted. Numeric agreement is not identity agreement.

## F4 — the sentinel was authorizable

`UNVERIFIABLE_IMPLEMENTATION:…` was accepted as an `implementation_digest`, authorizing exactly the build the
sentinel exists to refuse.

**Repair.** Every digest field must be exactly 64 lowercase hex (`is_digest`), enforced at authorization
construction. Independently, `authorization_state()` refuses an unverifiable runtime implementation **before it
examines the supplied authorization at all**, so no payload can match its way past. Both are named refusals.

## Consumer inventory

`docs/evidence/fee_authorization_002/FEE_IDENTITY_CONSUMER_INVENTORY.txt` — every fee-identity consumer, what it
uses, and the one excluded false positive (`recorded_feed.IDENTITY_FIELDS` is a *quote* identity).

## Not done

No authorization authored or installed. No merge, deployment, timer recreation or paper execution. **The full
regression has not been started** — held for independent review, as instructed. Both digests changed in R2, so any
payload computed from an earlier commit is stale and will refuse.

---

# R3 — identity closure and computation closure (2026-09-13)

Base `0247f10`. Both findings reproduced first:
`docs/evidence/fee_authorization_002/R3_FINDING_REPRODUCTION_before_repair.txt`.

## F1 — `verify_approval` was not an exact verifier

It iterated `FEE_IDENTITY_FIELDS` with `a_id.get(k, "__ABSENT__")`. That proves the **named** fields match and says
nothing about an **undeclared** field on the approval — a consumer walking the declared fields cannot see an extra
one. Other checks sometimes refused such a record anyway; **a verifier that is only accidentally correct is not
one.**

**Repair.** One comparator, `fees.identity_disagreement(left, right, left_name=, right_name=)`: exact key equality
on **both** sides via `identity_shape_problem`, then exact value equality, returning a reason that names the side
and the field. `identity_problem` is a thin form of it. Every consumer routes through it, and a structural test
fails any module that iterates the identity fields itself.

## F2 — the digest was an allowlist of four functions

Reproduced with **two ordinary commits**, no monkeypatching: refactor the SEC component into a helper, then edit
only that helper — charge **0.06 → 0.05**, `implementation_digest` unchanged.

**Repair, the closed design.** All executable arithmetic and the declarative policy moved to
`apex/options_pilot/fee_computation.py`. `implementation_digest` is sha256 over **that module's entire canonical
AST**. A new helper, constant or branch is inside the digest by construction.

Three properties make the closure real, each structurally asserted:

1. **No authorization data in the module** — so digesting it cannot be circular.
2. **The dependency set is closed** — every free name resolves inside the module or to `EXTERNAL_DEPENDENCIES`
   (stdlib `decimal`/`math` only); a new unresolved global fails the test.
3. **Non-canonical classes are refused** — `compute_side` refuses any policy that is not exactly
   `FeeComputationPolicy` (`POLICY_NOT_CANONICAL`), and a `FeeSchedule` subclass reports
   `UNVERIFIABLE_IMPLEMENTATION`. Both close the "override it from outside the digested module" route that a
   module-level digest would otherwise reopen.

`FeeSchedule._side` is now **gating and identity only**; a structural test asserts it performs no arithmetic.

## Tests changed or superseded

| test | change |
|---|---|
| `r1::test_the_implementation_digest_is_independently_recomputable` | recomputes from the module AST, not the function allowlist |
| `r1::test_unreadable_source_fails_closed…` | sourceless-subclass trick no longer applies; exercises the module error path |
| `r1::test_7_changing_the_fee_ARITHMETIC…` | a `FeeSchedule` subclass is now `UNVERIFIABLE_IMPLEMENTATION` — closed more strongly |
| `r2::test_the_rounding_mapping_is_inside_the_digested_function` | renamed `…_module`; `mode` is no longer allowlisted |
| `r2::test_overriding_the_rounding_mapping…` + `…covers_the_policy_class` | replaced by `test_a_policy_subclass_is_refused_outright` |
| `r2::test_STRUCTURAL_…mutable_container` | now scans `fee_computation.py` |
| `002::test_5_an_altered_document_digest…` | uses a well-formed 64-hex digest, since malformed now refuses at construction |

## Honest threat boundary

Binds **committed source and declared policy** for a **paper** boundary. **Not** proof against a malicious
interpreter, a patched stdlib, or arbitrary in-process mutation — anything that can rewrite memory can rewrite the
digest. Procedural authorship is **unauthenticated**. Real-money use requires an external signed authorization and
a release attestation.

## Not done

No authorization authored or installed. No merge, deployment, timer recreation, ledger, order, or lifting of the
hold. **The full regression was not started.**

---

# R3.1 — the public execution surface, closed (2026-09-13)

Base `c8425c0`. Reproduced before repair: `R31_FINDING_REPRODUCTION_before_repair.txt`, after:
`R31_AFTER_REPAIR.txt`.

## The finding

R3 digested `fee_computation.py` and left the public path outside it. A wrapper needs no arithmetic to change a
fee — it can change side, quantity, principal, policy or the returned components. All five mutations changed the
charge with **both digests unchanged**, and the decisive check:

```
baseline                                      auth=AUTHORIZED usable=True exit=0.06
after forcing the exit down the entry branch  auth=AUTHORIZED usable=True exit=0.04
```

An authorization computed **before** the edit still reported `AUTHORIZED`. My R3 suite did fail on those
mutations, but only because it asserts fee **values** — a value assertion is not a closure, and tests do not run
in production. The digest, which is what an authorization actually binds, did not move.

## The repair

`FeeRuntime` — `terms`, `policy`, `_side`, `entry`, `exit` — now lives **inside** `fee_computation.py`, together
with `validate_terms_and_policy`. `FeeSchedule` inherits it and holds only data, identity and authorization.
After repair every mutation yields `AUTHORIZATION_MISMATCH`.

`fee_surface_problems(cls)` proves the closure: every fee-producing member must resolve to the digested module. A
**negative** test adds a fee path outside it and asserts the build fails.

`FeePolicyRefused` now inherits `FeeComputationRefused`, so one handler catches a schedule-level or runtime-level
refusal (the runtime cannot import `fees`, so it raises the base directly).

## Tests changed or superseded

| test | change |
|---|---|
| `r2::test_a_policy_subclass_is_refused_outright` | expects `FeeComputationRefused` — the runtime raises it directly now |
| `r3::test_a_non_canonical_policy_or_schedule_class…` | same |
| `r3::test_the_module_contains_no_authorization_data` | made precise: the runtime legitimately *calls* the gate and reports `authorization_status`; what must never appear is an authorization **payload** |

## Digest boundary

**Inside:** all of `fee_computation.py` — policy, validation, arithmetic, gate, and the complete public surface.
**Outside:** `FeeSchedule`'s data, `identity()`, `authorization_state()`, `FeeAuthorization` — so the digest is
not circular.

## Not done

No authorization authored or installed. No merge, deployment, timer recreation, ledger, order, or lifting of the
hold. **The full regression was not started.**
