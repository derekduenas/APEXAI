# FINDING — a release change strands the previous release's open position

Found: 2026-09-12, weekend commissioning Brick 5 rehearsal (`tests/test_weekend_brick5_rehearsal.py::TestRehearsal::
test_changed_release_strands_the_previous_release_s_open_position_FINDING`). Status: **OPEN, BLOCKING for any restart
under a different release while a position is open.** Not repaired this weekend: the repair changes recovery semantics
at the boundary and needs its own review.

## Observed

1. A process under release `rel-A` fills one contract and dies before the exit window.
2. A process under `rel-B` starts on the same ledger and session. `Boundary._verify_intent_identity` refuses the
   `rel-A` intent (`INTENT_FROM_OTHER_RELEASE`), so `recover_positions` returns nothing for it.
3. The `rel-B` process scans, opens its **own** position, discharges only that one, and writes `pilot_session_close`.
4. The `rel-A` position remains an open obligation on the ledger: **stranded**, invisible to the new process's exit
   loop, and not counted against its reservations when it opened a second position.

## Why it matters for Monday

Any restart under a new release (a deploy, or a rollback) while a paper position is open leaves that position
unmanaged. The rule "refusing new entries must not strand existing positions" is honoured for the event gate, and
violated for release changes.

## Operational rule until repaired

Do not restart the paper service under a different release while `pilot_fill` records without a discharging
`pilot_outcome` exist for the session. Check with the operator view (`open positions`) before any re-point of
`/opt/apex/current`; if a position is open, either wait for its exit window under the running release or perform
the exit under the same release first.

## Proposed repair (for review, not applied)

Recovery of an intent for **filling** stays refused across releases (an unfilled intent from another release must
never be executed by this one). Recovery of a **FILLED** position for **exit** is honoured across releases: the
outcome record names the exiting release and carries `cross_release_exit: {opened_under, exited_under}`; the Book
counts the position against the new process's aggregate limits from the first scan. Acceptance: the pinned test
flips to "discharged, both releases named, no second position opened while the first is open unless limits allow".
