# CAMPAIGN_V1_ATTEMPT_2 — ABORTED_ENGINEERING_FAILURE (LAB-04)

Accelerated run 2026-08-16: Pass A's 8-way parallel context fetches hit
provider concurrency pressure; failures were silently converted to EMPTY
DailyContexts AND CACHED, so 82/92 sessions scanned a blindfolded
universe (healthy states, zero context -> everything liquidity-rejected
-> zero abnormalities) while 10 pre-cached days behaved normally. The
report's integrity gate initially read CLEAN because states were
healthy — the context-starvation class was invisible to it. Caught in
Pass-3 adversarial reading (impossible concentration: signals only on
previously-cached days). ZERO observations contribute.

Fixes (LAB-04): poisoned caches can neither be written nor trusted on
read (quarantine + rebuild); workers die loudly below 50% context
health; default workers 8->4; integrity gate now locks economics on
context-starved sessions. Ledger + day caches preserved for diagnostics.

## Reclassification (2026-08-16, LAB-05)

Root cause CORRECTED: the mass context failures were HTTP 402 —
PROVIDER DAILY QUOTA EXHAUSTED — not (only) concurrency pressure. The
storm burned the vendor's daily allowance; every subsequent non-cached
fetch failed deterministically, in every retry, at any worker count.
The LAB-04 guards remain correct and necessary (they caught the blind-
fold both times); the semaphore remains correct debt-closure; but the
first cause was quota. 402 is now classified loudly as
PROVIDER_QUOTA_EXHAUSTED and never retried. ATTEMPT_3's Pass A caches
(50 verified days) remain valid; completion resumes when the provider
window resets, at ~6k remaining requests — leaving ample allowance for
Monday's forward clock (~5k/day), which takes absolute priority over
the laboratory.

## LAB-07 (2026-08-16): the forward reserve was a number, not a control

**Discovered by inspection while resuming the campaign, then confirmed
empirically against the provider.**

`FORWARD_RESERVE_CALL_UNITS = 35_000` existed. `lab_spare_units()`
computed headroom from it. `grep` across the entire repo found that
function had **zero callers**. Nothing consulted the reserve at the
moment units were actually spent.

Two compounding defects made that fatal rather than merely untidy:

1. `QuotaGovernor.used` starts at zero in every new process. A budget
   that resets per process cannot bound a shared daily resource.
2. `hunter_replay_fast.py` constructs one governor per **(worker × day)**,
   inside `_run_day`, while printing to the operator: *"structural
   invariant: workers can never collectively exceed the lab total."*
   That claim was false. With 6 workers × 7,500 units × ~50 days the real
   ceiling was ~375,000 units against a stated cap of 45,000.

**Observed consequence.** The auto-resume monitor correctly gated on
≥35k spare and released the campaign at the midnight-GMT rollover. The
campaign then ran the provider counter to exactly **100,000 / 100,000**
for GMT day 2026-08-16 — spending the entire forward reserve. Had this
been a Monday, Epoch 1's first forward session would have been blind,
and the failure would have looked like a data outage rather than
self-inflicted starvation.

**Fix.** `apex/intraday/quota_ledger.py`: a cross-process, GMT-date-keyed,
`flock`-serialized, atomically-replaced spend counter. Two purposes, two
ceilings — LAB stops at limit − reserve; FORWARD may spend the reserve,
because the reserve exists for it. `QuotaGovernor` gained `purpose`
(defaulting to LAB, so a caller that forgets cannot quietly spend
Monday's quota) and now requires BOTH its local budget and the shared
ledger to allow a claim. `lab_spare_units()` no longer merely computes:
it reconciles the ledger against the provider, taking the max in both
directions (the local counter sees in-flight claims the provider has not
billed; the provider sees spend that never passed through a governor).
The false invariant claim is deleted, and the fast runner now exits
early when lab headroom is zero.

**Negative control.** Four processes, each with an effectively infinite
local budget — the exact old configuration — were granted **160,000
units** collectively (2.5× the lab ceiling, 1.6× the entire daily limit).
Under the fix the same four processes stop at 65,000 with the reserve
whole. That control is now a test (`test_quota_reserve.py`, 15 tests),
along with restart survival, stale-provider-bucket rejection, torn-file
recovery, and a guard that fails if the false invariant text ever
returns or the reserve helper ever becomes callerless again.

**Disease class.** Same family as LAB-04: a governance guarantee that
existed in prose and arithmetic but had no enforcement path, so the
system could violate it while reporting compliance. The museum rule
applies — the reserve is now enforced at the only place that matters,
the moment of spend.

**Campaign status unchanged.** Still paused; 51 verified Pass-A day
caches preserved. GMT day 2026-08-16 is fully consumed and the lab
cannot resume until the midnight-GMT reset. Monday 2026-08-18 is a fresh
bucket, so Epoch 1's reserve is intact.

## CAMPAIGN V1 FINAL RUN COMPLETED (2026-08-17 ~03:50 UTC)

92/92 predeclared sessions replayed under LAB-07 quota enforcement
(first campaign where the forward reserve was structurally unreachable).
Pass B 9.8m; 234 capital records; ledger chain valid; Rule 17 = 0; class
pure EODHD_HISTORICAL_EXPLORATORY; zero production writes.

**INTEGRITY VERDICT: NOT CLEAN — ECONOMICS LOCKED.** One context-starved
session (2026-05-06, context health 0.068 vs min-rule) trips the
three-level gate. The gate working as designed: 91 clean sessions do not
outvote one blindfolded one.

**UNLOCK PATH (after Epoch-1's first forward session, not before):**
quarantine 2026-05-06's daily context + any day cache, re-run the
campaign harness (resume skips the 91 cached days), re-run the analysis.
If the rebuilt day is healthy the verdict recomputes; if the provider
simply lacks that day's context, the session is reclassified
LEGITIMATE_PARTIAL under the prereg and the lock re-evaluates.

Until then the funnel numbers in CAMPAIGN-REPORT.json exist but are
LOCKED: no economics reading, no playbook conclusions, no Epoch-2
motivation may cite them. Observed-but-locked is recorded here precisely
so nobody "discovers" the numbers later and forgets the lock.
