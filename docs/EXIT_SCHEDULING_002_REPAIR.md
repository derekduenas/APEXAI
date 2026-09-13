# EXIT-SCHEDULING-002 — bounded repair of the three findings at `01fcda9` (2026-09-12)

Branch `exit-scheduling-002-repair`. Synthetic only. **No recorded evaluation, fitting, deployment, activation,
data acquisition, fee change, affordability change or limit change.** The recorded driver is neither wired nor run.

All three findings were correct and all three reproduced before any fix. The reproducers are committed and now
pass; each names the behaviour it pins.

## 1. A resolved exit could be reported as exhausted

**Reproduced.** The due timer fires first and fails because no snapshot has arrived, queuing a retry. An arrival at
due + 1 s resolves the position. The queued timer then runs on to window close, and because the suppression block
sat **before** the check that the position still exists, it overwrote `entry["final"]` with
`EXIT_EXHAUSTED_UNRESOLVED`. The ledger, the Book and the session close were all correct; the lifecycle report
contradicted them.

**Fixed** by checking terminal state first. `_service_exit` now looks for the position before any suppression or
scheduling decision, and a stale event returns the existing terminal state with a named reconciliation note,
`STALE_EVENT_RECONCILED_POSITION_ALREADY_RESOLVED`, touching nothing.

Five assertions now cover it: the ledger and Book agree it resolved, **the report agrees with the Book**, no
valuation happens after the resolution and the boundary is not even asked again, the session reports
`CLOSED_CLEAN` with zero outstanding obligations, and the stale timer is reconciled by name.

## 2. A notification id is not proof of which quote was evaluated

**Correct, and the optimisation is disabled.** `_on_exit_arrival` recorded the notification id as attempted
*before* asking the boundary. Nothing bound that id to the quote actually returned, and no refusal reason was
examined, so a transient provider failure marked an observation attempted when no quote had been seen at all, and
suppressed the later timer that would have succeeded.

**`skip_timer_when_no_new_observation` is now `False` in `EXIT_POLICY_V2`, with no replacement mechanism.** The
switch remains, off, so the behaviour is nameable rather than deleted. Arrival triggering fixes the demonstrated
case without it, which the historical-geometry test still proves.

**The policy identity records the change.** The hash with suppression on is preserved as
`ARRIVAL_POLICY_HASH_WITH_SUPPRESSION = 74aa8314…`, and a test asserts the current hash differs from it. Turning an
optimisation off changes the policy, and a reader comparing two runs can see that from the hash alone.

The reproducer runs an arrival, a transient provider failure, and a usable quote later on the timer path, and
asserts the position resolves.

## 3. Notification traffic could end the loop before a deadline

**Reproduced** with more notifications than the global budget while a position was open. The old 500-arrival test
never approached the 20,000 limit.

Two changes, and **the global budget is not raised**:

- **Coalescing by (availability instant, contract).** Notifications sharing an instant and a contract cannot be
  distinguished by the loop, which will ask the boundary once and receive one quote, so they become one event
  carrying `n_coalesced` and the ids. This groups only what is **already available at that instant**, so nothing
  later is pulled forward; a test asserts every quote the boundary was served had arrived by the moment it was
  asked. Fifty notifications at one instant become one event.
- **Separate accounting.** The global budget is a **non-convergence detector**: it exists to catch a loop that
  keeps scheduling itself. A finite list of supplied notifications cannot do that, and charging them to that
  detector was the actual mistake. Arrivals are now counted against `arrival_event_budget` and reported as
  `n_arrival_events`. When that bound is reached, further notifications are not scheduled and the reason is
  recorded; **obligation events already queued are untouched, so no deadline is starved and no terminal accounting
  is lost.**

Also tested: duplicate ids, the same id on a different contract, and notifications for a contract with no position.

## Acceptance, strengthened

- **Terminal reports are asserted**, not just fills and balances: `exit_entries[…]["final"]`, `completion` and
  `outstanding_obligations` in both the resolved and the exhausted cases.
- **The quote-visibility tautology is replaced.** The old test asserted a property of the fixture's own filter. The
  feed now records what it actually served, and the tests assert the recorded quote matches one the feed served,
  that its observation had arrived by the request instant, and that its age is inside the freshness limit.
- **The identical-fixture comparison survives**: the 127-millisecond geometry resolves under V2 and still fails
  under V1, spending all five attempts.
- **The phase sweep survives**, across the full 60-second period.
- **The limits are unchanged**: 5 attempts, 120-second window, 15.0-second freshness, and the V1 hash is pinned.

One earlier test is superseded in place: it asserted that blind retries *were* skipped, which this repair removes.
Its surviving point, that a scheduling decision is never counted as an attempt in either direction, is kept.

## Results

| suite | result |
|---|---|
| `tests/test_exit_scheduling_002_repair.py` | 29 passed |
| affected suites together | **288 passed** |

Candidate: this branch's head. Base `01fcda9d3cf6bcd6d2ba2d66a5bd4ff36e4f25e0`.

## Recovery: reported, not changed

**Carried-forward limitation, unchanged by this repair.** A position inherited from an earlier process receives one
labelled recovery attempt and is then excluded from further servicing in that run, **arrivals included**.

`TestRecoveryIsACarriedForwardLimitation` demonstrates it end to end: a restart, a failed recovery attempt, and
then a usable quote arriving at due + 30 s, well inside the remaining window. **That quote is not used.** The
position stays an obligation with retained exposure, and the test asserts exactly that rather than dressing it up.
The previous brick's restart test showed no duplicate fill and no duplicate fee, which is true, but it did not
establish continued exit servicing, and it should not have been read as doing so.

Whether an inherited position should be serviced by arrivals is a policy question about the recovery contract, not
a bug in this scheduler, and it is out of scope here.

## Remaining limitations

- **Not exercised on recorded data.** The recorded driver supplies no observation feed; wiring it is the next
  brick and is not started.
- **Arrival triggering needs a feed.** Without one, V2 behaves as V1 with the suppression off.
- **Affordability is untouched**, and remains why the funnel produced no proposal.
- **Coalescing assumes the loop cannot distinguish two notifications at one instant for one contract**, which is
  true of this boundary because it fetches one quote per request. A boundary that could fetch per-observation
  would need this revisited.
