# EXIT-SCHEDULING-003 — restart continuity, arrival-to-quote provenance, deterministic coalescing (2026-09-12)

Branch `exit-scheduling-003`, base `16513b08fb38f262b29b7f2222be0830e4615334`. Synthetic only. **The recorded driver
is neither wired nor run. No fee, capital limit, affordability, strategy selection or deployment change.**

All three cases were reproduced against the unmodified base before any code changed: `tests/test_exit_scheduling_003.py`
ran **14 failed, 14 passed** at `16513b0`. After the changes the same file runs **28 passed**. Each reproducer's
docstring names the behaviour it pinned.

## 1. Restart continuity

**Reproduced.** An inherited position received one labelled recovery attempt via `_recovery_attempt` and was then
settled out of servicing. A usable quote arriving at due + 30 s, inside the remaining window, was not used.

**Repaired.** `_recovery_attempt` is removed. An inherited position flows through the same `_service_exit` as one the
process opened, under the original policy's remaining window and remaining attempt budget. `recovered_seqs` survives
only as a label.

> **Corrected 2026-09-12 (see "Bounded correction" below).** As first written this claim was false, and the document
> contradicted itself by admitting as much in edge case 4. Only the fill instant and the attempt count came from the
> ledger; the horizon, window, attempt budget and retry spacing came from the **restarting process**. A restart under
> a wider policy did extend the contract — measured at 50 attempts where the original allowed 5. The binding is now
> real: the policy is resolved from the persisted fill and hash-verified before anything is scheduled or requested.

**The ledger states which invocation performed each attempt.** `Boundary.record_outcome` takes `process_identity`
and stamps every `pilot_outcome` with `{process_id, started_utc, inherited_position, basis}`. The runner's
`process_id` defaults to `"<session_id>@<start canonical µs>us"`; the entry point supplies it from the session start,
so a replay of the same restart names the same invocation.

**`process_id` is a logical invocation label and nothing more.** It is not an operating-system process identity, it
is not authenticated, and it is **not proof of exclusivity** — it does not prevent concurrent writers, and two runs
configured alike could mint the same label. The record says so in its own `basis` field rather than leaving a reader
to infer a guarantee that does not exist.

Asserted: a recovery run resolves on a later fresh arrival; the window and the attempt budget are the original
ones, not new ones; recovery cannot create a second fill, fee, outcome or discharge; stale and malformed quotes are
still refused during recovery; each outcome names its process and whether the position was inherited.

### The consequence that must be stated plainly

Under this contract **an exhausted position is exhausted for every later process too**. Before 003 each restart
spent one extra labelled attempt on it, which is how the entry-point recovery test eventually discharged two exhausted
positions on a fourth run. That path is gone: the superseded test now asserts that a later run with valid quotes makes
**no attempt** on them (`outcomes == []`) and they remain explicit obligations with retained exposure across every
subsequent run and are reported as foreign by other sessions. How an exhausted position is eventually discharged is a
policy decision I have not taken; see "Remaining recovery edge cases".

## 2. Arrival-to-quote provenance

**Reproduced.** Two observations sharing one provider timestamp could not be told apart in the outcome record, and
the arrival trace recorded only the notification id, with nothing binding it to the quote the boundary was served.

**Repaired.** The quote-adapter contract (`records.validate_quote`) carries optional `observation_id` and
`available_epoch` and always states `identity_basis`: `ADAPTER_SUPPLIED_UNVERIFIED` when the source gave an identity,
`NOT_SUPPLIED` when it did not. **Nothing is invented for a legacy adapter.** An `available_epoch` earlier than the
quote's own timestamp is refused, and the boundary separately refuses one later than receipt (see the correction
below). The outcome's `exit_quote_observed` persists all three fields.

Every arrival-triggered attempt in the lifecycle trace records `arrival_observation_id`, `quote_observation_id`,
`request_epoch`, `receipt_epoch`, `quote_available_epoch` and `same_observation`, with a note that the arrival only woke the
scheduler; the quote the boundary was served is identified separately and need not be the waking observation. The
non-matching case is tested (a second observation available at the same instant is what gets served), the matching
case is tested, and a quote with no identity is recorded as unidentified rather than faked.

## 3. Deterministic coalescing

**Reproduced.** The coalesced representative was the last id in input order and the id list was truncated after
eight, so permuting the feed changed the trace and evidence was elided.

**Repaired.** The representative is the canonical **minimum** id (`representative_rule: CANONICAL_MIN_ID`); the
complete set is carried sorted and **never truncated**; `coalesced_ids_digest` is `sha256` over the sorted set
serialised compactly; `n_coalesced` is recorded; `input_order` is preserved as the one declared ordering field.
Groups iterate in `(instant, contract)` order. Tests permute a five-id feed three ways and assert the same
representative and digest, carry forty ids intact, and show the lifecycle event stream is byte-identical apart from
`input_order`.

