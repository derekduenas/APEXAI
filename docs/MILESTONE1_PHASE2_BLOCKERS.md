# Phase 2 — blocker reconciliation (CORRECTED)

**Supersedes the first version in full.** That version is preserved in git
history at `9836986f`. Phase 2 remains OPEN; real-data admission remains
NOT_AUTHORIZED.

## What was wrong, and why it mattered

The superseded D3 and D4 quoted **intermediate** PULSE-008 findings as if they
were current, and then proposed relaxing a declaration to resolve them. Both
were wrong. The disagreement had already been fixed by measurement, not by
redefinition, and proposing to weaken a declaration to close an
already-closed finding is precisely the failure mode this programme exists to
prevent.

`results/pulse008_SUMMARY.json` records three stages. Reading the middle one as
the outcome was my error.

| Stage | Verdicts | Violations |
|---|---|---|
| `before_pulse008` | 4 of 6 contradicted | — |
| `observation_time_only` | 4 of 5 contradicted | `nbbo_size_imbalance` on four subjects |
| **`observation_time_plus_boundary_fix`** | **all 5 MIRROR_CONSISTENT** | **`{}` — empty** |

Operational recovery and data validity remain separate problems. Nothing in
Milestone 1 makes any datum admissible.

---

## Operational

### O1 — orchestrator production recovery
- **Status** UNVERIFIED. Loop live since 2026-09-06T04:51:05Z. Unit
  `NRestarts` 2864 at 05:50Z on the 7th, `Result=oom-kill`.
- **Evidence** `results/milestone1_recovery_regression.json`;
  `results/orchestrator_oom001_diagnosis.json`; candidate `07dcbb05`.
- **Completion** After an authorized deploy: `NRestarts` static from the first
  successful start, no oom-kill journal lines after it, heartbeat advancing,
  every ledger prefix hash unchanged.
- **Smallest action** Resolve O2, then deploy and observe 30 minutes.
- **Depends on O2.** Not authorization alone — the earlier claim was premature.
- **Market session?** No. **Deadline** the next trading session, 2026-09-08.

### O2 — maintenance-block enforcement is ABSENT
- **Status** OPEN and blocking O1. Traced read-only at `07dcbb05`: neither
  orchestrator source file references `MAINTENANCE_BLOCK` in any form. Two
  block files exist and are not read.
- **Why it blocks** A working orchestrator starts `equity-fabric` and
  `options-paper` at a phase transition. `equity-fabric` is under an explicit
  block. Deploying in a quiet window does not authorize the launch that happens
  at the next transition without human action.
- **Completion** Either the tick honours the block files and records the
  suppression, or an arrangement outside the orchestrator prevents those two
  services starting without human action.
- **Smallest action** A separate reviewed brick for the first. It is a third
  production change and is outside Milestone 1's authorization.
- **Do not** lift the blocks to make this go away.

### O3 — apex-gate2-opener.service failed
- **Status** OPEN, unexamined. `Description=GATE2 T-0 integrity gate then
  conditional start of b125a7c5a`; state failed, exit-code.
- **Not declared noncritical.** It is an integrity gate that conditionally
  starts a component, so its failure may be suppressing a Phase-2 dependency.
  Its governed dependencies have not been traced.
- **Smallest action** A bounded read-only diagnosis, as for the orchestrator.

### O4 — historical regression working-tree identity
- **Status** UNRESOLVED for runs before Milestone 1; CLOSED for new ones.
- Not repairable. New runs carry before/after manifests. The integration run is
  additionally **not hermetic**: five shards read outside their worktree, and
  the shared checkout was aligned mid-run at shard 114. Recorded, not erased.

---

## Data validity

### D1 — historical as-known availability (**the binding constraint**)
- **Status** NOT_PROVEN, unchanged across PULSE-007 through 010.
- **Evidence** pulse007: "the vendor history endpoint returns records as they
  stand at retrieval; nothing establishes when a value became available."
- **Completion** Documented publication and revision semantics with
  point-in-time retrieval, **assessed per source and per field**, or a corpus
  whose availability is known by construction.
- **Needs** vendor clarification, or prospective capture, or both by family.
- **See the research-route section.** This does not reduce to "wait".

### D2 — mirror coverage INCOMPLETE (a coverage hole, not a disagreement)
- **Status** INCOMPLETE. One comparison never produced a result: NKLA
  reconstructs nothing, its quote being 553 days old, so PULSE-008 refuses it
  as STALE_BEYOND_POLICY.
- **Kept separate from D3 deliberately.** This is about whether a subject can
  be compared at all. It is not evidence of any value disagreement.
- **Completion** A subject set where every declared subject reconstructs,
  chosen before the run. Choosing it after seeing which subjects pass would be
  selection.
- **Market session?** Yes, for fresh quotes on a thin name.

### D3 — mirror under original declarations BLOCKED (by coverage only)
- **Status** BLOCKED. **Value agreement is EXACT on all five comparable
  subjects**: `observation_time_plus_boundary_fix` records all five
  MIRROR_CONSISTENT with an empty violation set, under the ORIGINAL
  declarations and the ORIGINAL tolerances. It is BLOCKED solely because
  coverage is incomplete, which is D2.
- **WITHDRAWN from the superseded version.** The `nbbo_size_imbalance`
  disagreements belong to the intermediate `observation_time_only` stage and
  were resolved by the boundary fix. They are not a current defect. The
  proposal to relax the equivalence declaration is withdrawn entirely: no
  declaration needs relaxing, and none should be.
