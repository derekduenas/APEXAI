# FLOW-VALIDATION-001 — pre-execution audit (2026-09-12)

Review and synthetic verification only. **No recorded data was evaluated.** Every driver scenario below ran the
actual command line in a subprocess against a generated collection; no market observation was read.

**Candidate pin for the evaluation:** `operating-loop-001` at `e8ebbee94a0933d34efd1061d439bbd9a75b310d`, plus the
audit repairs committed on `flow-validation-001` and listed under "What the audit changed".

**SECOND PASS, after review of `f87113a`.** Two further findings were raised against the driver and both were
correct. Section 7 below closes them, and `docs/FLOW_VALIDATION_001_FIT_CONTRACT.md` answers P7 in full.

## The headline: the audit found a crash the recorded run would have hit

`scripts/loop_demonstration.py` stripped `exit_quote_fn` from its sources, a line the old driver needed because it
called `S.scan(**src)` directly. Under the shared scheduler that key is what services exits. **The first exit of
the recorded run would have died with `KeyError: 'exit_quote_fn'`**, after the scans had run and a position was
open. Nothing short of executing the real command would have found it: every library test passes, because the
library was never the problem.

It is fixed, and `LifecycleRunner` now refuses at construction when a source the loop needs is absent, so the same
class of mistake surfaces immediately rather than mid-run.

## Readiness table

| # | check | verdict | evidence |
|---|---|---|---|
| 1 | Actual decision path mapped from records | **PASS** | Map below, read off persisted `model_identity` and `pilot_funnel` traces, not off source. Every one of the eight funnel stages carries a value or a named absence on every decision |
| 1b | Unavailable layers named, not implied | **PASS** | `joint_engine` UNAVAILABLE with reason on both policies; `variance`/`regime`/`simulation` UNAVAILABLE by design on the rule path; signal labelled `PLACEHOLDER_NOT_A_SIGNAL` |
| 1c | Fallbacks identified | **PASS, with a finding** | A real fallback exists: GARCH-t → EWMA. On the synthetic fixture it fired (`NU_AT_BOUND`) and was recorded per scan as `variance_kind` |
| 2 | Quote visibility uses recorded availability | **WAS PARTIAL, NOW PASS** | Chain was correct. NBBO used the quote's own `as_of` and bars fell back to `event_time + 60`; both fixed. All families now pass one gate. §7 |
| 2b | No fabricated fill when no quote is eligible | **PASS** | Chain gap across an exit window leaves an explicit unresolved obligation and a null net |
| 3 | Replay dataset/use authorization and input binding | **WAS FAIL, NOW PASS** | The authorization recorded digests that nothing verified. It now recomputes them from the files that will be read and refuses a mismatch; a boundary is refused until inputs are verified |
| 3b | Verification precedes parsing | **WAS FAIL, NOW PASS** | Inputs were parsed at the top and verified at the bottom. The run directory is now claimed first, the manifest is required, the bytes read are the bytes hashed and the bytes parsed. §7 |
| 3c | Prior-bar historical availability | **GAP, REPORTED NOT ASSUMED** | Every row's receipt is `event_time + 60` exactly, one distinct value across 5,170 rows, from a bulk pull. Classified `FORMULAIC_NOT_MEASURED`; the assumption is P3 |
| 7 | Fit contract enumerated and budgeted | **PASS** | `docs/FLOW_VALIDATION_001_FIT_CONTRACT.md`. One `fit()` call, at most three counted attempts, internal optimizer attempts enumerated. Budget pinned to 3 |
| 4 | The `alpaca` governance finding | **PASS, test is stale** | Twelve market-data references, no broker SDK, no placement function. The mechanical placement scan returns zero offenders. Detail below |
| 4b | The "stale exemption register" finding | **MISCLASSIFIED BY ME — it is environmental** | `REPO = Path("/opt/apex-repo")` is hardcoded in that test. All six registered files exist in the checkout |
| 5 | Driver and CLI exercised on synthetic inputs | **PASS** | Six scenarios, 23 tests, real subprocess |
| 5b | Independent reconstruction of results | **PASS** | Book vs primary-field recomputation agrees line by line; hash chain verifies |
| 6 | Durable input preservation and manifest | **PASS** | `scripts/preserve_inputs.py`, copies re-read after writing, refuses to overwrite, carries the acquisition history |
| — | Recorded evaluation authorization | **UNVERIFIED, operator decision** | P2 and P3 below are unresolved |
| — | Independent review of the candidate | **UNVERIFIED** | Still outstanding, and this audit does not substitute for it |

