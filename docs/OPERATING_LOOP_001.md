# OPERATING-LOOP-001 — the reliable operating loop every instrument will share (2026-09-12)

Built on `trace-replay-001` at `1b86541`, on branch `operating-loop-001`, in a dedicated worktree with an
interpreter outside it. No provider was contacted, nothing was fitted, no limit, universe or selection rule was
changed, no fee was authorized, nothing was deployed and no order exists. **Synthetic inputs only.**

## What was wrong, in one paragraph

The twelve-scan demonstration produced eleven consecutive `KERNEL_REFUSED` decisions. The kernel was right every
time it was asked; the driver never asked. It ran all twelve scans, then set `rec.t = t0 + HOLD_S` to value the
exits — moving the clock from 16:15Z back to 13:45Z — so a position whose exit had long been due was never valued
and kept blocking new entries. The same driver wrote to a fixed directory and unlinked its ledgers on start, so the
corrected re-run destroyed the original run it was correcting. It ran recorded data through a boundary labelled
`LIVE_FEED`, because the boundary could not represent replay at all. And it summed `realized_pnl or 0.0`, which
turns an unknown into a zero. Four different failures, one cause: **nothing owned the chronology.**

## 1. The shared lifecycle scheduler — `apex/options_pilot/lifecycle.py`

One loop drives production and recorded-data execution. It reuses the real boundary, the real session functions and
the real Book; it adds ordering and deadline discipline, not a second execution path. `run_pilot` now delegates to
it, so the production entry point and any recorded run are the same code.

**The total order for simultaneous events** is `(canonical microsecond, event rank, scheduling ordinal)`:

| rank | event | meaning |
|---|---|---|
| 0 | `DATA_AVAILABLE` | an input becomes visible. Admits no risk by itself |
| 1 | `INTENT_EXPIRY` | an outstanding authorization reaches its TTL and is retired |
| 2 | `EXIT_DUE` | an open position reaches its deadline and is valued |
| 3 | `EXIT_RETRY` | a scheduled re-attempt inside the exit window |
| 4 | `EXIT_WINDOW_CLOSE` | the last instant an exit may be attempted; exhaustion is recorded |
| 5 | `SCAN` | **new risk may be admitted** |
| 6 | `SESSION_CLOSE` | the session is closed and its obligations reported |

Every existing due obligation outranks `SCAN`, so due obligations are processed before new risk at the same instant.
Ties inside a rank break by scheduling order, so the order is total and reproducible.

- **Exit servicing does not depend on the next scan.** `EXIT_DUE` is its own event. A run with one scan and no
  further scans still discharges its position at the deadline.
- **The clock never rewinds.** `MonotonicClock.advance_to` refuses an earlier instant; a negative sleep is refused;
  scheduling into the past is refused unless an obligation is declared overdue, and an overdue obligation is
  scheduled at the current instant, never before it. The driver's exact assignment is now a refusal.
- **It advances only to the next relevant event**, and after every handler it re-drains anything that became due at
  the current instant and reconciles the ledger's obligations against the queue before time may move again.
- **An inherited obligation is not this run's to re-drive.** A position recovered from an earlier process gets one
  labelled recovery attempt; the frozen policy's attempt budget belongs to the run that opened it.

## 2. One canonical timestamp representation — `apex/options_pilot/instant.py`

The canonical instant is **an exact integer of microseconds since 1970-01-01T00:00:00Z**, obtained by the same
conversion the record serializer performs, so a canonical round trip is the identity.

Instants are compared as integers. **The epsilon is gone.** The previous repair compared `created > now + 1e-6`,
which accepted an instant one full microsecond in the future — the next representable instant. That is a future
timestamp, and it is now refused. What the original defect needed was canonical *equality*, and equality is what the
comparison does. Conversion and rounding are documented on `CONVERSION_RULE`, which is sealed into the run start
record. Source timestamps are preserved separately by `stamp(...)` and are never overwritten.

`tests/test_loop_lifecycle_and_precision.py::test_the_tolerance_is_exactly_one_granularity_and_no_more` asserted the
old epsilon and is **superseded** by `test_there_is_no_epsilon_only_canonical_equality`.

## 3. Run-scoped output directories — `apex/options_pilot/run_dir.py`

Every evaluation claims `base/<run_id>` by creating it. An existing directory is a refused collision. An artifact
name is claimed once and a second claim is refused. **Nothing in the module unlinks, truncates or overwrites**, and
a structural test enforces that. A run writes `RUN_START.json` before any work (run id, start instant, code pin with
dirty flag, per-input SHA-256, configuration digest, timestamp rule) and exactly one terminal marker: `RUN_COMPLETE`
or `RUN_FAILED`. **A failed run keeps its partial ledger and every artifact it produced**, and says so.

