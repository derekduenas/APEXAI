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

_TESTS = Path(__file__).resolve().parents[1] / "tests"
CONFORMANCE = _TESTS / "test_nsi_conformance.py"

# Guards live in more than one file. Scanning only the conformance file is how
# a load-bearing governance guard could sit outside the audit entirely -- which
# is adjacent to the defect that produced the vacuous unlock check.
AUDITED_FILES = [
    CONFORMANCE,
    _TESTS / "test_governance_unlock.py",
    _TESTS / "test_screening.py",
    _TESTS / "test_feature_factory.py",
    _TESTS / "test_research_discovery.py",
    _TESTS / "test_architecture_firewalls.py",
    _TESTS / "test_research_engines.py",
    _TESTS / "test_component_registry.py",
    _TESTS / "test_portfolio_projection.py",
    _TESTS / "test_apex003_path.py",
]

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
    # Added at Step 3 re-certification. The corporate-action rate is only
    # meaningful if its denominator counts the same objects as its numerator.
    "test_the_exclusion_rate_is_pairs_over_pairs": [
        "test_counterexample_a_cell_denominator_moves_with_the_date_grid",
    ],
    # Added for B1. The "100% PIT-compliant" figure is only evidence if the
    # measure is capable of reporting less than 100%.
    "test_pit_holds_on_every_populated_cell": [
        "test_counterexample_a_future_filing_is_not_used_before_it_exists",
        "test_counterexample_the_pit_measure_flags_a_deliberately_late_filing",
    ],
    # Added 2026-08-12 after the dry-run certification reported "no validation
    # unlock token exists" while one sat at the true path. The check read
    # REPO/validation.unlock, which nothing writes, so it could not fail.
    "test_the_token_path_is_where_tokens_are_actually_written": [
        "test_counterexample_the_repo_root_path_is_the_one_that_never_exists",
    ],
    "test_the_status_reports_absent_when_no_token_exists": [
        "test_counterexample_the_status_reports_present_when_a_token_exists",
    ],
    "test_the_report_check_passes_when_no_token_exists": [
        "test_counterexample_the_report_check_FAILS_on_a_token_naming_this_experiment",
    ],
    "test_a_locked_period_without_a_token_is_refused": [
        "test_counterexample_a_stale_token_naming_another_experiment_is_refused",
    ],
    # APEX Screening Protocol v1.0, added 2026-08-12. A new governance surface
    # outside the audit is the blind spot the unlock check already
    # demonstrated, so the screen's guards are registered here from the start.
    "test_a_complete_dossier_is_accepted": [
        "test_counterexample_an_incomplete_dossier_cannot_be_screened",
    ],
    # S1 amendment 2026-08-12: the field list is transcribed from the protocol,
    # not invented by the implementation.
    "test_the_required_fields_are_transcribed_from_the_protocol": [
        "test_counterexample_the_transcription_check_would_notice_an_added_field",
    ],
    # S13: a screening outcome is an eligibility decision, never evidence.
    "test_the_evaluation_path_cannot_read_the_screen_log": [
        "test_counterexample_the_s13_isolation_check_detects_a_reachable_screen",
    ],
    "test_the_hash_is_content_addressed_not_order_dependent": [
        "test_counterexample_a_changed_dossier_gets_a_different_hash",
    ],
    "test_a_rejection_is_logged_as_permanently_as_a_survival": [
        "test_counterexample_an_unlogged_rejection_cannot_silently_disappear",
        "test_counterexample_editing_a_logged_reason_is_detected",
    ],
    "test_the_outcome_type_cannot_express_tuning_information": [
        "test_counterexample_a_score_is_not_a_verdict",
        "test_counterexample_a_screen_returning_optimisation_data_is_refused",
    ],
    "test_a_changed_dossier_after_rejection_is_a_new_event": [
        "test_counterexample_a_rejected_dossier_cannot_be_screened_again",
    ],
    "test_survive_grants_eligibility_only": [
        "test_counterexample_a_survivor_creates_no_experiment_and_spends_no_credit",
        "test_counterexample_an_unregistered_survivor_cannot_enter_validation",
    ],
    "test_re_screening_the_same_frozen_dossier_is_deterministic": [
        "test_counterexample_a_flip_flopping_screen_is_refused",
    ],
    "test_the_default_window_is_in_sample": [
        "test_counterexample_a_window_touching_the_holdout_is_refused",
        "test_counterexample_a_window_touching_validation_is_refused",
        "test_counterexample_a_window_merely_overlapping_the_holdout_is_refused",
        "test_counterexample_run_screen_refuses_a_locked_window",
    ],
    "test_a_screen_does_not_touch_the_protocol_or_criteria": [
        "test_counterexample_a_screen_cannot_mutate_the_dossier",
    ],
    "test_the_screening_module_never_writes_to_the_research_ledger": [
        "test_counterexample_the_ledger_isolation_scan_detects_an_injected_reference",
    ],
    "test_the_screen_log_chain_verifies_after_many_events": [
        "test_counterexample_extending_ledgerentry_would_break_the_live_chain",
    ],
    # Feature factory / registry, added 2026-08-12. Redundancy detection is a
    # control born from the f1_mom_63 / f4_vs_market identity, so its guards
    # join the audit from the start rather than becoming an unaudited surface.
    "test_the_registry_has_no_duplicate_ids": [
        "test_counterexample_two_features_with_the_same_formula_are_detected",
    ],
    "test_the_real_registry_contains_no_identical_formulas": [
        "test_counterexample_reciprocal_ratios_are_flagged_algebraic",
    ],
    "test_a_per_date_scalar_difference_is_identical_information": [
        "test_counterexample_correlated_features_are_not_called_identical",
    ],
    "test_positive_control_ratio_is_computed_exactly": [
        "test_counterexample_a_zero_denominator_is_excluded_not_infinite",
    ],
    "test_pit_a_future_filing_is_not_used_before_it_exists": [
        "test_counterexample_the_pit_validator_flags_a_late_knowability_date",
    ],
    "test_roe_roa_are_built_from_raw_not_the_empty_vendor_field": [
        "test_data_gaps_are_marked_not_faked",
    ],
    # --- Research discovery layer (2026-08-12) ------------------------------
    # A new governance surface must not sit outside the audit -- that is the
    # blind spot the unlock check already demonstrated.
    "test_the_screenable_content_is_a_certified_dossier": [
        "test_counterexample_an_incomplete_hypothesis_is_refused_by_the_shared_definition",
        "test_counterexample_a_hypothesis_with_no_features_is_refused",
    ],
    "test_provenance_is_not_part_of_the_scientific_identity": [
        "test_counterexample_changing_the_science_changes_the_hash",
    ],
    "test_a_before_002_hypothesis_needs_no_rejustification": [
        "test_counterexample_a_postmortem_hypothesis_is_flagged_as_descendant",
        "test_counterexample_an_explicit_descendant_is_flagged_even_if_epoch_is_clean",
        "test_counterexample_an_invalid_epoch_is_refused",
    ],
    "test_a_twin_state_is_deterministic": [
        "test_counterexample_a_twin_that_uses_a_future_filing_is_refused",
    ],
    "test_a_new_feature_set_is_novel": [
        "test_counterexample_the_same_feature_set_as_a_closed_experiment_is_a_modification",
        "test_counterexample_a_subset_of_a_closed_experiment_is_redundant",
        "test_counterexample_an_identical_prior_dossier_is_a_duplicate",
    ],
    "test_a_combination_requires_an_economic_reason": [
        "test_counterexample_a_combination_without_a_reason_is_refused",
        "test_counterexample_a_single_feature_is_not_a_combination",
    ],
    "test_disagreement_is_preserved_not_averaged": [
        "test_counterexample_a_dossier_without_the_adversary_is_refused",
        "test_counterexample_a_dossier_without_replication_is_refused",
    ],
    "test_a_survivor_reaches_a_review_packet_that_decides_nothing": [
        "test_counterexample_a_redundant_hypothesis_never_reaches_the_screen",
    ],
    "test_the_discovery_layer_cannot_reach_registration": [
        "test_counterexample_the_no_registration_check_can_detect_a_breach",
    ],
    # --- Architectural firewalls (2026-08-12) -------------------------------
    # Arms every planned layer's boundary before its engine exists, reusing the
    # audited module_closure walk. A new governance surface must be audited.
    "test_layer_closure_obeys_its_forbidden_set": [
        "test_counterexample_the_firewall_detects_a_forbidden_import",
    ],
    "test_every_contract_that_is_a_new_hypothesis_consumes_a_credit_or_is_free_discovery": [
        "test_counterexample_a_new_hypothesis_layer_with_no_governance_is_rejected",
    ],
    # --- Reusable research engines (2026-08-12) -----------------------------
    # stats/manifest/ml-accounting/causal/regime: each evaluates a declared
    # question and structurally cannot search or select.
    "test_positive_control_bootstrap_ci_excludes_zero": [
        "test_negative_control_bootstrap_ci_includes_zero",
        "test_counterexample_the_stats_engine_exposes_no_select_best",
        "test_counterexample_a_bad_block_size_is_refused",
    ],
    "test_positive_control_permutation_rejects_null": [
        "test_negative_control_permutation_does_not_reject",
    ],
    "test_manifest_science_id_is_stable_across_presentation_changes": [
        "test_counterexample_a_science_change_changes_identity",
        "test_counterexample_a_manifest_missing_a_science_key_is_refused",
        "test_counterexample_a_freeform_science_field_is_refused",
    ],
    "test_the_search_denominator_counts_distinct_specs": [
        "test_counterexample_a_different_hyperparameter_grid_is_a_new_comparison",
        "test_counterexample_select_best_is_refused",
    ],
    "test_a_descriptive_claim_needs_no_placebo": [
        "test_counterexample_a_causal_hypothesis_without_a_placebo_is_refused",
        "test_counterexample_a_causal_hypothesis_without_assumptions_is_refused",
        "test_counterexample_an_unsupported_identification_strategy_is_refused",
    ],
    "test_regime_assignment_is_deterministic": [
        "test_counterexample_a_future_state_value_is_refused",
        "test_counterexample_a_mismatched_label_count_is_refused",
    ],
    # --- Minimal monetisation evaluator (2026-08-12) ------------------------
    # A fixed-policy evaluator that cannot tune or select; viability thresholds
    # declared before use.
    "test_positive_control_a_strong_wide_factor_is_viable": [
        "test_negative_control_a_weak_factor_is_not_viable",
        "test_counterexample_a_narrow_factor_fails_the_breadth_gate",
    ],
    "test_the_policy_is_fixed_and_declared": [
        "test_counterexample_a_bad_breadth_is_refused",
    ],
    # --- APEX-003-H1 gross profitability path (2026-08-12) ------------------
    # Orientation is the erratum-class risk: higher profitability = score 100 =
    # decile 1. Isolation from the #001/#002 scorers.
    "test_highest_profitability_scores_100": [
        "test_counterexample_the_nsi_lower_is_better_convention_would_invert",
    ],
    "test_the_gp_path_reaches_no_other_experiments_scorer": [
        "test_counterexample_the_isolation_audit_flags_a_contaminated_entry",
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
    "test_positive_control_growth_pairs_across_four_quarters": (
        "hand-computed growth (150/100-1) against a fixture; wrong arithmetic "
        "fails the comparison directly"
    ),
    "test_accruals_subtracts_in_the_right_order": (
        "hand-computed (50-30)/100 against a fixture; a swapped subtraction "
        "fails the comparison directly"
    ),
    "test_every_built_spec_has_complete_metadata": (
        "asserts required metadata fields are non-empty; a blank field fails "
        "the assertion directly"
    ),
    "test_built_and_certified_components_have_a_real_module": (
        "reconciles registry state against disk; a wrong claim fails the "
        "os.path check intrinsically"
    ),
    "test_no_component_claims_holdout_access": (
        "boolean assertion over the registry; a True value fails it directly"
    ),
}

# The negative cases that carry the alignment invariant. Their absence would
# hollow out the ORDINARY classification above, so they are required to exist.
REQUIRED_NEGATIVE_CASES = [
    "an_ineligible_security_that_got_ranked_is_caught",
    "a_silently_dropped_eligible_security_is_caught",
]


def main() -> int:
    defined = set()
    for path in AUDITED_FILES:
        defined |= {
            n.name for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.FunctionDef)
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

    print("\nRunning the audited suites")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *[str(p) for p in AUDITED_FILES], "-q"],
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
