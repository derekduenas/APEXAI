# FLOW-VALIDATION-001 — execution package, frozen before execution (2026-09-12)

**Nothing has been run. No recorded data was evaluated.** This document pins the code, inventories the retained
data, freezes the evaluation contract and acceptance criteria, lists the unresolved prerequisites, and gives the
exact command. It stops there, by instruction.

**What this evaluation is.** Flow validation: does available data reach the models, produce a decision, pass risk,
enter, exit on schedule, reconcile, and preserve every result. **What it is not.** Strategy evaluation. The data is
one exposed partial session; nothing it produces is out-of-sample evidence, a profitability finding, or a test of
shares versus options.

## 1. The pinned candidate, and what the regression actually says

| | |
|---|---|
| branch | `operating-loop-001` |
| code pin for the evaluation | `e8ebbee94a0933d34efd1061d439bbd9a75b310d` |
| docs pin (this package's base) | `02eade9` |
| review status | **INDEPENDENT REVIEW OUTSTANDING.** Everything below is builder-reported. |

### The 14 remaining failures, grouped by REASON

Earlier I reported that the candidate's 14 failures were identical to the baseline's *by test identifier*, and
called all 14 environment failures. **The identifier match is not a cause match, and the "all environment" claim
was wrong.** Reading the tracebacks from the isolated run at `e8ebbee`:

| # | cause | tests | environment or repo |
|---|---|---|---|
| 5 | `/opt/apex-repo/...` absent on this host | 3 NKLA packet tests, `test_pulse_v1_minute_path_reads_no_ledger`, `test_checkpoint_module_declares_the_law` | environment |
| 3 | `/apex-data/core/edgeforge/research_board.jsonl` absent | 3 `test_research_board` reconciliation tests | environment |
| 1 | `/opt/apex/shared/venv/bin/python` absent | `test_audit_script_passes` | environment |
| 2 | Linux-only `/proc` (`self/status`, `self/cgroup`) on macOS | `test_memory_does_not_grow_linearly...`, `test_running_inside_research_containment` | environment |
| 1 | macOS `/private/var/folders` tmp has no sticky world-writable ancestor, unlike Linux `/tmp` | `test_a_sticky_world_writable_ancestor_is_accepted` | environment (platform) |
| **2** | **repository content, NOT environment** | see below | **repo** |

**The two that are not environment failures:**

- `test_architecture_claims.py::test_no_execution_or_broker_dependency_exists` fails on
  `AssertionError: 'alpaca' present: execution has entered research`. It is a governance-boundary assertion about
  repository content, and the offending text is a corpus id (`corpus:alpaca_1m`) and a bar-ingestion call inside a
  research file. It fails identically at the baseline, so **this brick did not cause it**, but it is a standing
  governance finding rather than a missing host path and should not be filed under "environment".
- `test_whole_ledger_guard.py::test_every_registered_offender_still_exists` fails because six paths in
  `KNOWN_UNREPAIRED` no longer exist (`apex/pulse/premarket.py`, `apex/pulse/rolling.py`, and four scripts). That is
  a **stale exemption register**, which the test exists to catch. Also present at the baseline.

### Does any of them block THIS evaluation?

**No.** The one that had to be checked properly is the sticky-ancestor failure, because it lives in a module named
`real_data/boundary.py` and admission of a data root is exactly what a recorded evaluation does. It belongs to
`apex.world_model.real_data.boundary`, the **equities research corpus** boundary, not the options pilot boundary. A
transitive import check confirms it: importing `apex.options_pilot.replay`, `apex.options_pilot.lifecycle` and
`apex.decision_wb.engine.FunnelEngine` pulls in **no** `real_data` module, and none of the six files on the options
replay path mentions `world_model`.

The remaining eleven test host artifacts, Linux `/proc`, or a host venv. None is on the options replay path.

### Deployment blockers, kept separate and not dismissed

These do not block flow validation. They **do** block live paper operation and none is closed:

- **Cross-release recovery is OPEN.** A position filled under one release cannot be resolved by a boundary running
  another release. `FINDING_RELEASE_CHANGE_STRANDS_POSITION.md`; `CONVENTIONS-AMENDMENT-A-012` still drafted.
- **DEPLOYMENT_DIVERGENCE_001** stands.
- **The two repo-content failures above** are governance findings a reviewer should rule on before commissioning.
- **The fee schedule is CANDIDATE**; `LIVE_DEFAULT_FEES = UNVERIFIED_FEES`; v2026-09-12b is not authorized for live.
- **No order placement capability exists**, by structural seal.

## 2. Inventory of the already-retained data

No new outcome was read. Counts, digests and instants below come from the files' own records and from
`docs/evidence/EVIDENCE_REGISTER.json`.

**Location, and a fragility that must be fixed first.** The four files live in this session's scratchpad at
`/private/tmp/claude-501/-Users-derekduenas/83f91d89-.../scratchpad/`. That directory is session-scoped and may be
cleaned at any time. **Copying them to a declared durable path, with digests recorded, is prerequisite P4 below.**

| file | bytes | sha256 (first 16) | records | window |
|---|---|---|---|---|
| `collection_2026-09-11/chain_SPY.jsonl` | 12,352,950 | `3c664e3fca7599ed` | 166 `pilot_collection_chain` | 13:30:23Z to 16:15:24Z |
| `collection_2026-09-11/nbbo_SPY.jsonl` | 445,390 | `362219d0dac13d11` | 662 `pilot_collection_nbbo` | 13:30:22Z to 16:15:39Z |
| `collection_2026-09-11/bars_SPY.jsonl` | 298,451 | `b2df9bd85a680fd5` | 166 `pilot_collection_bars` | 13:30:22Z to 16:15:24Z |
| `prior_bars_SPY.json` | 1,104,390 | `e6985762b51b2585` | 5,170 one-minute bars | event dates 2026-09-02 to 2026-09-11 |

The prior-bars digest matches the value recorded in the evidence register, so the file is the one the register
describes.

**Permitted dataset and use.** `PILOT-COLLECTION/2026-09-11`, role `PROSPECTIVE_OBSERVATION`, status **BURNED** on
2026-09-12. The register states it "may support mechanism validation only" and "may never support any claim about
edge, expectancy, or calibration". It has already been read for the Stage 0 census, the fees-authorized census, the
Part 1 trace replay, the funnel first run and the twelve-scan demonstration. **It is thoroughly exposed.**

`HIST-A-OPTIONS/2022-2024` (`EVALUATION_SEALED`) and `HIST-A-OPTIONS/2025-2026-08-28` (`RESERVE_SEALED`) stay
sealed and are not touched by this package.

**Coverage and its gaps.**

- **One symbol.** SPY only.
- **A partial session.** 13:30Z to 16:15Z is 09:30 to 12:15 ET, roughly 2h45m of a 6h30m regular session. The
  collection stops at 12:15 ET; the afternoon does not exist in this data.
- **Cadence.** Chain and bars about every 60s, NBBO about every 15s. At the pilot's 15-minute scan cadence this
  yields **12 scan instants**, which is the entire opportunity set.
- **Option quotes** exist only as full-chain snapshots at those 166 instants. There is no continuous option quote
  stream, so an exit is valued at the **most recent snapshot whose recorded availability is at or before the exit
  instant**. **CORRECTED 2026-09-12:** an earlier draft said "the nearest recorded snapshot", which would permit a
  future one and is lookahead. The implementation never does that, and `docs/FLOW_VALIDATION_001_AUDIT.md` §2 proves
  it three ways. If no snapshot is available inside the exit window, the position stays explicitly unresolved.
- **Availability is recorded** per row (`receipt_epoch`), which is what makes an honest as-of replay possible.
- **The prior-bar file was obtained OUTSIDE authorization** (`SCOPE_DEVIATION_001.md`), and `FULL_FUNNEL_V1`'s
  variance fit requires it. This is prerequisite P3.

## 3. The frozen evaluation contract

Frozen here, before execution. An amendment after results exist is a dated amendment, never an edit.

**Machinery, all real, none substituted.** The shared lifecycle scheduler (`apex.options_pilot.lifecycle`); the
recording boundary and ledger; `CertifiedRiskAuthority` with the kernel's predeclared limits **unchanged**
($500/trade, $1,500 aggregate, $600 same-underlying, $1,000 family, $1,000 session drawdown); `RISK_ENVELOPE_V1`;
`ROBINHOOD_RHF_2026` v2026-09-12b with decimal-cent arithmetic; `EXECUTION_POLICY_V1`; `EXIT_AT_HORIZON_15M_V1`
(due + 900s, 120s window, at most 5 attempts); the real `Book`; and `apex.options_pilot.accounting` for the
aggregate.

**Adapters and labels.** Recorded adapters read only rows whose recorded availability is at or before the clock.
The run takes the `RECORDED_REPLAY` route: `HISTORICAL_DEVELOPMENT_REPLAY` / `NONE_REPLAY`, with
`live_promotion_eligible`, `prospective_results_eligible` and `live_authorization_eligible` sealed to `False`, and
a `ReplayAuthorization` naming all four inputs by digest. **This will be the route's first use on recorded data.**

**Policies, on identical instants.** `WAIT` (the null, exactly zero), `PILOT_RULE_V2` (the deterministic options
policy) and `FULL_FUNNEL_V1`. Same 12 scan instants, same chain snapshots, same NBBO, same bars, same clock.

**Candidate universes, declared rather than reconciled.** They differ, and that difference is a known confound the
run must not paper over:

| policy | universe |
|---|---|
| `PILOT_RULE_V2` | first expiry with DTE ≥ 21; nearest cap-feasible strike on the signal's side |
| `FULL_FUNNEL_V1` | first expiry with DTE ≥ 21; ATM ± 4 strikes, both rights |

The comparison therefore varies **both** the intelligence and the available contracts. The report must say so and
must not attribute any difference to the intelligence.

**No new fitting, no substitution.** No model is fitted beyond the funnel's own declared walk-forward variance fit
on the retained prior bars. No model is silently replaced by a fallback: a stage that cannot run records
`UNAVAILABLE` with its reason. `JOINT_FUNNEL_V1` stays unavailable, since no R4 fit is authorized.

**Nothing is tuned to produce a trade.** No strike band widened, no limit raised, no fee altered, no universe
extended, no threshold moved. **A no-trade result is a valid result.**

**Retention.** Every scan, decision, rejection, refusal, exit attempt, unresolved obligation and integrity problem
is persisted. Each policy writes its own quarantined ledger, never merged. Output goes to a **unique run
directory** that refuses a collision and never unlinks or overwrites, carrying `RUN_START.json` with the code pin,
the four input digests and the configuration digest, and exactly one terminal marker.

## 4. Acceptance: lifecycle and evidence integrity, not economics

The run **passes** if all of the following hold, and **fails** if any does not. None of them mentions profit.

1. **Chronological availability.** No scan sees a quote, bar or event whose recorded availability is after its own
   instant.
2. **No clock rewind.** Every clock advance has a non-negative delta and the event stream is monotonic in canonical
   microseconds.
3. **Timely exit attempts.** Every fill's first valuation attempt falls at or after its due instant and at or
   before its window close, and no exit waits for a later scan.
4. **Correct reservations.** Reserved capital equals the sum of open envelope debits at every point, is released
   when an intent finishes, and is never `None` while presented as a number.
5. **No duplicate fills or fees.** One fill per intent, one entry fee per fill, one exit fee per resolved outcome.
6. **Explicit unknown accounting.** `total_net_pnl` is a number only when the aggregate is complete; otherwise it
   is null with named reasons. `assert_no_phantom_zero` passes. An unresolved or exhausted position appears in the
   aggregate as an obligation, never as a zero.
7. **Independent reconstruction.** Cash, fees, reservations and P&L recomputed from primary ledger fields agree
   with the Book line by line, the hash chain verifies, and every decision reconstructs from its receipts.
8. **Honest labels.** Every persisted record carries the replay evidence class, and `prospective_only()` excludes
   all of them.

A crash is an acceptable outcome of a first run: the run directory preserves the partial ledger and a
`RUN_FAILED.json`, and that is itself evidence about the flow.

## 5. How economics may be reported

Descriptively, on an exposed partial session, and never otherwise. Permitted: the count of trades, the realized
amounts where estimable, the observed fees, the spread crossed, the decisions by kind, and the obligations left
open. **Forbidden:** calling it out-of-sample, clean, a profitability finding, an edge claim, a calibration result,
or a test of shares versus options. The direction input remains a labelled placeholder (`SIGNAL_STATUS_001.md`), so
a negative result is the expected result and says nothing about the system.

## 6. Unresolved prerequisites

| | prerequisite | who |
|---|---|---|
| **P1** | **Independent review of `operating-loop-001` at `e8ebbee`.** The scheduler, the canonical instant change, the replay route and the accounting are all builder-reported. | reviewer |
| **P2** | **Authorization to consume the burned collection for this evaluation.** The data is already burned, so no new exposure is created, but the register records uses and this one is not yet listed. | operator |
| **P3** | **A ruling on the prior-bar file.** It was obtained outside authorization (`SCOPE_DEVIATION_001.md`) and `FULL_FUNNEL_V1` cannot fit its variance model without it. Either authorize its use for this evaluation, or run with `WAIT` and `PILOT_RULE_V2` only and record the funnel as unavailable. **Do not run the funnel on it without a ruling.** | operator |
| **P4** | **A durable copy of the four input files.** They currently live only in a session scratchpad that may be cleaned. Copy to a declared path and record digests before running. | either |
| **P5** | **RETIRED by the audit.** The driver has now executed end to end on synthetic inputs, and doing so found a crash that would have hit the recorded run at its first exit. See `docs/FLOW_VALIDATION_001_AUDIT.md`. | — |
| **P6** | **First use of the `RECORDED_REPLAY` route on recorded data.** Its behaviour is proven synthetically only. | noted |

## 7. The exact proposed command

After P1 to P4 are resolved, from a checkout at `e8ebbee` with an interpreter outside it:

```bash
python scripts/loop_demonstration.py \
  <durable_collection_dir> \
  <durable_prior_bars_SPY.json> \
  docs/evidence/flow_validation \
  flow_validation_001
```

It writes `docs/evidence/flow_validation/flow_validation_001/` containing `RUN_START.json`, one quarantined ledger
per policy, `loop_demonstration.json`, and one terminal marker. It refuses if that directory already exists.

If P3 is declined, the same command runs with the funnel excluded and the exclusion recorded, which requires a
one-line change to the policy tuple in the driver and is not made here.

**Nothing recorded has been executed.**

**AUDITED 2026-09-12.** `docs/FLOW_VALIDATION_001_AUDIT.md` is the pre-execution audit of this package. It corrected
two of my classifications, corrected the quote-selection wording above, closed a real hole in the replay route's
input binding, and found a crash in the driver. The command in §7 is superseded by the two-step command at the end
of the audit, which preserves the inputs first and passes their manifest.
