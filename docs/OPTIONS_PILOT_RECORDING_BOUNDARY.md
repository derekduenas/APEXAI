# OPTIONS-PILOT-001 r4 — the recording boundary, repaired and integrated

**Prospective paper only. No feed adapter, no broker, no orders, no capital,
no service change.** The maintenance block on `apex-options-paper.service`
stays in place; the deployed release is untouched. This is the review
candidate for the brick "REPAIR THE RECORDING BOUNDARY AND PROVE THE REAL
SESSION INTEGRATION" plus the bounded r3 repair pass (six findings against
`48fde2d1`, §9) and the r4 pass (four findings against `0c23f702`, §10).
Branch `options-pilot-001`, built on `6022a187`.

## 0. Reproduced failures (before the repair)

`repro_old_boundary.py` was run against the **old** package at `6022a187`
(2eaab8f6 boundary) in the pilot worktree before any new file was shipped.
Output, verbatim (`docs/evidence/repro_old_boundary_OUTPUT_6022a187.json`):

| # | Finding | Old behaviour |
|---|---|---|
| F1 | NaN provider timestamp | **FILLED**, and the literal `NaN` reached the ledger line |
| F2 | caller-supplied `risk={"approved": True}` | **FILLED** (self-attestation was authorization) |
| F3 | malformed instant `"2026-09-10 25:99:00Z"` (ends with Z) | **FILLED** (string check) |
| F4 | provider stamps at request, takes 20 s to deliver | **FILLED**, `why: null` (clock read before the quote) |
| F5 | six workers past the duplicate check on a barrier | **6 fills on disk, 0 refused** |
| F6 | `ask_size=True` | **FILLED** (`True < 1` is False) |
| F7 | seq 1 altered and re-hashed, seq 2 verified | **verified** (one record, not its history) |

Each is now an acceptance test (`test_reproduced_old_defects_are_now_refused`
plus the parametrised quote/forecast cases); all refuse.

## 1. Exact changes and contract mapping

New/rewritten in `apex/options_pilot/` (additive package; nothing outside it
changed except the one seam in the script):

| File | Role |
|---|---|
| `clock.py` (new) | causal clock contract: `parse_utc` (tz-aware only), `to_utc_string`, `check_reading`, `Clock(now_fn)`; field meanings documented |
| `records.py` (rewritten) | strict contracts: finite/bool rejection (`is_real`, `is_exact_int`), causal forecast fields, `validate_quote` (QUOTE_CONTRACT_V1), `validate_intent` with `signal_used`, session identity, `HORIZON_RELATIONSHIP`, `labels_for(provenance)`, `canonical_json` with `allow_nan=False` |
| `ledger.py` (rewritten) | `verify_chain`, `verify_receipt(chain=True)`, `transaction()` on `<path>.txn.lock`, `commit_once(txn_id)` idempotent transition with lost-ack reconciliation; recipe and threat boundary in the module docstring |
| `risk_gate.py` (new) | `RiskAuthority`, intent-bound `binding_hash`, `verify_approval`, `ProductionRiskAuthority` (refuses: integration is the next brick), `SyntheticRiskAuthority` (harness token only) |
| `boundary.py` (rewritten) | `Boundary` class: forecast → risk-bound intent → history re-verification → quote → atomic fill → outcome; freshness after receipt; expiry; TRADE/WAIT/REFUSE; refusal persistence reported |
| `session.py` (rewritten) | stable `scan_id`, `next_seq`, duplicate-scan detection, one `pilot_decision` per scan, `resume` policy, `close_session` |
| `synthetic_harness.py` (new) | controlled clock, synthetic-parameter forecast provider (`forecast_from_params`), quote knobs (age/size/fail/slow/override), synthetic risk authority |
| `entrypoint.py` (new) | `route(args)`, `ProductionSources` (refusing), `run_pilot`, `run_from_args` |
| `scripts/options_paper_session.py` | `build_parser()` split out; `--pilot-boundary` (default off), `--pilot-synthetic-fixture`, `--pilot-session-id`, `--pilot-release`; `main(argv=None, *, pilot_sources=None)` routes to the pilot before pedigree/heartbeat/legacy loop. `_scan_symbol`, `resolve_open` and everything below the seam are byte-identical. |