## 1. The actual invocation map

Read from the records of a synthetic run, per policy.

| stage | `PILOT_RULE_V2` | `FULL_FUNNEL_V1` |
|---|---|---|
| data | recorded chain, NBBO and bars, gated on `receipt_epoch <= now` | same |
| Twin | `compose()` → `OPTIONS_TWIN_STATE_V0`, `state_hash` on the funnel trace | same |
| forecast | `EXP002_L`, `NOT_VALIDATED: INVALID_NULL_CONTROL` | same |
| signal | `HEURISTIC_DIRECTION_V1`, `PLACEHOLDER_NOT_A_SIGNAL` | same |
| variance | `UNAVAILABLE` by design | `GARCH-t/EWMA`, fit `READY`, **fell back to EWMA on this fixture** |
| regime | `UNAVAILABLE` by design | `CAUSAL_REGIME_FILTER_V1`, `RAN` |
| simulation | `UNAVAILABLE` by design | `ConditionalSimulator`, 2000 paths |
| candidates | none recorded, only the chosen contract | `expression_war.table`, ATM ± 4 both rights |
| selection | `PILOT_RULE_V2` deterministic rule | expression war then PRIME |
| risk | `RISK_CERTIFICATE_V0` + `ORGANISM_PAPER_V1` + `RISK_ENVELOPE_V1` + `ROBINHOOD_RHF_2026` | same |
| fill | recording boundary, `EXECUTION_POLICY_V1` | same |
| exit | `EXIT_AT_HORIZON_15M_V1`, scheduler event | same |
| Book | real `Book` + `accounting.net_result` | same |
| joint engine (R4) | `UNAVAILABLE`: no authorized fit | `UNAVAILABLE`: same |

**A reporting defect found and fixed.** `model_identity` was computed before the run, so it reported the engine's
fit state before anything was fitted and contradicted the per-scan records: header said `NOT_FITTED` and
`NOT_REACHED` while every `pilot_funnel` record said `READY` and `RAN`. It is now computed after the run, and the
pre-run snapshot is retained separately as `model_identity_at_start`. **The per-scan `pilot_funnel.engine.fit`
records remain authoritative.**

**The fallback, stated plainly.** `FULL_FUNNEL_V1` may substitute EWMA for GARCH-t when the GARCH fit refuses, and
on the synthetic fixture it did, with `NU_AT_BOUND`. This is a declared, recorded substitution, not a silent one,
but it is a substitution and the recorded run may or may not trigger it. Read `variance_kind` on every scan before
reading anything else about the funnel's output.

## 2. "Nearest recorded snapshot" was the wrong phrase, and the code is right

The `FLOW_VALIDATION_001_PACKAGE.md` said an exit is valued "at the nearest recorded snapshot". **Nearest can mean
a future one, and that would be lookahead.** The implementation does not do that. `Rec._snap()` keeps only
snapshots whose recorded `receipt_epoch` is at or before the current instant and takes the last of them: the most
recent AVAILABLE snapshot, never the closest in absolute time. The package wording is corrected.

Three proofs, all synthetic:

- **The general invariant over a whole run.** For every fill and every outcome, the provider's own timestamp on the
  quote used is at or before the instant that requested it. Asserted across both trading policies, with a floor on
  how many records must have been checked so the assertion cannot pass vacuously.
