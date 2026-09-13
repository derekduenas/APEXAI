# EXIT-SCHEDULING-002 — service exits when usable observations arrive (2026-09-12)

Branch `exit-scheduling-002`, based on `3112a3a`. Synthetic inputs only. **No recorded rerun, no fitting, no
deployment, no collector restart, no freshness relaxation, no risk-limit change, no cross-instrument work.** The
earlier run remains evaluated under its original policy, which is unchanged and still hashes to the same value.

## Three corrections taken first

1. **A data-arrival trigger does not guarantee a fresh quote.** A newly received snapshot can carry an old provider
   timestamp. My previous proposal called arrival triggering "the only option that makes the freshness rule reliably
   satisfiable"; that was wrong. It changes *when* the boundary is asked, nothing else. Freshness, the deadline
   timers and explicit unresolved handling are all retained, and a test proves a new arrival carrying a 40-second-old
   quote is still refused.
2. **Shares do not automatically solve affordability.** At a $770 underlying, a $500 fully funded loss limit excludes
   one whole share too. My earlier sentence that the same cap "buys a meaningful share position" was simply false.
   Fractional shares, a different underlying or another approved expression would each need their own contract.
3. **The census figures needed reconciling.** Done in §5. They were two different populations, not a contradiction,
   but my report set them side by side without saying so.

## 1. The versioned rule

`EXIT_AT_HORIZON_15M_V2_ARRIVAL`, in `apex/options_pilot/exit_policy.py`. `EXIT_AT_HORIZON_15M_V1` is untouched and
a test pins its hash, so the earlier run's policy cannot drift.

**What changes: when an attempt fires.** A position that is due and inside its window may be attempted the moment a
new observation for its contract becomes available, rather than only on the timer.

**What does not change**, and each is asserted:

| | |
|---|---|
| attempt budget | 5, same as V1 |
| window | 120 s, same as V1 |
| horizon | 900 s, same as V1 |
| freshness limit | 15.0 s, untouched |
| boundary checks | provider timestamp, receipt, contract identity, sides, prices, all as before |
| deadline timers | retained. With no data at all the window still expires on its own and the position is still an explicit unresolved obligation |

**Exit servicing is not driven by the captain, the chart or a strategy scan.** A test runs a scenario whose only
scan is the one that opens the position and shows the exit resolving on its arrival with no scan in between.

### The one judgement call, declared

`skip_timer_when_no_new_observation` lets the scheduler decline to fire a timer retry when the newest visible
observation is one an earlier attempt already rejected. **This is not reclassifying a rejection**: the boundary is
never asked, so no attempt is created, consumed or renamed. It exists because re-reading the same stale snapshot
four times is exactly what consumed fill 37's budget. Set it `False` for V1's blind-timer behaviour; the arrival
trigger still fixes the original case either way. **Flagged for your review as the one behavioural choice here.**

## 2. Attempt and event accounting

Stated once, in `exit_policy.ATTEMPT_ACCOUNTING`, and reported on every run:

> **One attempt is consumed each time the boundary is asked to value a position, whatever the answer.** A stale
> quote, a missing bid, a malformed quote and a provider failure all consume an attempt exactly as a successful
> valuation does. What does **not** consume an attempt is a scheduling decision not to ask.

Scheduling decisions are recorded separately, each carrying `is_attempt: False`:
`DUPLICATE_OBSERVATION_IN_FEED`, `DUPLICATE_OBSERVATION_ALREADY_ATTEMPTED`, `TIMER_SKIPPED_NO_NEW_OBSERVATION`,
`ARRIVAL_BUT_NOT_DUE_OR_NO_BUDGET`, `ARRIVAL_TRIGGER_BUDGET_REACHED`, `EXIT_EVENT_ALREADY_PENDING`,
`PENDING_RETRY_CANCELLED_POSITION_RESOLVED`.

- **Deduplication** happens at ingestion by observation id, and again per position for anything that survives.
- **Flood bound**: `max_arrival_triggers` (64) per position, plus the existing event budget. A test fires 500
  arrivals inside one window and the deadline still terminates the obligation with the budget intact.
- **Cancellation**: a resolved position settles, and a scheduling event records that its pending timer was cancelled.

**Two bugs the tests found while writing this.** Timer and arrival chains could both be pending for one fill, so
retries doubled; and duplicate window-close events each fired an attempt. Both are fixed by a single-pending-event
guard, and the skip rule now applies at the window close where it goes terminal rather than spending the remainder.

