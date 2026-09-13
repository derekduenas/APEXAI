# Regression reconciliation — per test ID, under matching conditions (2026-09-13)

The first report gave "30 failures" in a full run and then a 14-vs-16 subset comparison. That does not account for
all 30, and **a matching failure count is not equivalence**. This is the reconciliation that was asked for.

## Method

| | |
|---|---|
| baseline | `4682e4f7a29d09f74699dbc8815cdcdb465e529d` (the commit already accessible for review) |
| candidate | `35af566087537ccc1c203ed049a522019cc4c224` (the final committed candidate) |
| checkouts | two separate `git worktree` checkouts, neither the working tree |
| command | identical: `pytest tests/ -q -p no:randomly --continue-on-collection-errors --junitxml=…` |
| ordering | identical and deterministic (`-p no:randomly`) |
| execution | **sequential**, same host, so neither run competed with the other for CPU |
| comparison | per test ID from the JUnit XML of each run, not by count |

`--continue-on-collection-errors` is why the collection failure of `tests/test_validation_observer.py` is now
*recorded in both runs* instead of aborting the session, which is what allows every failure to be accounted for.

## Result

```
baseline  4682e4f : 5687 tests, 15 failing   (14 failed + 1 collection error, 5646 passed, 26 skipped, 45:17)
candidate 35af566 : 5827 tests, 15 failing   (14 failed + 1 collection error, 5786 passed, 26 skipped, 41:37)

FAILING IN BOTH (pre-existing, identical test IDs) : 15
NEW FAILURES INTRODUCED BY THE CANDIDATE           : 0
FIXED BY THE CANDIDATE                             : 0
tests ADDED by the candidate                       : 140  (failing: 0)
every candidate failure accounted for              : True
```

The two failing sets are **the same fifteen test IDs**, not two sets of the same size.

## Where the earlier "30" came from

That run was executed **in the dirty working tree**, not an isolated checkout, and under different ordering. The
extra failures were the `exp002` / `exp004` historical-path cascade, which is order-sensitive: those tests share
state and fail in a bulk full-suite ordering that the deterministic ordering used here does not produce. They
appear in **neither** run above. The earlier number was an artifact of how it was run, and reporting it as though
it characterised the candidate was wrong.

## The fifteen, by cause

None is a code defect introduced by this branch; all fifteen fail identically at the baseline.

**Host-environment: droplet paths absent on this Mac (9)**
- `test_pulse_anchor_freshness::test_NKLA_inputs_recomposed_refuse_the_anchor_and_everything_built_on_it` — `/opt/apex-repo/results/pulse007_frozen_packets.jsonl`
- `test_pulse_anchor_freshness::test_NKLA_sealed_packet_still_shows_the_original_anchor_defect` — same
- `test_pulse_derived::test_NKLA_frozen_packet_still_shows_the_original_defect` — same
- `test_research_board::test_audit_script_passes` — `/opt/apex/shared/venv/bin/python`
- `test_research_board::test_reconciliation_root_is_deterministic_and_order_independent` — `/apex-data/core/edgeforge/research_board.jsonl`
- `test_research_board::test_reconciliation_root_changes_if_a_legacy_board_changes` — same
- `test_research_board::test_swapping_two_legacy_boards_changes_the_root` — same
- `test_whole_ledger_guard::test_checkpoint_module_declares_the_law` — `/opt/apex-repo/apex/pulse/checkpoint.py`
- `test_whole_ledger_guard::test_pulse_v1_minute_path_reads_no_ledger` — `/opt/apex-repo/apex/pulse/runtime_v1.py`

**Host-environment: Linux-only procfs, absent on macOS (2)**
- `test_null_rig_memory::test_memory_does_not_grow_linearly_with_completed_sweep_seeds` — `/proc/self/status`
- `test_world_model_bootstrap::test_running_inside_research_containment` — `/proc/self/cgroup`

**Host-environment: macOS `/tmp` semantics (1)**
- `test_real_data_boundary::test_a_sticky_world_writable_ancestor_is_accepted` — expects a sticky world-writable
  component on the path chain; macOS `/tmp` is a symlink to `/private/tmp`.

**Collection error (1)**
- `tests/test_validation_observer.py` — `mkdir /apex-data` on a read-only root.

**Genuine content assertions, pre-existing and unchanged (2)**
- `test_architecture_claims::test_no_execution_or_broker_dependency_exists` — `'alpaca' present: execution has
  entered research`. A real finding about the repository, present at the baseline, untouched by this branch.
- `test_whole_ledger_guard::test_every_registered_offender_still_exists` — registered offenders
  (`apex/pulse/premarket.py`, `apex/pulse/rolling.py`, …) no longer present and should be removed from
  `KNOWN_UNREPAIRED`. Housekeeping in the guard's own registry, present at the baseline.

**Eleven of the fifteen would be expected to pass on the droplet**, where those paths exist. They have not been
run there, and that is not claimed.

## Artifacts

- `reconciliation.json` — the machine-readable per-test-ID comparison
- `regression_baseline_4682e4f.xml` / `regression_candidate_35af566.xml` — the raw JUnit XML of both runs
