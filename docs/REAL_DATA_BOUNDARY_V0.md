# WORLD_MODEL_REAL_DATA_BOUNDARY_V0 — specification and evidence

Status: **IMPLEMENTED and TESTED (engineering, disposable fixtures)**.
Not yet used on real rows. The laboratory boundary is unchanged by hash.

## Purpose

A separate, fail-closed route by which a research process may read REAL
historical data — only under an admission decision that the process did
not write. It keeps four decisions apart and lets none stand in for
another:

| Decision | Who / what | Where recorded |
|---|---|---|
| technically readable | the OS | — |
| assessed eligible for a use | eligibility document | `EXP001_ELIGIBILITY.md`, `EXP001_ADMISSION_PACKAGE.md` |
| **authorized** for that use | admission authority | bound decision under `/apex-data/governance/admissions/` |
| experiment passed | the experiment's sealed result | its output ledger |

## Modules (`apex/world_model/real_data/`)

- `boundary.py` — `verify_decision(...) -> Grant`, `open_file(grant, ...)`,
  `open_output(grant, name)`, `output_authority(path)`, `binding_for(body, key)`.
- `manifest.py` — `build(root, ...)`, `write(manifest, path)`: content
  commitment (sha256 per file; bytes hashed, nothing parsed).
- `loader.py` — `load_session`, `loader_for(grant)`, `sessions_by_period`:
  the EXP-001 row shape on this route; fields restricted at rebuild.
- `scripts/exp001_real_execute.py` — `--plan` / `--execute`; refuses
  without a valid decision; evaluation always sealed.
- `exp001/run.py` gains `session_loader=None` (default = laboratory route);
  `exp001/bars.py` factors `session_from_doc`. Registration untouched.

## The admission decision binds

| Required by mandate | Field(s) | Check |
|---|---|---|
| dataset identity and content commitment | `dataset.{dataset_id, root, manifest_path, manifest_sha256}` | manifest hash and id/root must match; each file's sha at read |
| permitted source families and fields | `scope.source_families`, `scope.fields` | file's declared family; fields rebuilt from the permitted set |
| temporal range and universe | `scope.temporal_range`, `scope.universe` | per-file session date and symbol, cross-checked with manifest |
| availability and revision semantics | `availability.{event,receipt,publication,revision}_time` | vocabulary enforced; contradictions refused; NOT_AVAILABLE requires `restricted_use` |
| corporate-action treatment | `availability.corporate_actions` | vocabulary enforced; must match manifest |
| research purpose and experiment | `purpose.{research_purpose, experiment_id, registration_hash}` | caller's experiment and registration must match |
| code / configuration identity | `code.commit` | must equal the importing checkout's HEAD |
| output location and authority | `output.{root, authority_classification}` | not in evidence/corpus/release/checkout roots; stamped `RESEARCH_HISTORICAL` |
| decision provenance | `provenance.{decided_by, decided_utc, review_reference}` | `decided_by` may not be caller/engineering/self |
| binding | `binding.{body_sha256, hmac_sha256}` | digest of the body; HMAC under `WM_ADMISSION_KEY` |

Location rules: the decision must be under the admission root, not inside
the code checkout, not inside the output root. No boolean, environment
variable or force flag exists.

Prohibited dataset roots (no decision opens them): `/apex-data/core`,
`/apex-data/runtime`, `/opt/apex-repo/results`, `/opt/apex/releases`, the
laboratory fixture root. Permitted historical roots: `/apex-data/history-a`,
`/apex-data/history-b`.

## Negative controls (tests/test_real_data_boundary.py, 26 tests)