Contract → implementation → test:

| Item | Implementation | Tests |
|---|---|---|
| 1 forecast/artifact claims | inventory in `docs/OPTIONS_PILOT_ARTIFACT_INVENTORY.md`; EXP-002 wording corrected there and in the audit; provider contract proven with `SYNTHETIC:`-digested params; `drives_expression_selection: false`; `signal_used` persisted and checked against the forecast label; hold-horizon extrapolation refused | `test_forecast_meaning_is_explicit_and_does_not_drive_selection`, `test_hold_horizon_extrapolation_is_refused` |
| 2 causal clock | every instant parsed (`ClockRefused` on naive/malformed/non-string/non-finite); reference, target_end (= reference + 900 s exactly), input_event ≤ reference, event ≤ available ≤ cutoff ≤ created ≤ clock; persisted, expiry, quote_request/receipt, provider ts (meaning recorded); one timeline (T0 = 2026-09-10T00:26:40Z for fixture clock and forecast); freshness from the reading **after** receipt; slow provider test; `order_proof` on every fill; `QUOTE_ELIGIBILITY_V2` declared | 21 parametrised forecast refusals, `test_the_fixture_clock_and_the_forecast_share_one_timeline`, `test_clock_readings_and_timestamps_reject_bool_nan_inf`, `test_quote_timestamp_semantics…`, `test_freshness_is_measured_after_receipt…`, `test_reproduced…` (d) |
| 3 finite values / strict JSON | `_real`/`_int` refuse bool, NaN, ±inf, strings; `canonical_json(allow_nan=False)`; `append_with_receipt` refuses non-strict entries before `chain_append`; quote contract documented; single snapshot timestamp semantics | 14 parametrised malformed-quote cases through the session path, `test_boolean_quote_size_is_not_a_size`, `test_strict_serialization_refuses_nan_before_anything_lands`, `test_non_dict_and_failing_providers_fail_closed` |
| 4 verify history | `verify_chain` (prev_hash links + per-record hash); `verify_receipt` verifies 1..N; execute re-verifies intent **and** its forecast (hash, id, symbol, session, scan, horizon, signal/right/action/qty, risk binding); recipe documented; threat boundary stated and **tested as a limit** | `test_an_altered_predecessor_breaks_the_chain…`, `test_intent_history_is_reverified_at_execution`, `test_state_canonicalization_recipe…`, `test_threat_boundary_a_consistent_rewrite_is_not_detected` |
| 5 atomic idempotency | `transaction()` (thread lock + flock on `.txn.lock`) spans read-check-append; `commit_once(txn_id)`; ids: `scan_id = session:seq:sym`, `forecast_id`/`intent_id`/`fill_id` sha-derived; duplicate scan → REFUSE; duplicate delivery → the **same receipt back** (reconciled, no quote, no append); crash before commit → resume fills once; crash after fsync/before ack → reconciled; resume retires expired/closed/other-release/other-session/stale-risk with terminal records; fsync retained via `chain_append` | `test_concurrent_workers_cannot_fill_the_same_intent_twice` (6 threads, barrier: 1 fill, 5 reconciled), `test_concurrent_intents_cannot_consume_one_forecast_twice` (5 threads, distinct contracts: 1 intent, 4 refused), `test_crash_before_durable_commit…`, `test_crash_after_durable_commit_reconciles_the_lost_ack`, `test_resume_policy_retires_stale_intents…`, `test_duplicate_delivery_and_duplicate_scan…`, `test_fsync_durability_is_retained`, `test_next_seq_survives_restart` |
| 6 risk | `ProductionRiskAuthority.approve` raises `RiskIntegrationMissing`; any approval must carry `risk_provenance`, `authority_id`, a recomputed `binding_hash` and a finite `certified_max_loss`; a bare `approved: True` is refused as self-attestation; approval re-verified from disk at execution and on resume | `test_risk_self_attestation_is_refused_and_production_authority_refuses` (5 sub-cases), entry-point `test_production_risk_authority_refuses_even_if_a_forecast_is_supplied` |
| 7 real session path | seam + `entrypoint.py`; `fenced` fixture makes `_scan_symbol`, `seal_before_card`, `simulate_entry`, `build_pedigree`, `Heartbeat`, `observe` raise if touched; provenance vs execution mode on every record and in the report; provider failures fail closed; refusal-persistence reported in decisions | `tests/test_options_pilot_entrypoint.py` (8 tests) |
| 8 tests run | see §6 | |

