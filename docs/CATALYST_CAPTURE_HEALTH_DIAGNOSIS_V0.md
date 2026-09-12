# CATALYST_CAPTURE_HEALTH_DIAGNOSIS_V0

Read-only diagnosis. No code changed, no service acted on, no daemon
reloaded, no data modified, no market row read. Branch base
`event-source-001 @ a851f85`, fresh detached checkout at
`/apex-data/tmp/cs001_wt`, clean.

All times UTC unless marked ET. Every claim is tagged **[observed]** or
**[inferred]**.

## 1. Root cause: CONFIRMED — this is not a stall

**The capture is correctly idle. It was never broken, and my EVENT-SOURCE-001
claim that it was is withdrawn.**

The service evaluates its own phase from the exchange calendar. Evaluated
read-only at 2026-09-08T02:06Z **[observed]**:

```json
{"kind": "catalyst_phase", "phase": "IDLE", "session": "2026-09-07",
 "why": "2026-09-07 is not a trading day", "decision_power": "SHADOW_CONTEXT_ONLY"}
```

At 02:06Z on 8 September the ET calendar day is still **7 September —
Labor Day**. The preceding days were Saturday 5th and Sunday 6th. The last
work therefore falls at Friday 4th's close, and the next scheduled work is
`OVERNIGHT_SCAN` at 07:00 ET on Tuesday 8 September.

Corroborating evidence, independent of the phase evaluation:

| Fact | Value | Tag |
|---|---|---|
| cycles per day, whole history | Thu 8/27 98 · Fri 8/28 91 · **Mon 8/31 93** · Tue 9/1 91 · Wed 9/2 88 · Thu 9/3 86 · Fri 9/4 93 | [observed] |
| cycles on Sat 8/29 or Sun 8/30 | **none** — the previous weekend shows the identical gap | [observed] |
| APEX exchange calendar | 9/5 WEEKEND · 9/6 WEEKEND · **9/7 HOLIDAY** · 9/8 SESSION | [observed] |
| last cycle | `2026-09-04:POST_CLOSE_SEAL`, ended 20:02:01, 16/17 sources, 1 new event — a clean end of day, not a crash | [observed] |
| process state | PID 737236, up 5d 20h, `State: S (sleeping)`, `wchan hrtimer_nanosleep`, 4 threads, RSS 86 MB, 0.0% CPU | [observed] |
| journal since 2026-09-04T20:02 | **no entries at all** | [observed] |
| service loop | non-working phases take `beat.beat()` — *"presence only; no work claimed"* | [observed, source] |

A blocked process would sit in a socket or futex wait, not a timer sleep; a
crash loop would show journal entries and a rising `NRestarts`; a
disconnected source would appear as failures in the cycle log. None is
present. **[inferred from the above]**

## 2. The nine measurements, kept separate

| Measure | Value at 2026-09-08T02:32Z | Verdict |
|---|---|---|
| process liveness | PID 737236 alive since 2026-09-02T06:19:35, sleeping on a timer | **ALIVE** |
| successful source contact | 10,285 of 10,871 source checks over 640 cycles (94.6%) | healthy, last contact Fri 20:02 |
| accepted observation | 5,209 accepted of 223,532 raw offered (2.33%) | dedup working as designed |
| persisted observation | 5,209 raw observations, 5,163 events, 46 event updates | matches accepted |
| heartbeat freshness | `beat_utc` 02:32:03, **30 s old** | **FRESH** |
| output freshness | `events.jsonl` mtime 2026-09-04T20:02:01, **3 d 6 h 30 m old** | STALE by clock, **EXPECTED by calendar** |
| useful-work count | `work_completed: 267` | consistent with 7 trading days |
| error count | `sources_failed` 586 of 10,871 (5.4%); heartbeat `last_error: null` | see §3 |
| silent-discard count | 218,323 raw items discarded by dedup **[counted]**; events refused in ~426 cycles **[counted in the cycle log, NOT surfaced anywhere else]** | see §3 |

