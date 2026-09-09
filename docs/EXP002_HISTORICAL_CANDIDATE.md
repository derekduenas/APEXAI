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

---

## Revision after independent review — candidate `538bbc52`

The reviewer found two code-level blockers in the historical adapter and one
evidence gap. The qualified model specification and both synthetic
qualification records are unchanged; the repair is to the integration only.

| Item | a7b0b2f9 (withdrawn) | 538bbc52 (candidate) |
|---|---|---|
| Candidate commit | `a7b0b2f935115792e090d31e159fb4942929f12b` | `538bbc52e7a00efbf6aca3a1c1082d5941bf1111` |
| Bound source tree | `cf28f17315c3adbb…14722a1f` | `b27d847aeb6a3737a6626c4035bd74ffd04ef6ee400bd80c4b5fc867b0da7428` |
| EXP-002 registration | `fe15f818…` | `fe15f818…` (unchanged) |
| Launcher sha256 (not bound) | `4b9b187a…` | `4b9b187a…` (unchanged) |
| Execute script sha256 (bound) | `a45fbb27…` | `a45fbb27…` (unchanged) |
| Unsigned request | code → a7b0b2f9 | code → 538bbc52, sha256 `4f86b88f…`; dry-validated with a throwaway key: grant as EXP-002, `EXPERIMENT_MISMATCH` as EXP-001B |

### Finding 1 — fit admission bypassed the qualified volatility rule (fixed)

`historical.run` built fit rows with `_usable` (features + target only) and
passed them straight to `fit_arms`; `tournament()` applies `_admit` (RV_FLOOR)
first, and `evaluate()` applies it to scoring rows. Below-floor rows could
therefore reach historical fitting while being refused at scoring.

Reproduction (`scripts/exp002_fit_admission_repro.py`, disposable fixture with
a 60-minute flat-price stretch → 31 rows with `rv_30 == 0`), same fixture on
both trees:

| | old tree a7b0b2f9 | repaired tree 538bbc52 |
|---|---|---|
| usable fit rows / below floor | 1650 / 31 | 1650 / 31 |
| `tournament()` on the same rows | NOT_SELECTED, params `99e9df2fee7597b7`, n_train 1619 | identical |
| `historical.run` | **INVALID_INPUT** — the 31 rows reached the Student-t fit, `INSUFFICIENT_OR_NONFINITE_RESIDUALS` | NOT_SELECTED, params `99e9df2fee7597b7`, n_train 1619, `refused_rows.RV_FLOOR = 31` |

On this fixture the bypass surfaced as a spurious refusal because `rv_30` was
exactly zero (residuals divided by zero). A row with `0 < rv_30 < RV_FLOOR`
would instead have fitted silently on rows the qualified rule excludes; the
repair covers both because fitting now goes through the same `_admit`.

Repair: `_admitted_rows_for` = `_rows_for` → `_admit`; the fit stage records
`usable_rows`, `admitted_rows`, `refused_rows` including `RV_FLOOR`, and the
rule used. Pairing is preserved (a refused row is refused for every arm).
Test: `test_fit_admission_uses_the_qualified_rule_and_reproduces_tournament_params`
— refusal count > 0, `n_train == admitted`, and the fitted `params_hash`
equals `tournament()`'s on independently reloaded rows.

### Finding 2 — observed-period failure could read as overall success (fixed)

The record now carries two distinct fields:

- `scientific_status` — the development verdict (selection authority G1 only), always preserved together with the full `development` block;
- `status` / `execution` — whether the **requested** run completed. If observed reporting was requested and hit an admission refusal, an exception, or an invalid result, `execution.complete = false`, `observed.status = NOT_EVALUATED` with the failure recorded, and `status` becomes `INCOMPLETE_OBSERVED_ADMISSION_REFUSED` (→ `AUTHORIZATION_REFUSED`, exit 3) or `INCOMPLETE_OBSERVED_REPORTING` (→ `INVALID_INPUT_OR_FAILURE`, exit 5). The launcher's `_NOT_COMPLETED` markers (`INCOMPLETE`, `REFUS`, `INVALID`) mean such a result is never counted.