## 2. Concurrency and restart evidence

- **Six workers, one intent**, all released by a barrier *inside* the quote
  provider (so all six passed the pre-quote check): one `pilot_fill` on disk,
  six receipts pointing at the same seq, five marked `reconciled`, zero
  refusals, chain verifies.
- **Five workers, one forecast, five different contracts**, barrier inside
  the risk authority: one `pilot_intent`, four `FORECAST_ALREADY_CONSUMED`
  refusals persisted.
- **Crash before commit** (provider raises `KeyboardInterrupt`): ledger ends
  at `pilot_intent`; resume executes once; second resume does nothing.
- **Crash after fsync, before ack** (`append_with_receipt` raises after the
  write on the fill): one fill on disk; redelivery returns the reconciled
  receipt, no second quote; resume has nothing to do.
- **Resume policy** over five unfinished intents on one ledger: this session
  unexpired → EXECUTED; closed session → CANCELLED (SESSION_CLOSED); other
  release → CANCELLED (WRONG_RELEASE); other open session → CANCELLED
  (STALE_AUTHORIZATION); this session past TTL → EXPIRED. One quote call in
  total; nothing left unfinished; a second resume is a no-op.
- **Restart through the entry point**: first run dies in the provider; the
  second run with the same session id reconciles the session-open record,
  resumes the intent (FILLED), and continues at seq 0002; a new session id
  starts at 0001.

## 3. Artifact inventory and limits

`docs/OPTIONS_PILOT_ARTIFACT_INVENTORY.md`. In one line: complete for
inference (all constants and the feature recipe are saved), **not** complete
for a live adapter (live-bar equivalence unproven, no reviewed adapter, model
specification not statistically established). The distribution is recorded
and does not choose the expression; the 15-minute horizon is not stretched to
the close.

## 4. Synthetic record examples

Produced by the CLI seam itself:

```
scripts/options_paper_session.py --ledger …/synthetic_ledger.jsonl --out …/report.json \
  --symbols SPY --dry-run --pilot-boundary --pilot-synthetic-fixture \
  --pilot-session-id SYN-EXAMPLE-1 --pilot-release example
```

gives seven records — `pilot_session_open`, `pilot_forecast`, `pilot_intent`,
`pilot_fill`, `pilot_decision`, `pilot_outcome`, `pilot_session_close` — every
one carrying `evidence_class: PROSPECTIVE_PAPER`, `decision_power: NONE_PAPER`,
`data_provenance: SYNTHETIC_FIXTURE`, `synthetic: true`,
`execution_mode: PROSPECTIVE_ORCHESTRATION`. Abridged:

