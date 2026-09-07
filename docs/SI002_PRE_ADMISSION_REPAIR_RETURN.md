# STRATEGIC-INTEGRATION-002 — PRE-ADMISSION REPAIR — return for independent review

```text
REPRODUCTIONS:           10/10 REPRODUCED at 566600dc (results/si002_reproductions.json); 0 refuted
TEMPORAL_SEMANTICS:      REPAIRED in ALPHA-EXP-001B (exchange calendar, six clocks, elapsed horizon, no imputation)
RESEARCH_GOVERNANCE:     ALPHA-EXP-001 PRESERVED (hash-pinned); ALPHA-EXP-001B REGISTERED (b3930727…), no real row read
ADMISSION_AUTHORITY:     REAL_DATA_BOUNDARY_V1 — OpenSSH-signed decisions, verification-only trust, source-content binding
RUN_IDENTITY:            unique exclusive run dirs; immutable identity/authority/result records; 4 process outcomes
REAL_DATA_ADMISSION:     NOT_AUTHORIZED (no key created, no decision issued; host trust paths non-compliant)
EXP_001B_REAL_EXECUTION: NOT_PERFORMED (command refused NO_DECISION / TRUST_PATH_WRITABLE on the host)
RTH_COMMISSIONING:       PENDING (observer pid 1714883 alive; fires 2026-09-08T13:15Z; untouched)
PAPER_TRADING:           HELD (options-paper, equity-fabric, btc-resolver); no launch
REAL_MONEY_EXECUTION:    NOT_AUTHORIZED
REAL_MARKET_EDGE:        NOT_ESTABLISHED
```

## 1. Reproductions (before any repair)

