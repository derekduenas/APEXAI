# STRATEGIC-INTEGRATION-002 — return for independent review

```text
STRATEGIC_ARCHITECTURE: DOCUMENTED (APEX_CANONICAL_ARCHITECTURE_V2, IMPLEMENTATION_ROADMAP_V2,
                        CHALLENGER_REGISTER_V0, FIRST_ECONOMIC_PROGRAM); no runtime activation
REAL_DATA_BOUNDARY:     IMPLEMENTED and TESTED on disposable fixtures (26 negative-control tests);
                        refusals demonstrated on the real proposal; no real row read
DATASET_ELIGIBILITY:    ASSESSED for history-b/etf_continuous SPY, fields OHLCV+event_time,
                        2016-01-04..2021-12-31 (train+validation only), RESTRICTED_USE named
                        (no publication/revision record; bulk receipt 2026-08-29); evaluation
                        2022-2024 and reserve 2025+ NOT in the proposal
REAL_DATA_ADMISSION:    NOT_AUTHORIZED (proposal is unbound and marked PROPOSED; no admission key exists)
EXP_001_REAL_EXECUTION: NOT_PERFORMED (command exists; --plan refused NO_DECISION / DECISION_NOT_ADMIT)
RTH_COMMISSIONING:      PENDING — observer pid 1714883 alive (elapsed 4h05m at 22:00Z), fires
                        2026-09-08T13:15Z; /apex-data/tmp/m1_rth/ not yet created; not replaced,
                        not duplicated, window untouched
PAPER_TRADING:          options-paper HELD (MAINTENANCE_BLOCK_options_paper, ConditionResult=no);
                        equity-fabric HELD; btc-resolver HELD; no new launch
REAL_MONEY_EXECUTION:   NOT_AUTHORIZED
REAL_MARKET_EDGE:       NOT_ESTABLISHED
```

## 1. Current-state reconciliation (independently re-derived on the host)

Heads at start of milestone: `milestone1-r2` = `eca00a9e5`, `alpha-exp-001`
= `dc321587e`, deployed release `/opt/apex/current` →
`73fc712d355032e0a66b41675ba114491b04799d`, `world-model-shadow-v0` =
`d01e961b6`. These were the latest heads; nothing had moved.

Precise scope of the prior report's "no production change": the trading
release `73fc712d` and all systemd units were unchanged; the **dashboard
process** (a loopback stdlib server, not a systemd unit, not part of the
release) was patched in the `milestone1-r2` checkout and restarted (old pid
1720323 stopped, new pid 1734061). Those are different facts and are kept
separate here.

Seven categories, recorded separately:

| Category | Content |
|---|---|
| 1 Repository implementation | chain R1–R4 (orchestrator, chain ledger); EXP-001 registration, bars, models, run, economic path; dashboard v0; **this milestone:** real-data boundary, manifest, loader, execute command, five canonical documents, proposal |
| 2 Tested implementation | 52 orchestrator/chain tests; 13 EXP-001 engineering; 12 economic path; **26 boundary**; applicable gate: see §5 |
| 3 Deployed implementation | release `73fc712d` (orchestrator R1–R4) only |
| 4 Commissioned behavior | orchestrator quiet-period (30 samples, peak 13.5 MiB, bounded records, 166 deferrals in 1,777 bytes); **RTH: PENDING** |
| 5 Historical predictive evidence | **NONE** on real data (synthetic acceptance court closed; EXP-001 engineering fixtures only) |
| 6 Prospective predictive evidence | **NONE** |
| 7 Economic evidence | **NONE** (engineering-mode economic path only; Risk refuses stock-with-stop; option path NOT_IMPLEMENTED) |

A dashboard card, a module's existence, or a passing engineering suite
promoted nothing across these rows.

## 2. Exact base and final commits

