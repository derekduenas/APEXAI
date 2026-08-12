# INCIDENT-001 — APEX-002 validation transaction failure

**Date:** 2026-08-12
**Classification (ruled by operator):** APEX-002 — INCONCLUSIVE / EXECUTION FAILURE.
Credit 2 consumed, no hypothesis result recorded.
**This is not a result about net share issuance.** No predictive conclusion
exists. The APEX-002 hypothesis remains UNTESTED.

---

## 1. What happened

`scripts/run_validation.py` was authorised and executed once against the frozen
snapshot. It crashed in the reporting layer after the credit was consumed and
after the statistics were computed, but before anything was persisted.

```
AttributeError: 'NSIOutput' object has no attribute 'features'
  scripts/run_validation.py:84   attribution = attribute(output, ...)
  apex/report/attribution.py:130 rescored = build_scores(output.features, ...)
```

## 2. Failure boundary — what was computed

Established by control flow, not by inspection. **No computed value was read,
printed, or examined**, and none appears in any artifact.

| # | Stage | Line | Ran? | Persisted? |
|---|---|---|---|---|
| 1 | smoke-run precondition | 55 | yes | n/a |
| 2 | `ProductionSource` panel build | 76 | yes | no |
| 3 | `require_signed`, `require_protocol_unmodified` | pipeline:128 | yes | n/a |
| 4 | `require_unlocked` → **`ledger.spend`** | registration:224 | **yes** | **YES — credit consumed** |
| 5 | `build_nsi_output` (signal + forward returns) | pipeline:145 | yes | no |
| 6 | `evaluate` → IC daily, IC non-overlapping, deciles | pipeline:155 | **yes** | no |
| 7 | `attribute` (§9) | 84 | **CRASHED** | no |
| 8 | `experiment_verdict` | 90 | never reached | no |
| 9 | `simulate_null_tstats` | 99 | never reached | no |
| 10 | **`ledger.record_result`** | 105 | **never reached** | **no result entry** |
| 11 | payload build, JSON write | 137 | never reached | no |
| 12 | stdout of values | 139 | never reached | no |

IC and decile figures existed in the memory of a process that has since exited.
They were never rendered. The crash occurred at stage 7; every stage that could
have exposed or stored a number is at stage 10 or later.

## 3. Confirmation that nothing was persisted

```
results/validation_APEX-002.json      ABSENT
results/002_validation.txt            683 bytes, traceback only
                                      0 lines matching ic|decile|t_stat|spread
ledger                                3 entries
  1. spend  APEX-001
  2. result APEX-001  INCONCLUSIVE  t=0.3019828992574129
  3. spend  APEX-002              ← no matching result entry
```

The ledger records the spend and no result. That asymmetry is the correct and
intended record of what occurred.

## 4. Root cause — the transaction was never adapted to #002

The crash is one symptom of a single root cause: **`run_validation.py` is
APEX-001's transaction end to end.** Execution certification covered
`build_nsi_signal`, `build_nsi_output` and `run_period`. It never exercised the
validation transaction past `run_period`, so everything downstream stayed
#001-shaped and unaudited.

Three defects, of which only the first fired:

**D1 — `attribute()` requires `PipelineOutput.features`** *(crashed)*
`apex/report/attribution.py:130` calls `build_scores(output.features, ...)`,
and line 31 imports `apex.features.composite.build_scores`. #002's `NSIOutput`
has no `features` field, by design: the experiment has one signal, not four
components. The §9 attribution layer also pulls #001's composite scorer into
the validation transaction, which the frozen specification forbids on the
scoring path.

**D2 — `source.exclusions()` does not exist on `ProductionSource`** *(latent)*
`run_validation.py:131` calls it while assembling the payload.
`ProductionSource` defines only `__init__`, `dataset_fingerprint` and `load`.
Had D1 been fixed in isolation, the run would have crashed here instead — after
the credit was spent again.

**D3 — #001's success criteria are hardcoded** *(latent, and the most serious)*
`run_validation.py:90`:

```python
min_mean_ic=0.015, min_t_stat=2.5, min_robustness_t=2.0
```

APEX-002 §13 registers something different:

| | applied by the script | APEX-002 §13 |
|---|---|---|
| mean IC | ≥ 0.015 | **positive** |
| t-statistic | ≥ 2.5 | **≥ one-sided α=1% critical value from the simulated null (≈2.92 validation)** |
| robustness | t ≥ 2.0 | **agrees in sign** |

Had D1 and D2 not existed, the run would have computed an APEX-002 verdict
against APEX-001's hurdles and written it to the ledger as the experiment's
recorded result. **The crash prevented a wrong verdict from being recorded.**
That is luck, not control.

## 5. Why the certification did not catch this

Step 3 certified fourteen items about the signal, the universe, the ranking and
the determinism of the panel — all against `build_nsi_signal`, all correct. The
dry run exercised `build_nsi_output`. Neither touched `attribute`,
`source.exclusions`, `experiment_verdict`'s arguments, or
`ledger.record_result`.

