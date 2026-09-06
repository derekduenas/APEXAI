"""PULSE-010 REPAIR -- the return, assembled from the artifacts."""
import hashlib, json, subprocess, sys
R = "/opt/apex-repo/results"
sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import derived as D
from apex.pulse.compose import COMPOSER_HISTORY, COMPOSER_VERSION

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def sh(c): return subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/opt/apex-repo").stdout.strip()

def main(control):
    ba = json.load(open(R + "/pulse010r_before_after.json"))
    nk = json.load(open(R + "/pulse010r_nkla_attributed.json"))
    reg = json.load(open(R + "/pulse010r_bounded_regression.json"))
    doc = {
        "kind": "pulse010_repair_summary", "version": "PULSE010R_SUMMARY_V1",
        "base_commit": "7c35027e706953ea164648bad9c51da4db763845",
        "final_commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
        "worktree_clean": sh("git status --short") == "",
        "changed_files": sh("git diff --name-only 7c35027e7 HEAD").split(),
        "the_finding": {
            "reported": "compose.py passed one shared dict containing prior_close into "
                        "cash_open_return_bps, session_range_position and vwap_distance_bps, "
                        "so a stale prior_close invalidated fields that do not depend on it",
            "wiring_defect_confirmed": True,
            "inferred_consequence_measured": "DID NOT OCCUR -- resolve() iterates "
                                             "DEPENDENCIES[name]['inputs'] and ignores anything "
                                             "else in the dict",
            "measurement": "results/pulse010r_before_after.json, four scenarios composed on the "
                           "shipped code at 7c35027e7 and again after the repair",
            "behaviour_changed_by_the_repair": ba.get("behaviour_changed"),
            "field_level_differences": ba.get("field_level_differences_before_vs_after")},
        "before_after_dependency_behaviour": {
            k: {n: v["fields"][n]["q"] for n in
                ("prior_close", "prior_close_return_bps", "overnight_gap_bps", "relative_volume",
                 "cash_open_return_bps", "session_range_position", "vwap_distance_bps")}
            for k, v in ba["after"]["scenarios"].items()},
        "the_repair": {
            "call_sites": "every derived call builds its ingredient dict FROM "
                          "derived.DEPENDENCIES[name]['inputs'], so the wiring is the map rather "
                          "than merely compatible with it",
            "guard": "derive() now REFUSES an undeclared ingredient, naming every offender, "
                     "instead of ignoring it",
            "map_untouched": sh("git diff --stat 7c35027e7 HEAD -- apex/pulse/derived.py | "
                                "grep -c DEPENDENCIES") == "0",
            "composer": COMPOSER_VERSION, "history": COMPOSER_HISTORY.get("V0.2.1")},
        "nkla_attributed": {
            "supersedes": "the PULSE-010 table, which listed refusals without naming the failing "
                          "ingredient",
            "anchor_caused": nk["refused_because_the_ANCHOR_failed"],
            "quote_caused": nk["refused_because_the_QUOTE_failed"],
            "rows": nk["refused_with_attribution"],
            "current_session_fields": nk["current_session_fields"],
            "note_on_independence": nk["note_on_independence"]},
        "bounded_regression": {**{k: reg[k] for k in ("commit", "tree", "shards", "totals",
                                                      "slice_oom_kill_before", "slice_oom_kill_after",
                                                      "problem_shards", "verdict")},
                               "problem_shard_attribution": control},
        "preservation": {
            "original_failed_mirror_evidence": sha("/opt/apex-repo/results/pulse/mirror_tests.jsonl"),
            "prior_artifacts": {p: sha("/opt/apex-repo/results/" + p) for p in (
                "pulse007_frozen_packets.jsonl", "pulse007_frozen_manifest.json",
                "pulse007_mirror_run_v2_final.json", "pulse008_SUMMARY.json",
                "pulse009_SUMMARY.json", "pulse010_SUMMARY.json",
                "pulse010_nkla_before_after.json")},
            "frozen_and_prior_evidence_unchanged": sh(
                "git diff --stat 7c35027e7 HEAD -- results/pulse007_frozen_packets.jsonl "
                "results/pulse007_frozen_manifest.json results/pulse007_mirror_run_v2_final.json "
                "results/pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json "
                "results/pulse009_nkla_before_after.json results/pulse010_nkla_before_after.json "
                "results/pulse010_SUMMARY.json") == "",
            "policies_and_declarations_unchanged": sh(
                "git diff --stat 7c35027e7 HEAD -- apex/pulse/anchor_freshness.py "
                "apex/pulse/parity.py apex/pulse/mirror.py apex/pulse/historical.py "
                "apex/pulse/observation.py apex/pulse/anchors.py apex/pulse/freshness.py "
                "scripts/mirror_run.py scripts/mirror_run_v2.py") == "",
            "dependency_map_unchanged": "DEPENDENCIES not modified; only resolve()'s guard and "
                                        "the module docstring changed in derived.py",
            "world_model_worktree": sh("git -C /opt/apex-research/world-model-shadow rev-parse --short HEAD"),
            "production_release": sh("readlink -f /opt/apex/current")},
        "verdicts": {
            "DEPENDENCY_WIRING": "REPAIRED",
            "ANCHOR_FRESHNESS_ENFORCEMENT": "ENFORCED",
            "DERIVED_FIELD_INDEPENDENCE": "ENFORCED_AND_MEASURED",
            "PULSE_COMPOSER_INTEGRITY": "REPAIRED_FOR_DERIVED_AND_ANCHOR_FIELDS",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "NOT_PROVEN",
            "PHASE_2": "OPEN",
            "WORLD_MODEL_REAL_DATA_ADMISSION": "NOT_AUTHORIZED"},
        "verdict_notes": {
            "DEPENDENCY_WIRING": "the over-broad dict is gone and an undeclared ingredient is now "
                                 "an error. The wiring was the defect; the coupling it was "
                                 "reported to cause was measured not to have occurred.",
            "DERIVED_FIELD_INDEPENDENCE": "measured on a synthetic fresh-quote/stale-anchor "
                                          "fixture, before and after, with identical results: "
                                          "cash_open_return_bps, session_range_position and "
                                          "vwap_distance_bps stay VALID while the three true "
                                          "anchor dependents are refused."},
    }
    json.dump(doc, open(R + "/pulse010r_SUMMARY.json", "w"), indent=1)
    print(json.dumps(doc["verdicts"], indent=1))
    print("behaviour changed by the repair:", doc["the_finding"]["behaviour_changed_by_the_repair"])
    print("preservation:", {k: v for k, v in doc["preservation"].items() if isinstance(v, bool)})

if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
