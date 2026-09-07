# STRATEGIC-INTEGRATION-002 — PRE-ADMISSION CLOSURE — return for independent review

```text
A_TRUST_PATH:            host measured, gaps CONFIRMED, verification enforces the whole ancestor
                         chain and a trusted verifier executable; operator changes prepared, NOT executed
B_CALENDAR_2016_2021:    independently reconciled date by date, ZERO mismatches; the "wrong table
                         fails closed" claim CORRECTED and both silent-distortion cases reproduced
C_RUN_PROVENANCE:        imports verified byte-for-byte against the admitted commit; source identity
                         recomputed at completion; a changed source marks the result invalid
REAL_DATA_ADMISSION:     NOT_AUTHORIZED (no key created, no decision issued; trust chain absent)
EXP_001B_REAL_EXECUTION: NOT_PERFORMED
EXP_001B_REGISTRATION:   UNCHANGED (b3930727…) -- no table error was found, so no re-registration
RTH_COMMISSIONING:       PENDING (observer pid 1714883, fires 2026-09-08T13:15Z, untouched)
PAPER_TRADING:           HELD ×3; REAL_MONEY_EXECUTION: NOT_AUTHORIZED; REAL_MARKET_EDGE: NOT_ESTABLISHED
```

## 1. Commits

| Commit | Content |
|---|---|
| `3e7df9973` | closure implementation A/B/C, tests, reproductions, reconciliation and audit artifacts |
| `e9a1972f0` | audit targets the production constants (outside `RELEVANT_SOURCE_PATHS`) |
| **`6be2507fb`** | **final code**: production admission root → `/etc/apex/admissions` |
| `__DOCS__` | this return, operator package, revised proposal, spec amendments (docs only; outside `RELEVANT_SOURCE_PATHS`, so the bound tree is unchanged — re-verified after the commit) |

Final bound source tree: **`24322971f61bcf2c02d1f98d77aa3c2ea20f1695122af03779bd64e70316dd8c`**
(48 tracked files under the relevant paths, clean). Base: `f829f3be9`.

One process note: the `/etc/apex` constant change was written in an earlier
command that died on a shell parse error, so it never ran, and `3e7df997`
shipped the old paths while the audit still reported the old location. Caught
by reading the recorded chain rather than the summary line, and fixed in
`6be2507f`. The audit was re-run against the corrected constants.

## 2. A — trust-path and verifier provenance

**Measured, not inferred** (`results/si002_trust_path_audit.json`,
`scripts/si002_trust_path_audit.py`, read-only):

| Component | uid | mode | research can replace? |
|---|---|---|---|
| `/` | 0 | 0755 | no |
| `/apex-data` | **1000 (research)** | 0755 | **yes — it owns it** |
| `/apex-data/governance` | 1000 | 0775 | **yes** |
| `/apex-data/governance/admissions` | 1000 | 0775 | **yes** |
| `/etc` | 0 | 0755 | no |
| `/etc/apex/admissions` (new root) | — | absent | **no replaceable component** |

The reviewer's point is confirmed exactly: root-owning `admissions/` would
have established nothing, because its parent is research-owned and the whole
directory can be renamed away. **And a larger finding the audit surfaced: the
research account holds `(ALL) NOPASSWD: ALL`.** While that is true, no
filesystem check is a boundary against it. That cannot be fixed in code; it is
item 6 of the operator package (a separate unprivileged research account), and
it is stated in the module docstring rather than papered over.

**Enforced now:**

- `_check_ancestor_chain` walks `/` → leaf for the admission root, the
  `allowed_signers`, the decision and its signature, refusing
  `TRUST_PATH_WRITABLE` / `TRUST_PATH_OWNED_BY_RESEARCH` **naming the offending
  component**. Sticky world-writable directories are the one exception (sticky
  forbids renaming another owner's entry — this is what makes `/tmp` chains
  legitimate), and that exception is itself tested.
- `trusted_executable` refuses a relative name (`VERIFIER_NOT_ABSOLUTE` — a
  PATH lookup is a lookup in directories the caller can influence), a missing
  one, a non-root-owned one, or one whose ancestor chain is writable. The
  verifier runs with `env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "IFS": …}`
  and `cwd="/"` — nothing inherited, asserted by a test that captures the real
  subprocess kwargs.
- Production constants moved to `/etc/apex/admissions`; the dataset manifest
  deliberately stays outside the trust chain because the signed decision
  commits to its sha256.
- `SHARED_CHECKOUT` refuses execution from `/opt/apex-repo`, `/opt/apex/current`
  or a release.