- Base: `alpha-exp-001` @ `dc321587ed673dd027460344f9182531c152ff95`
- Branch: `strategic-integration-002`, worktree `/apex-data/tmp/si002_wt`
- Final: `566600dca8632cd5e3831ef20304c29ae725bb0a (code + canonical docs); this return document lands in the following docs-only commit`
- Production, holds, observers, sealed courts, EXP-001 registration: untouched.

## 3. Changed-file inventory

| File | Change |
|---|---|
| `apex/world_model/real_data/__init__.py` | new — route declaration |
| `apex/world_model/real_data/boundary.py` | new — `verify_decision`, `open_file`, `open_output`, `binding_for` |
| `apex/world_model/real_data/manifest.py` | new — content commitment builder |
| `apex/world_model/real_data/loader.py` | new — EXP-001 row shape on this route; field restriction; `known_from` |
| `apex/world_model/exp001/bars.py` | `session_from_doc` factored out; `load_session` behaviour identical |
| `apex/world_model/exp001/run.py` | `session_loader=None` kwarg (default = laboratory route); `RealDataRefused` → BLOCKED; `route` recorded |
| `scripts/exp001_real_execute.py` | new — `--plan` / `--execute`; refuses without decision; evaluation always sealed |
| `tests/test_real_data_boundary.py` | new — 26 tests |
| `docs/APEX_CANONICAL_ARCHITECTURE_V2.md` | new |
| `docs/IMPLEMENTATION_ROADMAP_V2.md` | new |
| `docs/CHALLENGER_REGISTER_V0.md` | new |
| `docs/FIRST_ECONOMIC_PROGRAM.md` | new (EXP-002 PROPOSAL, not registered) |
| `docs/REAL_DATA_BOUNDARY_V0.md` | new |
| `docs/admissions/EXP001_ADMISSION_DECISION_PROPOSED.json` | new — unbound proposal |
| `docs/STRATEGIC_INTEGRATION_002_RETURN.md` | this document |

Host artifacts outside the repository (data, not configuration):
`/apex-data/governance/admissions/manifests/etf_continuous_SPY_manifest_v0.json`
(sha256 `3ac8b250eefb47c5f66c7217508e1080f5f86ae5e4a63c20062a4e931a424c39`,
2,679 files, bytes hashed only) and a copy of the proposal under
`/apex-data/governance/admissions/`. No key was created; `/apex-data/research`
does not exist.

## 4. Architecture / authority reconciliation

See `APEX_CANONICAL_ARCHITECTURE_V2.md` §1–§5. Nothing rearranged: Risk
keeps its veto, Book stays the single funding site, execution stays sealed,
organs propose and PRIME selects. Expanded capabilities are placed with
interfaces and prohibited authorities; each has an evidence gate; none is
activated. The laboratory boundary is not superseded — a second route is
added beside it.

## 5. Boundary implementation and evidence

Specification, field-by-field checks, and the mapping from every mandate
test requirement to a named refusal: `REAL_DATA_BOUNDARY_V0.md`.

Focused run (worktree, contained, `MemoryMax=1400M`): 51 passed — 26
boundary + 13 EXP-001 engineering + 12 economic path.

Applicable regression gate — every test module touching `world_model`,
`chain_ledger` or `exp001` (22 modules), one contained shard each, on the
working tree whose code/test files hash to
`/apex-data/tmp/si002_gate/tested_tree.sha256` (identical to the committed
blobs, checked in §7):

```text
22 modules, 22 rc=0, 677 passed, 0 failed, 0 errors; 22:09:54Z -> 22:17:48Z; MemoryMax=1400M per shard, 0 kills
test_bounded_regression 12 | test_exp001_economic_path 12 | test_exp001_engineering 13 | test_ledger_concurrency 4
test_live_book 17 | test_real_data_boundary 26 | test_result_audit 37 | test_result_validator 164
test_verification_law 12 | test_world_model_authority 24 | test_world_model_bootstrap 24 | test_world_model_contracts 86
test_world_model_court 30 | test_world_model_inference 17 | test_world_model_r3 13 | test_world_model_r4 8
test_world_model_r5 13 | test_world_model_r51 9 | test_world_model_r7 11 | test_world_model_r71_qualification 13
test_world_model_teststand 43 | test_world_model_worlds 89
```

