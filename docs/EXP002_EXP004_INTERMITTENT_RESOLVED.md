# EXP-002 / EXP-004 intermittent — CAUSE FOUND (2026-09-12)

Open across four blocks as "UNREPRODUCED / CAUSE_UNKNOWN". **Reproduced and explained today.** It is not test
isolation in the usual sense, not shared fixture state, and not environmental.

## The mechanism

`tests/test_real_data_boundary.py::test_a_changed_module_file_is_detected_as_mismatched` deliberately **mutates a
tracked source file in the working tree**:

```python
target = REPO / "apex/world_model/exp001b/models.py"
original = target.read_bytes()
try:
    target.write_bytes(original + b"\n# transient\n")     # the tree is DIRTY for the duration
    ...
finally:
    target.write_bytes(original)                          # restored
```

`tests/test_exp002_historical_path.py` and `tests/test_exp004_activation_path.py` both call `_require_clean()`,
which fails the test outright when `boundary.source_identity(REPO)["dirty"]` is non-empty:

```
Failed: ACCEPTANCE TEST REQUIRES A CLEAN BOUND TREE; commit first.
dirty=[' M apex/world_model/exp001b/models.py']
```

**If the two run at the same time in the same checkout, the second sees the first's transient edit and fails.** The
window is milliseconds wide, which is exactly why it looked random.

## Why every previous reproduction attempt failed

The three attempts in the decision-path block ran the EXP files **alone**, in a single process, in a quiet
checkout. Nothing was mutating the tree, so nothing failed. The failures always occurred inside a **full-suite run**
or while another pytest process was running in the same working tree — including today, where a full regression was
running in `~/apex-equities` at the same moment as the EXP hunt. Attempt 3 of 6 errored; the other five passed. Attempts 1 and 2 produced no summary line because the hunt's own
`head -12` truncation cut them, so the honest count is **1 confirmed error in 6 attempts run concurrently with a
full regression**, against 0 in 3 attempts run alone.

Within a single pytest process the two are sequential and cannot collide, which is why the full suite does not fail
every time either: it depends on whether anything else is touching the tree during those two files' execution.

## Classification

A **test-isolation defect with a real-world trigger**, not an environmental flake:

1. A test mutates a tracked file in the shared working tree rather than in a temporary copy.
2. Two other tests assert on the cleanliness of that same shared tree.
3. Any concurrency in the checkout — a second pytest process, an editor autosave, a watcher, a scheduled job in the
   same directory — turns (1) and (2) into an intermittent failure.

It is also a **live-operations hazard**, not only a test problem: the same guard runs in the EXP activation path, so
a real activation attempted while anything writes into the checkout would refuse for the same reason. That refusal
is correct behaviour; the defect is the test that manufactures the condition.

## Proposed repair (not applied here; this is a status block)

Smallest correct change: `test_a_changed_module_file_is_detected_as_mismatched` should copy the checkout, or use a
path outside the bound source set, instead of mutating a tracked file in place. A second, independent hardening:
`_require_clean()` should name the offending file **and** state that a concurrent writer is a possible cause, so the
next person does not spend four blocks on it.

## Standing rule established

**Do not run two pytest processes in the same checkout.** Every previous "environmental" label on this failure was
mine, and it was wrong: the cause was reachable the whole time by running the suite concurrently, which is what
finally reproduced it.
