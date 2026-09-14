# PREMARKET-SEQUENTIAL-AUDIT-001-R1 — Checkpoint 1A (2026-09-13)

Base `862970fa9cac359f6a43f4e6fb22c9dce0af7c34` (verified). Separate clean worktree. Hold intact.
**Scheduler NOT activated. Packet NOT wired into TwinSources. No sources connected. Checkpoint 2 not started.**

## Root cause of the 19-day gap

```
launchctl print gui/501/com.apex.premarket
    runs = 0
    last exit code = (never exited)
```

**launchd has never executed this job in the current load session.** The calendar triggers *are* registered
(Mon–Fri 05:14, `com.apple.UserEventAgent-Aqua`), so the job is armed — it simply has not fired since the agent
was last (re)bootstrapped.

**A correction to my own earlier evidence:** I quoted `LastExitStatus = 0` from `launchctl list` as though it
showed a successful run. It is the *initial* value. `runs = 0` contradicts it. "Loaded" is not evidence of running,
and neither is that field.

Corroboration: `logs/premarket.log` ends cleanly at **Aug 25 06:27** with the 7th `PACKET SEALED`, and contains
**not one line since** — no crash, no traceback, nothing.

### Two defects that made the gap *silent* (independent of why it stopped)

1. **The plist has no `StandardOutPath`/`StandardErrorPath`.** Anything failing before the script's own redirect
   is invisible.
2. **`ops/premarket.sh` reads the keychain secret on line 6 and opens its log on line 9**, under `set -euo
   pipefail`. A secret failure exits **with no log line at all** — indistinguishable from never starting.

I could not separate *asleep at 05:14* from *Aqua session inactive* from *secret failure* with the evidence that
exists, and I am not asserting one. **That is itself the finding**: the producer had no accounting that could
answer it.

## Expected vs observed runs

```
expected weekday runs : 14      produced packets : 1      MISSED, NOT RETRIED : 13
```

Full dated table in `docs/evidence/premarket_audit_001/R1_RUN_TABLE.txt`. Missing events are counted as MISSED,
never inferred as successes. **A missed `StartCalendarInterval` is not retried by this configuration.**

## Corrected time model — `PREMARKET_TIME_V1`

**Your correction accepted:** seal-time `known_from` is **conservative for causality** — the sealed packet cannot
be known before it is sealed. I called it unsafe; that was wrong. The defect is that *one* field also implied
source freshness.

Now separate: `source_event_time`, `source_publication_time`, `source_request_time`, `source_receipt_time`,
`source_known_from`, `packet_collection_started_at`, `packet_data_cutoff`, `ai_request_time`, `ai_response_time`,
`packet_created_at`, `packet_sealed_at`, `packet_known_from`.

Enforced: `packet_known_from >= packet_sealed_at`; cutoff **derived from accepted observations**, never from the
seal clock; per-source freshness measured from the cutoff; a source known after the cutoff **refused, not
clipped**; unavailable stays unavailable; `known_from` defaults to **receipt**, never to event time.

**Legacy packets are labelled, not reinterpreted**: their downstream availability is reconstructible from
`as_of_time`; their **source freshness is not**, and is reported UNAVAILABLE.

## Run accounting — `PREMARKET_RUN_RECORD_V1`

Every run leaves a unique, non-overwriting record — including one that fails before any packet. A bounded lock
prevents overlapping runs; a **stale lock is diagnosed, never silently stolen** (holder pid, age, liveness
reported; recovery is a reviewed action).

## Scheduler repair — prepared, NOT activated

`ops/premarket_repair/`: corrected plist (adds the missing stdout/stderr), corrected script (log redirect **before**
the secret read, named failure reasons), `install.sh`, `rollback.sh` (restores the **byte-exact** prior state —
verified identical to what is installed), `status.sh`, `once.sh`.

A test asserts the corrected plist is **not** installed.

## Revised Checkpoint 1 verdicts

| | |
|---|---|
| Causal packet availability | **PASS** for the inspected packet |
| Source freshness | **UNRESOLVED** — legacy packets cannot reconstruct it |
| Scheduler reliability | **FAIL** — 13 missed runs; repair prepared, not exercised in production |
| AI factual accuracy | **PASS for the specific numeric claims audited only** — not complete factual accuracy |
| Interpretation quality | **NOT_EVALUATED** — no declared rubric exists. My earlier PASS is withdrawn. |
| Packet integrity | **PASS** — content integrity under the implemented recipe. Establishes **neither source authenticity nor authorship**. |
| Downstream consumption | **FAIL** — unchanged |
| Ready for next layer | **NO** |