Scope of the gate: modules selected by grep for `world_model`, `chain_ledger`
or `exp001` in `tests/`; it is not the WM line's full 4,213-nodeid regression,
which this change does not touch (the WM branch is unmodified).

Honest limitations of the tests: fixtures are synthetic 390-bar sessions;
the end-to-end run proves the route reaches `fit` and `validation` and
keeps `evaluation` sealed — it proves nothing about real data; the
subprocess provenance test covers one child; BINDING_SPOOF_RESISTANCE is
PARTIAL (key readable by the service account).

## 6. Preservation checks

| Item | Check | Result |
|---|---|---|
| EXP-001 registration | `registration_hash()` = `1a3f55a5…`; `registration.py` sha `11afb342…`; `results/exp001_registration.json` sha `96ea6edc…` | unchanged (pinned in tests) |
| Laboratory boundary | `sources.py` sha `25131307…`, `authority.py` sha `b33091a2…` | unchanged (pinned in tests) |
| Production release | `/opt/apex/current` → `73fc712d…` | unchanged |
| Maintenance holds | three markers present; options-paper `ConditionResult=no`, inactive | intact |
| RTH observer | pid 1714883 alive; window unchanged | intact |
| Sealed courts | WM line `d01e961b6` untouched | intact |
| Orchestrator | active/running, success, NRestarts 4017 (static) | unchanged |

## 7. Field-specific admission recommendation (submitted assessment, not a decision)

Dataset `history-b/etf_continuous`, symbol SPY, fields `event_time_utc,
open, high, low, close, volume`, 2016-01-04..2021-12-31:

- **Recommend ADMIT with restrictions** for EXP-001 train+validation:
  RESTRICTED_USE named (no publication/revision record; bulk receipt
  2026-08-29; `known_from` = bar close); corporate actions raw/explicit.
- **Not recommended in this decision:** evaluation 2022–2024 (separate
  unsealing decision), reserve 2025+, any other symbol, any other field.
- **Unresolved limitations:** vendor revision history absent; two missing
  XLRE sessions are irrelevant to SPY; the EXP-001 hypothesis is weak by
  design and its power figures are illustrative.
- If any field fails review, narrow the field list; do not block the
  corpus.

## 8. One exact next execution authorization request

> Issue the admission decision for `docs/admissions/EXP001_ADMISSION_DECISION_PROPOSED.json`:
> set `decision: ADMIT`, fill `code.commit` with `566600dca8632cd5e3831ef20304c29ae725bb0a (code + canonical docs); this return document lands in the following docs-only commit`, fill provenance,
> place it under `/apex-data/governance/admissions/`, create
> `/home/apex/.apex-secrets/WM_ADMISSION_KEY` (≥ 16 bytes, mode 600) and add the
> binding computed by `boundary.binding_for(body, key)`. Then authorize exactly:
> `PYTHONPATH=/apex-data/tmp/si002_wt /opt/apex/shared/venv/bin/python scripts/exp001_real_execute.py --decision <path> --execute`
> — train + validation only; evaluation stays sealed; output under
> `/apex-data/research/exp001` stamped RESEARCH_HISTORICAL.

Nothing else is requested. Engineering will not perform any of the six
issuance steps.

## 9. Dependency-ordered route to the first prospective paper economic test

`IMPLEMENTATION_ROADMAP_V2.md` §2. Critical path: admission key → ETF
decision → EXP-001 real train/validation → event-calendar acquisition and
admission → EXP-002 registration → implied estimator → option expression
with Risk certification → prospective paper selection → adversarial
commissioning. Engineering durations are days-to-weeks per step; the
evidence needed at steps 3, 6 and 7 is counted in observations and
carries no calendar promise.
