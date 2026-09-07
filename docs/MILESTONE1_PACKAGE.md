# MILESTONE 1 — consolidated package: operational recovery and the first registered experiment

Two priorities, reported separately. Every status below is one of:
implemented · integrated · tested · historically evaluated · prospectively
validated · authorized for production. They are not interchangeable.

---

## PART A — OPERATIONAL RECOVERY

### A1. Candidates and evidence commits

| Line | Commit | Branch | Role |
|---|---|---|---|
| **Deployed recovery candidate** | `73fc712d355032e0a66b41675ba114491b04799d` | `milestone1-recovery-candidate` | off the running release `5eff1cf5`; seven files, two production |
| Integration candidate | `295d80e4243077ebd6b38875a45dd4cb6959f517` | `milestone1-r2` | full development line; carries the same two production files |
| Deployment + regression evidence | `289f4b34`, `d9850e6e` | `milestone1-r2` | package v3, final regressions, gated-deploy record, pre-deploy artifacts |
| Commissioning evidence | *see A7* | `milestone1-r2` | observer output and verdict |

Historical, not targets: `39bd4412`, `07dcbb05`, `658e6971` (earlier forms
of the recovery candidate); `3b9a26f2`, `1bb32df1` (earlier integration).

### A2. What changed in production — two files

| File | Change | Closes |
|---|---|---|
| `apex/governance/chain_ledger.py` | **R1** bounded previous-hash search, 256 KiB widening to a declared 8 MiB ceiling, then `ChainTailUnresolved` before any write | the amplifier: a 262,275-byte final record forced a whole-file read of 438 MB needing 1267 MiB against a 512 MiB cap |
| `scripts/apex_orchestrator.py` | **R2** bounded incident history: deferrals held apart from recovery attempts, count + first/last + sample, ≤7 entries | the generator: 1907 identical per-tick entries re-serialised into every record |
| | **R3** maintenance preflight: asks systemd for the unit's drop-in conditions and tests the declared markers; BLOCKED and INDETERMINATE refuse, fail closed | a doomed start being attempted and mis-recorded |
| | **R4** truthful launch reporting: bounded `systemctl start`, result captured, unit state read; outcomes `START_COMMAND_FAILED` / `CONDITION_REFUSED` / `PROCESS_ACTIVE` / `START_UNCONFIRMED`; `STARTED` removed | three refused starts recorded as `STARTED` on 2026-09-04 |

Five test files accompany them. The tests carry no production authority.

### A3. Corrections made along the way, kept visible

- **"Maintenance enforcement was absent" was wrong.** Both blocked units carry
  a systemd drop-in with `ConditionPathExists=!<marker>`; the orchestrator
  starts through `sudo -n systemctl start`; systemd refuses. Verified with
  `systemd-analyze condition`. The real defect was the orchestrator not
  *knowing* — `systemctl start` exits 0 on a condition-skipped unit.
- **Marker location** is `/apex-data/core/ops/`, reached through a symlink from
  the runtime path I first quoted.
- **The seven-day loop duration** was wrong; the journal retains eleven days
  and shows the loop began 2026-09-06T04:51:05Z.
- **D3/D4 in the blocker table** quoted intermediate PULSE-008 findings as
  current; the final stage shows all five comparable subjects consistent with
  an empty violation set. My proposal to relax a declaration is withdrawn.
- **Commissioning counters** were first taken from the research harness slice,
  which is unrelated; the unit sits in `/apex.slice/apex-market.slice`, shared
  by five units, and only the unit's own signals attribute anything.
- **A gate script aborted the first dry-run** because `systemd-analyze`
  exits nonzero when a condition *fails* — the wanted answer — and `pipefail`
  overrode grep's match. Fixed to test the output. The abort read as a
  production state change and was not one.
- **Two `results/` subdirectory commits** were silently excluded by an ignore
  pattern; both re-added under flat names.

### A4. Regressions at the integration boundary (source provenance)

Each candidate in its own clean worktree, manifest of every tracked file
before and after, outputs outside the tree, subprocesses pointed at the
candidate, explicit exit status per shard.