`scripts/si002_reproduce_findings.py`, run in a detached worktree at
`566600dca8632cd5e3831ef20304c29ae725bb0a` as the `apex` user under the
usual containment, disposable synthetic fixtures under tempdir, actual
functions (`exp001.bars/models/run`, `real_data.boundary/loader`, the
command's `main`). No real corpus row read.

| # | Finding | Status | Measured evidence | Introduced |
|---|---|---|---|---|
| F1 | loader `known_from` not honored by the forecast | REPRODUCED | row `t` = bar open; loader `known_from` = t+60; `forecast.known_from` = t → claims availability 60 s before the bar completes | `7f26e938f`; loader convention added in `566600dca` and not threaded through |
| F2 | outcome availability uses the wrong bar clock | REPRODUCED | `_targets` returns the target bar's OPEN; its completion is +60 s; grader accepted because both clocks were early by one bar | `7f26e938f` |
| F3 | fixed UTC session mishandles winter and early closes | REPRODUCED | winter 2019-01-15: 390 rows kept 13:30Z–19:59Z = 60 pre-market bars included, 60 regular bars dropped; early close 2019-11-29: 120 post-close bars included | `7f26e938f` |
| F4 | missing minutes stretch a row-count horizon | REPRODUCED | 10-minute gap → row i and row i+15 are 25 minutes apart; a target was still returned | `7f26e938f` |
| F5 | validation invokes economics | REPRODUCED | `validation` record carries `economic` with status READY on a NO_SIGNAL run; registration says EVALUATION only | `7f26e938f` |
| F6 | economics not next-bar-open | REPRODUCED | realised = close-to-close target − spread; next-bar-open-to-open differs (row 60: 3.88e-4 vs 4.69e-4); registration says NEXT_BAR_OPEN | `7f26e938f` |
| F7 | `certified_1R` is not certified max loss | REPRODUCED | `"certified_1R": stop + rt` with stop = rv_30; `risk_certificate` not imported by `run.py` | `7f26e938f` |
| F8 | dirty source retains HEAD identity | REPRODUCED | `git status`: ` M apex/world_model/exp001/models.py`; `verify_decision` → GRANT with `code_commit == HEAD` | `566600dca` |
| F9 | invalid result → exit 0 | REPRODUCED | `run()` forced to `INVALID_INPUT`; `main()` returned 0 | `566600dca` |
| F10 | output dir reuse mixes/overwrites evidence | REPRODUCED | second `open_output` returned the same dir; `_AUTHORITY.json` rewritten; prior `forecasts_validation.jsonl` left in place for append | `566600dca` |

Two first-pass "refutations" were artifacts of the reproduction, not of
the findings, and were corrected before recording: F6's fixture had
`open == previous close` (so the two conventions coincided numerically);
F8 ran as root under `systemd-run`, where git refuses the apex-owned
worktree and the verifier hit `CODE_IDENTITY_UNKNOWN` instead of the HEAD
check. No reviewer finding was refuted.

## 2. Repairs

| Area | What changed | Where |
|---|---|---|
| Session | NYSE regular session in exchange-local time; the rule of `apex.intraday.sessions.classify` reproduced (parity-tested, not imported — see §3) with 2016–2026 tables (rule-derived holidays, Good Friday and special-closure tables, early-close rule); bars outside `[open, close)` dropped and counted; wrong-date / unaligned / non-session refused | `apex/world_model/exp001b/exchange_calendar.py`, `exp001b/bars.py` |
| Clocks | six per row (event_time, bar_complete, assumed_available, publication_time=None, decision_time, outcome_available); forecast `known_from` = assumed availability; grader receives target completion; `availability_basis=ASSUMED_BAR_CLOSE` and `publication_time=NOT_AVAILABLE` on every forecast | `exp001b/bars.py`, `exp001b/models.py` |
| Horizon | elapsed 15 minutes: target = bar at exactly t+15 min; features require every minute bar in [t−30, t]; refusals `MISSING_FEATURE_BARS` / `MISSING_TARGET_BAR` / `EMBARGO`; no imputation | `exp001b/bars.py` |
| Validation | distributional only; economics only on a separately unsealed evaluation, from the same sealed M1 forecasts | `exp001b/run.py` |
| Execution convention | NEXT_BAR_OPEN legs: entry open at t+1 min, exit open at t+16 min, half spread per leg; missing leg → NOT_EXECUTABLE | `exp001b/bars.execution_legs`, `run.economic_evaluation` |
| Certification | `certified_1R` removed; `stop_distance_rv30_diagnostic` named diagnostic; `RISK_CERTIFICATION = NONE in this experiment` | `exp001b/registration.py`, `run.py` |
| Registration | ALPHA-EXP-001 untouched (pins); ALPHA-EXP-001B with `SUPERSEDES` (7 defects, `real_outcomes_consulted: False`) | `exp001b/registration.py`, `results/exp001b_registration.json`, `docs/EXP001B_SUCCESSOR_REGISTRATION.md` |
| Admission authority | OpenSSH signatures over the decision file; `allowed_signers` only on the research path; `verify_decision()` has no injection parameters; `verify_decision_with(TrustConfig)` for tests; trust-path mode and ownership checks | `real_data/boundary.py`, `docs/REAL_DATA_BOUNDARY_V1.md` |
| Source binding | `code.commit` = HEAD **and** `code.source_tree_sha256` = content hash of tracked files under the relevant paths **and** those paths clean; runtime import provenance recorded | `boundary.source_identity`, `runtime_provenance` |
| Runs | exclusive directories, `O_EXCL` identity/authority/result records; process outcomes 0/3/4/5 tested through the actual paths | `boundary.open_run/seal_result`, `scripts/alpha_exp_real_execute.py` |
| Removed | `scripts/exp001_real_execute.py` (defective command); V0 proposal withdrawn | — |

## 3. Commits

- Base: `strategic-integration-002` @ `82e76af78` (code at `566600dca`).
- Code candidate 1: `74003aef33d80929cc48195d71ff7ba18e2bdea7` — **failed its own gate**
  (§4): the calendar module sat at the top level of `apex/world_model/` and changed the
  sealed World Model surface hash (`f6b87f29…` → `92750b69…`, pinned by the closed courts),
  and it imported `apex.intraday.sessions`, which the World Model import law forbids; one
  test used per-process-random `hash()` seeds.
- Code candidate 2 (final code): `28153e1affc2d05b5dccc92ffc075abece8d9770` — calendar moved
  to `apex/world_model/exp001b/exchange_calendar.py` (surface hash restored to `f6b87f29…`),
  production import removed and replaced by a test-side parity proof against
  `apex.intraday.sessions.classify` over a 54k-point grid, deterministic seeds. Relevant
  source tree `720f1ad0d0a3a0f7dda67b8b05c39227189624af9dfe9b2170345222e1efc6e2` (48 files, clean).
- Documentation (this return, packages, supersession notes): the docs-only commit
  immediately following `28153e1a` — relevant source tree unchanged by construction (docs
  are outside `RELEVANT_SOURCE_PATHS`; re-verified after the commit, see §3a).

On "reuse governed exchange-session machinery": the rule of
`apex.intraday.sessions.classify` is reused (same wall-clock windows, same table
semantics) but the module cannot be imported by the laboratory without breaking a
frozen law; the tables (2016–2026) were supplied to BOTH implementations in the parity
test. Recorded as a deliberate deviation from the literal instruction.

Changed files: `apex/world_model/exp001b/exchange_calendar.py` (new),
`apex/world_model/exp001b/{__init__,registration,bars,models,run}.py` (new),
`apex/world_model/real_data/{boundary,loader}.py` (rewritten),
`scripts/alpha_exp_real_execute.py` (new), `scripts/si002_reproduce_findings.py` (new),
`scripts/exp001_real_execute.py` (deleted), `tests/test_exchange_calendar.py`,
`tests/test_exp001b_temporal.py`, `tests/test_real_data_boundary.py` (new/rewritten),
`results/si002_reproductions.json`, `results/exp001b_registration.json`,
docs: `EXP001B_SUCCESSOR_REGISTRATION.md`, `REAL_DATA_BOUNDARY_V1.md`,
`EXP001B_ADMISSION_PACKAGE.md`, `admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json`,
this file; amended `REAL_DATA_BOUNDARY_V0.md`, `STRATEGIC_INTEGRATION_002_RETURN.md`;
withdrawn `admissions/EXP001_ADMISSION_DECISION_PROPOSED.json`.

### 3a. Source identity across the docs-only commit

`RELEVANT_SOURCE_PATHS` exclude `docs/` and `results/`, so the tree hash
`720f1ad0…` is unchanged by the documentation commit by construction. It
is re-computed on the host after that commit (`source_identity` on the
worktree: commit = new HEAD, `tree_sha256 = 720f1ad0…`, `dirty = []`) and
reported with the return message; the authority fills `code.commit` with
that HEAD.

## 4. Tests

Focused (worktree, `MemoryMax=1400M`, run as `apex`): **90 passed** —
`test_exchange_calendar` 28 (26 before the parity and placement tests were added), `test_exp001b_temporal` 12,
`test_real_data_boundary` 27, `test_exp001_engineering` 13 and
`test_exp001_economic_path` 12 unchanged.

Applicable bounded regression (every module touching `world_model`,
`chain_ledger` or `exp001`; one contained shard each; as `apex`). Gate 2 on
`74003aef` **failed** — 10 of 24 modules, all traceable to the calendar's location and
import and to one random seed (surface-hash pins in `test_result_audit` ×4,
`test_result_validator`, `test_world_model_r7`, `test_world_model_r71_qualification`;
import-law checks in `test_world_model_authority/contracts/court/teststand/worlds`;
`test_command_outcomes…` seed). Gate 3 on the final code `28153e1a`:

```text
24 modules, 24 rc=0, 718 passed, 0 failed, 0 errors; 22:59:44Z -> 23:08:23Z; MemoryMax=1400M per shard, User=apex, 0 kills
test_bounded_regression 12 | test_exchange_calendar 28 | test_exp001_economic_path 12 | test_exp001_engineering 13
test_exp001b_temporal 12 | test_ledger_concurrency 4 | test_live_book 17 | test_real_data_boundary 27
test_result_audit 37 | test_result_validator 164 | test_verification_law 12 | test_world_model_authority 24
test_world_model_bootstrap 24 | test_world_model_contracts 86 | test_world_model_court 30 | test_world_model_inference 17
test_world_model_r3 13 | test_world_model_r4 8 | test_world_model_r5 13 | test_world_model_r51 9
test_world_model_r7 11 | test_world_model_r71_qualification 13 | test_world_model_teststand 43 | test_world_model_worlds 89
```

Scope: modules selected by grep for `world_model`, `chain_ledger` or `exp001`
under `tests/`; not the WM line's full 4,213-nodeid regression (the WM
branch is unmodified). The sealed surface hash `f6b87f29…` is re-pinned by
`test_result_audit`, `test_result_validator`, `test_world_model_r7` and
`test_world_model_r71_qualification` in this run.