```json
{"kind":"pilot_forecast","scan_id":"SYN-EXAMPLE-1:0001:SPY","forecast_id":"4f6b781695b9088a5b773337",
 "family":"STUDENT_T","location":2.5238e-05,"scale":3.0e-04,"nu":6.0,
 "model_id":"SYNTHETIC_FIXTURE_MODEL","artifact_digest":"SYNTHETIC:0bcead7c…","params_hash":"SYNTHETIC:0bcead7c4ced138d",
 "reference_time_utc":"2026-09-10T00:25:00.000000Z","target_end_utc":"2026-09-10T00:40:00.000000Z",
 "input_event_time_utc":"2026-09-10T00:25:00.000000Z","input_available_utc":"2026-09-10T00:26:00.000000Z",
 "input_cutoff_utc":"2026-09-10T00:26:00.000000Z","created_utc":"2026-09-10T00:26:40.000000Z",
 "drives_expression_selection":false,"direction_signal":"LONG","inputs":{"ret_1":1e-4,"ret_5":-2e-4,"rv_30":1e-4},
 "validation_status":"SYNTHETIC_FIXTURE: no validation claim","txn_id":"forecast:4f6b781695b9088a5b773337"}
{"kind":"pilot_intent","intent_id":"90651498f8a1cfa33fff6a49","expression":"LONG_CALL","signal_used":"LONG",
 "contract_id":"SPY|2026-10-09|645.0|CALL","quantity":1,"expiry_utc":"2026-09-10T00:28:40.000000Z",
 "forecast_ref":{"seq":2,"entry_hash":"1557…","forecast_hash":"16ad…","forecast_id":"4f6b781695b9088a5b773337"},
 "risk":{"approved":true,"authority_id":"SYNTHETIC_FIXTURE_AUTHORITY","binding_hash":"bb4e…",
         "certified_max_loss":250.0,"risk_provenance":"SYNTHETIC_FIXTURE"},"txn_id":"intent:90651498f8a1cfa33fff6a49"}
{"kind":"pilot_fill","fill_id":"347d45cc997b282c46a435de","decision":"TRADE","status":"FILLED","price":2.5,"net_debit":250.0,
 "quote_request_utc":"2026-09-10T00:26:40.000000Z","quote_receipt_utc":"2026-09-10T00:26:40.000000Z",
 "quote_age_at_receipt_s":1.0,"quote_ts_minus_intent_persisted_s":-1.0,"provider_latency_s":0.0,
 "quote_observed":{"ask":2.5,"ask_size":12,"bid":2.4,"bid_size":9,"timestamp_epoch":1788999999.0,
                   "timestamp_meaning":"PROVIDER_SNAPSHOT: one asserted timestamp for both sides; …"},
 "eligibility_policy":"QUOTE_ELIGIBILITY_V2: …","order_proof":"ledger seq proves intent persisted BEFORE the quote was requested; it does NOT prove …"}
{"kind":"pilot_decision","scan_id":"SYN-EXAMPLE-1:0001:SPY","decision":"TRADE","forecast_id":"4f6b…","intent_id":"9065…","fill_id":"347d…"}
```

The same command **without** `--pilot-synthetic-fixture` (production route,
`data_provenance: LIVE_FEED`, `ProductionRiskAuthority`) produces
`pilot_session_open` → `pilot_refusal` (`FORECAST_PROVIDER_FAILED:
ProviderNotIntegrated: NO_REVIEWED_INFERENCE_ADAPTER …`) → `pilot_decision`
(REFUSE, `refusal_persisted: true`) → `pilot_session_close`. No forecast, no
intent, no fill. That is the honest state of the production pilot.

## 5. Protected-surface changes

- Governed source set for the alpha-research path (`RELEVANT_SOURCE_PATHS`:
  `apex/world_model`, `apex/governance/chain_ledger.py`,
  `apex/intraday/sessions.py`, `scripts/alpha_exp_real_execute.py`): **no file
  changed**.
- `apex/governance/chain_ledger.py`: untouched; the pilot layers its
  `.txn.lock` transaction *around* `chain_append` and keeps its fsync.
- `scripts/options_paper_session.py`: **one seam** — argparse moved into
  `build_parser()`, four new flags (all default off), and a routing block at
  the top of `main()`; `main` gained `argv`/`pilot_sources` parameters. The
  legacy loop, `_scan_symbol`, `resolve_open`, outbox emission and the replay
  import are unchanged. With the flag off the legacy path runs exactly as
  before (`test_the_seam_is_off_by_default…`).
- `apex/predators/options/*`, `apex/organism/*`, `apex/ops/*`: untouched.
- Signing keys, installed admissions, frozen registrations, prior results,
  the deployed release `/opt/apex/current`, the maintenance block: untouched.

## 6. What works through the entry point, and test runs

Through `scripts/options_paper_session.main --pilot-boundary`: session open
(idempotent), resume, per-symbol scan through the boundary, TRADE/WAIT/REFUSE
decisions with stable ids, outcome resolution for TRADE fills, session close,
a strict-JSON report naming route, provenance, execution mode and risk
authority. The legacy geometry path is unreachable on this route (fenced in
tests). Provider failures fail closed as persisted refusals.

Runs, all contained (`systemd-run … MemoryMax=1400M`, worktree
`/apex-data/tmp/pilot_wt`):

