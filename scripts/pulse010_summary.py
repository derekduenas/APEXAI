"""PULSE-010 -- the return, assembled from the artifacts."""
import hashlib, json, subprocess, sys
R = "/opt/apex-repo/results"
sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import anchor_freshness as A, derived as D
from apex.pulse.compose import COMPOSER_HISTORY, COMPOSER_VERSION, _ANCHOR_QUALITY

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/opt/apex-repo").stdout.strip()

def main(control):
    nkla = json.load(open(R + "/pulse010_nkla_before_after.json"))
    audit = json.load(open(R + "/pulse010_consumer_audit.json"))
    reg = json.load(open(R + "/pulse010_bounded_regression.json"))
    doc = {
        "kind": "pulse010_summary", "version": "PULSE010_SUMMARY_V1",
        "base_commit": "93ee36929b04bacbf2f84839f1f547eabbc013ae",
        "final_commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
        "worktree_clean": sh("git status --short") == "",
        "changed_files": sh("git diff --name-only 93ee36929 HEAD").split(),
        "anchor_freshness_contract": A.describe(),
        "classification_to_quality": {k: v for k, v in _ANCHOR_QUALITY.items()},
        "composer": {"version": COMPOSER_VERSION, "history": COMPOSER_HISTORY},
        "dependency_effects": {
            "anchor_dependent_fields_that_follow_it": ["prior_close_return_bps",
                                                       "overnight_gap_bps", "relative_volume"],
            "current_session_fields_unaffected": ["session_open", "session_high", "session_low",
                                                  "session_vwap", "session_volume",
                                                  "cash_open_return_bps", "mid", "spread_bps",
                                                  "nbbo_size_imbalance", "session_range_position",
                                                  "vwap_distance_bps"],
            "mechanism": "PULSE-009's dependency map: the anchor carries its own quality and "
                         "derive() refuses to run a formula on it",
            "prior_session_volume": "comes off the same bar as the prior close and inherits the "
                                    "same verdict",
            "new_provenance_field": "prior_close_session -- which exchange session the anchor "
                                    "belongs to, and which one was expected"},
        "nkla_before_after": {
            "refused": nkla["fields_that_were_VALID_and_are_now_refused"],
            "count": nkla["count_refused_by_the_repair"],
            "not_attributable": list(nkla["changed_but_not_attributable_to_the_repair"]["fields"]),
            "quote_age_s_retained": nkla["quote_age_s_retained"],
            "independent": nkla["independent_fields_unaffected"],
            "sealed_packet_untouched": True},
        "consumer_audit": {
            "modules_touching_features": audit["modules_touching_features"],
            "anchor_field_readers": audit.get("anchor_field_readers", []),
            "anchor_readers_without_a_quality_check": audit.get("anchor_readers_without_a_quality_check", []),
            "read_value_without_any_quality_check": audit["read_value_without_any_quality_check"],
            "assessment": "the only modules reading a value without checking quality are this "
                          "session's own PULSE-007/008 probes, which read FROZEN packets to "
                          "measure them. No live or research consumer can treat a non-VALID "
                          "anchor as usable: it carries v = null, enforced by twin.Field.",
            "structural_guarantee": audit["structural_guarantee"]},
        "bounded_regression": {**{k: reg[k] for k in ("commit", "tree", "shards", "totals",
                                                      "slice_oom_kill_before", "slice_oom_kill_after",
                                                      "problem_shards", "verdict")},
                               "problem_shard_attribution": control},
        "preservation": {
            "original_failed_mirror_evidence": sha("/opt/apex-repo/results/pulse/mirror_tests.jsonl"),
            "prior_brick_artifacts": {p: sha("/opt/apex-repo/results/" + p) for p in (
                "pulse007_frozen_packets.jsonl", "pulse007_frozen_manifest.json",
                "pulse007_mirror_run_v2_final.json", "pulse007_SUMMARY.json",
                "pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json",
                "pulse008_SUMMARY.json", "pulse009_nkla_before_after.json",
                "pulse009_SUMMARY.json")},
            "sealed_evidence_unchanged": sh(
                "git diff --stat 93ee36929 HEAD -- results/pulse007_frozen_packets.jsonl "
                "results/pulse007_frozen_manifest.json results/pulse007_mirror_run_v2_final.json "
                "results/pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json "
                "results/pulse009_nkla_before_after.json") == "",
            "declarations_tolerances_mirror_observation_unchanged": sh(
                "git diff --stat 93ee36929 HEAD -- apex/pulse/parity.py apex/pulse/mirror.py "
                "apex/pulse/historical.py apex/pulse/observation.py apex/pulse/anchors.py "
                "scripts/mirror_run.py scripts/mirror_run_v2.py") == "",
            "freshness_policy_version_history_preserved": sh(
                "git diff --stat 93ee36929 HEAD -- apex/pulse/freshness.py") == "",
            "world_model_worktree": sh("git -C /opt/apex-research/world-model-shadow rev-parse --short HEAD"),
            "production_release": sh("readlink -f /opt/apex/current")},
        "tests_updated_not_relaxed": [
            "test_pulse_derived.py composer version pin -> starts-with, history keys still asserted",
            "test_pulse_derived.py NKLA prior_close VALID -> STALE, with the reason stated in "
            "place; the PULSE-009 invariant is asserted where it belongs, on a FRESH anchor"],
        "defect_found_by_this_suite": "a DATE-ONLY vendor record was read as UTC midnight and "
                                      "converted to ET, moving it back one session; a bar from "
                                      "the CURRENT session would have passed as the immediately "
                                      "preceding one",
        "verdicts": {
            "ANCHOR_FRESHNESS_CONTRACT": "DEFINED",
            "ANCHOR_QUALITY_ENFORCEMENT": "ENFORCED",
            "ANCHOR_DERIVED_PROPAGATION": "ENFORCED",
            "PULSE_COMPOSER_INTEGRITY": "REPAIRED_FOR_DERIVED_AND_ANCHOR_FIELDS",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "NOT_PROVEN",
            "PHASE_2": "OPEN",
            "WORLD_MODEL_REAL_DATA_ADMISSION": "NOT_AUTHORIZED"},
    }
    json.dump(doc, open(R + "/pulse010_SUMMARY.json", "w"), indent=1)
    print(json.dumps(doc["verdicts"], indent=1))
    print("NKLA refused:", doc["nkla_before_after"]["count"], "| preservation:",
          {k: v for k, v in doc["preservation"].items() if isinstance(v, bool)})

if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
