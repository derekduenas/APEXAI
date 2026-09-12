# DEPLOYMENT_DIVERGENCE_001 — the thing in production is not the thing under review

Status: **OPEN**. Recorded 2026-09-12 (first stated in prose on 2026-09-11 during the Defect Repair and First
Seal Block; carried forward here as a record so it cannot fall through a branch boundary).

## Finding

| Item | Value |
|---|---|
| Deployed release on the research host (`/opt/apex/current`) | `73fc712d355032e0a66b41675ba114491b04799d` = tip of `milestone1-recovery-candidate` |
| Nature of that branch | a "minimal production-recovery candidate" (R1+R2 pruning) that **deletes 232 files / 91,274 lines** relative to `milestone1-r2` |
| Its two substantive patches (R3 maintenance-block enforcement, R4 truthful launch reporting) | present in `milestone1-r2` by patch identity, therefore in `main` |
| `main` at the time of this record | `b9998d02` and descendants: both lineage tips merged, 3,533 files |
| Consequence | every review since 2026-09-11 has read `main`; the process that would run in production is a pruned subset that has never been reviewed as a whole against the reviewed tree |

Verified read-only on 2026-09-12: `/opt/apex/releases` holds three release directories; `/opt/apex-repo` is at
`eca00a9e5` ("milestone1: consolidated package v2"), which is neither the deployed release nor `main`. Three
different trees: reviewed, canonical-repo, deployed.

## Why it stays open

Closing it requires a release pinned from `main` (a commit that is the whole system, with the decision-path
repair reviewed), installed under `/opt/apex/releases/<sha>` with `/opt/apex/current` re-pointed, and the
maintenance block still in place. That is deployment: operator-authorized, out of scope for every block so far.

## Rule while open

**Nothing deploys until this closes.** No paper session may be started under a release that is not `main` at a
reviewed commit. The commissioning checklist (`docs/COMMISSIONING_CHECKLIST.md`) carries this as a blocking row.