## 3. Ordering and causal equivalence

```
DATA_AVAILABLE < INTENT_EXPIRY < EXIT_DUE < EXIT_ARRIVAL < EXIT_RETRY < EXIT_WINDOW_CLOSE < SCAN < SESSION_CLOSE
```

`DATA_AVAILABLE` first, so an observation arriving at the same instant an exit falls due is already visible when
`EXIT_DUE` fires. `EXIT_ARRIVAL` before `EXIT_RETRY`, so a genuine arrival beats a blind timer at the same instant.
`EXIT_WINDOW_CLOSE` after both, so a deadline never pre-empts an attempt that could still resolve. All obligations
before `SCAN`. Ties inside a rank break by scheduling order, and a test asserts three identical runs produce an
identical event stream.

Production and replay use the same scheduler. An observation is scheduled at its **recorded availability** and is
invisible before it. The runner never reaches into a feed's future contents to pick an advantageous retry time, and
a structural test enforces that.

Every attempt records its trigger, the observation id where applicable, the policy version, the rejection reason
and the remaining window. Every scheduling decision records its reason.

## 4. Acceptance evidence

`tests/test_exit_scheduling_002.py`, **44 tests, all passing**, through the real lifecycle path.

| case | result |
|---|---|
| quote arrives 127 ms after due, historical geometry | **resolves under V2** |
| the same fixture under V1 | **still fails, all five attempts spent** |
| arrivals at −2.0, −0.5, −0.001, 0, +0.001, +0.127, +1, +5 s | all resolve |
| sweep across the whole 60 s period: 0, 3.7, 11.2, 14.9, 15.1, 22.5, 31, 44.4, 52.8, 59.9 s | all resolve |
| new snapshot carrying a 40 s old quote | refused, position remains an obligation |
| eligible arrival between fixed retry times | resolves |
| duplicate arrivals | one exit, one fee, one outcome transaction |
| timer/arrival race | nothing attempted after the resolution |
| no data before window expiration | explicit exhaustion, exposure retained |
| five attempts exhausted before expiration | budget is the binding limit, and the record says so |
| restart with an exit pending | recovered, no duplicate fill, one entry fee |
| flood of 500 arrivals | budget intact, deadline still terminated it |
| completed exit | exposure released, total net estimable |
| unresolved exit | exposure retained, total net null |

The V1 comparison matters most: the same fixture, unchanged, still fails under the old policy. **The sweep is
deliberately across the full snapshot period rather than tuned to the historical millisecond.**

Affected suites re-run: **295 passed**, one pre-existing assertion updated because this brick adds required fields
to each attempt record.

## 5. The affordability correction

Both earlier figures were right about different populations, and I placed them together without saying so.

| quantity | definition | value |
|---|---|---|
| **ask principal** | `ask × 100 × 1 contract` | the figure both numbers described |
| **$682 to $1,169** | scan 1 only, minimum **and** maximum across its 18 option candidates | one scan |
| **$650** | the minimum across all twelve scans, which occurs on scan 12 | twelve scans |
| **envelope reservation** | `envelope_for(...)`, a **third** quantity: capped at the kernel price, so $500.00 for every candidate whether feasible or not, with `feasible=False` when the ask exceeds the cap | not the same as principal |
| **fees** | entry $0.04, exit $0.05 on a filled contract | three to four orders of magnitude below the gap |

Populations, per scan, identical on all twelve: **19 rows, of which 1 is WAIT and 18 are option candidates. Zero
option candidates fit.** Minimum ask principal by scan:

```
682  701  689  691  654  695  688  677  666  674  665  650
```

The cheapest candidate on any scan was $650 against a $500 cap, 1.3× over. No market-data request was made; this is
recomputed from the retained candidate records.

## 6. Limitations

- **Not exercised on recorded data.** Synthetic only, by scope. The recorded run stands under V1.
- **The skip rule is a judgement call** and is flagged above for review rather than presented as settled.
- **Arrival triggering needs an observation feed.** The recorded driver does not yet supply one, so a recorded run
  under V2 would need that wiring, which is not built here.
- **This does not make exits reliable in general.** It removes a schedule that systematically missed available
  quotes. If no eligible quote exists in a window, the position is still an explicit unresolved obligation, and it
  should be.
- **Nothing here addresses affordability**, which remains the reason the funnel produced no proposal.