**Verifier decision on today's host:** `WOULD_REFUSE — TRUST_PATH_MISSING:
/etc/apex`. Correct: fail-closed until the operator acts.

## 3. B — calendar validation for 2016–2021

**Independent reconciliation** (`results/exp001b_calendar_reconciliation_2016_2021.json`,
`scripts/si002_calendar_reconciliation.py`): the primary NYSE Group
announcements were transcribed per year and compared **date by date, on both
attributes**, for every weekday in the window.

| | authoritative | code table |
|---|---|---|
| holidays 2016-01-04..2021-12-31 | 54 | 54 |
| early closes | 12 | 12 |
| weekdays examined | 1,565 | — |
| **mismatches** | **0** | |

Sources (each cited in the artifact): ICE IR releases of 2014-12-08 (2016),
2016-02-02 (2017), 2017-11-27 (2018–2020), 2018-12-04 (2019–2021), and the
2018 announcement of the 2018-12-05 national-day-of-mourning closure. Two
source conflicts were resolved and recorded rather than smoothed over:

1. The 2017-11-27 release lists 2020 Independence Day as an early close on
   Friday 2020-07-03; the later 2018-12-04 release lists that Friday as the
   **full closure**. The later release governs, and matches the code table.
2. A secondary aggregator reports a **2:00 p.m.** close on 2016-11-25. That is
   SIFMA's recommended **bond**-market close; the NYSE equities release states
   1:00 p.m. (crossing session to 1:30). The primary equities source governs.

Searched for unscheduled closures in the window: none beyond 2018-12-05. The
2020 trading-floor closure did not close the market — electronic trading
continued, so no session is absent for it.

**Corpus cross-check, metadata only** (file names, session dates and byte
sizes from the committed manifest; **no bar parsed**, and nothing outside
2016–2021 touched):

- 1,511 SPY sessions present; **none missing** relative to the authoritative
  calendar; **none present on an authoritative holiday**. That is an
  independent confirmation of the holiday table.
- Early closes are only partially corroborated by size: 10 of 12 fall below
  the 5th percentile of full-session file size (0.845 of median); the two
  exceptions are 2018-12-24 (0.875) and 2021-11-26 (0.976). No full session
  falls below the smallest early-close ratio's neighbourhood except one
  (min 0.738), and **no short file is a non-early-close day**. So the size
  proxy corroborates 10 of 12 and is silent — not contradictory — on 2. Stated
  as corroboration, not proof: byte size cannot establish a close time.

**The false claim is corrected, and both failure modes are reproduced:**

| Case | Behaviour (measured on disposable bars) |
|---|---|
| early close **omitted** (2019-11-29) | 390 rows admitted instead of 210 — **180 post-close bars silently accepted**, `dropped_outside_session.after_close = 0`, no refusal |
| early close **wrongly added** (2019-11-22) | 210 rows instead of 390 — **180 valid bars silently discarded**, no refusal |
| **holiday** error | `NOT_A_SESSION: HOLIDAY` — the only calendar error that fails closed |

Because a wrong table distorts rather than refuses, the calendar now carries
an explicit `VERIFICATION` record and
`session_bounds(require_verified=True)` — which the loader **always** passes —
refuses any date outside the reconciled window with `CALENDAR_NOT_VERIFIED`.
Behaviour inside 2016–2021 is bit-identical, so the EXP-001B registration is
**unchanged** (no table error was found; the registration is not edited to
tidy prose). Dates in 2022–2026 are now refused until reconciled — recorded
below as an evaluation blocker.

The parity test is relabelled: it proves the classification **logic** matches
`apex.intraday.sessions.classify` given identical tables (54,000+ points), and
proves nothing about the tables themselves.

## 4. C — run source provenance

- `verify_imports_against_commit` hashes **every loaded `apex.*` module** and
  compares it with the blob at the admitted commit. Modules outside the
  checkout, untracked at that commit, or byte-different are refused
  (`IMPORT_PROVENANCE_REFUSED`) **before a run directory is created**; modules
  inside the checkout but outside `RELEVANT_SOURCE_PATHS` are listed as
  `unbound_dependencies` — the execution dependencies the decision does not
  cover, named rather than hidden.
- `recheck_source_identity` recomputes commit, tree hash and cleanliness at
  **completion**. On any change the raw record is still sealed, and carries
  `acceptance_qualification: INVALID_SOURCE_CHANGED_DURING_RUN` plus an
  explicit `invalidated` sentence; the process outcome becomes a failure
  (exit 5). Tested by mutating the checkout *during* a disposable run.
- `_RUN.json` now carries the trust chain, the resolved verifier path and the
  import verification.
- "Controlled checkout" is enforced negatively (`SHARED_CHECKOUT`) and by
  content equality before and after; the operator package adds the dedicated
  research-owned checkout. Immutability *during* the run is not claimed —
  it is detected, not prevented, and that distinction is stated.

## 5. Tests

Focused, contained (`MemoryMax=1400M`, as `apex`): **114 passed** —
`test_exchange_calendar` 34, `test_exp001b_temporal` 12,
`test_real_data_boundary` 43, and `test_exp001_engineering` 13 +
`test_exp001_economic_path` 12 unchanged. (Counts are collected test ids;
parametrised cases expand.)

Applicable bounded regression on the final code `6be2507f` (every module
touching `world_model`, `chain_ledger` or `exp001`; one contained shard each):

```text
24 modules, 24 rc=0, 740 passed, 0 failed, 0 errors; 23:36:41Z -> 23:45:08Z; MemoryMax=1400M per shard, User=apex, 0 kills
test_bounded_regression 12 | test_exchange_calendar 34 | test_exp001_economic_path 12 | test_exp001_engineering 13
test_exp001b_temporal 12 | test_ledger_concurrency 4 | test_live_book 17 | test_real_data_boundary 43
test_result_audit 37 | test_result_validator 164 | test_verification_law 12 | test_world_model_authority 24
test_world_model_bootstrap 24 | test_world_model_contracts 86 | test_world_model_court 30 | test_world_model_inference 17
test_world_model_r3 13 | test_world_model_r4 8 | test_world_model_r5 13 | test_world_model_r51 9
test_world_model_r7 11 | test_world_model_r71_qualification 13 | test_world_model_teststand 43 | test_world_model_worlds 89
```

Scope unchanged from the previous pass: modules selected by grep for
`world_model`, `chain_ledger` or `exp001` under `tests/`; not the WM line's
full 4,213-nodeid regression. The sealed World Model surface hash and the
frozen contracts are re-pinned by `test_result_audit`, `test_result_validator`,
`test_world_model_r7` and `test_world_model_r71_qualification` in this run.

Three test defects of my own were found and fixed during this pass, one of
them the **third** instance in this programme of a guard matching its own
text: the `certified_1R` check matched my own explanatory comment, and then
matched the registration's prose inside the record. It is now an AST check
plus a recursive **key** walk. Also fixed: a `.strip()` in a test helper that
ate the leading space of the first `git status --porcelain` line and mangled
exactly one path, and a fixture directory created without `parents=True`.

## 6. Preservation

| Item | Result |
|---|---|
| ALPHA-EXP-001 registration, `registration.py`, `results/exp001_registration.json` | unchanged (hash-pinned in two suites) |
| ALPHA-EXP-001B registration `b3930727…` | unchanged — no table error found |
| Laboratory boundary `sources.py` / `authority.py` | unchanged (pinned) |
| Production release `/opt/apex/current` → `73fc712d` | unchanged |
| Maintenance holds ×3; options-paper inactive, `ConditionResult=no` | intact |
| RTH observer pid 1714883 | alive, window untouched |
| Sealed WM courts / `world-model-shadow-v0` `d01e961b` | untouched |
| Admission key / decision / real run | none created, none issued, none performed |

## 7. Recorded blockers for the separate evaluation gate

1. **N0 is computed but not enforced on evaluation.** `run()` enforces
   `n0_is_no_signal` on validation and returns `INVALID_INPUT` if the null
   fires, but the evaluation branch computes `n0` and proceeds to economics
   without the same guard. Recorded, deliberately **not** changed here: it
   alters the evaluation gate's behaviour, which this closure is not
   authorized to open. (The `certified_1R` field was fixed rather than
   deferred, because it was a false label contradicting its own registration,
   not a behavioural change.)
2. **Calendar verification stops at 2021.** Evaluation (2022–2024) and reserve
   (2025+) are now refused with `CALENDAR_NOT_VERIFIED`. Opening evaluation
   requires extending the reconciliation to those years first.
3. Economic-stage assumptions (spread model, no queue position or latency)
   remain labelled and unsupported; the fundable expression class is still
   NOT_IMPLEMENTED.

## 8. One exact next authorization request

Perform `docs/ADMISSION_OPERATOR_PACKAGE.md` items 1–6 (none executed by
engineering), then issue the signed decision from
`docs/admissions/EXP001B_ADMISSION_DECISION_PROPOSED.json` with
`code.commit` = the reviewed HEAD and `code.source_tree_sha256` =
`24322971…`, and authorize exactly:

```text
PYTHONPATH=<dedicated checkout> /opt/apex/shared/venv/bin/python scripts/alpha_exp_real_execute.py --decision /etc/apex/admissions/<decision>.json --execute
```

Train + validation only; distributional only; evaluation sealed. Expected
outcomes: `SCIENTIFIC_COMPLETE / NO_SIGNAL` (exit 0) or `EVALUATION_SEALED`
(exit 4). Nothing else is requested.