## Carried-forward acceptance, re-asserted

| case | result |
|---|---|
| 127 ms fixture: resolves under V2, fails under V1 spending all five attempts | holds |
| phase sweep across the full 60 s period | holds |
| no observation is served before its recorded availability | holds |
| 5 attempts, 120 s window, 15.0 s freshness, V1 hash pinned, suppression disabled | unchanged |

## Superseded tests

- `tests/test_exit_scheduling_002_repair.py::TestRecoveryIsACarriedForwardLimitation` — asserted the limitation;
  now asserts the repaired behaviour on the same fixture, plus process attribution.
- `tests/test_options_pilot_entrypoint.py::test_f6_lifecycle_recovery_through_the_entry_point` — runs 2 to 6
  rewritten for the new contract, including the exhausted-stays-exhausted consequence above.

`session.attempt_exits` still contains a `recovery=True` branch producing `UNRESOLVED_AFTER_RECOVERY_ATTEMPT`. No
caller passes `recovery=True` and the lifecycle no longer uses it; it is left in place as the legacy pre-lifecycle
driver rather than changed in this brick.

## Test fixture corrections made while writing this

Two of my reproducers initially failed for fixture reasons, not scheduler reasons, and were corrected: the synthetic
feed tie-broke same-instant snapshots on input order (now on identity), and the provenance test's ids happened to
make the waking observation the one served under the canonical-minimum rule (ids renamed so the case is what its
docstring says).

## Results

