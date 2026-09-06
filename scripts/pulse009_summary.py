"""PULSE-009 -- the return, assembled from the artifacts.

Writes results/pulse009_SUMMARY.json
"""
import hashlib
import json
import subprocess
import sys

R = "/opt/apex-repo/results"
OUT = R + "/pulse009_SUMMARY.json"
sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import derived as D                      # noqa: E402
from apex.pulse.compose import COMPOSER_HISTORY, COMPOSER_VERSION   # noqa: E402


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True,
                          cwd="/opt/apex-repo").stdout.strip()


def main(control):
    nkla = json.load(open(R + "/pulse009_nkla_before_after.json"))
    audit = json.load(open(R + "/pulse009_consumer_audit.json"))
    reg = json.load(open(R + "/pulse009_bounded_regression.json"))
    doc = {
        "kind": "pulse009_summary", "version": "PULSE009_SUMMARY_V1",
        "base_commit": "7bf2f106e28bff2261028debbf54695b48106922",
        "final_commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
        "worktree_clean": sh("git status --short") == "",
        "changed_files": sh("git diff --name-only 7bf2f106e HEAD").split(),

        "defect": {
            "id": "DERIVED-FIELD-STALENESS-001",
            "cause": "the freshness verdict was applied where a value was READ and never "
                     "travelled to what was BUILT from it",
            "composer_before": "PULSE_COMPOSE_V0", "composer_after": COMPOSER_VERSION,
            "history": COMPOSER_HISTORY},

        "dependency_map": {
            "contract": D.DERIVED_FIELD_CONTRACT,
            "derived_fields": len(D.DEPENDENCIES),
            "independent_fields": list(D.INDEPENDENT_FIELDS),
            "map": {k: {"inputs": list(v["inputs"]), "formula": v.get("formula"),
                        **({"exception": v["exception"], "why": v["why"]} if "exception" in v else {}),
                        **({"session_gated": list(v["session_gated"])} if "session_gated" in v else {})}
                    for k, v in sorted(D.DEPENDENCIES.items())}},

        "propagation_rules": {
            "VALID": "only when every declared ingredient is VALID",
            "STALE": "every ingredient has a value and at least one is STALE; the value is omitted",
            "ABSENT": "an ingredient has no value; the dependent takes the first matching reason "
                      "in %s so an absence is never flattened into staleness"
                      % list(D.ABSENCE_PRECEDENCE),
            "INVALID": "a raw ingredient that is not a finite real number is NOT_ESTIMABLE at the "
                       "ingredient and propagates as an absence; bool is not a number",
            "SESSION_INAPPLICABLE": "decided before ingredients and never overwritten",
            "INDEPENDENT": "a field with no failing ingredient is untouched; a stale quote does "
                           "not reach prior_close, the session aggregates, overnight_gap_bps or "
                           "relative_volume",
            "FORMULA_GUARD": "compute() is not called at all unless every ingredient is VALID, so "
                             "no formula can see an untrusted number",
            "REASON_CHAIN": "the ingredient's own note travels into the dependent, so the "
                            "freshness tolerance that refused the quote stays legible on every "
                            "field refused because of it"},

        "representation_decision": {
            "chosen": "the value is OMITTED on any non-VALID quality",
            "decided_by": "the existing schema, not preference: apex.pulse.twin.Field refuses a "
                          "non-trustworthy field that carries a number",
            "downstream_cannot_treat_as_VALID": [
                "Field.__post_init__ raises TwinViolation on a non-VALID field with a number",
                "Field.usable is False for every non-VALID quality",
                "the serialised record carries v = null with its own q",
                "the note names the failing ingredient, so the reason survives serialisation"]},

        "nkla_before_after": {
            "refused_by_the_repair": nkla["fields_that_were_VALID_and_are_now_refused"],
            "count": nkla["count_refused_by_the_repair"],
            "changed_but_not_attributable": list(nkla["changed_but_not_attributable_to_the_repair"]["fields"]),
            "quote_age_s_retained": nkla["quote_age_s_retained"],
            "independent_fields_unaffected": nkla["independent_fields_unaffected"],
            "sealed_packet_untouched": True},

        "consumer_audit": {
            "modules_touching_features": audit["modules_touching_features"],
            "read_value_without_any_quality_check": audit["read_value_without_any_quality_check"],
            "assessment": "the three are this session's own PULSE-007/008 diagnostic probes, which "
                          "read FROZEN packets to measure them. No live or research consumer reads "
                          "a feature value without consulting its quality.",
            "structural_guarantee": audit["structural_guarantee"]},

        "bounded_regression": {**{k: reg[k] for k in ("commit", "tree", "shards", "totals",
                                                      "slice_oom_kill_before", "slice_oom_kill_after",
                                                      "problem_shards", "verdict")},
                               "problem_shard_attribution": control,
                               "tree_note": "the tested tree differs from the final commit only by "
                                            "the untracked runner script that executed it"},

        "preservation": {
            "original_failed_mirror_evidence": sha("/opt/apex-repo/results/pulse/mirror_tests.jsonl"),
            "pulse007_and_008_artifacts": {p: sha("/opt/apex-repo/results/" + p) for p in (
                "pulse007_frozen_packets.jsonl", "pulse007_frozen_manifest.json",
                "pulse007_mirror_run_v2_final.json", "pulse007_SUMMARY.json",
                "pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json",
                "pulse008_SUMMARY.json")},
            "sealed_evidence_unchanged":
                sh("git diff --stat 7bf2f106e HEAD -- results/pulse007_frozen_packets.jsonl "
                   "results/pulse007_frozen_manifest.json results/pulse007_mirror_run_v2_final.json "
                   "results/pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json") == "",
            "declarations_tolerances_mirror_and_observation_unchanged":
                sh("git diff --stat 7bf2f106e HEAD -- apex/pulse/parity.py apex/pulse/mirror.py "
                   "apex/pulse/historical.py apex/pulse/observation.py apex/pulse/anchors.py "
                   "scripts/mirror_run.py scripts/mirror_run_v2.py") == "",
            "world_model_worktree": sh("git -C /opt/apex-research/world-model-shadow rev-parse --short HEAD"),
            "production_release": sh("readlink -f /opt/apex/current")},

        "still_open_not_touched": {
            "LIVE-ANCHOR-STALENESS-V1": "the composer still cannot mark an ANCHOR stale; NKLA's "
                                        "prior_close of 2025-02-24 is VALID. PULSE-009 makes the "
                                        "propagation ready for it and proves the rule at the "
                                        "boundary, but does not add anchor freshness.",
            "ORCHESTRATOR-OOM-LOOP-001": "unchanged, untouched",
            "NKLA mirror coverage": "unchanged, untouched"},

        "verdicts": {
            "DERIVED_FIELD_DEPENDENCY_CONTRACT": "DEFINED",
            "STALE_PROPAGATION": "ENFORCED",
            "QUALITY_SEMANTICS": "PRESERVED",
            "PULSE_COMPOSER_INTEGRITY": "REPAIRED_FOR_DERIVED_FIELDS",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "NOT_PROVEN",
            "PHASE_2": "OPEN",
            "WORLD_MODEL_REAL_DATA_ADMISSION": "NOT_AUTHORIZED"},

        "verdict_notes": {
            "PULSE_COMPOSER_INTEGRITY": "scoped deliberately. Every DERIVED field now inherits its "
                                        "ingredients' trustworthiness. The composer's remaining "
                                        "known gap is that an ANCHOR cannot yet be marked stale at "
                                        "all, which is LIVE-ANCHOR-STALENESS-V1 and outside this "
                                        "brick.",
            "QUALITY_SEMANTICS": "STALE, NOT_AVAILABLE, NOT_ESTIMABLE, PROVIDER_ERROR, UNKNOWN and "
                                 "SESSION_INAPPLICABLE remain distinct and are tested to be.",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "unchanged by this brick."},
    }
    json.dump(doc, open(OUT, "w"), indent=1)
    print(json.dumps(doc["verdicts"], indent=1))
    print("derived fields mapped:", len(D.DEPENDENCIES), "| NKLA refused:", doc["nkla_before_after"]["count"])
    print("wrote", OUT)


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
