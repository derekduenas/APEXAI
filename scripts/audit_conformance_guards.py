"""Meta-test: does every load-bearing guard have DEMONSTRATED detection?

A guard that asserts "the violation is absent" proves nothing about its own
ability to notice the violation. It can read the wrong source, an empty or
wrapped function, a pattern that does not match the real construct, or code
outside the scanned scope -- and still pass, forever, silently.

CLASSIFICATION IS RULED, NOT INFERRED
-------------------------------------
An earlier version of this audit guessed which guards were load-bearing from a
name heuristic. It produced five false flags and one false reassurance. The
classification below was ruled by the operator on 2026-08-11 and is recorded
here verbatim. The test:

    Does the guard require a separate demonstration that its mechanism can
    detect failure, or does the assertion itself necessarily fail when the
    claimed property is false?

The first category needs a counterexample. The second does not, and inventing
mutation tests for it converts the meta-test into bureaucracy.

AUDIT PROVENANCE -- do not delete
---------------------------------
On first run, five guards had NO demonstrated counterexample. Three were then
classified ordinary by ruling; two were genuine gaps and were fixed:
  * test_the_loader_never_calls_last                     FAILED -> fixed
  * test_a_uniform_rebasing_factor_cancels               FAILED -> fixed
  * test_the_frozen_protocol_hash_is_intact              FAILED -> fixed
  * test_no_winsorisation_clipping_or_smoothing_anywhere FAILED -> fixed
  * test_the_nsi_module_cannot_reach_experiment_001      FAILED -> fixed
The two source scans initially had counterexamples that re-implemented the scan
locally rather than calling it. That proves the copy works, not the guard. Both
scans are now SINGLE definitions shared by guard and counterexample.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

CONFORMANCE = Path(__file__).resolve().parents[1] / "tests" / "test_nsi_conformance.py"

# Guard -> the counterexample(s) that demonstrate it can fail.
LOAD_BEARING = {
    "test_the_loader_never_calls_last": [
        "test_counterexample_last_would_select_the_restatement",
        "test_the_last_scan_is_not_vacuous",
    ],
    "test_a_uniform_rebasing_factor_cancels": [
        "test_counterexample_a_level_measure_breaks_under_rebasing",
    ],
    "test_the_frozen_protocol_hash_is_intact": [
        "test_counterexample_a_modified_protocol_is_detected",
    ],
    "test_no_winsorisation_clipping_or_smoothing_anywhere": [
        "test_counterexample_the_transformation_scan_detects_an_injected_clip",
        "test_counterexample_the_scan_detects_a_winsorisation_inside_a_real_function",
        "test_the_transformation_scan_ignores_prose_not_code",
    ],
    "test_the_nsi_module_cannot_reach_experiment_001": [
        "test_counterexample_the_isolation_scan_detects_an_injected_001_reference",
        "test_counterexample_the_isolation_scan_detects_a_composite_import",
    ],
    # Added for B1. The "100% PIT-compliant" figure is only evidence if the
    # measure is capable of reporting less than 100%.
    "test_pit_holds_on_every_populated_cell": [
        "test_counterexample_a_future_filing_is_not_used_before_it_exists",
        "test_counterexample_the_pit_measure_flags_a_deliberately_late_filing",
    ],
}

# Ordinary assertions: failure is intrinsic to the assertion. Ruled 2026-08-11.
ORDINARY = {
    "test_ranked_set_equals_eligible_and_nsi_present": (
        "invariant demonstrated by its two negative-case tests, which drive the "
        "same assert_cross_section_alignment and require it to RAISE"
    ),
    "test_splits_are_NOT_in_the_exclusion_set": (
        "set-membership compared against the frozen expected set; a wrong set "
        "fails the comparison directly"
    ),
    "test_ties_are_broken_deterministically": (
        "deterministic expected output; non-determinism fails the comparison"
    ),
    "test_the_knowability_date_is_the_later_of_the_two_filings": (
        "asserts one expected date against a hand-computed fixture; a wrong "
        "date fails the comparison directly"
    ),
}

# The negative cases that carry the alignment invariant. Their absence would
# hollow out the ORDINARY classification above, so they are required to exist.
REQUIRED_NEGATIVE_CASES = [
    "an_ineligible_security_that_got_ranked_is_caught",
    "a_silently_dropped_eligible_security_is_caught",
]


def main() -> int:
    source = CONFORMANCE.read_text()
    defined = {
        n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)
    }

    print("=" * 78)
    print("APEX-002 GUARD AUDIT -- demonstrated detection")
    print("=" * 78)

    failures: list[str] = []

    print("\nLOAD-BEARING (counterexample required)")
    for guard, examples in sorted(LOAD_BEARING.items()):
        if guard not in defined:
            failures.append(f"registered guard {guard} does not exist")
            print(f"  MISSING  {guard}")
            continue
        missing = [e for e in examples if e not in defined]
        if missing:
            failures.append(f"{guard} missing counterexample(s): {missing}")
        status = "UNPROVEN" if missing else "PROVEN  "
        print(f"  {status} {guard}")
        for e in examples:
            print(f"             {'--' if e in defined else 'ABSENT'} {e}")

    print("\nORDINARY (failure intrinsic to the assertion; ruled 2026-08-11)")
    for guard, why in sorted(ORDINARY.items()):
        if guard not in defined:
            failures.append(f"registered ordinary guard {guard} does not exist")
        print(f"  {'ORDINARY' if guard in defined else 'MISSING '} {guard}")
        print(f"             {why}")

    for name in REQUIRED_NEGATIVE_CASES:
        if not any(name in d for d in defined):
            failures.append(f"missing negative case {name}; ORDINARY ruling is hollow")

    # An orphan counterexample means a guard was renamed or deleted while its
    # proof stayed behind -- the audit would then silently cover nothing.
    claimed = {e for v in LOAD_BEARING.values() for e in v}
    orphans = sorted(
        d for d in defined if "counterexample" in d and d not in claimed
    )
    if orphans:
        failures.append(f"counterexamples not tied to any guard: {orphans}")

    print("\nRunning the conformance suite")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(CONFORMANCE), "-q"],
        capture_output=True,
        text=True,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1:]
    print("  " + (tail[0] if tail else "no output"))
    if proc.returncode != 0:
        failures.append("the conformance suite does not pass")

    print("\n" + "=" * 78)
    if failures:
        print("VERDICT: FAIL")
        for f in failures:
            print(f"  - {f}")
    else:
        print(f"VERDICT: PASS -- {len(LOAD_BEARING)} load-bearing guards with "
              f"demonstrated detection, {len(ORDINARY)} ordinary by ruling")
    print("=" * 78)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