Systemd `ActiveState=active` was **not** treated as evidence of work at any
point; the work claim rests on `last_work_utc`, the cycle ledger and the
phase evaluation.

## 3. Two real defects the diagnosis did find

**(a) BLS has failed on essentially every cycle since go-live.**
`{"BLS": "BLS CUUR0000SA0: unexpected shape ('series')"}` — a **parser /
schema rejection**, 81 distinct cycle records name it and every sampled
cycle carries `sources_failed: 1` with 16/17 succeeding **[observed]**. It
has never escalated: the heartbeat reports `last_error: null` because a
per-source failure is not a service error. This is the **macro** source —
precisely the family EVENT-SOURCE-001 named as the best candidate for a
first event experiment.

**(b) The interpreter is refused constantly, and nothing outside the cycle
log knows.** Distribution of `last_error` across 640 cycles **[observed]**:

| Count | Kind |
|---|---|
| 389 | *"N refused: EV_…: cited sources ['https://news.google.com/rss/…'] were never retrieved"* |
| 88 | interpreter timed out after 180 s |
| 81 | BLS unexpected shape |
| 37 | refused: cited sources on finance.yahoo.com never retrieved |
| 12 | brain did not return JSON |

633 of 640 cycles (98.9%) recorded a `last_error`. The largest class is the
anti-fabrication guard firing: the LLM cited sources that were never
retrieved, and the event was **refused**. That is the guard working exactly
as designed — and it means roughly two thirds of cycles are discarding at
least one interpreted event, with `last_error: null` on the heartbeat.

## 4. Causes considered and excluded

| Candidate cause | Excluded by |
|---|---|
| source/API inactivity | 16/17 sources succeeded on the final cycle [observed] |
| authentication / authorization | interpreter capability line reports `available: true`, `OPERATOR_CLAUDE_SUBSCRIPTION` [observed] |
| network or DNS | no network errors in journal; final cycle contacted 16 sources [observed] |
| process blocked or deadlocked | `wchan hrtimer_nanosleep`, `State: S`, 0.0% CPU — a timer sleep [observed] |
| timer / scheduling failure | the schedule is *the reason*: `phase = IDLE`, `why = not a trading day` [observed] |
| backoff / retry state | no retry entries; journal empty [observed] |
| queue / backpressure | `backlog_remaining: 1` (the BLS source) [observed] |
| silent exception handling | loop catches exceptions into `beat.error(...)`; `last_error` is null [observed, source] |
| **writing to a different destination** | `results/` is a symlink: `/apex-data/runtime/results → /apex-data/core`, so the code's `results/catalyst/events.jsonl` resolves to `/apex-data/core/catalyst/events.jsonl`. A filesystem-wide search for catalyst/event files modified since 20:02 found only the heartbeat [observed] |
| output path / filesystem | inodes stable, mode 664, owner `apex:apex`, space available [observed] |
| permission / ownership | writer and files share `apex:apex` [observed] |
| **health reporting not representing useful work** | **partly true — see §5** |

## 5. What my EVENT-SOURCE-001 claim got wrong, and the residue that is real

I wrote that the service *"reports active/running, success, NRestarts=0, yet
nothing has been written since 2026-09-04T20:02Z"* and called it an
operational integrity failure. The first half is accurate; **the conclusion
was wrong**. I compared a timestamp against wall-clock now without checking
the exchange calendar — in the same programme where I had just built and
independently reconciled that calendar.

The residue that *is* real: an operator cannot distinguish **"idle because
the market is closed"** from **"broken"** without evaluating the phase
function by hand, as I had to. The heartbeat already separates presence
(`beat_utc`) from work (`last_work_utc`) — better instrumentation than I
credited — but it does not carry **why** it is idle or **when work is next
due**, though `phase_at()` computes exactly that string and discards it.

That is the gap worth closing, and it is a narrow one.