The audited boundary ended exactly where the defects began. A certification
that stops at signal production certifies signal production, and the report
should have said so rather than implying the validation path was proven.

## 6. Relationship to APEX-001

#001's validation crashed in the same layer — a `source.manifest`
`AttributeError` in `run_validation.py`, after its result was recorded — and
that was treated as a reporting nuisance rather than as evidence that the
transaction's tail was untested. It recurred here with a worse outcome. The
correct reading of both events is that the validation transaction, not the
signal, is the untrustworthy component.

## 7. State

```
#001       CLOSED — INCONCLUSIVE, trusted
#002       FROZEN + SIGNED + HASH-PINNED
           IMPLEMENTED · MEASUREMENT CERTIFIED
           EXECUTION COMPONENTS CERTIFIED
           VALIDATION TRANSACTION FAILED
Credit 2   SPENT — remains spent, no recovery attempted
Ledger     APEX-002 validation spend, no result
Verdict    NONE
Token      PRESENT — APEX-002
Holdout    SEALED
Hypothesis UNTESTED — no predictive conclusion
```

## 8. Remediation (2026-08-12)

All three defects fixed. `tests/test_validation_transaction.py`, 19 tests.

**D1** — `attribute()` no longer reads `output.features` and no longer imports
`build_scores`. Each output rescores itself: `PipelineOutput.rescore` calls
#001's composite, `NSIOutput.rescore` calls `build_nsi_scores`. The attribution
layer needs no branch and no import from either experiment. `NSIOutput` still
has no `features` field — the fix is that nothing depends on it, not that #002
grew an #001-shaped attribute.

**D2** — `ProductionSource.exclusions()` added, returning the `LoadReport` the
section 9 payload expects.

**D3** — success criteria moved out of the runner entirely, into
`config/experiment.yaml: success_criteria`, transcribed from §13:

```yaml
mean_ic:    {rule: positive}
t_stat:     {rule: at_least, by_period: {validation: 2.92, holdout: 2.88}}
robustness: {rule: same_sign}
```

`apex/evaluate/criteria.py` applies named rules and **knows no experiment
ids** — a test asserts the string `APEX-001` and `APEX-002` appear nowhere in
its executable code, because a per-experiment branch is the same defect with a
lookup table. `SuccessCriteria.from_config` raises rather than defaulting a
missing threshold. `interpret()` also carried a literal 2.5; it now takes the
registered value.

**A-001 preserved.** §13's threshold is null-derived, and A-001 bars the
simulated null from the decision path. The registered per-period constants
(2.92 / 2.88), which §13 states numerically, are used instead, so the decision
is a function of the frozen document alone. `SuccessCriteria.evaluate` takes no
reference argument — a test pins its signature. The simulated null is still
computed, after the decision, and the report now discloses the registered
threshold beside the null's 1% quantile at the actual observation count, so a
divergence is visible rather than absorbed.

**The required proof** — APEX-002 cannot pass on APEX-001's criteria:

| case | #001 | #002 | test |
|---|---|---|---|
| t = 2.60 | passes (≥2.5) | **FAILURE** (<2.92) | `..._cannot_pass_on_apex_001s_criteria` |
| mean IC = 0.005 | fails (<0.015) | SUCCESS (positive) | `..._mean_ic_rule_differs...` |
| robustness t = 0.4 | fails (<2.0) | SUCCESS (agrees in sign) | `..._robustness_uses_sign_agreement...` |
| robustness t = −2.5 | fails | **FAILURE** (opposes) | same |

Each counterexample also asserts the #001 comparison it inverts, so none is
inert. The rules are non-interchangeable in both directions.

---

## 9. Open governance question — RULED 2026-08-12

Does the protocol permit a **replacement execution** of the same registered
experiment after an execution failure, without treating it as a new hypothesis
and without silently refunding Credit 2?

The relevant facts, and nothing beyond them:

- no result was recorded, so the ledger's repeat-guard on `(experiment, period)`
  would not by itself block a second run;
- no statistic was observed by any human or written anywhere, so a replacement
  execution would not be a second look at a known answer;
- the frozen protocol and the hypothesis are unchanged and unexamined;
- the budget is a count of experiments, not of executions (CONVENTIONS A-003),
  which is what makes this genuinely ambiguous rather than obviously settled.

**RULING (operator, 2026-08-12):** a replacement execution is permitted under
the same Credit 2 allocation.

> An execution failure that occurs before a result is recorded does not
> constitute a second experimental observation.

Not a refund. The ledger continues to show the original spend.

```
APEX-002
Original credit:            Credit 2
Original execution:         FAILED — INCIDENT-001
Result recorded:            NO
Result observed:            NO
Replacement:                AUTHORIZED
Reason:                     remediation of execution failure
Hypothesis/protocol changed: NO
Additional credit:          NO
```

Conditions: same frozen protocol, same data snapshot, repaired transaction
only. No changed thresholds, dates, universe or methodology; no inspection of
the failed run's in-memory statistics; no alternative implementation chosen
because the first failed; no additional dry runs after seeing results.

The replacement token has NOT been created and nothing has been run.