| Run | Commit | Shards | Passed | Failed/Err | Skipped | Collected = executed | Manifest | OOM |
|---|---|---|---|---|---|---|---|---|
| `integration3` | `295d80e4` | 217 | 3880 | 0 | 19 | 3899 = 3899 | `8596a099` unchanged | 11 → 11 |
| `recovery3` | `73fc712d` | 16 | 268 | 0 | 4 | 272 = 272 | `9ca27c5a` unchanged | 11 → 11 |

The recovery run is focused (chain-primitive consumers plus the four new
modules); it is the candidate-specific gate the deployment required. Neither
result transfers to the other candidate.

**Supplemental verification** of the five integration shards that read
outside their worktree: all five pass; 720 discovery-observed paths hashed
before and after, none changed; five verification-only paths are the
instrument's own logs, reported as *uncovered*, not verified. Verdict
`PASS_WITH_UNCOVERED_INPUTS`. The shared checkout was pinned to the
candidate commit throughout (re-pinned at shard 41, released 15:45:07Z after
the supplemental).

**Limitations preserved.** The audit hook does not see native-code file
access, children that do not inherit the audit environment, memory-mapped
reads, or inherited descriptors. The observed set is a lower bound. An
earlier run (`integration2`, on the superseded `1bb32df1`) was stopped at
shard 114 when R4 landed; its partial log is retained.

### A5. Deployment — executed under the established conditions

Gated script `scripts/milestone1_deploy_gated.sh`, fail-stop, every
condition checked by command and re-checked at execution:

both regressions PASS on the exact commits with manifests held · candidate
commit exists · seven-file inventory, two production · current release was
`5eff1cf5` · unit `MemoryMax` 512 MiB unchanged · orchestrator still in the
OOM loop · both maintenance markers present · equity-fabric drop-in declares
its marker · systemd verified to refuse the blocked start · orchestrator
starts via systemctl · R3 preflight and R4 vocabulary present · five ledger
prefix hashes captured · orchestrator ledger still 438,867,453 bytes · host
memory and disk headroom.

Swap at **2026-09-07T15:46:07Z**. No service was restarted. The orchestrator
loaded the release on its own next restart at **15:46:21Z** (anchor T0,
N0 = 4017) and completed a tick on its first sample.

**Loaded-process accounting.** The symlink selects code at process start. The
orchestrator restarted and runs R1–R4. The seven long-lived writers holding
the chain primitive in memory (`apex-btc-derivatives`, `apex-btc-ws`,
`apex-organism`, `apex-catalyst`, `apex-equity-shadow`, `apex-equity-field`,
`apex-edgeforge-observatory`) **still run the old reader** until they next
restart. That mixed state is acceptable because their ledgers' tails are
inside the old 256 KiB window, and it is the meaning of "no unrelated
restarts". The service actions that would bring them onto R1 are listed in
the deployment document and were **not** executed.

### A6. Maintenance behaviour, verified read-only on the deployed release

| Service | Supervised by | Preflight from `73fc712d` |
|---|---|---|
| `equity-fabric` | orchestrator | **BLOCKED** — `/apex-data/core/ops/MAINTENANCE_BLOCK_equity_fabric` |
| `options-paper` | orchestrator | NOT_BLOCKED — unit declares no maintenance condition |
| `btc-paper` | systemd | verified only, never started |
| `edgeforge-observatory` | systemd | verified only, never started |

Phase at deployment: IDLE (Monday, non-trading). No launch is attempted in
this phase. The first phase in which a launch can occur is RTH on
**Tuesday 2026-09-08 from 13:30Z**, and the only service the recovered
orchestrator would try to start is `options-paper`, up to three attempts,
each classified truthfully. That is the pre-existing intended behaviour of the
running release, not new authority; if it is unwanted, the same drop-in
convention blocks it and the reviewer has until 13:30Z.

**Race limits, restated.** The preflight is a file-existence check, not
atomic with block creation; a block written after preflight is caught by
systemd and classified `CONDITION_REFUSED`. Systemd remains the enforcing
authority.

### A7. Commissioning — thirty-minute observation: **PASS**

