# PREMARKET-SEQUENTIAL-AUDIT-001-R2 — Checkpoint 1A (2026-09-13)

Base `27273a499671592baeda105ce22a076ec5f59428` (verified). Hold intact. **Scheduler NOT installed, NOT armed.**

## The historical root cause: `UNDETERMINED_DUE_TO_MISSING_START_ACCOUNTING`

Both of my R1 claims were wrong, and the evidence is worse for me than the review suggested.

**1. `runs = 0` proves nothing about the gap — it is fully self-explaining.** The machine booted
**Fri 2026-09-11 16:09:42**, *after* that Friday's 05:14, and Sat/Sun are not weekdays. **No scheduled fire has
been due since boot.** `runs = 0` is exactly what a correctly-working job would show. I presented it as the
conclusive root cause; it is not even weak evidence.

**2. Missed runs while loaded and asleep are NOT permanently lost.** From this host's own
`man 5 launchd.plist` (macOS 12.7.6), verbatim:

> *"Unlike cron which skips job invocations when the computer is asleep, launchd will start the job the next time
> the computer wakes up. If multiple intervals transpire before the computer is woken, those events will be
> coalesced into one event upon wake from sleep."*

**Established:** no packets after 2026-08-25; 13 expected weekday packets absent; current load session reports
`runs=0`; the prior plist lacked `StandardOutPath`/`StandardErrorPath`; the script could exit during keychain
access before opening its own log.

**Not established:** whether the agent was loaded throughout; whether the Mac was asleep, off or logged out;
whether an Aqua session existed; whether launchd attempted a spawn; whether a pre-log keychain failure occurred.
The unified log retains nothing for this predicate and `pmset` history begins 2026-09-06.

## The long-sleep design — confirmed, plus a bug

One process starts at 05:14 PT and `time.sleep()`s through 08:15 / 08:32 / 09:05 / 09:20 ET to a 09:25 seal.
**Any interruption loses everything** — no partial packet, no record.

Beyond the design: `time.sleep(min(wait, 3600))` **caps the wait at one hour with no re-check**, so a stage whose
target is further away wakes early and absorbs at the wrong time.

## The simulated morning — SYNTHETICALLY_COMMISSIONED

Real: `seal()`, `PREMARKET_TIME_V1`, run accounting, brief firewall, packet schema.
Substituted only: clock, provider transport, model transport (`RECORDED_MODEL_RESPONSE` — **not** model
generation), output root.

**All ten declared source dispositions matched**, including syndication clustering, additive correction, stale
exclusion, future refusal, unavailable-marking, and the hostile headline **retained as data with no authority**.
Four separate bounded stage records, no long sleep. Real `seal()` returned `SEALED_BEFORE_OPEN`.

**Ten failure flights, each leaving its own non-overwriting evidence:** keychain failure at STARTED, provider
timeout, malformed payload (PARTIAL, accepted=2 rejected=1), model timeout, invalid Captain output
(`REFUSED_BY_FIREWALL`), `LATE_START` with the **actual** time not the scheduled one, `MISSED_WINDOW` with **no
retrospective fetch**, duplicate stage refused, interruption leaving an incomplete record, and post-seal
modification **detected** by recomputation.

**Shadow handoff:** identity verified, attached `PRIOR_CONTEXT`, disposition **`RETRIEVED_UNUSED`**, reader
labelled `CONSUMED_BY_TEST_READER` (audit reader, not production), trading authority **NONE**,
`BEHAVIORAL_EFFECT` **not manufactured**.

**Independent reconstruction** from artifacts only: 4 stages, cutoff, `known_from`, seal digest, 10 dispositions,
blind spots, shadow disposition — without calling the runner's summary.

## Why I did NOT install the scheduler

Step 7 authorizes installation **only after the preceding tests pass**, and step 6 requires a **disposable
LaunchAgent** proving Aqua execution, stdout/stderr capture, RunAtLoad, duplicate handling and clean removal.
**I have not run that.** Installing on the strength of a simulation would be exactly the substitution the
amendment warns against — a simulation cannot prove launchd will start anything.

## Verdicts

| | |
|---|---|
| 1. Simulated producer correctness | **PASS** |
| 2. Failure-handling correctness | **PASS** (10/10 flights) |
| 3. Packet factual correctness | **PASS** on the frozen fixture |
| 4. Captain factual accuracy | **NOT ESTABLISHED** — the response was recorded, not generated |
| 5. Packet integrity | **PASS** — content under the implemented recipe; not authorship |
| 6. Shadow-handoff correctness | **PASS** — correctly `RETRIEVED_UNUSED` |
| 7. Actual launchd reliability | **UNPROVEN** — no scheduled run has occurred |
| 8. Live provider readiness | **UNPROVEN** — no provider was called |
| 9. Production downstream integration | **MISSING** — unchanged |

**Implementation status: SYNTHETICALLY_COMMISSIONED. The live producer is NOT operational and is NOT armed.**
