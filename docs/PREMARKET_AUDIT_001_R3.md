# PREMARKET-SEQUENTIAL-AUDIT-001-R3 — Checkpoint 1A (2026-09-13)

Base `bac7486cc365e232de8f1660ee35e197fe6fc6a7` (verified). **Production scheduler NOT installed. No disposable
LaunchAgent was created.** Holds intact.

## 1. R2 status narrowed

**`STAGED_PREMARKET_ORCHESTRATION_SYNTHETICALLY_VERIFIED`**

| | |
|---|---|
| source-fixture processing | **PASS** |
| staged orchestration | **PASS in controlled time** |
| packet builder and sealer | **PASS** |
| Captain generation | **NOT TESTED** — recorded response |
| live providers | **NOT TESTED** |
| operating-system scheduling | **NOT TESTED** |
| production packet consumer | **MISSING** |

**And a correction to my own words:** I wrote *"Simulation complete with no defect found"* in the same turn the
simulation surfaced the early-wake defect. That was wrong. **The simulation found a defect.**

## 2. Was the production runner repaired? **No — and my R2 report was ambiguous in the direction that favoured me**

```
prepared plist  -> ops/premarket.sh  -> scripts/premarket_run.py
scripts/premarket_run.py  executable sleep() calls: 2
```

Only `apex/audit/fake_morning.py` was staged. The production path was untouched. You asked the question that
exposed it.

### The defect, reproduced

With a normal 08:14 ET start the defect is **dormant** — all four stages fire on target. It bites when the process
starts well before the first target:

```
start 02:00 ET (a coalesced wake -- launchd's documented post-sleep behaviour)
0815_ET_initial   target 08:15   absorbed 03:00   EARLY by 18900s
0832_ET_post_macro target 08:32  absorbed 04:00   EARLY by 16320s
0905_ET_refresh   target 09:05   absorbed 05:00   EARLY by 14700s
0920_ET_final     target 09:20   absorbed 06:00   EARLY by 12000s
```

The packet would be labelled `0815_ET_initial` while containing 03:00 ET data, and **nothing would record the
discrepancy** because `as_of_time` is stamped at seal. This is exactly the interaction with the coalescing
behaviour I got wrong two rounds ago: the correction and the defect are the same fact seen from two sides.

### The replacement

`scripts/premarket_stage.py` — one bounded invocation per stage, **zero executable `sleep()` calls** (verified by
AST, not grep). Each invocation claims one stage, writes its run record before anything can fail, takes the
durable lock, and **decides a disposition instead of sleeping**:

```
03:00 ET -> TOO_EARLY      08:15 ET -> ON_TIME
08:22 ET -> LATE_START     08:40 ET -> MISSED_WINDOW
```

Plus a `reconcile` stage that records missing stages as `LATE_START` or `MISSED_WINDOW` and **fetches no
retrospective data**.

## 3. What is NOT done, stated plainly

**`premarket_stage.py` is a staged SHELL.** It implements startup accounting, stage claiming, disposition,
locking and reconciliation. Its `SOURCES` stage is `NOT_IMPLEMENTED_IN_THIS_BRICK` — **the real `absorb()` logic
has not been ported into it**, and the prepared plist still points at the old runner.

So the production runner is **not yet replaced**. The scheduling *logic* is repaired and proven; the *producer*
is not.

**The disposable LaunchAgent proof was not attempted.** The brick gates it on the production repair
("if the production runner remains long-lived, repair it before the disposable LaunchAgent proof and rerun the
synthetic morning through the actual production entry point"). The repair is half done — logic yes, absorption no
— so the precondition is not met and running the OS proof now would test a path that is not the production path.

## 4. Revised Checkpoint 1A verdict

**FAIL — unchanged.** Scheduler mechanics cannot pass: the candidate production entry point is not yet truly
staged end to end, and no OS-level proof has been run.

Remaining, in order:
1. Port `absorb()` into `premarket_stage.py`; repoint `ops/premarket.sh` and the plist at it.
2. Rerun the synthetic morning **through the real production entry point**.
3. Then the disposable LaunchAgent proof (RunAtLoad, real calendar trigger, pre-log failure, duplicate, overlap).
4. Then install, arm, and observe one real scheduled morning.