Observer `scripts/milestone1_commission.py`, anchored on the first start of
the new release (T0 = 15:46:21Z, N0 = 4017), thirty samples at one-minute
intervals, judged on completed work and the unit's own counters. The shared
slice counter was never used.

| Check | Result |
|---|---|
| Restart counter static at N0 | true — 4017 throughout |
| No oom-kill journal line since T0 | true — 0 |
| Unit `Result` | `success` (was `oom-kill` for ~16 h) |
| Heartbeat `last_work_utc` advancing | true — every ~60 s |
| `work_completed` climbing | true — 1 → 30 over the window |
| Unit `memory.peak` under the 512 MiB cap | true — **13.5 MiB** maximum |
| Orchestrator ledger growing | true — 438,867,453 → 438,890,350 bytes (~30 records) |
| Newest record bounded | true — ~760 bytes, ≤7 history entries |
| No `STARTED` outcome in any new record | true |
| All five ledger prefixes identical at recorded length | true |

| Ledger | Recorded length | Size after | Prefix |
|---|---|---|---|
| ops/orchestrator.jsonl | 438,867,453 | 438,890,350 | identical |
| historical/continuous/decisions.jsonl | 687,925,800 | 687,925,800 | identical |
| btc/derivatives_ledger.jsonl | 439,994,687 | 440,659,836 | identical |
| btc/ws_book_ledger.g2.jsonl | 143,531,010 | 143,746,470 | identical |
| historical/continuous/outcomes.jsonl | 65,593,558 | 65,593,558 | identical |

Two ledgers grew by their own writers' live appends during the window; the
prefix at the recorded length is byte-identical in every case. For
comparison, the healthy long-lived process before the incident peaked at
349.9 MiB; the recovered process, with the bounded lookup and bounded history,
peaks at 13.5 MiB doing the same work.

**What this establishes.** The orchestrator is doing useful work again under
its existing cap, the ledger is preserved, and no service was restarted. It
does not establish anything about launch behaviour under RTH, which first
occurs Tuesday 13:30Z, nor anything about the seven long-lived writers still
running the old reader.

**Status: operational recovery authorized for production under its
established conditions and commissioned.**

### A8. Rollback

```bash
sudo ln -sfn /opt/apex/releases/5eff1cf5e00f21b02c537f25bcd74b1c1d317546 /opt/apex/current.new \
  && sudo mv -T /opt/apex/current.new /opt/apex/current
```
Reaches only processes that restart. The orchestrator would return to being
killed every ~31 s, because the oversized record is still on disk and the old
reader is the defect. **Rollback does not restore health.** Triggers: any
ledger prefix changes or shrinks; `ChainTailUnresolved` on any other ledger;
a healthy service starts failing; the orchestrator starts a service under a
block (which would mean the drop-in was altered).

### A9. Registered, not repaired

- `start()` records `START_COMMAND_FAILED`/`UNCONFIRMED` truthfully now, but
  the `DRY_RUN` path still records an attempt without a command, by design.