- **Completion** D2 closed. Nothing else is outstanding here.

### D4 — anchor repair, PULSE-007 FAIL, not re-measured since
- **Status** The FAIL is a **PULSE-007-era** verdict. The two pure anchor
  quantities were exact on 5 of 5, closing ANCHOR-001 and ANCHOR-002. Two
  features combining an anchor with the live mid stayed APPROXIMATE on AAOI,
  for a measured quote-timing reason.
- **The honest position.** That quote-timing cause is the same defect PULSE-008
  fixed at the boundary. Whether the anchor verdict would now pass has **not
  been re-measured**, and I will not claim it either way. The superseded
  version repeated the residual as a current defect and proposed declaring the
  composite APPROXIMATE by nature. Both withdrawn.
- **Smallest action** Re-run the anchor comparison under the boundary fix and
  read the result. Cheap, and it replaces speculation with a measurement.

### D5 — full-RTH equity-fabric commissioning
- **Status** OPEN. Not evidenced as complete in the repository artifacts.
  Related units exist (`apex-equity-fabric.service`, a v1 variant, a GATE2
  opener that is failed) and `equity-fabric` is under a maintenance block.
- **Not declared noncritical.** A fabric that has not run a full regular
  session has not demonstrated it can carry one.
- **Depends on** O2, since the block and the orchestrator's start authority
  interact, and on O3 if GATE2 gates it.
- **Needs a market session.** Yes, a full RTH session.

### D6 — prospective PULSE commissioning
- **Status** OPEN. PULSE-007 through 010 established contracts and repaired
  the composer; none of that is a commissioned prospective collector.
- **Completion** The composer running across live sessions, writing
  observation-stamped packets durably, with its refusals and staleness
  behaviour observed rather than asserted.
- **Depends on** O1, since the orchestrator is what notices a collector that
  fails to produce work.
- **Needs market sessions.**

### D7 — market and cross-sectional context
- **Status** OPEN, **and I could not evidence its current state.** No
  cross-sectional or market-context artifact was found in the integration
  candidate's results directory.
- **Not declared noncritical.** Absence of an artifact is not absence of a
  requirement; it means the gate is untraced.
- **Smallest action** Locate the governing declaration and record its status.

### D8 — BTC integrity
- **Status** OPEN, partially evidenced. Two BTC ledgers are live and healthy
  against the chain-tail window (416.1 MB and 135.8 MB, final records 6,406 and
  762 bytes). Their writers are unaffected by R2 and are affected by R1 only in
  how a previous hash is found.
- **Untraced** whether a separate BTC integrity gate is outstanding beyond
  ledger health. Not declared noncritical.

### D9 — World Model real-data admission
- **Status** NOT_AUTHORIZED.
- **Depends on** D1 principally, plus D2, and on whichever of D5 to D8 the
  admission declaration names.
- The World Model line's own court closed at
  `PASS_WITH_FINAL_SYNTHETIC_ACCEPTANCE_COURT_V1` — **synthetic**. That is
  precisely the boundary this gate sits on.

---

## The research route, reconciled

The superseded version collapsed three different things into "prospective
collection". They are distinct, and only the third requires waiting.

### Three separate things

1. **Prospective raw collection** — capturing observations forward with
   receipt timestamps. Necessary, not sufficient. A timestamp on capture is not
   the same as knowing when the value became available at source.
2. **Corpus admission** — a decision that a body of data may be used for
   research. Requires availability semantics, durable capture, and stable
   identity. A prospectively captured corpus is **not automatically
   admissible**: if the capture is lossy, or restarts lose windows, or the
   receipt time is our clock rather than the source's publication time, it
   fails the same test the historical corpus fails.
3. **Prospective forecast evaluation** — forecasts made before an outcome, with
   the cutoff enforced at forecast time. This is what actually requires calendar
   time. It cannot be simulated from history at all.

### Historical eligibility is per source and per field

The superseded version implied every source must wait for new observations.
That is wrong, and it would discard usable research. The right question is asked
per family:

| Family | Availability question | Likely eligibility |
|---|---|---|
| Exchange daily bars, prior closes | Are they revised after publication, and is the revision visible? | Plausibly eligible if the vendor documents no silent revision |
| Intraday quotes and trades | Same, plus whether history reflects the consolidated tape as it stood | Needs the vendor answer we do not yet have |
| Corporate actions, splits, dividends | Announcement versus effective date, and whether history is back-adjusted | **High risk** — back-adjustment silently rewrites the past |
| Fundamentals, filings | Filing timestamp is publication; restatements must be visible as revisions | Eligible if restatement history is exposed |
| News and event data | Publication timestamp is the availability time | Eligible if timestamps are source, not ingest |

The blocker is not "history is unusable". It is that **eligibility has not been
assessed per family against documented semantics**, and a corpus mixing eligible
and ineligible families inherits the weakest member.

### Recommended sequence

1. Assess eligibility per family against documented vendor semantics. Cheap,
   read-only, no market session, and it may unlock historical research for
   several families immediately.
2. In parallel, commission prospective capture (D6) so that forecast evaluation
   can begin accruing, since that clock cannot be started retroactively.
3. Admit a corpus only from families that pass step 1, with the assessment
   recorded per family.
4. Begin prospective forecast evaluation once capture is commissioned.

Neither is authorized here. This milestone builds no corpus, admits no data,
and starts no tournament.