| Set | Result |
|---|---|
| `tests/test_options_pilot_boundary.py` + `tests/test_options_pilot_entrypoint.py` | **80 passed** (72 + 8) |
| `tests/test_options_*.py` (which the glob makes include the two pilot files), `test_ledger_concurrency.py`, `test_live_book.py`, outbox users (`test_catalyst_commissioning.py`, `test_runtime_autonomy.py`) | **449 passed** = 80 pilot + 369 pre-existing options/ledger/outbox tests, 0 failed |

## 7. The old mislabelled records — annotated, not rewritten

All 19 `options_live_card` and 19 `options_outcome` records in
`/apex-data/core/options_live_ledger.jsonl` (sessions 2026-08-24 → 2026-09-04)
carry `evidence_class: HISTORICAL_DEVELOPMENT_REPLAY` / `decision_power:
NONE_REPLAY` because the script imports `seal_before_card` from the replay
module. Those sessions were prospective paper in fact; the labels are wrong.
They are **preserved as written** — hash-chained records are not edited — and
this section is the annotation. Nothing produced by `apex/options_pilot` can
carry those labels (`assert_prospective`), and the legacy import is left in
place so the annotation stays true of the old path.

## 8. What is NOT in this brick (the next execution-accounting brick)

- Risk integration: `risk_certificate.certify()` + `risk_kernel.check()`
  (per-trade $500, aggregate $1,500, same-underlying $600, family $1,000,
  session drawdown halt $1,000), reservations against open intents, release
  on expiry/cancel. Until then the production route cannot approve an intent.
- A reviewed live-bar inference adapter for the retained artifact, with a
  demonstration that live features equal the historical recipe.
- A reviewed live quote adapter for the pilot path (`NO_QUOTE_ADAPTER`).
- Fees, re-quoting at T+Δ, exit-quote capture windows, position accounting,
  reconciliation against an external record.
- GARCH, regime models, Multiverse, a dashboard.
- Lifting the maintenance block; any service start; any broker order.


## 9. r3 — the six findings against `48fde2d1`, repaired

The reviewer reproduced six cases in which a path returned or committed a
record without establishing the state it claimed. Each is now a negative
acceptance test (`test_f1_…` … `test_f6_…` in the boundary file; `test_f6_…`
in the entry-point file), and the r2 tests are unchanged except where the
old expectation was itself the defect (noted below).