## 4. Preserved unknown accounting — `apex/options_pilot/accounting.py`

`total_net_pnl` is a number **only** when the aggregate is complete: every position closed, every fee known, no exit
exhausted, no intent unfinished. Otherwise it is null and `why_not_estimable` names each missing input. Known
realized amounts are still reported, always beside the counts of what is missing, so they cannot be read as a total.
**Zero is a valid total only for a policy that actually opened nothing** (`zero_basis = ACTUAL_NO_TRADE_POLICY`);
`assert_no_phantom_zero` refuses a zero that arises from missing economics and refuses a net reported while the
aggregate is not estimable. `independent_check` recomputes cash, fees, reservations and P&L from the primary ledger
fields without consulting the Book, and `reconcile` compares the two line by line.

## 5. Honest evidence classes — `apex/options_pilot/replay.py`

**Finding: the boundary could not represent replay.** `records.PROVENANCE` was `("SYNTHETIC_FIXTURE", "LIVE_FEED")`
and `assert_prospective` refused the replay labels outright, so the demonstration ran recorded data as `LIVE_FEED`
and every record claims `PROSPECTIVE_PAPER` evidence about a session that had already happened.

A separate, explicitly selected, fail-closed route now exists. `RECORDED_REPLAY` provenance carries
`HISTORICAL_DEVELOPMENT_REPLAY` / `NONE_REPLAY` and seals `live_promotion_eligible`,
`prospective_results_eligible` and `live_authorization_eligible` to exactly `False`. It is reachable only by
constructing a `ReplayAuthorization` that names the recorded inputs by digest; an authorization without digests is
refused. A replay ledger and a prospective ledger can never be the same file. `assert_live_authorizable` and
`prospective_only` are the tested exclusion points.

**The live route is not weakened.** `assert_prospective` is unchanged and still refuses every replay marker; a
replay record cannot pass it. `assert_record_labels` dispatches on the class a record claims and refuses a record
that claims neither.

## The twelve acceptance proofs

`tests/test_operating_loop_001.py` — 50 tests, all through the real lifecycle path, all synthetic.

| # | proof | test |
|---|---|---|
| 1 | exit due between scans is serviced within its window | `test_1_an_exit_due_between_scans_is_serviced_inside_its_window` |
| 2 | scan just before exit due remains subject to the actual open exposure | `test_2_a_scan_just_before_the_exit_is_due_still_carries_the_open_exposure` |
| 3 | completed exit releases capacity and a later eligible scan can trade | `test_3_a_completed_exit_releases_capacity_and_the_next_scan_can_trade` |
| 4 | unavailable quotes trigger scheduled retries without clock rewind | `test_4_unavailable_quotes_schedule_retries_and_never_rewind_the_clock` |
| 5 | exhausted exits remain explicit unresolved obligations | `test_5_an_exhausted_exit_is_an_explicit_unresolved_obligation` |
| 6 | restart recovers pending obligations without duplicate fills or fees | `test_6_a_restart_recovers_the_obligation_without_a_duplicate_fill_or_fee` |
| 7 | simultaneous exit/scan ordering is deterministic | `test_7_an_exit_and_a_scan_at_the_same_instant_order_the_exit_first` |
| 8 | replay input is invisible before its recorded availability | `test_8_a_recorded_input_is_invisible_before_its_recorded_availability` |
| 9 | next-representable future timestamps refuse | `test_9_the_next_representable_future_instant_is_refused` |
| 10 | output collisions refuse and failed artifacts survive | `test_10_a_collision_is_refused_and_nothing_is_overwritten` |
| 11 | unknown costs cannot produce an apparently complete net result | `test_11_an_unknown_exit_fee_makes_the_aggregate_not_estimable` |
| 12 | WAIT is persisted as a decision | `test_12_a_wait_is_a_persisted_decision_record` |

Independent arithmetic checks accompany them: `TestIndependentArithmetic` recomputes cash, fees, reservations and
P&L from primary ledger fields and against hand-computed values. **No limit was lowered and no fixture was selected
by observed profitability** — the trading fixture is the demonstration's own binding condition and its exit is a
loss.

## The synthetic event trace

`docs/evidence/operating_loop/operating_loop_trace/` (`trace.json`, `lifecycle_report.json`, `RUN_START.json`,
`RUN_COMPLETE.json`, `ledger.jsonl`), produced by `scripts/operating_loop_trace.py`.

```
1  00:27:00.000  SCAN       TRADE, exit due 00:42:00
2  00:42:00.000  EXIT_DUE   RESOLVED, capacity released
3  00:42:30.000  SCAN       TRADE, exit due 00:57:30
4  00:57:30.000  EXIT_DUE   RESOLVED, capacity released
```

