"""PULSE-010 REPAIR -- dependency behaviour, measured before and after.

Three deterministic scenarios, one composer call each, no network and no
clock. Run with `before` or `after`; the two records are merged into
results/pulse010r_before_after.json so the change is a measurement rather
than a claim.
"""
import json
import os
import sys

sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import derived as D                       # noqa: E402
from apex.pulse.compose import COMPOSER_VERSION, compose   # noqa: E402

OUT = "/opt/apex-repo/results/pulse010r_before_after.json"
AT = "2026-09-01T13:45:00+00:00"
FRESH_Q = "2026-09-01T13:44:59Z"
STALE_Q = "2025-02-26T00:59:59Z"
FRESH_A = "2026-08-31T04:00:00Z"          # the immediately preceding session
STALE_A = "2025-02-24T05:00:00Z"          # 553 days and ~388 sessions earlier

WATCHED = ("mid", "prior_close", "session_open", "session_high", "session_low",
           "session_vwap", "session_volume",
           "prior_close_return_bps", "overnight_gap_bps", "relative_volume",
           "cash_open_return_bps", "session_range_position", "vwap_distance_bps")
QUOTE_ONLY = ("cash_open_return_bps", "session_range_position", "vwap_distance_bps")
ANCHOR_ONLY = ("prior_close_return_bps", "overnight_gap_bps", "relative_volume")


def build(quote_t, anchor_t):
    snap = {"latestQuote": {"bp": 100.0, "ap": 100.04, "bs": 3, "as": 5, "t": quote_t},
            "latestTrade": {"p": 100.01, "t": quote_t},
            "prevDailyBar": {"c": 99.0, "v": 1000, "t": anchor_t},
            "dailyBar": {"o": 99.5, "h": 101.0, "l": 99.0, "c": 100.0, "v": 5000,
                         "vw": 100.02, "t": "2026-09-01T04:00:00Z"},
            "minuteBar": {"v": 20, "c": 100.0, "t": "2026-09-01T13:44:00Z"}}
    return compose(subject="SYNTH", snapshot=snap, scheduled_time=AT, capture_start=AT,
                   complete_time=AT, universe_version="PULSE010R").seal()


def scenario(label, quote_t, anchor_t):
    p = build(quote_t, anchor_t)
    fields = {n: {"q": p["features"][n]["q"], "v": p["features"][n]["v"],
                  "note": (p["features"][n].get("note") or "")[:150],
                  "declared_inputs": list(D.DEPENDENCIES.get(n, {}).get("inputs", []))}
             for n in WATCHED}
    return {"label": label, "quote_as_of": quote_t, "anchor_as_of": anchor_t, "fields": fields}


def run(phase):
    rec = {"phase": phase, "composer": COMPOSER_VERSION, "scenarios": {
        "fresh_quote_stale_anchor": scenario("fresh quote, stale anchor", FRESH_Q, STALE_A),
        "stale_quote_fresh_anchor": scenario("stale quote, fresh anchor", STALE_Q, FRESH_A),
        "stale_quote_stale_anchor": scenario("stale quote, stale anchor", STALE_Q, STALE_A),
        "both_fresh": scenario("both fresh", FRESH_Q, FRESH_A)}}
    doc = {}
    if os.path.exists(OUT):
        doc = json.load(open(OUT))
    doc["kind"] = "pulse010_repair_before_after"
    doc["question"] = ("does a stale prior_close reach fields that do not declare it, and does a "
                       "stale quote reach fields that do not declare the mid?")
    doc[phase] = rec
    if "before" in doc and "after" in doc:
        diffs = {}
        for sc in doc["before"]["scenarios"]:
            b = doc["before"]["scenarios"][sc]["fields"]
            a = doc["after"]["scenarios"][sc]["fields"]
            d = {n: {"before_q": b[n]["q"], "before_v": b[n]["v"],
                     "after_q": a[n]["q"], "after_v": a[n]["v"]}
                 for n in b if b[n]["q"] != a[n]["q"] or b[n]["v"] != a[n]["v"]}
            diffs[sc] = d
        doc["field_level_differences_before_vs_after"] = diffs
        doc["behaviour_changed"] = any(diffs.values())
    json.dump(doc, open(OUT, "w"), indent=1)

    print("phase=%s composer=%s" % (phase, COMPOSER_VERSION))
    for key, sc in rec["scenarios"].items():
        f = sc["fields"]
        print("  %-26s anchor-dependent: %-42s quote-only-dependent: %s"
              % (key, ",".join("%s=%s" % (n, f[n]["q"]) for n in ANCHOR_ONLY),
                 ",".join("%s=%s" % (n, f[n]["q"]) for n in QUOTE_ONLY)))
    return rec


if __name__ == "__main__":
    run(sys.argv[1])
    print("wrote", OUT)
