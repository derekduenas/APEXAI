# Phase 2 — current blocker reconciliation

From repository artifacts and read-only host evidence, 2026-09-07. Phase 2
remains OPEN and real-data admission remains NOT_AUTHORIZED.

**Operational recovery and data validity are separate problems.** Everything in
this milestone is operational: it makes the machine able to run. None of it
makes any datum admissible. A perfectly healthy orchestrator changes nothing
about whether a historical value was knowable when we model it as known.

## Operational

### O1 — orchestrator production recovery
- **Status** UNVERIFIED. The loop is live: killed ~1 s after each start, 31 s
  cycle, ~116/hour, since 2026-09-06T04:51:05Z.
- **Evidence** `results/orchestrator_oom001_diagnosis.json`;
  `results/orchestrator_oom001_r1_RETURN.json`; R2 at `3b9a26f2`.
- **Completion criterion** After an authorized deploy of `39bd4412`: restart
  counter static, heartbeat `last_work_utc` advancing every 60 s,
  `work_completed` climbing, no ledger changed except by growth.
- **Smallest action** Review and authorize the deployment package, deploy in a
  non-trading window, observe 30 minutes.
- **Depends on** Nothing technical. Authorization only.
- **Needs a market session?** No. **Deadline** Tuesday 2026-09-08, the next
  trading session.

### O2 — deployed release predates the PULSE work
- **Status** OPEN by design. Production runs `5eff1cf5` (2026-08-30). PULSE-007
  through PULSE-010, the null-rig repair and R1/R2 are all later.
- **Completion criterion** A separate, reviewed decision about whether the
  PULSE line is deployed at all. It is research instrumentation, not a money
  path, and it does not have to ship to unblock Phase 2.
- **Smallest action** None in this milestone. The recovery candidate
  deliberately excludes it.
- **Depends on** O1 first; do not compound two changes.

### O3 — apex-gate2-opener.service failed
- **Status** OPEN, unexamined. Reported in passing during the OOM diagnosis;
  not an OOM.
- **Completion criterion** Cause established and either repaired or registered.
- **Smallest action** A bounded read-only diagnosis, like ORCHESTRATOR-OOM-001.
- **Depends on** Nothing. Not on the critical path to the tournament.

### O4 — historical regression working-tree identity
- **Status** UNRESOLVED for past runs and CLOSED for new ones. Runs before this
  milestone recorded the commit but no source manifest, so what they executed
  cannot be proven from their artifacts.
- **Completion criterion** Not repairable. New runs carry a before/after
  manifest of every tracked file; the historical gap stays recorded.
- **Smallest action** Already done for this milestone's runs.

## Data validity

### D1 — historical as-known availability (**the binding constraint**)
- **Status** NOT_PROVEN, unchanged across PULSE-007, 008, 009 and 010.
- **Evidence** pulse007 note: "the vendor history endpoint returns records as
  they stand at retrieval; nothing establishes when a value became available.
  Corpus admission stays blocked."
- **Why it dominates** A World Model tournament scored on history is only
  honest if every input was knowable at the modelled instant. A vendor endpoint
  that returns today's view of the past cannot establish that. No amount of
  software correctness substitutes for it.
- **Completion criterion** Either (a) documented vendor semantics giving
  publication and revision timestamps with point-in-time retrieval, or (b) a
  prospectively collected corpus whose availability is known by construction.
- **Smallest action** For (a) a vendor clarification, which we do not control.
  For (b) run the existing PULSE composer forward and accumulate its
  observation-stamped packets, which needs no vendor cooperation.
- **Needs** (a) vendor clarification; (b) market sessions and calendar time.

### D2 — mirror coverage incomplete
- **Status** INCOMPLETE since PULSE-007, unchanged.
- **Evidence** NKLA reconstructs nothing comparable; an all-LIVE_ONLY
  comparison is a coverage hole. Its quote is 553 days old, so PULSE-008
  refuses it as STALE_BEYOND_POLICY. Five of six is not a pass and the runner
  does not report one.
- **Completion criterion** Every declared subject reconstructs, or a subject
  set whose declarations match what the vendor can actually reconstruct, chosen
  before the run rather than after seeing results.
- **Smallest action** Re-declare the subject set with a liveness precondition
  and rerun the mirror. Choosing the set after seeing which subjects pass would
  be selection, not repair.
- **Depends on** D3 for the declaration question.
- **Needs a market session?** Yes, for fresh quotes on a thin name.

### D3 — mirror under original declarations blocked
- **Status** BLOCKED, not FAIL. Zero violations, but coverage is incomplete so
  it cannot be PASS.
- **Evidence** Under observation-time reconstruction, `nbbo_size_imbalance` is
  declared SEMANTICALLY_EQUIVALENT yet differs on four subjects, e.g. live
  −0.5294 against replay −0.625 on the index subject.
- **Completion criterion** Either the declaration is corrected to what the
  quantity actually is across a quote boundary, or the reconstruction is fixed
  so the declaration holds.
- **Smallest action** Decide which of those two is true for size imbalance
  specifically. Sizes at the touch change faster than prices; a declaration of
  exact equivalence across reconstruction may simply be wrong.
- **Depends on** D2 for coverage.

### D4 — anchor repair FAIL
- **Status** FAIL under the strict rule fixed before the run.
- **Evidence** The two pure anchor quantities are exact on 5 of 5, closing
  ANCHOR-001 and ANCHOR-002. The two features combining an anchor with the live
  mid stay APPROXIMATE on AAOI for a measured quote-timing reason. The rule was
  not relaxed.
- **Completion criterion** Those features exact, or a declaration that a
  live-mid composite is APPROXIMATE by nature, made on the measurement.
- **Smallest action** Adopt the second, with the residual classification as
  evidence. It is defensible and already measured.

### D5 — World Model real-data admission
- **Status** NOT_AUTHORIZED.
- **Completion criterion** D1 satisfied, D2 and D3 resolved, and an explicit
  admission decision.
- **Depends on** D1, D2, D3.

## Shortest defensible route to the first real-data tournament

The binding constraint is D1, and it is not a software problem. Two routes:

**Route A, vendor clarification.** Fastest if the answer is yes. Establish
whether the history endpoint documents publication timestamps, revision
history and point-in-time retrieval. If it does, a historical corpus becomes
constructible and D2/D3 are the remaining work. We do not control the answer,
and a vendor that cannot answer precisely leaves D1 exactly where it is.

**Route B, prospective collection.** Slower but wholly within our control. The
PULSE composer already stamps observation time, refuses stale inputs, and
propagates staleness through derived fields, so packets accumulated forward
have known availability by construction. This is the defensible route: it does
not depend on anyone's answer, and it cannot be undermined by a later
discovery about vendor revisions.

**Recommendation: pursue B as the spine and A in parallel as a cheap read.** B
determines the timeline; A can only shorten it. Neither is authorized here, and
this milestone builds no corpus, admits no data, and starts no tournament.

Sequenced, the route is: O1 recovery commissioned, so the machine reliably
turns up; then D2 and D3 resolved, so the mirror can report a real PASS; then
D1 satisfied by accumulation under B; then, and only then, D5 as an explicit
admission decision.
