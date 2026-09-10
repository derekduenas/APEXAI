# EXP-004 memory qualification at registered scale

**Synthetic only. No admitted data, no admission, no historical execution.**
Registration hash unchanged: `9155024f…45bf9`.

Why: `run.tournament` holds full session objects for **both** periods, where
EXP-002's adapter converted each session to rows and discarded it. Peak memory
was unestablished, and EXP-001B's first historical attempt was OOM-killed.

---

## 1. The first two runs are WITHDRAWN — attribution could not be established

The runs recorded at commit `430f4ff2` completed and their arithmetic was
sound, but the script did not capture what the process executed, and the script
itself was committed **after** those runs. Committing it afterwards does not
establish facts about the completed processes. Both artifacts
(`results/exp004_memory_reduced_B.json`, `results/exp004_memory_full_B.json`)
are **deleted, not corrected**.

**What is recoverable, and by what means.** Both units were `--collect`ed, so
`systemctl show` returns empty `InvocationID` and `ExecMainStartTimestamp`; the
only retained evidence is the two JSON artifacts and two logs, none of which
carries a commit, tree hash, or interpreter version.

From file timestamps and commit times one can *reconstruct* that the run
finished 05:26 UTC, that `HEAD` was `8f52bd57` (committed 04:58) and that
`430f4ff2` (which first added the script) was committed at 05:27:49 — implying
the checkout carried an untracked script during the run. **This is a timeline
reconstruction from mtimes and commit timestamps, not process-captured
evidence, and it is not offered as attribution.** No executed commit,
bound-tree hash, checkout cleanliness, or interpreter/NumPy version can be
established for those processes.

**Remedy taken:** the registered-B qualification was repeated from a frozen,
clean checkout with the process capturing its own provenance. Nothing from the
withdrawn runs is carried forward as evidence.

## 2. Three reporting corrections

- **Units.** The withdrawn record labelled the cap and peaks "MB" where the arithmetic was **MiB** (1024²). The script now emits `*_MiB` fields with the unit stated in the record.
- **Sampling scope.** The old sampler polled `memory.current` only and read `memory.events` once, at exit — so "no OOM events" rested on a final cumulative read. It now samples `memory.events` **throughout**, reports both the maximum seen across samples and the final read, and preserves the **complete trajectory** rather than only its maximum.
- **Parameter provenance.** `bootstrap_resamples_used` copied the command-line argument, so requesting `20000` would have executed the registered `10000` while reporting `20000`. The script now (a) **refuses** an unsupported value up front — the adapter path accepts only the registered `B`, and a synthetic value is validated by `resolve_inference_parameters` before anything runs — and (b) reports `inference_parameters_used` **read back from the run record**, refusing on any mismatch.

## 3. Scope of what a passing run establishes

- Two runs at two values of `B` do **not** establish general flatness in `B`. The structural reason to expect little dependence is that the bootstrap allocates one array of `B` floats (80 KiB at `B` = 10,000); that is an argument, not a measurement, and only the measured points are claimed.
- This exercise uses **synthetic on-demand loading with `ledger_dir=None`**. The governed path — the admitted loader, import-provenance verification, run-directory creation and result sealing — is **not** exercised. Capacity under the governed path is a separate question.
- The systemd unit summary line disagreed with the in-unit cgroup measurement. That line is excluded from headroom evidence here; **no general claim about systemd instrumentation is made**, and the discrepancy is unresolved.
- Synthetic bars, not admitted data; one machine; one run per configuration; no distribution claimed.
- It establishes **capacity only** — not correctness, alpha, options profitability, GARCH value, or a time machine.

## 4. Method of the attributable run

`scripts/exp004_memory_qualification.py`, **committed at `2200c668` before the
run**, executed from a frozen `git worktree` at that commit (verified clean,
0 modified files), inside a `systemd-run` unit at the intended
`MemoryMax=1400M`, as `apex`, in `wmresearch.slice`.

The process itself records, before measuring: executed commit, bound-tree
sha256 and file count, the dirty list (and **refuses to run** if non-empty),
the resolved `__file__` of every module in the EXP-004 chain plus any module
loaded from outside the checkout, `sys.executable`, the interpreter version and
the NumPy version. Source identity is recomputed at completion and compared.

## 5. Result — attributable run at registered inference

Record: `results/exp004_memory_adapter_registeredB.json`.

**Provenance, captured by the process before measuring:**

| | |
|---|---|
| executed commit | `2200c668e96b64fb644ec4e670ba3554be9f1eb2` |
| bound tree sha256 | `8fbe6ed6155df0e4b8fb09f6dd8ce54c7e1cf064cea29592e08fa44a41996991` (67 files) |
| dirty | `[]` — the script refuses to run otherwise |
| source identity at completion | **unchanged** |
| interpreter / NumPy | CPython 3.12.3 / 2.4.6 |
| modules loaded outside the checkout | none |
| entry point / run mode | `run.tournament` → **HISTORICAL** |
| inference parameters **used** (read back from the record) | `B = 10,000`, seed `20260909`, `registered_values: true`, `historical_path_valid: true` |

**Measurement, full registered scale** — 754 fit sessions (2016-01-04 →
2018-12-31), 757 development sessions (2019-01-01 → 2021-12-31), 247,740
eligible fit rows, 248,730 eligible development rows:

| | bytes | MiB |
|---|---:|---:|
| cgroup `memory.peak` | 772,960,256 | **737.2** |
| cap (`memory.max`) | 1,468,006,400 | 1,400.0 |
| headroom at measured peak | 695,046,144 | **662.8** |
| peak fraction of cap | | **0.5265** |

`memory.events` sampled **throughout** and at completion, identical:
`low 0, high 0, max 0, oom 0, oom_kill 0, oom_group_kill 0`. Elapsed **723.5 s
(12 min 4 s)**; completion `NOT_SELECTED`.

**Finding.** On this synthetic fixture, at full registered scale and registered
inference, the implementation peaks at about 53% of the cap with ~663 MiB
headroom and no limit or OOM events at any sampled point. The precondition
recorded in the adapter brick — that holding full session objects for both
periods might not fit — **does not materialise here**, subject to every limit
in §3, in particular that the governed loading, provenance and sealing path is
not exercised and that this is not admitted data.

The systemd unit summary again reported a figure (`3.2M`) irreconcilable with
the in-unit cgroup peak of 772,960,256 B. It is excluded from evidence; the
discrepancy remains unresolved and no general claim is made about it.
