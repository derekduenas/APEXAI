# BRANCH_REALITY_AUDIT — what `main` is and is not

Date: 2026-09-11. Inventory only; nothing is merged by this record. 27 origin branches, counted from
`git branch -r` filtered to `origin/` (a `droplet` mirror doubles the raw count to 54 and is excluded).

## Headline

`main` last moved on **2026-09-04** and is **behind 26 of the 27 branches, ahead of none**. It carries **1,079 of
3,524 files** in the union across all branches. **2,445 files — 69 % of the system — are invisible from `main`.**

But the repository is **not** 27 independent partial realities. It is **two stacked lineages and one divergent
candidate**. Every branch except three is an ancestor of one of two tips:

| Tip | Head | Files | Contains |
|---|---|---|---|
| `r4-repair-r2` | 2026-09-11 | 3,404 | 16 branches: `world-model-shadow-v0` → `alpha-exp-001` → `strategic-integration-002` → `event-source-001` → `catalyst-stall-001` → `bls-source-001` → `exp001b-activation-001` → `exp001b-launch-fix` → `exp001b-bounded-memory` → `exp002-tournament` → `options-pilot-001` → `frontier-build` → `r4-draft31-review-patch` → `r4-implementation` → itself |
| `milestone1-r2` | 2026-09-07 | 1,199 | 10 branches: `pulse-007-anchor-reconciliation` → `pulse-008-observation-time` → `pulse-009-derived-staleness` → `pulse-010-anchor-freshness` → `pulse-010-repair-dependency-wiring` → `regression-oom-001-null-rig-memory` → `orchestrator-oom-001-diagnosis` → `orchestrator-oom-001-r1` → `orchestrator-oom-001-r1-provenance` → itself |

Neither tip contains the other. **Their union recovers 3,523 of 3,524 files, or 100 % of the system to within one
file** (`docs/R4_IMPLEMENTATION_R1.md`, renamed on `r4-repair-r2`). The assembly problem is two merges, not 27.

`milestone1-recovery-candidate` is the exception: 4 ahead, **20 behind**, contained in nothing, contributing no
file that the two tips lack. It is the only genuinely divergent branch and the only merge that would need a
decision rather than a fast-forward.

## Full inventory

| Branch | Head | Ahead | Behind | State | On a tip's path |
|---|---|---|---|---|---|
| `main` | 2026-09-04 | 0 | 0 | BASE | — |
| `alpha-exp-001` | 2026-09-07 | 48 | 0 | superseded | A |
| `bls-source-001` | 2026-09-08 | 72 | 0 | superseded | A |
| `catalyst-stall-001` | 2026-09-08 | 70 | 0 | superseded | A |
| `event-source-001` | 2026-09-08 | 69 | 0 | superseded | A |
| `exp001b-activation-001` | 2026-09-08 | 79 | 0 | superseded | A |
| `exp001b-bounded-memory` | 2026-09-09 | 104 | 0 | superseded | A |
| `exp001b-launch-fix` | 2026-09-08 | 86 | 0 | superseded | A |
| `exp002-tournament` | 2026-09-10 | 162 | 0 | superseded | A |
| `frontier-build` | 2026-09-11 | 194 | 0 | superseded | A |
| `milestone1-r2` | 2026-09-07 | 31 | 0 | **TIP B** | B |
| `milestone1-recovery-candidate` | 2026-09-07 | 4 | **20** | **DIVERGENT** | none |
| `options-pilot-001` | 2026-09-11 | 165 | 0 | superseded | A |
| `orchestrator-oom-001-diagnosis` | 2026-09-06 | 14 | 0 | superseded | B |
| `orchestrator-oom-001-r1` | 2026-09-06 | 16 | 0 | superseded | B |
| `orchestrator-oom-001-r1-provenance` | 2026-09-07 | 17 | 0 | superseded | B |
| `pulse-007-anchor-reconciliation` | 2026-09-06 | 2 | 0 | superseded | B |
| `pulse-008-observation-time` | 2026-09-06 | 4 | 0 | superseded | B |
| `pulse-009-derived-staleness` | 2026-09-06 | 6 | 0 | superseded | B |
| `pulse-010-anchor-freshness` | 2026-09-06 | 8 | 0 | superseded | B |
| `pulse-010-repair-dependency-wiring` | 2026-09-06 | 11 | 0 | superseded | B |
| `r4-draft31-review-patch` | 2026-09-11 | 193 | 0 | superseded | A |
| `r4-implementation` | 2026-09-11 | 195 | 0 | superseded | A |
| `r4-repair-r2` | 2026-09-11 | 196 | 0 | **TIP A** | A |
| `regression-oom-001-null-rig-memory` | 2026-09-06 | 13 | 0 | superseded | B |
| `strategic-integration-002` | 2026-09-08 | 68 | 0 | superseded | A |
| `world-model-shadow-v0` | 2026-09-06 | 44 | 0 | superseded | A |

"superseded" means every commit on the branch is already contained in a tip; the branch is a checkpoint, not a
fork. Merge-base for all 27 is a commit on `main`; none has diverged except `milestone1-recovery-candidate`.

## Capability that exists nowhere on `main`

Eight `apex/` modules are absent from `main` entirely. `main` carries 51.

| Module | Branches carrying it | Reachable from |
|---|---|---|
| `world_model` | 15 | tip A |
| `options_pilot` | 6 | tip A |
| `backtest_wb` | 4 | tip A |
| `decision_wb` | 4 | tip A |
| `multiverse_wb` | 4 | tip A |
| `pulse_options` | 4 | tip A |
| `worldmodel_wb` | 4 | tip A |
| `joint_wb` | 2 | tip A |

Every module absent from `main` is on tip A. Tip B contributes no new module; it is repairs and guards to modules
`main` already has (PULSE anchor and staleness work, orchestrator out-of-memory diagnosis, the null-rig memory
regression, milestone 1 recovery).

## What a reader of `main` is and is not seeing

**Sees:** 51 `apex/` modules, 1,079 files, the doctrine set, the reality scoring substrate, the equities research
path, and a repository whose last activity looks like 2026-09-04.

**Does not see:** the entire options sleeve — the recording boundary, the funnel engine, the joint market-state
workbench and its pinned contract; the world model; the multiverse, backtest, decision and pulse-options
workbenches; the R4 specification and its eight review rounds; the PULSE anchor and staleness repairs; the
orchestrator out-of-memory diagnosis and its provenance work; 2,445 files and 410 commits made since Epoch 1
opened.

**Consequence.** Any audit of `main` — by a reviewer, a counterparty, a future session, or the operator six months
from now — audits a fiction that is 69 % incomplete and one week stale. That is exactly what happened on
2026-09-11: an external review cloned the default branch, produced a confident and well-evidenced inventory of
"the last three weeks of commits," and named none of the options work, because none of it is there. The review's
conclusions largely survived the error, but the inventory it rested on was wrong, and nothing in the repository
would have told it so.

**Second consequence.** `ECONOMIC_THROUGHPUT_FAILURE_001.md`, the record declaring the governance alarm tripped,
is being committed on `throughput-recovery-001` and is therefore invisible from `main` too. A governance record
that cannot be found from the default branch is decorative in exactly the way the record itself warns about.

## Not done here

No merge, no branch deletion, no default-branch change. Those are operator decisions. The arithmetic above is
offered only so the decision can be made on facts: two merges plus one judgement call on
`milestone1-recovery-candidate` reconstitute the system, and there is no third lineage hiding anywhere.