- **A closer future quote loses to an older available one.** The snapshot immediately after each scan instant is
  rewritten to be far cheaper. A nearest-in-time lookup would often pick it, since it can sit closer to the instant
  than the previous snapshot. No fill in the run uses that price.
- **No eligible quote in the window leaves it unresolved.** A chain gap spanning an exit window produces an
  explicit unresolved obligation, a null total net with a named reason, and no outcome resolved against a quote
  from outside its window.

The scheduler does exactly what the correction asks: it advances to the deadline, applies the exit policy and the
freshness rules there, retries on schedule inside the window, and records exhaustion rather than reaching for a
convenient quote.

## 3. The replay route's own controls: a real gap, now closed

**Not importing `real_data` establishes only that one corpus boundary is absent.** Reviewed directly, the replay
route's own controls had a hole: `ReplayAuthorization` recorded input digests and **nothing ever checked them**.
The authorization described what someone said the inputs were.

Closed. `verify_inputs()` recomputes every declared digest from the file that will actually be read and refuses a
mismatch, a missing label, an unnamed extra, or a missing file. `replay_boundary` refuses to construct until that
has happened. The driver calls it before the run.

A second distinction the audit added, because verification against a digest you just computed yourself is close to
worthless: the run records **where the declared digests came from**. With `scripts/preserve_inputs.py`'s manifest
the declaration is independent; without one the run states that it proves only that the bytes did not change
between two reads in the same process.

Also confirmed: every persisted record carries the replay evidence class, the three exclusion flags are `False`,
and `prospective_only()` returns nothing from a replay ledger.

## 4. The two repository-content failures

**The `alpaca` finding: a stale test, not execution in research.** Reproducing the scan, twelve unexempted files
name the vendor. Every one is market data: a corpus id (`CORPUS:ALPACA_1M`), a data URL constant, an adapter class
name, a health-artifact filename, three experiment `SOURCE` strings, a checkpoint-graph label, a fee-schedule note
naming the account's data vendor, and header helpers. **No file imports a broker SDK.** The other five banned terms
(`import ib_insync`, `robin_stocks`, `order_management`, `place_order`, `submit_order`) appear nowhere outside the
three sealed modules. And the invariant the test itself calls "the claim that actually matters",
`scan_package_for_placement("apex")`, returns **zero offenders**.

The test's own docstring already exempts five modules for precisely this reason. The exemption list simply never
grew as a legitimate data vendor's name spread. **I did not weaken the test.** Two of the twelve
(`pulse_options/providers.py`, `pulse_options/sources.py`) are on the options replay path, and they are the data
adapters, which is what they should be. A reviewer should decide between extending the exemptions with the same
recorded justification and narrowing the term to an SDK import.

**The "stale exemption register": I misclassified it.** That test hardcodes `REPO = Path("/opt/apex-repo")`. All
six registered files exist in the checkout; the check reports them absent because the root it looks under does not
exist on this host. **It is an environment failure, not a repo-content one**, which makes the tally thirteen
environment and one repo-content, not twelve and two. The register is not stale.

## 5. The driver and CLI, exercised

`tests/test_flow_validation_readiness.py`, **23 tests, all passing**, each driver scenario a real subprocess against
`tests/synthetic_collection.py`, which writes the collector's exact on-disk shape including vendor string values and
Eastern-naive quote timestamps. A tidier fixture would have bypassed the provider-boundary validation entirely; the
first version did, and produced zero eligible expiries until it was made faithful.

| scenario | result |
|---|---|
| successful lifecycle | rule path trades, exits service at their deadlines, session closes |
| mandatory WAIT | every contract above the cap: no trades, every WAIT persisted with a reason, total exactly 0.00 with `ACTUAL_NO_TRADE_POLICY` |
| missing exit | chain gap leaves an explicit unresolved obligation and a null net |
| restart | **not applicable at the driver level**, and the audit says so rather than faking it. Each run claims a fresh directory and therefore a fresh ledger. Restart recovery is proven where it lives, over one ledger across two processes |
| output collision | second run with the same id refused, first run's artifacts byte-identical afterwards |
| failure preservation | a corrupt input fails the run; `RUN_START.json`, the partial ledgers and `RUN_FAILED.json` all survive |

