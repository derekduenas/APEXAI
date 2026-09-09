# EXP-002 — HISTORICAL-EXECUTION CANDIDATE AND ADMISSION PACKAGE

**For independent review. Nothing signed. No historical fitting has occurred.**
The synthetic qualification (revision 2) is accepted narrowly: expected behaviour on six
seeded fixtures, not general detection power or a measured false-positive rate.

## 1. Candidate

| | |
|---|---|
| commit | `a7b0b2f935115792e090d31e159fb4942929f12b` |
| bound source tree | `cf28f17315c3adbb195cd79e888571b492272b35fffd71880f20ce0614722a1f`, 57 files |
| EXP-002 registration | `fe15f818129acfb09702cad70401b80f2bdd35af625c44a64800ffa197a3d3f2` — **unchanged since qualification** |
| launcher `research_activation.py` | `4b9b187a…` (not a bound path; pinned by the commit) |
| execute script | `a45fbb27…` (a bound path; covered by the tree) |
| dataset manifest | `3ac8b250…`, 1511 sessions |

The bound tree moved from EXP-001B's `06eee315…` because the exp002 modules and the
experiment switch in the execute script are bound paths. That is precisely why EXP-002
needs its own admission and why an EXP-001B admission cannot authorise it.

## 2. What was preserved, unchanged

The five arms, estimators, information set, horizon, matched selection gate, both
inference methods, the declared bootstrap estimator, and the five-fit budget. The
registration hash proves it. Both synthetic qualification records (revision 1 not
qualified, revision 2 qualified) and EXP-001B's result, registration, signed decisions,
checkouts and aborted run are untouched; hashes in `results/exp002_historical_package.json`.

## 3. The governed path, reused

No parallel authority. `scripts/alpha_exp_real_execute.py` gains `--experiment`
(default EXP-001B) and dispatches registration hash, periods, runner and status map.
The existing loader lists sessions per period; the boundary verifies the decision and
import provenance; `open_run` and `seal_result` are the same functions EXP-001B used.
The launcher names the experiment on the inner command and every operator command,
binds sealed results under the experiment's own run directory, and reads EXP-002's
registration hash from the checkout being launched.

`exp002/historical.py` opens **fit 2016–2018**, **development 2019** (selection
authority; development data with prior exposure) and **observed 2020–2021**
(authority NONE, scored with the same fitted parameters). Evaluation and reserve are
never requested, and their presence in the period map is refused. Exactly five fits
are recorded. A compact hash-chained ledger of every arm's forecast hash is sealed per
row.

## 4. Implementation changes since qualification, and applicability

| change | bound? | effect on the qualified computation |
|---|---|---|
| `run.py`: `tournament` split into `fit_arms` + `evaluate`, one code path | yes | none intended; same operations in the same order. **Spot check:** W2S rerun at full scale under the refactored runner — see package record |
| `historical.py` new adapter | yes | adds the historical periods and the hash ledger; no change to arms, estimators or gates |
| execute script `--experiment` switch | yes | EXP-001B default path unchanged in behaviour |
| launcher `--experiment` | no | plumbing and binding only |
| `evaluate(..., ledger_dir)` compact forecast-hash sealing | yes | records hashes; forecasts are deterministic from recorded params and rows; no arithmetic touched |

The synthetic qualification record was produced by the pre-refactor code. Its
applicability to this candidate rests on the refactor being behaviour-preserving,
supported by the 173-test regression and by the W2S spot check comparing every
statistic against the revision-2 record. A full synthetic rerun on the candidate is
available on request and was not performed unprompted.

## 5. Acceptance on the real path, nothing stubbed

`tests/test_exp002_historical_path.py`, 10 tests, `checkout_root` = this repository, a
clean bound tree required (the file fails rather than skips otherwise):

- plan opens nothing and never lists a sealed period;
- execute opens exactly the fit, development and observed sessions and **never the
  evaluation trap**; roles and authorities recorded as declared;
- **exactly five fits** even with the secondary period, same `params_hash`;
- **import provenance verified for real**, `all_imports_match_admitted_commit = true`;
- an EXP-001B admission is refused for EXP-002 (`EXPERIMENT_MISMATCH`), and the right
  experiment with the wrong registration is refused (`REGISTRATION_MISMATCH`);
- unsigned → `UNSIGNED_DECISION`; wrong key → `SIGNATURE_INVALID`; wrong commit →
  `CODE_IDENTITY_MISMATCH`; wrong tree → `SOURCE_IDENTITY_MISMATCH`; nothing written;
- one result sealed, a second refused, run record names the decision, launcher binding
  accepts it under EXP-002 and rejects it under EXP-001B;
- an exception in the runner exits 5 with the traceback sealed;
- launcher names the experiment on every command and reads both registration hashes;
- **fresh clone in a child interpreter**: the clone's own modules run, import
  provenance and source identity verify against the clone's commit; dirtying one bound
  file forces `SOURCE_DIRTY`.

## 6. Environment and commands

| | |
|---|---|
| research root | `/apex-data/research-exp002` |
| runner root | `/opt/apex-runner-exp002` |
| account | `apexresearch3` |
| decision | `/etc/apex/admissions/exp002_admission.json` |

Read-only preflight against these targets passed with nothing created.

Setup, verify and probe come **after** review, as for revision 2. Then, from the fresh
checkout, after checking the launcher hash:

```bash
sudo -n /usr/bin/python3.12 scripts/research_activation.py launch --research-root /apex-data/research-exp002 --runner-root /opt/apex-runner-exp002 --research-user apexresearch3 --experiment ALPHA-EXP-002 --commit a7b0b2f935115792e090d31e159fb4942929f12b --decision /etc/apex/admissions/exp002_admission.json
```

Append `--apply` to execute. That is the only difference.

## 7. What a result will mean

`MATCHED_IMPROVEMENT` on 2019 selects the quadratic Student-t as a candidate for later
confirmation of incremental predictive information. It is not validated alpha, not
economic value, and licenses nothing in options. `NOT_SELECTED` means this specification
did not demonstrate improvement over the matched linear Student-t on this information
set at this horizon. The 2020–2021 report is context with no authority.

**Stop here for independent review before signing or historical execution.**