| step | ledger seq | value |
|---|---|---|
| forecast | 2 | `SYNTHETIC_FIXTURE_MODEL`, signal LONG |
| decision | 5 | TRADE |
| intent | 3 | `SPY|2026-10-09|650.0|CALL` |
| reservation | 3 | envelope debit 500.00, certified max loss 500.00 |
| fill | 4 | 4.95, net debit 495.00, entry fee 0.97 |
| due exit | — | 00:42:00.000Z, attempt 1 |
| outcome | 6 | RESOLVED at 4.73, exit fee 1.00, pnl −23.97 |
| released capital | — | reserved 0.00, open cost 0.00 |
| subsequent decision | 10 | TRADE at 00:42:30 |

Book: 2 closed, 0 open, 0 integrity problems, ledger chain verified. Net −47.94, status `NET`. The independent
recomputation agrees on all four lines (cash 9952.06, reserved 0.00, open cost 0.00, realized −47.94).

## Test evidence

| suite | result |
|---|---|
| `tests/test_operating_loop_001.py` | 50 passed |
| pilot-path suites (`pilot`, `boundary`, `ledger`, `record`, `book`, `risk`, `fee`, `session`, `funnel`, `joint`, `weekend`, `part1`, `decision`, `trace`, `loop`, `clock`, `organism`) | 663 passed, 4 failed, 2 skipped |

The four failures are the pre-existing environment failures also present at the parent
(`test_real_data_boundary.py::test_a_sticky_world_writable_ancestor_is_accepted`, three in
`tests/test_whole_ledger_guard.py`; they require `/opt/apex-repo`, which does not exist on this host).

**Prior regression results, not restated as this candidate's.** The isolated sequential regressions run earlier
tested `5b6863e` (candidate), its parent, and `1b86541` (final): 14 failed / 5269 passed, 14 failed / 5158 passed,
and 14 failed / 5288 passed respectively — the same 14 environment failures in all three. **Those runs did not test
the code in this brick.** The isolated regression on this exact candidate is reported separately below.

## Two tests were deliberately changed

Both encoded behaviour this brick replaces, and both were replaced by a stronger assertion rather than deleted:

1. `test_the_real_entry_point_runs_housekeeping_between_cycles` grepped `run_pilot` for `S.resume(` and
   `S.attempt_exits(`. There is no cycle loop now. It became
   `test_the_real_entry_point_services_obligations_before_new_risk`, which asserts the scheduler's rank order.
2. `test_the_tolerance_is_exactly_one_granularity_and_no_more` asserted that `+1e-6` is accepted. Item 2 removes
   that epsilon. It became `test_there_is_no_epsilon_only_canonical_equality`.

One further expectation changed as a consequence: in `test_trade_wait_refuse_in_one_cycle_with_stable_ids` the QQQ
WAIT intent is now retired at its own TTL with a named reason (`FORECAST_STALE_BEFORE_EXECUTION`) instead of being
swept up at session close, because intent expiry is part of the chronological stream. The reservation is released
earlier, which is the intended behaviour.

## The demonstration driver is repaired but NOT re-run

`scripts/loop_demonstration.py` now uses the lifecycle scheduler, a run-scoped directory and the recorded-replay
route, and its aggregate goes through the unknown-preserving accounting. **It was not executed**: recorded
evaluation is outside this brick's scope. It is repaired-but-unexercised-on-recorded-data, and its building blocks
are covered by the acceptance tests. `tests/test_operating_loop_001.py::TestTheRepairedDemonstrationDriver` checks
that each of the four defects is gone from its code.

## Remaining blockers

- **CROSS-RELEASE RECOVERY IS OPEN.** A position filled under one release cannot be resolved by a boundary running
  another release; `recover_positions` reports it as foreign and does not touch it. `FINDING_RELEASE_CHANGE_STRANDS_POSITION.md`
  and the drafted `CONVENTIONS-AMENDMENT-A-012` stand. **Not closed by this brick and not silently broadened into it.**
- **DEPLOYMENT_DIVERGENCE_001** is carried forward unchanged.
- **No validated directional signal.** `SIGNAL_STATUS_001.md` still holds: `HEURISTIC_DIRECTION_V1` is a
  placeholder, and no P&L produced under it is evidence about anything but the pipeline.
- **The fee schedule is CANDIDATE**, `LIVE_DEFAULT_FEES = UNVERIFIED_FEES`; v2026-09-12b is not authorized.
- **The recorded-replay route has never been exercised on recorded data** — by design here, and it is the first
  thing to run when a recorded evaluation is next authorized.
- **APEX has no order placement capability** and Stage 4 remains document-only.

## The next proposed brick

`docs/CROSS_INSTRUMENT_001_SPEC.md` — shares, options and WAIT compared on the same forecast and account state.
**Specification for review before implementation. No new trading authority is implied.**
