# OPTIONS-PILOT-001 — the forecast-and-intent recording boundary

**Synthetic fixtures only.** No feed, no broker, no orders, no capital, no
service change. The maintenance block on `apex-options-paper.service` stays in
place. The existing options stack is untouched: this brick is one new package,
`apex/options_pilot/`, plus its tests.

## The three findings, accepted and built in

1. **No manufactured forecast.** The forecast record is a *distribution* for
   the registered 15-minute log return at its native horizon, with explicit
   meaning fields. The identified frozen artifact is EXP-002's sealed result,
   `params_hash ca04fc6e713e1a5c` (registered L arm, shared `s* = 3.288`,
   `ν* = 6.384`) — a **well-specified** forecast from a **NOT_SELECTED**
   experiment, carried as `validation_status: NOT_VALIDATED …; no edge claim`.
   A trend label is stored as `direction_signal` with
   `direction_signal_meaning: HEURISTIC …; not part of the forecast distribution`.
   The recorded meaning says in words: *NOT an expected directional move, NOT a
   hold-to-close forecast.* A 30-minute horizon, a "move to close" target, an
   unknown family, or a missing parameter hash is a **recorded refusal**.
2. **One deterministic rule, no "best option".** `expression_rule.py`:
   signal LONG → BUY one CALL, SHORT → BUY one PUT; nearest expiry with
   DTE ≥ 21; nearest-ATM strike; quantity 1, **filled or unfilled**. The intent
   carries `no_best_option_claim: true`. Breakeven ranking is not used.
3. **The seal check is not trusted.** `simulate_entry` accepts any 32+
   character string. The boundary verifies the persisted intent by **re-reading
   the ledger and recomputing its `entry_hash`** from the bytes on disk
   (`ledger.recompute_entry_hash`), comparing seq, kind, hash and contract
   identity. Every fill record says so:
   `seal_verification: "… simulate_entry's own 32-char check is NOT relied upon"`.

## Acceptance contract, item by item

