# RECORDED-OBSERVATION WIRING — the recorded route's observation feed for the shared V2 runner (2026-09-12)

Base `c37e60be8d158b506ac07f0b72bf5729c88f90fa`, branch `exit-scheduling-003`. **Synthetic acceptance only.** No
recorded collection was opened, no FLOW-VALIDATION rerun happened, no provider was called, no replay was
authorized, and no fee, limit, affordability, selection or deployment change was made.

## What was missing

`EXIT_POLICY_V2` services a due exit the moment a NEW observation for its contract becomes available. The runner
learns that from `observation_feed`. Production gets those notifications from the live feed; **the recorded route
had no way to produce them at all**, so a recorded run under V2 behaved exactly like V1 — arrival triggering was
built and unreachable. That is the gap this closes, and it closes nothing else.

## What was built

`apex/options_pilot/recorded_feed.py` — `RecordedQuoteSource`, which turns recorded chain snapshots into the two
things the runner needs, **from the same recording**:

- `observation_feed(contract_ids)` → `[(available_epoch, {observation_id, contract_id})]`
- `exit_quote_fn(contract)` → the quote from the currently visible snapshot, stamped with `observation_id` and
  `available_epoch` per the 003 adapter contract

Because both come from one source, a notification can never announce an observation the quote source would not
serve. A test asserts exactly that.

**Visibility reuses the existing gate.** `replay.most_recent_available` decides what is visible, on the recorded
receipt. No second path to the data, and nothing reaches past the clock.

**Identity is derived, not invented.** `observation_id = sha256(contract_id, canonical availability instant,
recorded quote fields)[:32]` — a pure function of persisted values, so a reviewer can recompute it from the ledger
and match an attempt back to the recording. It is **not** a provider-issued sequence number and does not claim to
be one.

**Refusals rather than repairs.** A row whose quote timestamp postdates its own recorded receipt is excluded and
named (`RECORDED_QUOTE_AFTER_ITS_OWN_RECEIPT`); a row with no timestamp is refused rather than defaulted.

The module reads no files, opens no socket, holds no credential, and names no collection — `ReplayAuthorization`
and the driver own all of that.

## Evidence — `tests/test_recorded_feed_wiring_001.py`, 24 tests, all through the real `LifecycleRunner`

| requirement | how it is shown |
|---|---|
| availability-based visibility | every served snapshot has `available <= asked_at`; every persisted quote has `available_epoch <= receipt` |
| observation identity | the outcome names the observation; the id is **recomputed from the ledger** and matched; identical quotes at different instants are different observations; the feed and the quote source agree by construction |
| arrival-triggered resolution | the 127 ms geometry resolves from the recording's own arrival, with `trigger = OBSERVATION_ARRIVAL` and the boundary's own request/receipt instants on the trace |
| a new receipt is not a fresh quote | a recorded arrival carrying a 40 s old quote is still refused as stale |
| unchanged V1 | the same recording under V1 spends five timer attempts and does not resolve; a feed supplied to a V1 position is recorded as `ARRIVAL_TRIGGER_NOT_ENABLED_BY_POLICY` with `is_attempt: False`; the V1 hash and limits are pinned |
| original-policy recovery | an inherited position is serviced from the recording under its own policy; a restart configured for 50 attempts / 600 s still gets 5 attempts inside 120 s |
| remaining-budget accounting | two attempts spent by one process, three by the next — five total, read from the ledger, not reset by the restart |
| no eligible quote → explicit unresolved exposure | five `NOT_ESTIMABLE` attempts each with its reason, `pilot_exit_exhausted` written, exposure retained, `CLOSED_WITH_OUTSTANDING_OBLIGATIONS`, cash identity holds |
| immutable run outputs | run directory claimed once; collision, duplicate artifact name and second terminal marker all refused; `feed_digest` names the inputs by content |
| reconstructible records | chain verified; the outcome carries request/receipt instants, observation identity, the bound original policy and the process label; the identity recomputes |

Two of my own assertions were wrong on first run and were corrected, not worked around: an instantaneous synthetic
provider makes request equal receipt (the strict inequality is proved under the slow-provider fixture in
`test_exit_scheduling_003_correction.py`), and the scheduling-note key is `reason`, not `note`.

| suite | result |
|---|---|
| `tests/test_recorded_feed_wiring_001.py` | **24 passed** |
| 12 affected suites together | **508 passed, 1 skipped, 0 failed** |

## Limitations

- **Not exercised on the recorded collection.** By scope. The driver still has to build normalised rows and hand
  them in; this module deliberately does not normalise vendor rows, so there is exactly one normalisation in the
  system (`pulse_options.sources.live_chain_rows`).
- **One contract row per snapshot in the fixtures.** Multi-contract snapshots are supported by construction
  (the feed emits one notification per contract per snapshot) but the fixtures here exercise a single contract.
- **A recorded rerun of FLOW-VALIDATION-001 is a separate grant** and was not performed.