| suite | result |
|---|---|
| `tests/test_exit_scheduling_003.py` at base `16513b0` | 14 failed, 14 passed |
| `tests/test_exit_scheduling_003.py` after | 28 passed |
| three exit-scheduling suites together (002, 002-repair, 003) | 101 passed |
| eleven lifecycle/entry-point/accounting/execution suites | 308 passed, 1 skipped (one 002 assertion on the arrival record's `observation_id` field failed once; the field is retained alongside the new pair, then all pass) |
| five suites touching the quote contract (`validate_quote` / `quote_observed`) | 196 passed |

## Remaining recovery edge cases (not addressed)

1. **Discharge of an exhausted position.** Nothing will ever attempt it again. The operator needs a named,
   authorised route (a separate labelled policy or manual instruction), and it must not be a silent budget reset.
2. **A restart after the window closed but before `pilot_exit_exhausted` was written.** The inherited position has
   remaining budget but no remaining window; it will be recorded exhausted by the new process on its first service.
   Correct under the contract, but the exhaustion record is then stamped by a process that never attempted it.
3. **Two live processes on one ledger.** Attribution makes the overlap visible; it does not prevent it. Both would
   service the same obligation. Single-writer discipline remains the guard.
4. ~~**A restarted process with a different exit policy.**~~ **Closed by the bounded correction below.** The policy
   is now resolved from the persisted fill and hash-verified; a restarting process never substitutes its own.
5. **`session.attempt_exits` legacy branch** as noted above.

---

# Bounded correction (2026-09-12)

Base `b5b91f285a64be30bdbf17d03736fce9f20695e1`. Three source-review findings, **all three correct and all three
reproduced before any code changed**: `tests/test_exit_scheduling_003_correction.py` ran **17 failed, 6 passed** at
`b5b91f2` and **23 passed** after. Synthetic only; the recorded driver is still neither wired nor run.

## C1. The original policy binds — it did not before

**Reproduced, and worse than the review could see from source.** Opened under V1 (5 attempts, 120 s) and restarted
under a 50-attempt / 600 s policy, the position was attempted **50 times**. `_service_exit` and `record_outcome`
both took `pol = bd.exit_policy`: the fill instant and the attempt count came from the ledger, everything that
defines the contract came from the restarting process.

**Repaired.** `exit_policy.resolve_for_fill()` resolves a position's contract from the persisted evidence — the
fill's `exit_schedule.policy_hash`, with the intent's `pins.exit_policy_hash` as the pre-`exit_schedule` fallback
and as a cross-check — and every servicing path (`Boundary.record_outcome`, `LifecycleRunner._service_exit`,
`_on_exit_arrival`, `_reconcile`, and the legacy `session.attempt_exits`) asks it **before** scheduling anything or
requesting any quote.

Resolution is **by hash, never by name**, against three evidence sources, each verified by recomputing the
candidate's hash from its own frozen fields:

| source | when it is used |
|---|---|
| `PROCESS_CONFIGURED_POLICY` | the running process's own policy, **only** when its hash matches the persisted one |
| `FROZEN_POLICY_REGISTRY` | a policy this build ships, when its hash matches |
| — | refuse by name; the contract is not approximated |

Because the hash is recomputed rather than looked up, a policy whose definition was edited since the fill fails to
match and is named `EXIT_POLICY_DEFINITION_CHANGED`. The persisted deadlines are also re-derived from the resolved
policy and the commit instant; a mismatch is `EXIT_POLICY_SCHEDULE_INCOHERENT`. Fill and intent evidence that
disagree is `EXIT_POLICY_EVIDENCE_CONFLICT`, and neither is preferred.

**An unresolvable contract is an explicit unresolved obligation, not an exhaustion.** No quote is requested, no
attempt is consumed, no `pilot_exit_exhausted` is written, exposure is retained, and the entry carries
`final: UNSERVICEABLE_EXIT_POLICY_UNRESOLVED` with the named `policy_problem`. Legacy records without sufficient
policy evidence take exactly this path (`EXIT_POLICY_EVIDENCE_MISSING`, naming both fields it looked for).

Arrival triggering is now a property of the **position's** policy, not the process's: a V2-opened position resolves
on arrival even under a V1-configured restart, and a V1-opened position is not upgraded by a V2 process. Both
directions are tested on the same 127 ms geometry.

Every attempt records which contract governed it and how that was established: `policy_id`, `policy_hash`,
`binding: ORIGINAL_POLICY_OF_RECORD`, `resolved_from`, `process_policy_id` and
`process_policy_matches_original`. The run report's `exit_policy` is now explicitly labelled
`PROCESS_CONFIGURED_POLICY` — the invocation's configuration, which governs only the positions whose hash it
matches.

## C2. Request-time accuracy

**Reproduced and quantified.** With a provider that takes 250 ms to answer, the arrival trace recorded a request
instant of `…925.25` for a request that happened at `…925.0` — it read the clock *after* `_service_exit` returned,
i.e. after the provider call and after persistence. The true instants were already on the outcome record.

**Repaired.** The trace carries the boundary's own persisted `exit_quote_request_epoch` and
`exit_quote_receipt_epoch`, with `timing_basis` saying where they came from. `remaining_window_s` is now measured at
the request it describes rather than at some later moment. Tests assert the trace and the outcome agree **exactly**,
that request precedes receipt, and that the gap equals the fixture's injected latency.

## C3. Availability enforcement

**Reproduced, with an economic consequence.** A quote carrying a fresh provider timestamp and an `available_epoch`
five seconds in the future **resolved a position and produced a $472.00 exit cashflow**. `validate_quote` checked
only that availability was not before the quote's own timestamp; nothing checked it against receipt.

**Repaired, with the distinction the review drew.** The law is **availability ≤ receipt**, enforced at the boundary,
which is the only place that knows both. Availability strictly between request and receipt is **permitted** and
tested — a live request can legitimately be served a quote that became available while it was in flight — and
availability exactly at receipt is permitted. A violation is `EXIT_QUOTE_AVAILABLE_AFTER_RECEIPT`: NOT_ESTIMABLE,
no discharge, the position remains an obligation.

`validate_quote` deliberately does **not** impose an availability-before-request rule: it has no request instant and
must not invent one. It carries the value for the boundary to judge. Missing availability stays unknown and is never
manufactured. One assertion in `tests/test_exit_scheduling_003.py` had itself encoded the over-strict
availability ≤ *request* rule; it now asserts availability ≤ *receipt*.

**Recorded as-of lookup is a separate gate and stays separate.** `replay.most_recent_available()` enforces the
declared lookup instant, returns the most recent record available at or before it, and refuses a datum with no
recorded availability rather than assuming one. Tested here so the two semantics cannot be conflated.

## Results

| suite | result |
|---|---|
| `tests/test_exit_scheduling_003_correction.py` at base `b5b91f2` | **17 failed, 6 passed** |
| `tests/test_exit_scheduling_003_correction.py` after | **23 passed** |
| with `tests/test_exit_scheduling_003.py` | 51 passed |
| affected suites together | see the report accompanying the candidate |

## Not done here, deliberately

- **No exhausted-position rescue route.** Keeping the original experiment's budget spent is the correct behaviour.
  Eventual handling needs a separate recovery policy with its own records and its own authority; it must not
  rewrite the original experiment's result or manufacture a fill. Nothing in this correction moves toward it.
- **Recorded wiring is not started.**
- **`session.attempt_exits`** still carries the legacy `recovery=True` branch producing
  `UNRESOLVED_AFTER_RECOVERY_ATTEMPT`; no caller passes it. It now binds to the original policy like every other
  path, but the dead branch is left rather than changed in a bounded correction.