Honest limitations: fixtures are synthetic; the calendar tables are
rule-derived and not independently verified against each year's exchange
notice (a wrong entry refuses rows, it never invents them); the end-to-end
run proves the route reaches `fit`/`validation` and keeps evaluation
sealed, nothing about real data; ownership enforcement is exercised in
tests only via `enforce_ownership=True` against test-owned files (refusal
path), since tests cannot create foreign-owned files.

## 5. Preservation evidence

| Item | Check | Result |
|---|---|---|
| EXP-001 registration | `registration_hash()` `1a3f55a5…`; `registration.py` `11afb342…`; `results/exp001_registration.json` `96ea6edc…` | unchanged (pinned in two suites) |
| Laboratory boundary | `sources.py` `25131307…`, `authority.py` `b33091a2…` | unchanged (pinned) |
| EXP-001 code and tests | `test_exp001_engineering` 13, `test_exp001_economic_path` 12 | pass, unmodified |
| Production release | `/opt/apex/current` → `73fc712d…` | unchanged |
| Maintenance holds | three markers; options-paper inactive, `ConditionResult=no` | intact |
| RTH observer | pid 1714883 alive; window untouched; no artifact yet | intact |
| Sealed courts / WM line | `d01e961b6` untouched | intact |
| Admission key / decision / real run | none created, none issued, none performed | as required |

