# CATALYST-STALL-001 — return

```text
ROOT CAUSE:            CONFIRMED — NOT A STALL. Correct idle behaviour across the
                       weekend of 5-6 Sep plus Labor Day 7 Sep.
LAST USEFUL CAPTURE:   2026-09-04T20:02:02.655137Z (POST_CLOSE_SEAL, 16/17 sources)
RECORDS LOST:          NONE established. No poll was scheduled during the gap, so nothing was
                       fetched and discarded. Whether any weekend news existed that a 24/7
                       capture would have caught is UNKNOWN and unknowable from this host.
USEFUL WORK:           YES on trading days (267 work items, 640 cycles, 7 trading days);
                       correctly idle otherwise.
OUTPUT PATH:           CORRECT. /apex-data/runtime/results -> /apex-data/core, so the code's
                       results/catalyst/events.jsonl resolves to the observed file.
SERVICE ACTION:        NONE. No restart, no reload, no code change, no data modified.
PROTECTED SURFACES:    unchanged. Bound tree 616a1912 unchanged.
```

## 1. I was wrong, and this is the correction

In EVENT-SOURCE-001 I wrote that the capture was *"silently stale"* and an
*"operational integrity failure"*. **That conclusion was wrong.** The
service was idle because the market was closed — a weekend followed by Labor
Day — and I compared its last write against wall-clock now without
consulting the exchange calendar, in the very programme where I had just
built and independently reconciled that calendar.

The decisive evidence is that **the previous weekend shows the identical
gap**: 91 cycles on Friday 28 August, **zero** on Saturday and Sunday, 93 on
Monday 31 August. The pattern was in the data I had already scanned.

The service's live phase, evaluated read-only, is
`{"phase": "IDLE", "session": "2026-09-07", "why": "2026-09-07 is not a trading day"}`,
and the process is asleep on a timer (`wchan hrtimer_nanosleep`), with no
journal output at all since the last cycle.

## 2. Artifacts

| Artifact | Location |
|---|---|
| `CATALYST_CAPTURE_HEALTH_DIAGNOSIS_V0` | `docs/CATALYST_CAPTURE_HEALTH_DIAGNOSIS_V0.md` |
| `CATALYST_CAPTURE_HEALTH_EVIDENCE_V0` | `results/CATALYST_CAPTURE_HEALTH_EVIDENCE_V0.json` — 14 facts, each tagged observed or inferred, with command and hashes |
| `CATALYST_CAPTURE_HEALTH_METRICS_V0` | `results/CATALYST_CAPTURE_HEALTH_METRICS_V0.json` — the nine measures kept separate |
| `CATALYST_STALL_REPAIR_PROPOSAL_V0` | `docs/CATALYST_STALL_REPAIR_PROPOSAL_V0.md` — proposed, unimplemented |
| this return | `docs/CATALYST_STALL_001_RETURN.md` |

## 3. The nine measures, separately

| Measure | Value | Verdict |
|---|---|---|
| process liveness | PID 737236, up 5 d 20 h, sleeping on a timer | ALIVE |
| successful source contact | 10,285/10,871 (94.6%) | healthy |
| accepted observation | 5,209 of 223,532 offered (2.33%) | dedup as designed |
| persisted observation | 5,209 observations, 5,163 events, 46 updates | matches |
| heartbeat freshness | 30 s | FRESH |
| output freshness | 3 d 6 h 30 m | STALE by clock, **EXPECTED by calendar** |
| useful-work count | 267 | consistent with 7 trading days |
| error count | 586 source failures; 633/640 cycles carry a `last_error`; heartbeat `last_error: null` | see below |
| silent-discard count | 218,323 deduplicated (counted); ~426 cycles refused ≥1 event (cycle log only) | see below |

**`ActiveState=active` was never treated as proof of work.**

## 4. Two real defects found

1. **BLS fails on essentially every cycle** — `unexpected shape ('series')`,
   a parser/schema rejection, never escalated because a per-source failure
   is not a service error. This is the macro source, the family named as the
   best first event candidate.
2. **Refusals are invisible outside the cycle ledger** — 389 cycles refused
   an interpreted event because *the LLM cited sources that were never
   retrieved*, plus 88 interpreter timeouts and 12 malformed JSON responses.
   The anti-fabrication guard is working; nothing outside `cycles.jsonl`
   reports that it fired.

## 5. The legibility gap that is real

An operator cannot distinguish "idle because closed" from "broken" without
evaluating the phase function by hand — as I had to, after getting it wrong.
The heartbeat separates presence from work (better than I credited) but
carries neither `idle_reason` nor `work_expected_next_utc`, though
`phase_at()` computes exactly that and discards it. §2 of the repair
proposal closes it in six fields.

## 6. Verification

No tests were added: this brick changed no code. The smallest relevant
regression was run to prove the read-only inspection disturbed nothing:

```text
7 modules, 7 rc=0, 182 passed, 0 failed, 0 skipped, 0 errors, 0 OOM; MemoryMax=1400M per shard, User=apex
test_catalyst_capital 39 | test_catalyst_commissioning 61 | test_catalyst_eyes 10 | test_event_capture 3
test_event_admissibility 25 | test_event_source_certification 20 | test_parallax 24
```

Scope: the catalyst and event modules. No World Model regression: no code
changed anywhere in this brick.

Service state after the diagnosis, unchanged from before it:
`ActiveState=active ExecMainPID=737236 NRestarts=0 ExecMainStartTimestamp=Wed 2026-09-02 06:19:35 UTC`.

Protected surfaces, before and after:

```text
world_model_surface   a35afdd54ddbc6dc21eb48bfce94ffad9acb2d31b820d941a37f9038adb402f3
registrations         47b33a1247cd264ab5312d7ae32391c89be7b479aff4d5d2b1eeb12c107ab514
twin_contracts        dd904e978bd2a43ec293cb30c7b1ba0617ea89c057b4ee3f452f2ee70e7577f9
catalyst_events       303a8c2d8bc9fd7640acb4bfc9843be276a1ab535248fb15ec74b1674efa75dd
risk_book             8ba6574d66683df2683a5ea45e2229cddfe914f9ee26f69bf8fe762fa638bc0d
real_data_boundary    7612e5dde3c39705971c15dc7a18789192f990444ea417a86860608a5c738e6f
chain_ledger          f802d77b118fced57e6f08cd74bd4fbc181cf4398c0f5b23e5e633dda549024d
```

Identical to the EVENT-SOURCE-001 post-state: `UNCHANGED_VS_EVENT_SOURCE_001: True`.

Out of scope by instruction and recorded as a separate downstream defect:
the RFC-2822 vs ISO `event_time` mismatch (2,284 of 5,163 records).