The failure-preservation case was first demonstrated by accident, when the `exit_quote_fn` crash left exactly those
artifacts behind.

## What the audit changed

| file | change |
|---|---|
| `scripts/loop_demonstration.py` | stopped stripping `exit_quote_fn`; claims the run directory first; **requires** a manifest; reads bytes once, verifies those bytes, parses the same objects; gates NBBO on the record receipt; invents no bar receipt; classifies the prior-bar availability; pins `fit_budget = 3`; computes `model_identity` after the run |
| `apex/options_pilot/lifecycle.py` | `LifecycleRunner` refuses at construction when a required source is missing |
| `apex/options_pilot/replay.py` | `verify_inputs()`, `verify_bytes()`, `digest`, `most_recent_available()`, and `replay_boundary` gated on verified inputs |
| `scripts/preserve_inputs.py` | new: durable copy, verified after writing, manifest, refuses to overwrite, carries acquisition history |
| `tests/synthetic_collection.py` | new: a vendor-faithful synthetic collection generator |
| `tests/test_flow_validation_readiness.py` | new: the audit, 23 tests |
| `tests/test_operating_loop_001.py` | two label tests now name their `require_verified_inputs=False` waiver |

| `docs/FLOW_VALIDATION_001_FIT_CONTRACT.md` | new: the enumerated fit contract and this run's budget |

No model was added, no parameter tuned, no limit changed, no recorded data read. `fit_budget` is a run parameter
pinned to the enumerated maximum, not a tuning of any model. Suites re-run at the end of the second pass.

## 7. The two findings raised against `f87113a`, closed

### Verification ran after parsing, and could not refuse before it

Correct. The driver parsed all four inputs near the top and called `verify_inputs()` near the bottom. The digest
described one read and the decisions came from another, so a file replaced between the two would have passed and
then been used. It also could not refuse before parsing, and the run directory was claimed too late for a
validation failure to leave any evidence.

Closed, in this order:

1. **The run directory is claimed first**, before any input is opened, so a refusal is still a recorded run.
2. **The manifest is now REQUIRED.** Without it the driver exits with `MANIFEST_REQUIRED`; a digest this process
   computes from the same file it reads is not an independent declaration, and the self-declared path is gone.
3. **Each input is read once into memory**, and `ReplayAuthorization.verify_bytes()` hashes **those bytes**.
4. **The same objects are then parsed.** No file is reopened after verification, so there is no second read to
   disagree with the first.
5. Everything from the first read onward sits inside a handler that writes `RUN_FAILED.json` with
   `stage: INPUT_VALIDATION`.

Tested: the manifest requirement; a structural check that read precedes verify precedes parse and that nothing is
re-read afterwards; a replaced file that refuses with `REPLAY_INPUT_DIGEST_MISMATCH` and leaves both `RUN_START` and
`RUN_FAILED` behind; and a path passed where bytes are required.

### Availability was inconsistent across input families

Also correct, and the NBBO case was the serious one.

| family | at `f87113a` | now |
|---|---|---|
| chain | `receipt_epoch` | unchanged, correct |
| NBBO | **`payload["as_of"]`, the quote's own event time** | the record's `receipt_epoch`; `as_of` is retained separately as the event time |
| session bars | `b.get("receipt_time", b["event_time"] + 60.0)` | no default. A bar with no recorded receipt is **excluded and counted** |

Both families now pass through one gate, `replay.most_recent_available()`, which selects the last observation whose
recorded availability is at or before the instant and **refuses a datum whose availability is unknown rather than
backdating it**. The correction that a provider timestamp preceding a request is insufficient is exactly right, and
the test for it uses two quotes that both predate the scan by event time, separated only by when they arrived.

