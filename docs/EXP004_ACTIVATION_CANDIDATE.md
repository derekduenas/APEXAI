# EXP-004 activation-wrapper candidate — for independent review

**Before setup, signing, or historical execution.** No admission exists, nothing
is signed by the real authority, no admitted historical data was touched. The
"admitted" files in every test below are synthetic bars in a temporary
directory, admitted under a **disposable** throwaway key.

## 1. Reconciled source commitment

| | |
|---|---|
| candidate commit | `f1452b47084329cf733295b6d468cafce049bdc1` |
| bound source tree | `8fbe6ed6155df0e4b8fb09f6dd8ce54c7e1cf064cea29592e08fa44a41996991`, 67 files, `dirty: []` |
| EXP-004 registration | `9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9` — **unchanged** |
| execute script (bound) | `73aca971ce8fd16658bcd0b0c1e7c13b877cbb2981a3f9e40be499a79300f2c0` |
| **launcher (NOT bound)** | `823b0125b58b86ba653f0dfedf3c495dfe05cc7df79e4671c8717e4a57776b9e` — **moved** from `4b9b187a…` |

The bound tree is unchanged by this brick because `scripts/research_activation.py`
is **not** a bound path: the launcher is pinned separately, by hash, and checked
before it is invoked from the fresh checkout. Its hash has moved and must be
re-checked at setup time against the value above.

## 2. What changed in the wrapper

Minimal and additive:

- `EXPERIMENTS` gains `"ALPHA-EXP-004"`.
- `registration_hash_for` is generalised: EXP-001B keeps its frozen constant, and every later experiment resolves its hash from a `REGISTRATION_MODULE` table by reading the registration module **inside the checkout being launched** — so the plan binds to the code that will run, not to whatever the launcher imported. An unknown experiment still raises `UNKNOWN_EXPERIMENT`; a missing module still raises `REGISTRATION_MISSING`.

Everything else already dispatched on the `experiment` argument
(`_run_dirs`, `_sealed_results_for`, `prepare_launch`, `operator_commands`,
`run_launch`, the CLI choices) and needed no change.

## 3. Evidence — 8 tests, `tests/test_exp004_activation_path.py`

**Wrapper support**

- `registration_hash_for("ALPHA-EXP-004", REPO)` equals the module's own `registration_hash()`, differs from EXP-002's, and refuses an unknown experiment or a missing checkout.
- `operator_commands` emits `--experiment ALPHA-EXP-004` on prepare and execute, and never names EXP-002.
- The CLI advertises `ALPHA-EXP-004` in `--help` and rejects `ALPHA-EXP-999` as an invalid choice.
- A sealed EXP-004 result is counted for EXP-004 and **not** for EXP-002.

**Dispatch and refusal, through the real governed path**

- `--plan` lists exactly `{fit: 112, development: 6}`, names neither sealed period, and opens no row (spy on `boundary.open_file` raises if it does).
- An EXP-002 admission cannot authorise EXP-004 → `EXPERIMENT_MISMATCH`; the reverse likewise; the right experiment with EXP-002's registration hash → `REGISTRATION_MISMATCH`.
- `UNSIGNED_DECISION`, `SIGNATURE_INVALID` (foreign key), `CODE_IDENTITY_MISMATCH`, `SOURCE_IDENTITY_MISMATCH` all refused with exit 3.

**Full governed execution on synthetic admitted files**

```
rc=0  process_outcome=SCIENTIFIC_COMPLETE  status=NOT_SELECTED  run_mode=HISTORICAL
```

with, from the sealed `_RESULT.json`: `adapter.entry_point =
apex.world_model.exp004.run.tournament`; a tripwire on
`synthetic.synthetic_tournament` recording **0 calls**; exactly the 118 admitted
session dates opened and **no date ≥ 2022-01-01**; `evaluation: "SEALED…"`;
`imports_at_start.all_imports_match_admitted_commit: true`;
`acceptance_qualification: VALID`; `source_identity_at_completion.unchanged:
true`; `inference_parameters` = registered `B = 10,000`, seed `20260909`,
`historical_path_valid: true`; and `seal_result` refusing a second write with
`RESULT_EXISTS`.

## 4. Memory qualification scope, carried into this package

The synthetic memory qualification (`docs/EXP004_MEMORY_QUALIFICATION.md`,
commit `2200c668`, artifact `results/exp004_memory_adapter_registeredB.json`)
measured **737.2 MiB peak against the 1,400 MiB cap**, 662.8 MiB headroom, zero
limit/OOM events sampled throughout, 12 min 4 s, at full registered scale and
registered inference. It must be cited with its scope attached:

- `synthetic_only: true`, `admission: null`, `governed_path_exercised: false` — sessions were generated on demand with `ledger_dir=None`, so the admitted loader, import-provenance verification and result sealing were **not** exercised in that measurement. (The governed path *is* exercised in §3, but at 118 sessions, not at registered scale.)
- Provenance coverage is narrower than "no module loaded outside the checkout": the script checks the resolved paths of **ten named modules**, and does not inventory every loaded module or hash each imported file individually. `dirty: []` covers the **declared bound paths**, which exclude the qualification script itself; the frozen-checkout record covers that gap, not the dirty check.
- `HISTORICAL` there identifies the **code path**, not an admission.
- Two values of `B` do not establish general flatness in `B`; only the measured points are claimed.

**Not yet measured:** the governed path at registered scale — admitted loader,
import provenance and sealing over 1,511 real sessions. That combination has
never been run for EXP-004 and its memory and runtime are not established.

## 5. Test results at this candidate

| Suite | Result |
|---|---|
| `test_exp004_activation_path.py` + `test_exp004_historical_adapter.py` + `test_exp004_implementation.py` | **45 passed** (170 s) |
| `test_research_activation.py`, `test_activation_verifier_review.py`, `test_real_data_boundary.py`, `test_exp002_{tournament,revision2,studentt,controls,historical_path}.py` | **204 passed** (580 s) |

The regression includes the activation-wrapper suite and the EXP-002 acceptance
suite, which re-verify launcher behaviour and source/import identity after the
launcher change.

## 6. Deliberately not done

No setup, no signing, no admission request, no historical execution, and no
change to the registration, model, or inference. `research_activation.py` now
*accepts* `--experiment ALPHA-EXP-004`, but no environment for it exists and no
decision naming EXP-004 has been signed or installed.