- Three hard-coded absolute paths remain in tests (research-board
  interpreter, whole-ledger guard's audit subject, two PULSE fixture reads);
  five instances in this milestone, two fixed.
- `apex-gate2-opener.service` is in state failed; untraced; not declared
  noncritical.
- Seven names defined twice in `apex/ops/orchestrator.py`; dead code.
- The healthy orchestrator's historical peak was 349.9 MiB under a 512 MiB
  cap, ~32% headroom; a watch item.

---

## PART B — ALPHA-EXP-001 (implemented and tested in engineering mode; not historically evaluated; not admitted)

### B1. Commits

| Commit | Content |
|---|---|
| `7f26e938f71741bb7740a83a46851e682c557bbb` | registration, research path, 13 engineering tests, eligibility, admission document |
| `4074017291114abcb8b19172af3edf2f24d2bc41` | qualifications: test-development record, corrected power calculation, three-way distinction |

Branch `alpha-exp-001`, off `world-model-shadow-v0` at `d01e961b`. The
laboratory is reused unmodified: its source boundary, forecast contract,
sealed grader, dependence-aware statistic and null rule.

### B2. Hypothesis, registration, statistic

- **Hypothesis.** Conditional on the last 1 and 5 one-minute returns and the
  trailing 30-bar realised volatility, the 15-minute forward log return of SPY
  in the regular session has a distribution that a volatility-scaled Gaussian
  with a fitted conditional mean predicts with higher out-of-sample log
  likelihood than the same Gaussian with zero mean.
- **Why it might not be priced** is stated as a plausible mechanism, flagged
  `MECHANISM_IS_NOT_A_FACT`: the effect, if any, is smaller than the spread
  that would pay to price it — which is also why it may not pay us.
- **Registration.** `EXP001_REGISTRATION_V0`, hash
  `1a3f55a522f7595f179033827ad10d87e873b7839f1cc08fb05624067c8f391c`,
  committed at `7f26e938` **before any real row was read**; none read since.
  One baseline, one challenger, zero tuned hyperparameters; train 2016–2019,
  validation 2020–2021, evaluation 2022–2024 **sealed in code**, reserve
  2025+ untouched; 15-bar embargo; N0 block-permutation null.
- **Primary statistic.** `DEPENDENCE_AWARE_DM_HAC_V0`: d = logL_M1 − logL_M0,
  Bartlett kernel, L = 14, threshold 2.0 one-sided, n ≥ 60.
- **Economics.** Expression set {CASH, LONG_15M, SHORT_15M}; declared 2 bps
  spread crossed twice; certified 1R = stop distance + round-trip spread;
  dependence-aware standard error on realised after-cost return versus CASH.
  Option-implied benchmark at 15 minutes: `NOT_ESTIMABLE`, not claimed.

### B3. Engineering-mode evidence — proves integration only

Thirteen tests on deterministic synthetic fixtures through the real boundary:
real-evidence path refused as a *result*; forbidden class refused by name;
fixture without provenance refused; missing bars `INVALID_INPUT`;
insufficient rows named; warm-up carries a reason, not zeros; pure noise →
`NO_SIGNAL` with evaluation sealed; planted structure → `SIGNAL_DETECTED` on
validation with evaluation *still* sealed; unsealed evaluation reaches the
economic stage and writes attribution; cost veto selects CASH; no broker
dispatch reachable; sealed-forecast hash checked by the grader.

**Positive-control history — test development, recorded.**

| Attempt | Fixture | n | gain | HAC SE | iid SE | t | Verdict | N0 t |
|---|---|---|---|---|---|---|---|---|
| 1 | AR(1) φ=0.35, 8 sessions | 662 | — | — | — | — | NO_SIGNAL | — |
| 2 | φ=0.60, 12 sessions | 993 | — | — | — | — | NO_SIGNAL | — |
| diag | φ=0.00, 16 | 1324 | −0.0015 | 0.0040 | 0.0015 | −0.39 | NO_SIGNAL | +0.87 |
| diag | φ=0.60, 16 | 1324 | −0.0066 | 0.0128 | 0.0080 | −0.51 | NO_SIGNAL | −2.25 |
| 3 | **φ=0.90, 16** | 1324 | +0.1146 | 0.0550 | 0.0245 | **+2.08** | SIGNAL_DETECTED | −4.43 |

The final PASS proves the pipeline detects *that* synthetic structure at
~1,300 rows and that the null control then returns NO_SIGNAL. It does not
establish sensitivity to plausible market effects; a one-minute AR(1) of 0.9
is far outside anything expected in SPY. The moderate fixture's *negative*
gain shows the OLS mean costs out-of-sample likelihood when the effect is
weak.

### B4. Power — ILLUSTRATIVE, corrected

My earlier "t ≈ 0.3" was withdrawn: written out, it was wrong by an order of
magnitude. Under E[d] ≈ R²/2, SD[d] ≈ √R², n ≈ 170k validation rows, and HAC
inflation 2.2× (measured on fixtures) to 3.2× (theoretical):

t ≈ √(n·R²) / (2 · inflation) → R² 0.01%: ≈0.9 · R² 0.1%: ≈3.0 (2.0) · R² 1%: ≈9.

These figures **do not establish the power of the statistic** without a
justified mapping from explained variance to the log-likelihood differential
under the actual models, and they **do not establish what effect sizes are
plausible** in real markets. They bound expectations only. NO_SIGNAL is an
expectation at the low end; it is not a predetermined verdict.

### B5. Data eligibility — a submitted assessment, pending review

| Source | Classification (submitted) | Binding limitations |
|---|---|---|
| `history-b/etf_continuous`, SPY, Alpaca SIP raw 1m, 2016-01-04→2026-08-28, corpus `5c0d768b7ee2ea14`, 0 missing sessions | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS | no per-bar receipt/publication time; bulk-retrieved 2026-08-29 as the vendor's view *then*; corrections invisible; no bid/ask/spread/trade_count; extended-hours excluded by design |
| `history-b/pit_singlename`, 300 names, monthly PIT membership decided before each month | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS, for a later cross-sectional experiment | same bar limitations; a superseded defective membership file retained |
| `history-a/options_history`, 6 underlyings, 2018→, per-file `acquired_at`, per-row source timestamps | ELIGIBLE_WITH_EXPLICIT_LIMITATIONS for daily-or-longer horizons | NOT_ESTIMABLE as a 15-minute benchmark |
| ThetaData pilot sample (85 sampled days) | BLOCKED for EXP-001 | stratified pilot; superseded by S1 |
| Live capture (7 sessions) | prospective substrate only | too short for history |
| decisions/outcomes ledgers | BLOCKED as input | contain resolved outcomes; cost model reused as a model, not as data |

Time roles are held apart in the document: event, receipt, publication,
revision, decision cutoff, outcome. Receipt establishes possession, not
earlier publication.

### B6. The exact admission blocker, and the proposed separate contract

Three distinct things:

1. **The synthetic laboratory's prohibition** (`WORLD_MODEL_SOURCE_BOUNDARY_V0`):
   real-evidence roots refused by resolved path, permitted classes limited to
   fixtures, no override. A property of the lab. **Intact and must remain so.**
2. **Dataset eligibility** — a property of the data, submitted above.
3. **A separately governed real-data research path** — the reviewer's
   decision and a new authority.

EXP-001 is BLOCKED by the absence of (3) and the correct refusal of (1); not
by (2). Attempting the run produces, as a result:
`REAL_EVIDENCE_PATH: /apex-data/history-b/... resolves inside /apex-data/history-b`.

**Proposed separate admission contract.** A real-data research boundary,
distinct from the laboratory's, that: admits a dataset only against an
explicit eligibility record and a per-file provenance manifest (corpus
version, sha256, vendor, retrieval date, per-field limitations); forbids the
same categories the lab forbids (labels, resolved outcomes, book P&L,
execution results); records every admission as a chain-appended decision;
and through which `exp001.run` executes unchanged, since its loader takes the
boundary as a parameter. Extending the lab's own boundary is withdrawn as a
recommendation; mirroring real bars into the fixture root is retained only as
a documented expedient.

**Ready-to-run configuration** for the first real run is in
`docs/EXP001_ADMISSION_AND_READINESS.md`, sealed evaluation enforced in code.

### B7. Prospective readiness

Forecast-before-outcome persistence and delayed grading are implemented and
tested. The prospective substrate is the receipt-stamped live capture. **Not
activated**; it needs the same admission decision, and calendar time is the
binding input.

---

## PART C — what remains, and the next action

**Recovery.** Commissioning verdict in A7. If PASS: the recovered orchestrator
is authorized for production under its established conditions, and its first
launch decision arrives Tuesday 13:30Z for `options-paper` only. The seven
long-lived writers stay on the old reader until separately authorized
restarts.

**Research.** Nothing runs on real data until the reviewer decides the
separate admission contract and reviews the submitted limitations against the
proposed experiment. The next action justified by the findings is that
decision. No further research expansion is proposed.

Phase 2 remains OPEN. Real-data admission remains NOT_AUTHORIZED. These
recovery passes establish nothing about trading performance.
