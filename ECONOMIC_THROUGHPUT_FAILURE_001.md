# ECONOMIC_THROUGHPUT_FAILURE_001 — DECLARED TRIPPED

Date: 2026-09-11. Declared by: the operator's own alarm in `PROFIT_TRANSITION_DIRECTIVE.md`, lines 42-45.
Status: **TRIPPED.** This record exists to demonstrate that the governance layer fires against its own operator.

## The alarm, verbatim

```
- PROFIT CLOCK: from the first combat-ready sleeve, progress is
  measured in MARKET DAYS. ~7-10 market days producing schemas
  instead of economic observations = ECONOMIC_THROUGHPUT_FAILURE,
  investigate. (Not a quota -- a throughput alarm.)
```

## Facts and denominators

| Quantity | Value | Source |
|---|---|---|
| Epoch 1 opened | 2026-08-17 | `results/EPOCH1-STATUS.md` |
| Today | 2026-09-11 | — |
| Market days elapsed, inclusive (weekdays less Labor Day 2026-09-07) | **19** | computed; see command below |
| Directive threshold | 7-10 market days | `PROFIT_TRANSITION_DIRECTIVE.md:43-44` |
| Multiple of threshold | **1.9x to 2.7x** | 19 / 10 and 19 / 7 |
| Scored forward economic observations in the window | **0** | commit census below, path test |
| Commits in the window, all 27 origin branches | **410** | `git log` per branch, de-duplicated by hash |
| Commits touching any economic-outcome record path | **0** | path test below |

```
python3 - <<'EOF'
import datetime
start, today = datetime.date(2026,8,17), datetime.date(2026,9,11)
hol = {datetime.date(2026,9,7)}                      # Labor Day 2026
d, n = start, 0
while d <= today:
    if d.weekday() < 5 and d not in hol: n += 1
    d += datetime.timedelta(days=1)
print(n)                                              # 19
EOF
```

## Producer scoring state

`results/reality/calibration_report.json`, `chain_entries: 2762`, `lake_through: 2026-08-21`,
`generated_at: 2026-08-24T11:18:45Z` — **the report itself is 18 days stale**.

| Producer | `n_scored` | `n_effective_dates` | status |
|---|---|---|---|
| `baseline_base_rate` | 1 | **1** | `PRELIMINARY -- effective n is the date count, 1 < 10` |
| `baseline_momentum` | 1 | **1** | same |
| `baseline_momentum_rank` | 232 | **1** | same |
| `blind_twin` | 232 | **1** | same |
| `gp_rank` | 232 | **1** | same |
| `h3_rank` | 232 | **1** | same |

The binding number is `n_effective_dates = 1`, not `n_scored`. Four producers have 232 scored cross-sectional
predictions; all six have exactly one effective date, and the date count is what drives `PRELIMINARY`. An external
review of this repo on 2026-09-11 reported "n_scored: 1" as the headline; that was wrong for four of the six
producers and the error is recorded here so it does not propagate. One date is still one date.

## Paper ledger

`results/paper/paper_ledger.jsonl`: **1 line**, `marked_at: 2026-08-14T14:23:24Z`, `lake_through: 2026-08-13`,
`denominator: 6`, single mark date `2026-08-03`. The one line predates Epoch 1 by three days. **No paper ledger
line has been written since Epoch 1 opened.**

## Commit census, 2026-08-17 to 2026-09-11, all 27 origin branches

410 distinct commits. Classification is by commit subject except `ECONOMIC_OBSERVATION`, which is decided by
PATH — a commit counts only if it added or modified a record of a realized economic outcome
(`results/paper/`, `paper_ledger`, `*_ledger.jsonl`, `outcomes*.jsonl`, `fills*.jsonl`, `realized`). The subject
heuristic is published so the count can be re-derived or disputed; the economic count does not depend on it.

| Class | Commits | Share |
|---|---|---|
| CAPABILITY | 226 | 55.1 % |
| GOVERNANCE | 125 | 30.5 % |
| REPAIR | 59 | 14.4 % |
| **ECONOMIC_OBSERVATION** | **0** | **0.0 %** |

A subject-only classifier initially returned 3 economic commits. All three were false positives: the word
"scored" inside an R4 specification message and two repair messages. The path test returns zero, and zero is the
number that stands.

## Capital state, unchanged since Epoch 1 opened

`results/EPOCH1-STATUS.md`: `PAPER CAPITAL NOT AUTHORIZED`, `LIVE CAPITAL SEALED`, `CREDIT 5 SEALED`,
`HOLDOUT SEALED`.

`INSTRUMENT-STUDY-VERDICT.md:43-47` records that the live lake is the free out-of-sample machine, consumes zero
credits, and is "blocked only on the operator arming the nightly pull." That sentence has been in the repository
since 2026-08-14, which is 19 market days and 410 commits ago.

## Statement

Nineteen market days at 1.9x to 2.7x the declared threshold, 410 commits, and zero scored forward economic
observations. The alarm is tripped and was tripped for roughly the last nine market days before this record was
written. The governance instrument detected the condition it was designed to detect; nothing acted on it until
now. An alarm that fires and is not answered teaches the organization that the alarm is decorative, which is a
worse state than having no alarm.

No remedy is enacted by this record. Arming the nightly pull, authorizing paper capital, lifting the maintenance
block and activating the collector are operator decisions and remain unmade.

## Placement defect

This record is committed on branch `throughput-recovery-001`, not on `main`. `main` does not represent the system
(see `BRANCH_REALITY_AUDIT.md`), so a reader of `main` will not see this file. Leaving it here reproduces the exact
defect the branch audit documents. It must be merged to `main` to be non-decorative, and that merge is an operator
decision.
