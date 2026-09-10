# EXP-004 memory qualification at registered scale

**Synthetic only. No admitted data, no admission, no historical execution.**
Registration hash unchanged: `9155024f…45bf9`.

Why: `run.tournament` holds full session objects for **both** periods, where
EXP-002's adapter converted each session to rows and discarded it. Peak memory
was therefore unestablished, and EXP-001B's first historical attempt was
OOM-killed. The adapter brick recorded this as a precondition; this measures it.

## Method

`scripts/exp004_memory_qualification.py`, run inside a `systemd-run` unit at the
intended `MemoryMax=1400M`, as the `apex` user, in `wmresearch.slice`.
Sessions are generated **on demand by the loader**, mirroring the governed
loader's shape, so the fixture does not itself hold every session — what is
measured is the adapter accumulating them, which is the actual risk.

Measurement discipline, following the EXP-001B review:

- counters sampled **throughout** (0.25 s interval), not once at exit;
- read from the **running process's own cgroup** via `/proc/self/cgroup`, so the numbers are attributable to this unit and survive `--collect`;
- `memory.events` oom counters recorded;
- `VmHWM` recorded independently of the cgroup;
- an external monitor sampled the same cgroup every 30–60 s as a second, independent record.

## Results — full registered scale, 1,511 sessions

754 fit sessions (2016-01-04 → 2018-12-31) and 757 development sessions
(2019-01-01 → 2021-12-31): 247,740 eligible fit rows, 248,730 eligible
development rows.

| | reduced B = 200 | **registered B = 10,000** |
|---|---|---|
| entry point | synthetic (`SYNTHETIC_TEST`) | **adapter → `run.tournament` (`HISTORICAL`)** |
| cgroup `memory.peak` | 771,125,248 B (735 MB) | **766,705,664 B (731 MB)** |
| sampled max `memory.current` | 759,291,904 B | 759,746,560 B |
| `VmHWM` peak RSS | 788,533,248 B | 784,642,048 B |
| cap | 1,468,006,400 B (1400 MiB) | 1,468,006,400 B |
| **peak fraction of cap** | 0.5253 | **0.5223** |
| headroom | 696,881,152 B (665 MB) | **701,300,736 B (669 MB)** |
| `memory.events` | `low 0 high 0 max 0 oom 0 oom_kill 0` | `low 0 high 0 max 0 oom 0 oom_kill 0` |
| in-unit samples | 484 | 2,448 |
| elapsed | 142.7 s | **702.3 s (11 min 42 s)** |
| status | NOT_SELECTED | NOT_SELECTED |

**Memory is flat in B**, as the structure predicts: the bootstrap's own
allocation is one array of `B` floats (80 KB at B = 10,000), so the 50× increase
in replicates changed peak memory by −0.6%. The external monitor's trace agrees
with the in-unit sampler: 510 → 712 → 731 MB, then flat at 731 MB for the last
ten minutes while the bootstraps ran.

**Findings:**

1. The recorded precondition does **not** materialise. Peak is ~52% of the cap with ~669 MB headroom at full scale and registered inference; no `oom`, `oom_kill`, `high` or `max` events. Holding full session objects for both periods is affordable at this scale, on this fixture.
2. Runtime at registered inference is **~12 minutes**, dominated by ~132 bootstrap calls. That is well inside the launcher's behaviour for EXP-002 (46 min) and EXP-001B (21 min).
3. **systemd's own summary line is again wrong.** It reported `Memory peak: 2.2M` for a run whose own cgroup peak was 766,705,664 B. This independently confirms the earlier finding that that line is unattributable telemetry and must not be quoted as headroom evidence — the in-unit cgroup measurement is the one that counts.

## Limits of this evidence

- Synthetic bars, not admitted data. Real sessions may differ in bar counts (holidays, early closes, gaps), which changes row counts and therefore array sizes. The row counts here (247,740 / 248,730) are close to EXP-002's admitted counts at comparable scale (247,692 fit), so the shape is representative, but it is not a measurement on admitted data.
- One machine, one run per configuration. No distribution over repeated runs is claimed.
- This establishes **capacity**, not correctness of any result, and no alpha, options profitability, GARCH value, or time machine.

Records: `results/exp004_memory_reduced_B.json`, `results/exp004_memory_full_B.json`.