**The prior-bar artifact has no historical availability, and this is now reported rather than assumed.**
`availability_class()` inspects the offsets: every one of the 5,170 rows carries `receipt_time` exactly
`event_time + 60`, a single distinct value, with `publication_time` null throughout. That is a computed offset from
a bulk pull on 2026-09-12, not a record of when APEX could first have seen each bar. The run classifies it
`FORMULAIC_NOT_MEASURED` with `assumption_required: true`, and the proposed assumption is P3 below. **No
point-in-time evidence is manufactured; the gap is stated.**

### P7: the fit contract

Enumerated in `docs/FLOW_VALIDATION_001_FIT_CONTRACT.md`: the caller and its once-per-symbol-per-day trigger, the
seven-day training window and its cutoff, the 400-row minimum, the three counted model-fit attempts, the conditional
EWMA fallback and when it is skipped, the behaviour after each failure, and every internal optimizer attempt that
the counter does not see.

**The budget for this run is 3**, the exact maximum one `fit()` call can consume, pinned in the driver and asserted
against the run's own records. 400 was the constructor default and is not retained.

## Unresolved prerequisites

| | prerequisite | who |
|---|---|---|
| **P1** | Independent review of the candidate. This audit is still builder-reported. | reviewer |
| **P2** | Authorization to consume the burned collection for this evaluation. | operator |
| **P3** | A ruling on the prior-bar file, obtained outside authorization, which `FULL_FUNNEL_V1` needs for its variance fit. Without it, run WAIT and the rule policy only. | operator |
| **P4** | Run `scripts/preserve_inputs.py` to create the durable copy and manifest before executing. | either |
| **P5** | **RETIRED.** The driver has now executed end to end, twelve times, on synthetic inputs. | — |
| **P6** | First use of the recorded-replay route on recorded data. Still true, but the route is now exercised through the real driver rather than only in unit tests. | noted |
| **P7** | **ANSWERED.** The contract is enumerated and the budget is pinned to 3. What remains is the operator's word on the wording below. | operator |

## Exact authorization wording

If you grant these, the words below are what I will treat as the grant and quote into the run's records. Nothing
starts without them.

**P2 — the collection.**

> I authorize one FLOW-VALIDATION-001 diagnostic run to consume `PILOT-COLLECTION/2026-09-11`, already BURNED. This
> authorizes a new use of an exposed dataset. It is not evidence of edge, expectancy or calibration, and it does not
> alter the dataset's status or its prior-use record.

**P3 — the prior bars and their availability assumption.**

> I authorize the retained `ALPACA-SPY-1MIN-2026-09-02..09-11` artifact as an input to this single diagnostic run,
> and I accept the declared assumption `BULK_PULL_AVAILABILITY_V1`: a one-minute bar is treated as available at its
> event time plus sixty seconds. This is a formula, not a recorded receipt, and the artifact carries no evidence of
> when APEX could first have seen each bar. Any claim resting on it is diagnostic only. This authorizes a use; it
> does not retroactively legitimize the acquisition recorded in `SCOPE_DEVIATION_001.md`.

**P7 — the fit.**

> I authorize the declared variance and regime fit for this run under `docs/FLOW_VALIDATION_001_FIT_CONTRACT.md`:
> one `fit()` call, a seven-day training window, a cutoff at the session day start, a 400-row minimum, and a
> model-fit budget of 3. The GARCH-to-EWMA fallback policy is unchanged. No other fit is authorized.

## The command, after P1 to P4

```bash
python scripts/preserve_inputs.py <scratchpad_collection_dir> <scratchpad_prior_bars.json> <durable_dir>
python scripts/loop_demonstration.py <durable_dir>/collection <durable_dir>/prior_bars.json \
  docs/evidence/flow_validation flow_validation_001 <durable_dir>/INPUTS_MANIFEST.json
```

The manifest is the fifth argument and is **required**. The prior bars sit outside the collection directory on
purpose: a different dataset with a different authorization, named separately on the command line.

**Nothing recorded has been executed. Stopping for review.**