## 6. Successor registration and revised admission package

`docs/EXP001B_SUCCESSOR_REGISTRATION.md` (why it supersedes, no outcomes
consulted) and `docs/EXP001B_ADMISSION_PACKAGE.md` (precise eligible use:
train + validation, distributional only, SPY OHLCV+event_time 2016–2021,
restricted use named; unresolved limitations listed). Proposal:
`docs/admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json` — unsigned,
`PROPOSED`, `code.commit` to be filled by the authority; the relevant
source tree hash is fixed at `720f1ad0…`.

## 7. Host state the authority must fix before any admission can verify

`/apex-data/governance/admissions` is owned by `apex` with mode 775; no
`trust/allowed_signers`; no `/apex-data/research`. The verifier refuses
(`TRUST_PATH_WRITABLE`, then ownership, then `TRUST_PATH_MISSING`) until an
operator makes the admission root and trust directory root-owned (0755),
places `allowed_signers` (0644), and signs the decision file out of band.
Engineering did not and will not perform these steps.

## 8. One exact next authorization request

Review and, if accepted, issue the signed decision from
`docs/admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json` per §7, then
authorize exactly:

```text
PYTHONPATH=/apex-data/tmp/si002_wt /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py --decision <path> --execute
```

Expected outcomes: `SCIENTIFIC_COMPLETE/NO_SIGNAL` (exit 0) or
`EVALUATION_SEALED` (exit 4). Nothing else is requested; EXP-002, the
participant model and new data acquisition were not touched.
