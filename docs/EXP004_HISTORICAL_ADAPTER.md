# EXP-004 historical adapter — for independent review

**No historical data was accessed, no admission exists, nothing was executed.**
No registration, model, or inference change: registration hash remains
`9155024f51825d13487cdc035432d85b357d22e39a40f967477873a7a6145bf9`.

## What the adapter is

`apex/world_model/exp004/historical.py`. It is called by
`scripts/alpha_exp_real_execute.py --experiment ALPHA-EXP-004` under a verified
signed admission, exactly as EXP-002's adapter is. It never decides admission:
the route that admitted the files supplies the session loader.

Its single execution statement is:

```python
result = tournament(fit, dev)        # the ONLY invocation; no parameters exist to pass
```

`run.tournament` takes no inference parameters, so an admitted run can only use
the registered `B = 10,000`, seed `20260909`, and every record it produces
carries `run_mode = "HISTORICAL"`.

## The carried-forward requirement, discharged

| Requirement | Evidence |
|---|---|
| Imports and invokes **only** `run.tournament` | `test_adapter_imports_only_run_tournament_statically`: the module's AST shows `from .run import HISTORICAL, tournament`, a `tournament(...)` call, and no call or import whose name contains `synthetic` |
| **No direct route** to `exp004.synthetic` | same test; the module still *names* the forbidden module in its contract (`FORBIDDEN_MODULE`) but never imports it |
| **No transitive route** | `test_no_transitive_route_to_synthetic_from_the_adapter_chain`: every module in the chain (`historical, run, features, models, dispersion, inference, bootstrap_adapter, registration`) is AST-checked, and a **fresh child interpreter** importing the whole chain reports `apex.world_model.exp004.synthetic` **ABSENT** from `sys.modules`. The dependency is one-directional: `synthetic` imports `run`, not the reverse |
| The governed dispatch binds the adapter, not the synthetic path | `test_execute_script_binds_exp004_to_the_adapter_only`: the execute script imports `historical as H4`, calls `H4.run(...)`, and imports nothing named `synthetic` |
| **Runtime** proof | `test_adapter_run_never_reaches_synthetic_and_records_historical`: tripwires on `synthetic_tournament` and `synthetic_score` record **0 calls**; a spy on `run._core` records exactly `["HISTORICAL"]`; a spy on the adapter's `tournament` records **one** call with **no keyword arguments** |
| Records show `run_mode="HISTORICAL"`, `historical_path_valid=true` | asserted on the adapter record and the inner result, together with `(resamples, seed) == (10000, 20260909)` and the absence of `NOT_FOR_HISTORICAL_USE` |

## Fail-closed behaviour added by the adapter

| Case | Result |
|---|---|
| A sealed period is offered (`evaluation`, `reserve`) | `INTEGRITY_FAILURE: SEALED_PERIODS_OFFERED`, no `result` block |
| A required period has no sessions | `INTEGRITY_FAILURE: NO_SESSIONS_FOR_REQUIRED_PERIOD` |
| Any extra keyword argument (e.g. `bootstrap_resamples=50`) | `INTEGRITY_FAILURE: UNEXPECTED_ARGUMENTS` — an inference parameter cannot be smuggled through the adapter's own signature |
| The loader fails on any file | `INTEGRITY_FAILURE` at stage `load`, with the loader's named reason |
| A result arrives that is **not** historical | `INTEGRITY_FAILURE: NON_HISTORICAL_RESULT` — the adapter refuses to seal a `SYNTHETIC_TEST` record as a historical one, even if one somehow reached it |

`STATUS` maps `SELECTED`/`NOT_SELECTED` → `SCIENTIFIC_COMPLETE` and
`INTEGRITY_FAILURE` → `INVALID_INPUT_OR_FAILURE`, so an integrity failure can
never be counted as a completed run by the launcher.

## Scope kept, and what was deliberately NOT done

- **Not done:** any admission request, any signing, any historical read, any execution.
- **Not done:** `scripts/research_activation.py` still lists only `ALPHA-EXP-001B` and `ALPHA-EXP-002` in its `--experiment` choices, so EXP-004 **cannot be launched** even with a signed decision. That change belongs to the admission brick, together with `registration_hash_for`.
- **Consequence to note:** wiring the dispatch changed `scripts/alpha_exp_real_execute.py`, which is a bound source path. The bound tree hash therefore moves from the value recorded in the EXP-002 signing package. This does not alter EXP-002's sealed record (its `source_identity_at_completion` was verified at execution time and is preserved); it does mean the installed EXP-002 admission no longer matches the current tree, which is correct — that admission is spent.

## One risk to measure in the admission brick, not silently fixed here

`run.tournament(fit_sessions, dev_sessions)` takes **full session objects** and
holds both lists for the duration of the run. At registered scale that is ~754
fit sessions and ~757 development sessions of ~390 bars each. EXP-002's adapter
avoided this by converting each session to rows and discarding it. Peak memory
under the 1400 M cap is therefore **not established** for EXP-004 and must be
measured before any historical execution — the same failure that OOM-killed
EXP-001B's first attempt. Changing the memory shape would be a model/inference
path change, which this brick is not permitted to make, so it is recorded here
as a precondition rather than repaired.

## Preservation

All prior results and source commitments are unchanged: EXP-001B `NO_SIGNAL`,
EXP-002 `INVALID_NULL_CONTROL`, EXP-003 withdrawn, the EXP-004 registration
hash, and every sealed record and signed decision on file.