| # | Contract | Implementation | Test(s) |
|---|---|---|---|
| 1 | Explicit forecast meaning: target, units, horizon, family, location, scale, ν, model/param hashes, input cutoff, creation time, persistence receipt; trend label a heuristic; missing/incompatible → recorded refusal | `records.validate_forecast` (12 required fields, family-specific ν, UTC checks, `created ≥ cutoff`); receipt from `ledger.append_with_receipt` | `test_forecast_meaning_is_explicit…`, 11 parametrised refusal cases, `test_missing_forecast_fields_refuse` |
| 2 | Enforced order: forecast → decision + risk-approved intent → **later** quote → fill → outcome; proven by append receipts and record identity, not caller timestamps or hash-shaped strings | `boundary.record_forecast → record_intent → execute_intent → record_outcome`; order proven by **ledger seq assigned on append and re-read**; `quote_fn` is called only after `verify_receipt` of the intent succeeds | `test_order_is_proven_by_ledger_sequence…` (seq strictly increasing, receipts re-read and re-hashed), `test_quote_is_requested_only_after_the_intent_is_on_disk` (the quote callback observes the intent already on disk and exactly `seq(intent)` records) |
| 3 | Failed persistence prevents entry; unknown/altered/mismatched references refuse; restart and duplicate delivery cannot fill twice | `PERSISTENCE_FAILED` / `PERSISTENCE_UNPROVEN` (append reported success but bytes absent); `RECEIPT_MALFORMED / SEQ_UNKNOWN / FOREIGN_LEDGER / RECORD_HASH_MISMATCH / RECORD_ALTERED / KIND_MISMATCH`; `FORECAST_HASH_MISMATCH`, `FORECAST_ALREADY_CONSUMED`; `DUPLICATE_DELIVERY` scans the ledger for an existing fill of that intent **before** anything happens; `session.resume` rebuilds receipts **from disk** and fills exactly once | `test_failed_persistence_prevents_entry` (OSError on append → nothing lands; read-only directory → no file), `test_persistence_is_proven_by_reread_not_by_return_value`, `test_a_hash_shaped_string_is_not_a_receipt` (4 forgeries), `test_an_altered_forecast_on_disk_refuses_the_intent` (tampered field, kept hash → `RECORD_ALTERED`), `test_forecast_hash_mismatch_and_wrong_kind_refuse`, `test_crash_after_intent_then_restart_fills_exactly_once`, `test_duplicate_delivery_of_an_intent_cannot_fill_twice`, `test_a_forecast_cannot_back_two_intents` |
| 4 | Prospective labels on every new record; old mislabelled records preserved and annotated separately | every record carries `PROSPECTIVE_PAPER / NONE_PAPER / live_capital LOCKED / live_promotion_eligible false`; `records.assert_prospective` refuses any replay string in `evidence_class`, `decision_power` or `law` | `test_every_record_is_prospective_paper_and_never_replay` walks every record including refusals |
| 5 | Real session-path tests: write failure, wrong contract, wrong horizon, crash/restart | all of the above run through `session.scan` / `session.resume`; `CONTRACT_MISMATCH` on strike and on expiration → `UNFILLED`, recorded | `test_wrong_contract_at_execution_is_unfilled_and_recorded`, `test_rule_refusals_are_recorded_after_the_forecast` |
| — | **Audit correction: freshness per selected contract and side** | `boundary._quote_ok` checks the *selected* contract's identity and the *side to be crossed* (ASK on entry, BID on exit) against `MAX_SELECTED_QUOTE_AGE_S = 15`; a fresh quote elsewhere cannot mask it; future-dated quotes refuse | `test_freshness_is_checked_for_the_selected_contract_and_side` (16.0 s refuses, 14.9 s fills, −2 s refuses), `test_stale_exit_quote_is_not_estimable` |
| — | One-contract explicit filled/unfilled | `UNFILLED` with a named `why` (`NO_SIZE_AT_ASK`, `QUOTE_SIDE_MISSING`, stale, mismatch); outcome `NO_POSITION` for an unfilled intent; missing/stale exit → `NOT_ESTIMABLE`, never imputed; a second outcome for one fill → `DUPLICATE_OUTCOME` | `test_one_contract_is_filled_or_unfilled_explicitly`, `test_missing_exit_quote_is_not_estimable_never_imputed` |

**Tests:** `tests/test_options_pilot_boundary.py` — **31 passed** (0.6 s). The
existing options stack the pilot will reuse (`paper_execution`,
`live_session`, `live_book`) — **51 passed** at `/opt/apex-repo`, unchanged.

## The old mislabelled records — annotated, not rewritten

All 19 `options_live_card` and 19 `options_outcome` records in
`/apex-data/core/options_live_ledger.jsonl` (sessions 2026-08-24 → 2026-09-04)
carry `evidence_class: HISTORICAL_DEVELOPMENT_REPLAY`, `decision_power:
NONE_REPLAY` and the replay law text, because `scripts/options_paper_session.py`
imported `seal_before_card` from the replay module. Those sessions were
prospective paper in fact; the labels are wrong. They are **preserved as
written** — hash-chained records are not edited — and this note is the
annotation. Nothing produced by `apex/options_pilot` can carry those labels.

## What one honest fixture run proves, and what it does not

A fixture run shows the loop records a forecast, a risk-approved intent, a
later quote, a single fill and an outcome, in that order, each provable from
disk, with every refusal recorded. It does not show anything about feed
behaviour, quote cadence, fees, re-quoting, risk reservations, exits or
reconciliation — those are the **next execution brick**, as directed — and
nothing about edge.

## What is NOT in this brick

- Fees, re-quoting at T+Δ, risk reservations against the kernel's aggregate
  limits, exit-quote capture windows, reconciliation — **next brick**.
- Any live feed, any real forecast computation, any change to
  `scripts/options_paper_session.py` or to `simulate_entry`.
- Lifting the maintenance block.