| # | Finding | Repair | Acceptance test |
|---|---|---|---|
| 1 | A synthetic pending intent resumed through a `ProductionRiskAuthority` / `LIVE_FEED` boundary returned FILLED | `RiskAuthority.accepts(approval)`: the **active** authority must honour a stored approval (production honours none in this brick; synthetic honours only its own). `Boundary.authorization_problem` also requires the intent's `data_provenance` to equal the boundary's. Checked in `_history_problem` (before the quote AND inside the commit transaction) and in `session.resume` (which cancels with `STALE_AUTHORIZATION: …`). Outcomes check provenance too. | `test_f1_production_authority_and_provenance_are_checked_on_execution_and_resume` — direct execution refuses, resume cancels, no quote is ever requested; both mismatches (provenance; authority) and the reverse (LIVE intent on a synthetic boundary) |
| 2 | Quote callback cancelled the intent; ledger then read intent → cancellation → fill | The fill's `build(rows)` runs under the transaction lock from one snapshot and re-checks: no fill, **no expiry/cancellation record**, session not closed, intent + forecast history and authorization re-verified, whole chain verifies, clock ≤ expiry. `expire_intent` is symmetric: its build refuses if a fill or terminal record exists (`FILL_EXISTS`, `INTENT_ALREADY_TERMINAL`). Expiry crossed while the quote was in flight now yields a terminal record + refusal, never a fill record (an r2 test expected an UNFILLED fill there; that expectation was the defect and was changed). `COMMIT_CHECKS` is stamped on every fill. | `test_f2_cancellation_inside_the_quote_window_wins_and_no_fill_follows` (cancel-in-callback → `INTENT_TERMINAL_AT_COMMIT`; fill-then-cancel → `FILL_EXISTS`; close-in-callback → `SESSION_CLOSED_AT_COMMIT`; late commit clock), `test_f2_concurrent_cancel_and_execute_are_mutually_exclusive` (two threads, barrier, both orderings forced: exactly one of {fill, cancelled} exists, the loser's refusal is persisted) |
| 3 | A fill altered on disk (`net_debit`, hash untouched) was returned as `reconciled: true, FILLED` | `_reconcile_fill` verifies the existing record, the **whole** chain and its references (intent seq/hash, intent_id, contract_id, session) before returning it; `commit_once` reconciliation verifies the whole chain, not just the prefix (a consistently re-hashed record breaks its successor's link); outcome reconciliation likewise | `test_f3_reconciliation_verifies_the_existing_fill_and_its_chain` (hash untouched → `RECONCILE_ALTERED`, no quote; `commit_once` refuses; re-hashed with a successor → refused) |
| 4 | Duplicate scan returned REFUSE while its receipt pointed at the persisted TRADE decision | A scan_id with a persisted decision returns **that decision's payload** (verified), flagged `duplicate_delivery`/`reconciled`; the delivery is recorded as a separate `pilot_duplicate_delivery` record referencing the decision, never as a decision. A scan_id with records but no decision (interrupted) is refused `INCOMPLETE_SCAN`, and that refusal is its first and only decision. `_decision` returns the on-disk payload whenever `commit_once` reconciles. | `test_f4_duplicate_scan_returns_the_persisted_decision_not_a_new_story`, updated `test_duplicate_delivery_and_duplicate_scan…` |
| 5 | A forecast whose target ended at 23:40 was accepted at 00:26:40 and traded | `FORECAST_ELIGIBILITY_V1` (stamped on every forecast): `created ≤ clock`; `clock < target_end`; `clock − input_cutoff ≤ 120 s`. Re-checked at intent creation (`FORECAST_TARGET_ENDED_BEFORE_INTENT`) and at fill commit (`FORECAST_TARGET_ENDED_BEFORE_EXECUTION`, inside `_history_problem`). | `test_f5_a_forecast_about_a_completed_target_is_not_prospective_evidence` (target ended → refused; stale cutoff → refused; persisted-in-time forecast cannot back an intent after its target ends) |
| 6 | `run_pilot` resumed and filled an intent, returned no outcomes, closed with an empty unfinished list | `session.unresolved_fills` / `recover_positions` (own vs foreign); `run_pilot` recovers every unresolved own position from disk (including ones resume just created), attempts resolution, and reports `recovered_positions`, `unresolved_positions`, `foreign_unresolved_positions`, `outstanding_obligations`, `completion`. `close_session` records `unresolved_fill_seqs_at_close` and `completion: CLOSED_CLEAN \| CLOSED_WITH_OUTSTANDING_OBLIGATIONS`; each close is a new numbered record. A run against an already-closed session is `RECOVERY_ONLY` (no new scans against a closed session). | `test_f6_unresolved_positions_are_recovered_reported_and_block_clean_completion`, entry-point `test_f6_lifecycle_recovery_through_the_entry_point` (run dies → resume fills → resolution fails → close says outstanding 2 → recovery-only run resolves both → CLOSED_CLEAN; a different session reports them as foreign and does not touch them), updated `test_restart_resumes…` (resumed fill is resolved) |

**Completion wording corrected:** a session close no longer implies completion
because every intent has a fill. `completion` is `CLOSED_CLEAN` only when there
is no unfinished intent and no unresolved position of that session; otherwise
`CLOSED_WITH_OUTSTANDING_OBLIGATIONS` with the seqs listed. Unresolved
positions are retained and reported; exit strategy and fees remain deferred.

Test runs for r3 (contained, same worktree): pilot boundary + entry point
**88 passed** (72 → 79 boundary, 8 → 9 entry point); `tests/test_options_*.py` +
`test_ledger_concurrency.py` + `test_live_book.py` + outbox users: **457 passed** =
88 pilot + 369 pre-existing, 0 failed.


## 10. r4 — the four remaining cases against `0c23f702`, repaired

| # | Finding | Repair | Acceptance test |
|---|---|---|---|
| 1 | Expiry between quote receipt and commit produced `INTENT_EXPIRED_AT_COMMIT` but **no terminal record**; the intent stayed unfinished | The fill's commit `build` now raises a typed refusal carrying the terminal kind for TIME-based failures (intent expiry → `pilot_intent_expired`; forecast target ended / cutoff stale → `pilot_intent_cancelled`). After the fill transaction refuses, `expire_intent` persists that transition in **its own** transaction, which re-checks that no fill and no terminal record exist (mutual exclusion preserved), then the refusal is persisted. Structural failures (`HISTORY_INVALID_AT_COMMIT`, `INTENT_TERMINAL_AT_COMMIT`, `SESSION_CLOSED_AT_COMMIT`) refuse without a terminal record, as before. | `test_r4_expiry_between_receipt_and_commit_persists_terminal` — clock advanced deterministically immediately before the fill's `commit_once`: ledger ends `pilot_intent_expired, pilot_refusal`, no fill, one quote call, `unfilled_intents == []`, resume is a no-op, a later delivery is `INTENT_TERMINAL`. The r2/r3 expiry test now also **requires** the terminal record. |
| 2 | A missing exit quote produced `NOT_ESTIMABLE`, then `CLOSED_CLEAN` with zero obligations; restart recovered nothing | Outcomes are **valuation attempts** (`attempt` n, `txn_id = outcome:<intent>:<n>`). Only `RESOLVED` and `NO_POSITION` carry `discharges_position: true`; `NOT_ESTIMABLE` (missing, stale, malformed, provider failure) is persisted as an attempt and the position **remains** an unresolved obligation. `unresolved_fills` counts only discharging outcomes; `recover_positions` carries `valuation_attempts` and `last_attempt_why`; once discharged, further calls reconcile to the discharging record (verified). | `test_r4_missing_or_stale_exit_keeps_the_position_outstanding` (provider `None` → attempt 1, close says outstanding; stale → attempt 2; restart recovers it with 2 attempts; valid exit → attempt 3 discharges, `CLOSED_CLEAN`; provider failure → attempt, still outstanding). Entry point: `test_f6_lifecycle_recovery_through_the_entry_point` rewritten to use the **actual provider** returning `None`, then a stale quote, across three restarts (2 → 2 → 0 outstanding, `close_number` 3), with a foreign session's obligation reported and untouched. |
| 3 | A valid fill retried after its forecast target ended returned `FORECAST_TARGET_ENDED_BEFORE_EXECUTION` instead of its receipt | `_history_problem(for_new_fill=False)` checks identity and integrity only (receipt, contract, session, release, provenance, forecast reference/agreement, content, stored binding). `execute_intent` reconciles an existing fill on that basis **first**; only a NEW fill requires `for_new_fill=True` (active authority, unexpired intent, forecast eligible now). | `test_r4_late_duplicate_delivery_reconciles_after_the_forecast_target_ended` (1000 s later: same receipt back, no quote, no new record; a different still-pending intent on the same clock is expired and refused) |
| 4 | A forecast with a 130 s-old input cutoff still filled | `_forecast_eligibility_problem` applies the **complete** policy (target in the future AND cutoff within 120 s) at intent creation (`FORECAST_STALE_BEFORE_INTENT`), before the quote, and inside the commit (`FORECAST_STALE_BEFORE_EXECUTION`, cancelling the intent). | `test_r4_forecast_freshness_is_rechecked_at_intent_and_at_commit` (a: at intent; b: before the quote, no quote requested, intent cancelled; c: fresh at the quote and 130 s old at the commit → cancelled, no fill) |

**Policy interplay made visible by the tests:** the intent TTL (120 s from
persistence) and forecast freshness (120 s from input cutoff) both bind at a
fill; whichever is tighter decides, and each names its own terminal record.
Tests that need the TTL to bind use a clock on a minute boundary so the
fixture forecast's cutoff equals its creation instant.

Test runs for r4 (contained, same worktree): pilot boundary + entry point
**92 passed** (83 boundary, 9 entry point); `tests/test_options_*.py` +
`test_ledger_concurrency.py` + `test_live_book.py` + outbox users:
**461 passed** = 92 pilot + 369 pre-existing, 0 failed.