| Mandate item | Test | Refusal named |
|---|---|---|
| no authorization | `test_no_decision_is_refused`, `test_unbound_or_proposed_decision_is_refused`, `test_missing_key_refuses_even_a_well_formed_decision` | NO_DECISION, UNBOUND_DECISION, DECISION_NOT_ADMIT, NO_ADMISSION_KEY |
| caller self-admission | `test_caller_cannot_admit_itself` | DECISION_INSIDE_CHECKOUT, DECISION_OUTSIDE_ADMISSION_ROOT, BINDING_MISMATCH, DECISION_PROVENANCE_INVALID |
| wrong dataset / experiment / field / temporal scope | `test_prohibited_and_unpermitted_dataset_roots_are_refused`, `test_wrong_experiment_or_registration_is_refused`, `test_field_temporal_and_universe_scope_are_enforced_at_read` | PROHIBITED_DATASET_ROOT, DATASET_ROOT_NOT_PERMITTED, EXPERIMENT_MISMATCH, REGISTRATION_MISMATCH, FIELD_NOT_PERMITTED, OUTSIDE_TEMPORAL_SCOPE, OUTSIDE_UNIVERSE, DATE_MISMATCH, UNCOMMITTED_FILE, OUTSIDE_DATASET_ROOT |
| changed payload after commitment | `test_changed_payload_after_commitment_is_refused`, `test_changed_manifest_or_body_after_binding_is_refused` | CONTENT_CHANGED, MANIFEST_HASH_MISMATCH, BODY_DIGEST_MISMATCH |
| invalid / contradictory availability | 6 parametrized cases + `test_missing_required_fields_are_named` | AVAILABILITY_INVALID (×6), MISSING_FIELD |
| code identity | `test_code_identity_mismatch_is_refused` | CODE_IDENTITY_MISMATCH |
| authorized fixture → permitted research | `test_authorized_fixture_permits_a_restricted_read`, `test_authorized_fixture_runs_exp001_end_to_end_without_the_lab` | rows carry `known_from`; non-admitted fields absent; run() reaches fit and validation; evaluation BLOCKED (sealed) |
| synthetic-lab exclusion intact | `test_synthetic_lab_real_data_exclusion_is_unchanged` | sources.py / authority.py hashes pinned; lab refuses history-b and refuses this route's dataset; run() default route refuses |
| outputs cannot acquire authority | `test_research_outputs_carry_no_broker_or_live_authority`, `test_route_modules_reach_no_execution_layer` | stamp NONE/FORBIDDEN; OUTPUT_ROOT_INVALID; AST: no apex.execution/organism/capital imports, no broker constants |
| child processes import intended checkout | `test_child_process_imports_the_intended_checkout`, `test_execute_command_refuses_without_a_decision` | module paths under the worktree; command exit 3 NO_DECISION |
| command plan opens no rows | `test_execute_command_plan_opens_no_rows_and_keeps_evaluation_sealed` | `open_file` never called; no output dir; EXPERIMENT_MISMATCH refused |
| registration and sealed evidence unchanged | `test_registration_and_sealed_evidence_unchanged` | registration_hash, registration.py, results/exp001_registration.json pinned |

No test reads a real corpus row. Real roots appear only as strings that
must be refused.

## Real-host demonstration (no rows read)

- `scripts/exp001_real_execute.py --plan` → `REFUSED: NO_DECISION`, exit 3.
- With the proposal inside the checkout → `DECISION_OUTSIDE_ADMISSION_ROOT`.
- With the proposal copied under the admission root (still `PROPOSED`, still
  unbound) → `DECISION_NOT_ADMIT`.
- `/apex-data/research` was not created; `WM_ADMISSION_KEY` does not exist.

## Honest limitations

- **BINDING_SPOOF_RESISTANCE = PARTIAL.** The key is a file readable by the
  service account; the route defends against an engineering caller
  admitting itself, not against an actor holding the key. Holding the key
  outside the research host would raise this to FULL.
- Content commitment is per file (sha256); a manifest of 2,679 files is
  committed by its own hash. Rows are not individually committed.
- `known_from = event_time + 60 s` is the bar-close convention; it is not a
  vendor publication timestamp, which the corpus does not carry. This is
  why the ETF proposal names a `restricted_use`.
- Code identity is the checkout's `git rev-parse HEAD`; uncommitted
  modifications are not detected by the boundary (the provenance harness
  covers that at run time).
