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
process opened, under the **original** policy's remaining window and remaining attempt budget, both read from the
ledger (the fill's committed instant and the outcomes already on disk). A restart therefore cannot extend either.
`recovered_seqs` survives only as a label.

**The ledger states which process performed each attempt.** `Boundary.record_outcome` takes `process_identity`
and stamps every `pilot_outcome` with `{process_id, started_utc, inherited_position}`. The runner's `process_id`
defaults to `"<session_id>@<start canonical µs>us"`; the entry point supplies it from the session start, so a replay
of the same restart names the same process.

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
quote's own timestamp is refused. The outcome's `exit_quote_observed` persists all three fields.

Every arrival-triggered attempt in the lifecycle trace records `arrival_observation_id`, `quote_observation_id`,
`request_epoch`, `quote_available_epoch` and `same_observation`, with a note that the arrival only woke the
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
4. **A restarted process with a different exit policy.** Attempts are made under `bd.exit_policy` of the new process;
   the window and budget come from that policy's schedule, not from a policy id persisted with the fill. The V1 hash
   pin makes drift detectable, not impossible.
5. **`session.attempt_exits` legacy branch** as noted above.
