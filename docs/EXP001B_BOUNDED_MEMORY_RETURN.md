# EXP001B — BOUNDED-MEMORY RECOVERY

Branch `exp001b-bounded-memory`. An engineering revision following an aborted
attempt. **Not a new hypothesis:** the registration is unchanged, and neither the
learning algorithm nor the statistical procedure moved.

Two corrections from review are accepted and carried into this document. Raising a
memory cap is not inherently illegitimate, and I overstated that; here, removing
unnecessary retention is simply the better first choice. And complete, parseable
partial records support artifact integrity only — they establish nothing about
forecast correctness or a completed experiment.

---

## 1. THE ABORTED RUN — PRESERVED AND CLASSIFIED

**`20260908T131351Z-exp001b-2054eaa4` is INCOMPLETE_DUE_TO_OOM. There is no
statistical verdict.** It sealed no `_RESULT.json`.

The directory is preserved byte for byte and set read-only, with hashes recorded in
`results/exp001b_aborted_run_classification.json`. The signed decision, its
signature and the allowed-signers file are unchanged and hashed alongside.

Its 165,958 partial forecasts are complete and the hash chain is intact. That is
**artifact integrity, and only that.** They were not graded, not tuned from, and
not appended to, and the run directory is closed. Any rerun gets a new one.

---

## 2. WRAPPER REPAIRED FIRST

The OOM-killed run exited 0. Two causes, both fixed before anything else.

The child went through `cmd()`, which raises on non-zero and keeps 300 characters
of stderr, so the explanation of the failure was discarded. That is why the first
`SCOPE_INVALID` refusal had to be recovered by re-running the command by hand.
There is now a `run_child` that never raises and keeps both streams whole.

The CLI returned `0 if rec.get("ok", True)`, and the launch record carried no `ok`
key, so the default decided it. Outcomes are now classified and carried to the exit
code:

| outcome | exit | evidence used |
|---|---|---|
| `COMPLETED_WITH_RESULT` | 0 | exit 0 **and** a sealed `_RESULT.json` |
| `COMPLETED_WITHOUT_RESULT` | 7 | exit 0, nothing sealed |
| `REFUSED` | 3 | child's own `process_outcome` |
| `OOM_KILLED` | 5 | systemd's kill text |
| `TIMED_OUT` | 6 | timeout expiry |
| `FAILED` | 4 | any other non-zero |
| `NOT_STARTED` | 8 | spawn failure |

**A missing result can no longer become success.** Seven tests drive the real CLI
with real child processes scripted to seal a result, seal nothing, refuse, raise,
hang, and emit systemd OOM text. One asserts no outcome but `COMPLETED` maps to 0.

---

## 3. MEASURED BEFORE REPAIRED

Synthetic sessions at the admitted scale, on real trading days from the exchange
calendar, inside the 1400M cap. No real market data, and the aborted run was never
inspected.

| structure | bytes per usable row |
|---|---|
| null gradings `g0n`,`g1n` | 3654 |
| real gradings `g0`,`g1` | 3635 |
| forecasts `f0`,`f1`,`sealed` | 3153 |
| input rows | 1560 |

**Instrument caveat, stated rather than buried:** RSS does not shrink when Python
frees objects, so the "sessions alone" delta measured zero. That is the instrument,
not evidence the retention was free.

Extrapolated to the admitted run: forecasts 525 MB, real gradings 606 MB, null
gradings 609 MB, validation rows 260 MB, train rows 518 MB — about **2.5 GB against
a 1400 MB cap.** The observed kill came during the forecast loop at a 1.3 GB peak,
which is where this projection crosses the cap.

---

## 4. THE SMALLEST REPAIR THAT PRESERVES THE COMPUTATION

Three retentions were **unnecessary**:

- One session reference was kept **per row**, pinning every session's bars for the
  whole run. Only the economics stage reads them, and only on evaluation.
- Train rows were held through validation although the fit had consumed them.
- Every sealed entry hash was retained in order to use two.

Two more were **restructured without changing arithmetic**:

- Forecasts are no longer retained. The null pass recomputes them, which is exact
  because `M.forecast` and `M.fit` contain no randomness and `creation_time` is
  fixed for the period, so the function is pure in the row.
- The real and null grading sets no longer coexist. `dm` is computed and the first
  set released before the second is built.

Preserved deliberately: row ordering, train-only fitting, each forecast still
computed before its own grading, the local `Random(seed)` permutation whose call
order is irrelevant, overlap handling, and grading semantics.

---

## 5. EQUIVALENCE PROVED, NOT ASSERTED

The pre-repair `run.py` is committed as a fixture and executed side by side with
the repaired one over identical deterministic fixtures, with time frozen so
`creation_time` cannot differ.

| comparison | result |
|---|---|
| sealed forecast ledger | **byte-identical** |
| outcomes ledger | **identical** |
| whole result record apart from `elapsed_s` | **identical** |
| `dm` and `n0`, compared value by value | **identical** |

**No numerical differences were found.** Nothing is compared by record count.

---

## 6. PROTECTED SURFACES

**Exactly one file drifted: `apex/world_model/exp001b/run.py`, which is the
repair.** The other 56 are unchanged.

A bound path moving is precisely the event that spends the previous admission. It
is recorded in `results/exp001b_protected_surfaces_after_repair.json` rather than
re-baselined away, and `results/si007_protected_before.json` is left as the
pre-repair record.

---

## 7. NEW ADMISSION REQUEST

`results/exp001b_admission_request_v2.json`, bound to the repaired source.

| | |
|---|---|
| commit | `22ea5104c682145cbb6d5c25a336df4605c5c685` |
| bound tree | `06eee315eb02c697fd3a0f1723c6e12c9d878d89f31832149abf783fef1e8345` |
| previous tree | `616a191252be80aef59880a0c9f925de5f010ee44a65550975604009a4bb7545` |
| registration | `b3930727…` unchanged |
| manifest | `3ac8b250…` unchanged |
| scope | SPY, 2016-01-04 to 2021-12-31, 1511 sessions, evaluation sealed |

It names the decision it supersedes and why: the bound tree moved, so the previous
signature cannot authorise this source. The vocabulary corrections from the first
refusal are carried forward, so `source_families`, `availability` and
`authority_classification` all come from the manifest and the boundary's own
accepted values.

**No rerun on historical data until this is reviewed and freshly admitted.**

---

## 8. WHAT THIS RETURN DOES NOT CLAIM

No statistical verdict exists. No experiment has completed. Nothing here says
anything about whether the registered model extracts predictive information from
real data, and the partial forecasts from the aborted run say nothing about it
either.