Valid observed statistics are kept, with `promotion_authority = false` and
authority `NONE`. Three tests exercise the cases through the real
execute-and-seal path (file-integrity refusal on an observed session, a
scoring exception, an invalid observed status); each asserts the development
evidence is intact, the exit code is non-zero, and the launcher does not count
the result.

### Evidence — forecast-hash reconstruction (provided)

`forecast_hash` is the content identity and **excludes `creation_time`** by
design (`apex/world_model/forecast.py`, "CONTENT identity — creation_time
deliberately excluded"). The sealed result now persists, per period, the exact
fitted object (`fit.params`, whose recomputed hash equals `params_hash`), the
`forecast_creation_time` actually used, and the identity construction
(`forecast_identity`). `historical.reconstruct()` rebuilds every recorded hash
from those saved artifacts plus freshly admitted rows and compares against
the sealed ledger row by row.

`test_forecast_hashes_reconstruct_from_saved_artifacts`: development and
observed both `rows_admitted == rows_in_ledger == matched_rows == n_dev`, zero
mismatches; negative control (`t.s` × 1.01) → zero matches, arms S/L/C
differing (M0/M1 do not use `t`, so their hashes correctly stay equal).

What the retained hashes establish: that each ledger entry is the content
hash of the forecast produced from the persisted params and that admitted row.
They do not by themselves establish forecast correctness; that is the job of
the qualification and the reference tests.

### Finding 4 — fit-budget evidence by recording spy (added)

`test_fit_budget_by_recording_spy_on_the_real_fitters` wraps the real
`fit_arms`, baseline `fit`, `_fit_lstsq`, `fit_scale_nu` and `forecast`,
delegating to them and recording order. Established: one `fit_arms` call, its
four underlying fitter calls (baseline M0+M1 in one call, L, C, t — five model
fits), no fitter call after the first forecast, forecasts in both periods
built from one and the same params object, and
`development.params_hash == observed.params_hash == fit.params_hash`.

### Applicability of the qualification

`run.py` changes are non-numerical: the row identity builder was lifted to
module level (`pair_identity`, identical output), two fields are recorded
(`params_hash`, `forecast_creation_time`), and a reconstruction function was
added. `models`, `studentt`, `scoring`, `bootstrap`, `controls`, `registration`
are byte-identical to the qualified tree. The reproduction shows
`tournament()` giving the same `params_hash` and status on both trees. A
six-world rerun was therefore not performed.

---

## Revision 3 — reconstruction verifier — candidate `2a09d1ed`

Reviewer finding: `reconstruct()` excluded periods without metadata from the
check, so zero verified periods gave `all([]) == True`, and one present period
could carry overall success. Repair to the verifier only.

| Item | 538bbc52 | 2a09d1ed (candidate) |
|---|---|---|
| Candidate commit | `538bbc52…` | `2a09d1ed329fe0baa1db24afc542b226f4d7855f` |
| Bound source tree | `b27d847a…` | `c855b15d9c97fd76c5b340b042a12f719141b8818b65f808d52ebe2fd2fc2f6d` |
| Registration / launcher / execute script / r2 record | unchanged | `fe15f818…` / `4b9b187a…` / `a45fbb27…` / `884f6f50…` unchanged |
| Unsigned request | code → 538bbc52 | code → 2a09d1ed, sha256 `d8e359a8…`; dry-validated (grant as EXP-002, `EXPERIMENT_MISMATCH` as EXP-001B), throwaway key destroyed |

**Required periods are derived from the saved execution record:** `development`
always; `observed` when `execution.observed_requested` is true. Every
required period must have its metadata (`forecast_creation_time`), its ledger
artifact and its sessions, be checked, and match before `all_match`;
`all_match = (verified_periods == required_periods)` with a non-empty
requirement. Any missing item yields `status = NOT_VERIFIED` with the missing
items listed; zero verified periods can never produce `all_match = True`. A
missing `fit.params` is reported as missing and verifies nothing.

**What reconstruction verifies, separately stated** (`verifies` in the record):

- forecast contents — yes: each admitted row's per-arm forecast hash, looked up by `(event_time, i)`;
- ledger ordering — reported as `ledger_order_matches_admitted` per period and `ledger_ordering_matches` overall; not folded into `all_match`;
- chain integrity — **not verified** (`chain_integrity_verified = false`; the entry/prev hash chain is not checked by this function).

**Tests** (in `test_forecast_hashes_reconstruct_from_saved_artifacts`, alongside the successful and perturbed-parameter cases): both required periods missing → `NOT_VERIFIED`, no verified periods, both listed missing; one required period missing → `NOT_VERIFIED`, development verified alone does not carry success; observed ledger artifact absent → `NOT_VERIFIED`, `missing = ["observed.ledger"]`; observed not requested in the saved record → required is `["development"]` only and verifies; `fit.params` absent → `NOT_VERIFIED`. Perturbed params now report per-period `MISMATCH`.

Numerical logic, model, registration and qualification records untouched; no
six-world rerun, no signing, no historical execution.

---

## Environment setup and verification — 2026-09-09 (candidate `2a09d1ed`)

Sequence as it happened: **preflight passed → setup passed (12 stages VERIFIED, 22 s) → verify did not run** (my ad hoc `git rev-parse` in the same shell chain failed with `dubious ownership` and short-circuited it; no ownership or `safe.directory` change was made) **→ probe passed → verify rerun from the pinned checkout, passed → probe rerun, passed.** Records: `results/exp002_environment_setup.json`.

| Check | Result |
|---|---|
| Candidate / bound tree / launcher vs package | `2a09d1ed…` / `c855b15d…` (57 files) / `4b9b187a…` — all match; launcher hash identical in the pinned checkout |
| Targets | `/apex-data/research-exp002`, `/opt/apex-runner-exp002`, `apexresearch3` — all free before setup, disjoint from production |
| Account | uid 111, gid 114, groups `[apexresearch3]`, no privileged groups, `nologin`, no sudo |
| Ownership | research root/checkout/out owned by uid 111; runner root and venv root-owned 755, 2628 entries checked not writable by the research user |
| Runner | numpy==2.4.6 only, pinned, python 3.12.3 |
| Dataset view | 1511 files == exactly the in-range SPY manifest entries; 22/22 sampled sha256 match the manifest; bound read-only into the sandbox |
| Sandbox probe (launch config) | `MemoryMax=1400M`, `PrivateNetwork=yes`, `ProtectSystem=strict`, `NoNewPrivileges`, corpus visible only via the view: admitted readable, **evaluation not readable** (`SPY_2022-01-03.json` denied), other corpus files not visible, core/history-a/secrets not readable, corpus not writable, network not reachable — zero deviations |
| Preservation | `apexresearch` 109 / `apexresearch2` 110 intact; rev2 sealed result `4b23021d…`; signed decisions `1eafbe1f…`, `28bc2859…`; `allowed_signers` `ae30f60d…` unchanged; synthetic records r1 `f4825320…`, r2 `884f6f50…` unchanged |
| Unsigned request | already names commit `2a09d1ed`, tree `c855b15d…`, output root `/apex-data/research-exp002/out`, the three targets — matches the prepared checkout; unchanged (sha `d8e359a8…`) |

Not done: signing, installing `/etc/apex/admissions/exp002_admission.json`, historical fitting.

**Preparation (no fitting; refuses without a signed decision):**
```
sudo -n /usr/bin/python3.12 /apex-data/research-exp002/checkout/scripts/research_activation.py launch --research-root /apex-data/research-exp002 --runner-root /opt/apex-runner-exp002 --research-user apexresearch3 --experiment ALPHA-EXP-002 --commit 2a09d1ed329fe0baa1db24afc542b226f4d7855f --decision /etc/apex/admissions/exp002_admission.json
```
**Execution (historical fitting; only after review and the operator's off-host signature):** the same command with `--apply` appended.
