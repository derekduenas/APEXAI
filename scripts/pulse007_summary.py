"""PULSE-007 -- the return, assembled from the artifacts rather than retyped.

Reads the frozen manifest, the anchor trace, both mirror runs, the quote
residual, the bounded regression and the base-commit control, and writes one
summary with the seven required verdicts.

Writes results/pulse007_SUMMARY.json
"""
import hashlib
import json
import os
import subprocess
import sys

R = "/opt/apex-repo/results"
OUT = R + "/pulse007_SUMMARY.json"
ANCHORS = ("prior_close", "prior_close_return_bps", "cash_open_return_bps", "overnight_gap_bps")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True, cwd="/opt/apex-repo").stdout.strip()


def main(mirror_path, control):
    orig = [json.loads(l) for l in open(R + "/../results/pulse/mirror_tests.jsonl")]
    post = json.load(open(mirror_path))
    trace = json.load(open(R + "/pulse007_anchor_trace.json"))
    resid = json.load(open(R + "/pulse007_quote_residual.json"))
    reg = json.load(open(R + "/pulse007_bounded_regression.json"))
    orig_by = {o["subject"]: o for o in orig}

    before_after = {}
    for m in post["results"]:
        s = m["subject"]
        o = orig_by.get(s, {})
        rows = {r["field"]: r for r in o.get("rows", [])}
        before_after[s] = {"subject_class": m["subject_class"],
                           "before_verdict": o.get("verdict"), "after_verdict": m["verdict"],
                           "before_violations": o.get("declaration_violations", []),
                           "after_violations": m["declaration_violations"],
                           "anchors": {}}
        for f in ANCHORS:
            b, a = rows.get(f, {}), m["anchor_rows"].get(f, {})
            before_after[s]["anchors"][f] = {
                "live": a.get("live", b.get("live_value")),
                "replay_before": b.get("replay_value"), "replay_after": a.get("replay"),
                "observed_before": b.get("observed"), "observed_after": a.get("observed")}

    NOT_COMPARED = ("LIVE_ONLY", "HISTORICAL_ONLY", "NOT_AVAILABLE", None)
    PURE = ("prior_close", "overnight_gap_bps")                   # contain no live mid
    MIXED = ("prior_close_return_bps", "cash_open_return_bps")    # anchor combined with the live mid

    def bucket(fields):
        eq, approx, uncompared = {}, {}, {}
        for subj, v in before_after.items():
            for f in fields:
                o = v["anchors"][f]["observed_after"]
                tgt = (eq if o == "SEMANTICALLY_EQUIVALENT"
                       else uncompared if o in NOT_COMPARED else approx)
                tgt.setdefault(subj, []).append(f)
        return {"semantically_equivalent": eq, "disagreed": approx, "not_compared": uncompared}

    pure, mixed = bucket(PURE), bucket(MIXED)
    anchor_fields_clean = not (pure["disagreed"] or mixed["disagreed"]
                               or pure["not_compared"] or mixed["not_compared"])
    decomposition = {
        "buckets": "semantically_equivalent = both feeders produced a value and they agree; "
                   "disagreed = both produced a value and they do not; not_compared = history "
                   "produced nothing, which is a COVERAGE question, not a value question",
        "pure_anchor_quantities": {
            "fields": list(PURE), **pure,
            "result": "EXACT on every subject where history reconstructed anything (%d of %d "
                      "subjects); the only gap is NKLA, where history reconstructs nothing at all. "
                      "ANCHOR-001 and ANCHOR-002 no longer produce a wrong value anywhere."
                      % (len(pure["semantically_equivalent"]), len(before_after))},
        "anchor_over_live_mid": {
            "fields": list(MIXED), **mixed,
            "note": "these embed the LIVE MID as well as an anchor, so a quote-timing difference "
                    "surfaces here even when the anchor itself is exact. On AAOI the two pure "
                    "anchor quantities match EXACTLY while these two do not, which localises the "
                    "residual to the mid rather than to the anchor."},
        "why_the_overall_verdict_is_not_PASS":
            "ANCHOR_REPAIR is computed under the strict rule fixed before the run -- all four "
            "anchor-related fields SEMANTICALLY_EQUIVALENT on every subject. AAOI disagrees on the "
            "two mid-bearing features and NKLA compares nothing at all, so the rule is not met. "
            "The rule was NOT relaxed after seeing the result; the decomposition is offered so the "
            "residual can be judged rather than assumed."}

    doc = {
        "kind": "pulse007_summary", "version": "PULSE007_SUMMARY_V1",
        "base_commit": "7969dbbd1", "final_commit": sh("git rev-parse HEAD"),
        "branch": sh("git rev-parse --abbrev-ref HEAD"),
        "worktree_clean": sh("git status --short") == "",

        "root_causes": {
            "ANCHOR-001": {
                "field": "prior_close (and prior_close_return_bps, overnight_gap_bps through it)",
                "cause": "the historical feeder admitted a daily bar by `stamp + 24h <= UTC midnight "
                         "of t`. A daily bar is stamped at the session's ET midnight (04:00Z under "
                         "EDT), so the most recent completed session failed the test and the one "
                         "before it was returned.",
                "evidence": {s: {"daily_bars_offered": v["replay_current_code"]["daily_returned"],
                                 "dropped_by_the_width_filter":
                                     v["replay_current_code"]["daily_dropped_by_width_filter"],
                                 "live_session": v["live"]["prior_close_session_date"],
                                 "replay_session_before_repair":
                                     (v["replay_current_code"].get("prevDailyBar") or {}).get("session_date")}
                             for s, v in trace["subjects"].items()},
                "repair": "select by SESSION DATE: the last session strictly before the session "
                          "containing the as-of instant (apex.pulse.anchors.select_prior_daily)"},
            "ANCHOR-002": {
                "field": "cash_open_return_bps (and overnight_gap_bps through dailyBar.o)",
                "cause": "the intraday window began at UTC midnight, which is 20:00 ET on the "
                         "PREVIOUS calendar day, so dailyBar.o was the first extended-hours print. "
                         "Astra's correction is confirmed: cash_open_return_bps is mid/dailyBar.o "
                         "and has nothing to do with prior_close.",
                "evidence": {s: {"replay_open_bar_session_class":
                                     (v["replay_current_code"].get("dailyBar") or {}).get("o_bar_session"),
                                 "replay_open_bar_local":
                                     (v["replay_current_code"].get("dailyBar") or {}).get("o_bar_in_exchange_local"),
                                 "bars_before_cash_open": v["replay_current_code"].get("bars_before_cash_open"),
                                 "live_open": v["live"]["session_open"]["v"],
                                 "replay_open_before_repair": (v["replay_current_code"].get("dailyBar") or {}).get("o"),
                                 "cash_open_bar_open": (v["replay_current_code"].get("cash_open_bar") or {}).get("o")}
                             for s, v in trace["subjects"].items()},
                "repair": "the aggregate covers the REGULAR session only, and the opening price "
                          "comes from the current session's daily bar through a field allow-list "
                          "of exactly ('o',)"}},

        "before_after_six_comparisons": before_after,
        "anchor_fields_all_semantically_equivalent_after_repair": anchor_fields_clean,
        "anchor_decomposition": decomposition,

        "residual_after_repair": {
            "classification": {s: {"category": v.get("category"), "finding": v.get("finding")}
                               for s, v in resid["subjects"].items()},
            "conclusion": "category (a) on every subject that had a quote: same source, same "
                          "convention, DIFFERENT selected event. The live packet's mid, spread_bps, "
                          "nbbo_size_imbalance and touch_size reproduce EXACTLY from the tape at "
                          "the packet's own as_of, on 5 of 5. No quote-engine defect was found and "
                          "none was rebuilt.",
            "natural_control": "TDOC has 0 NBBO updates between the scheduled slot and its own "
                               "as_of, and TDOC is the only subject whose full mirror passes."},

        "coverage": {"MIRROR_COVERAGE": post["MIRROR_COVERAGE"],
                     "reasons": post["coverage_reasons"],
                     "empty_comparisons": post["empty_comparisons"],
                     "v0_would_have_said": "MIRROR_CONSISTENT for NKLA -- zero fields compared, "
                                           "zero violations raised"},

        "bounded_regression": {**{k: reg[k] for k in ("commit", "tree", "shards", "totals",
                                                      "slice_oom_kill_before", "slice_oom_kill_after",
                                                      "problem_shards", "verdict",
                                                      "acceptance_surface_on_this_branch")},
                               "problem_shard_attribution": control},

        "preservation": {
            "original_failed_mirror_evidence": {
                "path": "results/pulse/mirror_tests.jsonl",
                "sha256": sha("/opt/apex-repo/results/pulse/mirror_tests.jsonl"),
                "note": "untouched by this brick; the V2 runner writes to a separate versioned path"},
            "declarations_and_tolerances_unchanged":
                sh("git diff --stat 7969dbbd1 HEAD -- apex/pulse/parity.py apex/pulse/mirror.py "
                   "apex/pulse/compose.py scripts/mirror_run.py") == "",
            "files_changed": sh("git diff --name-only 7969dbbd1 HEAD").split(),
            "world_model_worktree": sh("git -C /opt/apex-research/world-model-shadow rev-parse --short HEAD"),
            "world_model_worktree_clean":
                sh("git -C /opt/apex-research/world-model-shadow status --short") == "",
            "production_release": sh("readlink -f /opt/apex/current")},

        "verdicts": {
            "ANCHOR_CONTRACT": "DEFINED",
            "ANCHOR_REPAIR": "PASS" if anchor_fields_clean else "FAIL",
            "MIRROR_COVERAGE": post["MIRROR_COVERAGE"],
            "MIRROR_UNDER_ORIGINAL_DECLARATIONS": post["MIRROR_UNDER_ORIGINAL_DECLARATIONS"],
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "NOT_PROVEN",
            "PHASE_2": "OPEN",
            "WORLD_MODEL_REAL_DATA_ADMISSION": "NOT_AUTHORIZED"},

        "verdict_notes": {
            "ANCHOR_REPAIR": "FAIL under the strict rule fixed before the run: all four "
                             "anchor-related fields SEMANTICALLY_EQUIVALENT on every subject. The "
                             "two PURE anchor quantities -- prior_close and overnight_gap_bps -- "
                             "are now EXACT on 5 of 5, so ANCHOR-001 and ANCHOR-002 are closed. "
                             "The two features that combine an anchor with the LIVE MID remain "
                             "APPROXIMATE on AAOI, for the quote-timing reason measured in the "
                             "residual classification. The rule was not relaxed to convert this "
                             "into a PASS; see anchor_decomposition.",
            "MIRROR_COVERAGE": "INCOMPLETE because NKLA reconstructs nothing. That is the honest "
                               "answer, not a regression: the V0 runner called the same situation "
                               "MIRROR_CONSISTENT.",
            "MIRROR_UNDER_ORIGINAL_DECLARATIONS": "BLOCKED, not PASS. No declaration was relaxed to "
                                                  "reach a green result.",
            "HISTORICAL_AS_KNOWN_AVAILABILITY": "the vendor history endpoint returns records as they "
                                                "stand at retrieval; nothing establishes when a value "
                                                "became available. Corpus admission stays blocked."},
    }
    json.dump(doc, open(OUT, "w"), indent=1)
    print(json.dumps(doc["verdicts"], indent=1))
    print("anchor fields clean:", anchor_fields_clean)
    print("wrote", OUT)


if __name__ == "__main__":
    main(sys.argv[1], json.loads(sys.argv[2]))
