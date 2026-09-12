"""PULSE-008 -- the return, assembled from the artifacts.

Writes results/pulse008_SUMMARY.json
"""
import hashlib
import json
import subprocess
import sys

R = "/opt/apex-repo/results"
OUT = R + "/pulse008_SUMMARY.json"
ANCHORS = ("prior_close", "prior_close_return_bps", "cash_open_return_bps", "overnight_gap_bps")
QUOTES = ("mid", "spread_bps", "nbbo_size_imbalance", "last_trade")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True,
                          cwd="/opt/apex-repo").stdout.strip()


def main(control):
    before = json.load(open(R + "/pulse007_mirror_run_v2_final.json"))          # scheduled time
    mid = json.load(open(R + "/pulse008_mirror_run_v2_1_observation_time.json"))  # obs time, pre-boundary
    after = json.load(open(R + "/pulse008_mirror_run_v2_1_observation_time_boundary_fixed.json"))
    bound = json.load(open(R + "/pulse008_query_bound_probe_v1.json"))
    reach = json.load(open(R + "/pulse008_tape_reach_probe_v1.json"))
    reg = json.load(open(R + "/pulse008_bounded_regression.json"))

    def rows(doc):
        return {m["subject_class"]: {r["field"]: r for r in m["rows"]} for m in doc["results"]}

    b, m2, a = rows(before), rows(mid), rows(after)
    per_field = {}
    for cls in sorted(set(b) | set(a)):
        fields = {}
        for f in sorted(set(b.get(cls, {})) | set(a.get(cls, {}))):
            rb, rm, ra = b.get(cls, {}).get(f, {}), m2.get(cls, {}).get(f, {}), a.get(cls, {}).get(f, {})
            if rb.get("observed") == ra.get("observed") and rb.get("replay_value") == ra.get("replay_value"):
                continue
            fields[f] = {"live": ra.get("live_value", rb.get("live_value")),
                         "replay_at_scheduled": rb.get("replay_value"),
                         "replay_at_observation_pre_boundary_fix": rm.get("replay_value"),
                         "replay_at_observation_final": ra.get("replay_value"),
                         "observed_before": rb.get("observed"), "observed_after": ra.get("observed")}
        if fields:
            per_field[cls] = fields

    unresolved = {m["subject_class"]: m["declaration_violations"]
                  for m in after["results"] if m["declaration_violations"]}
    refused = [{"subject_class": f["subject_class"], "subject": f["subject"], "stage": f["stage"],
                "error": f["error"]} for f in after["reconstruction_failures"]]

    doc = {
        "kind": "pulse008_summary", "version": "PULSE008_SUMMARY_V1",
        "base_commit": "dc4a9c11e6b3bbd63ff8ed5c0a4a55609b1360f8",
        "final_commit": sh("git rev-parse HEAD"), "branch": sh("git rev-parse --abbrev-ref HEAD"),
        "worktree_clean": sh("git status --short") == "",
        "changed_files": sh("git diff --name-only dc4a9c11e HEAD").split(),

        "authoritative_timestamp": {
            "selected": "features[*].as_of of the quote-derived block",
            "why": "the composer stamps every quote-derived field from one NBBO event time, so "
                   "the packet already records what it observed, per ingredient. This is the "
                   "twin's own law: a packet is not synchronous and every field keeps its own clock.",
            "unanimity_observed": {m["subject_class"]: (m["observation_time_provenance"] or {}).get("field_count")
                                   for m in after["results"]},
            "rejected": {
                "scheduled_time": "the slot the cycle was due; nothing was read then",
                "capture_start/capture_end": "IDENTICAL across all six subjects -- one bulk "
                                             "snapshot fetch. Used only as the upper causal bound.",
                "state_complete_time/known_from": "+17.1s to +31.0s per subject, after enrichment; "
                                                  "reconstructing a quote there imports tape the "
                                                  "live quote field never saw"},
            "observation_times_used": after["observation_times_used"],
            "what_moved": "the quote ingredient only; bar ingredients stay bounded by the slot "
                          "(TDOC observed 7 ms BEFORE its slot, so one packet-level instant is "
                          "wrong in both directions)"},

        "quote_boundary_defect": {
            "id": "QUOTE-BOUNDARY-001",
            "found": "while measuring why sizes still disagreed after the timestamps matched",
            "cause": "the vendor's `end` bound does not return the event AT the boundary, so a "
                     "query with end = t never contained the quote live used and the local filter "
                     "took the previous event",
            "truncation_refuted": {s: [c["truncated"] for c in v.get("configs", [])]
                                   for s, v in reach["subjects"].items() if "configs" in v},
            "evidence": {s: {"exact_event_present_by_query_margin":
                             {c["query_end_margin_s"]: c["exact_event_present"] for c in v["configs"]},
                             "gap_ms_by_margin": {c["query_end_margin_s"]: c["gap_to_instant_ms"] for c in v["configs"]},
                             "matches_live_by_margin": {c["query_end_margin_s"]: c["matches_live"] for c in v["configs"]}}
                         for s, v in bound["subjects"].items() if "configs" in v},
            "repair": "widen the vendor QUERY past the instant; the local `<= t` filter is "
                      "unchanged and remains the only thing that admits an event"},

        "per_field_before_after": per_field,
        "unresolved_fields": unresolved,
        "refused_comparisons": refused,

        "mirror": {
            "before_pulse008": {"verdicts": {m["subject_class"]: m["verdict"] for m in before["results"]},
                                "coverage": before["MIRROR_COVERAGE"],
                                "declarations": before["MIRROR_UNDER_ORIGINAL_DECLARATIONS"]},
            "observation_time_only": {"verdicts": {m["subject_class"]: m["verdict"] for m in mid["results"]},
                                      "violations": mid["declaration_violations"]},
            "observation_time_plus_boundary_fix": {
                "verdicts": {m["subject_class"]: m["verdict"] for m in after["results"]},
                "violations": after["declaration_violations"],
                "coverage": after["MIRROR_COVERAGE"],
                "coverage_reasons": after["coverage_reasons"],
                "anchor": after["ANCHOR_STATUS"],
                "declarations": after["MIRROR_UNDER_ORIGINAL_DECLARATIONS"]}},

        "bounded_regression": {**{k: reg[k] for k in ("commit", "tree", "shards", "totals",
                                                      "slice_oom_kill_before", "slice_oom_kill_after",
                                                      "problem_shards", "verdict")},
                               "problem_shard_attribution": control,
                               "tree_note": "the tested tree differs from the final commit only by "
                                            "scripts/pulse008_shard_regression.sh, the untracked "
                                            "runner that executed the run; it is imported by nothing"},

        "preservation": {
            "original_failed_mirror_evidence": {"path": "results/pulse/mirror_tests.jsonl",
                                                "sha256": sha("/opt/apex-repo/results/pulse/mirror_tests.jsonl")},
            "pulse007_evidence": {p: sha("/opt/apex-repo/results/" + p) for p in
                                  ("pulse007_mirror_run_v2_final.json", "pulse007_frozen_packets.jsonl",
                                   "pulse007_frozen_manifest.json", "pulse007_anchor_trace.json",
                                   "pulse007_SUMMARY.json")},
            "declarations_and_tolerances_unchanged":
                sh("git diff --stat 7969dbbd1 HEAD -- apex/pulse/parity.py apex/pulse/mirror.py "
                   "apex/pulse/compose.py scripts/mirror_run.py") == "",
            "frozen_packets_unchanged_since_pulse007":
                sh("git diff --stat dc4a9c11e HEAD -- results/pulse007_frozen_packets.jsonl "
                   "results/pulse007_frozen_manifest.json") == "",
            "world_model_worktree": sh("git -C /opt/apex-research/world-model-shadow rev-parse --short HEAD"),
            "production_release": sh("readlink -f /opt/apex/current")},

        "incidental_findings_reported_not_acted_on": {
            "DERIVED-FIELD-STALENESS-001":
                "the composer marked NKLA's RAW quote fields STALE (a 553-day-old NBBO) and "
                "marked the DERIVED fields computed from that same stale mid VALID, including "
                "prior_close_return_bps = -2869.94. Staleness is applied to the raw fields and "
                "not propagated to what is derived from them. A live-composer defect; not this brick.",
            "ORCHESTRATOR-OOM-LOOP-001": "unchanged from PULSE-007; still open, not touched"},

        "verdicts": {
            "OBSERVATION_TIME_CONTRACT": "DEFINED",
            "OBSERVATION_TIME_RECONCILIATION": ("RESOLVED_FOR_EVERY_RECONCILABLE_SUBJECT"
                                                if not unresolved else "UNRESOLVED"),
            "MIRROR_COVERAGE": after["MIRROR_COVERAGE"],
            "MIRROR_UNDER_ORIGINAL_DECLARATIONS": after["MIRROR_UNDER_ORIGINAL_DECLARATIONS"],
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "NOT_PROVEN",
            "PHASE_2": "OPEN",
            "WORLD_MODEL_REAL_DATA_ADMISSION": "NOT_AUTHORIZED"},

        "verdict_notes": {
            "OBSERVATION_TIME_RECONCILIATION": "every field that could be compared now agrees: "
                                               "5 of 6 subjects MIRROR_CONSISTENT with an empty "
                                               "violation list, under the ORIGINAL declarations "
                                               "and the ORIGINAL tolerances.",
            "MIRROR_COVERAGE": "INCOMPLETE because NKLA is refused as STALE_BEYOND_POLICY. Five "
                               "of six is not a pass and the runner does not report one.",
            "MIRROR_UNDER_ORIGINAL_DECLARATIONS": "BLOCKED, not FAIL: there are zero violations, "
                                                  "but coverage is incomplete, so the status "
                                                  "cannot be PASS.",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "unchanged. The vendor still returns history as it "
                                                "stands at retrieval; nothing here establishes when "
                                                "a value became available."},
    }
    json.dump(doc, open(OUT, "w"), indent=1)
    print(json.dumps(doc["verdicts"], indent=1))
    print("unresolved fields:", unresolved or "NONE")
    print("refused:", [r["subject"] for r in refused])
    print("wrote", OUT)


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
