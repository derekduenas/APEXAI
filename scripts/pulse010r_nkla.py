"""Corrected NKLA diagnostic: attribute EVERY refusal to the ingredient that
actually failed, so a field refused for its stale QUOTE is never presented as
evidence about the anchor. That ambiguity is what made the PULSE-010 return
look self-contradictory."""
import json, sys
sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import derived as D
from apex.pulse.compose import COMPOSER_VERSION, compose
from apex.pulse.twin import VALID

R = "/opt/apex-repo/results"
nkla = next(json.loads(l) for l in open(R + "/pulse007_frozen_packets.jsonl")
            if json.loads(l)["subject"] == "NKLA")
b = nkla["features"]
snapshot = {
    "latestQuote": {"bp": 0.2, "ap": 0.21, "bs": 1, "as": 2, "t": b["quote_age_s"]["as_of"]},
    "prevDailyBar": {"c": b["prior_close"]["v"], "v": 100, "t": b["prior_close"]["as_of"]},
    "dailyBar": {"o": b["session_open"]["v"], "h": b["session_high"]["v"],
                 "l": b["session_low"]["v"], "c": b["session_low"]["v"],
                 "v": b["session_volume"]["v"], "vw": b["session_vwap"]["v"],
                 "t": b["session_open"]["as_of"]},
    "minuteBar": {"v": b["last_minute_volume"]["v"], "c": b["session_low"]["v"],
                  "t": b["last_minute_volume"]["as_of"]},
    "latestTrade": {"p": b["session_low"]["v"], "t": b["quote_age_s"]["as_of"]}}
a = compose(subject="NKLA", snapshot=snapshot, scheduled_time=nkla["scheduled_time"],
            capture_start=nkla["capture_start"], complete_time=nkla["state_complete_time"],
            universe_version="PULSE010R_DIAGNOSTIC",
            evidence_class="DIAGNOSTIC_RECOMPOSITION").seal()["features"]

def culprits(name, note):
    """Which declared ingredients the note actually blames."""
    n = note or ""
    return sorted(k for k in D.DEPENDENCIES.get(name, {}).get("inputs", ()) if "'%s'" % k in n)

rows = {}
for name in sorted(set(b) & set(a)):
    if b[name]["q"] == a[name]["q"] and b[name]["v"] == a[name]["v"]:
        continue
    note = a[name].get("note") or ""
    if "ingredient(s)" in note:
        why, blamed = "PULSE-009 dependency propagation", culprits(name, note)
    elif "immediately preceding session" in note or "no regular session" in note:
        why, blamed = "PULSE-010 anchor freshness (the field IS the anchor)", ["prior_close"]
    else:
        why, blamed = None, []
    rows[name] = {"before_q": b[name]["q"], "before_v": b[name]["v"],
                  "after_q": a[name]["q"], "after_v": a[name]["v"],
                  "declared_inputs": list(D.DEPENDENCIES.get(name, {}).get("inputs", [])),
                  "failing_ingredients": blamed, "refused_by": why,
                  "note": note[:170]}
refused = {n: r for n, r in rows.items()
           if r["before_q"] == VALID and r["after_q"] != VALID and r["refused_by"]}
artefact = {n: r for n, r in rows.items()
            if r["before_q"] == VALID and r["after_q"] != VALID and not r["refused_by"]}
by_anchor = {n: r for n, r in refused.items() if "prior_close" in r["failing_ingredients"]}
by_quote = {n: r for n, r in refused.items() if "mid" in r["failing_ingredients"]
            or n in ("mid",) or "raw:quote" in (r["note"] or "")}
doc = {"kind": "pulse010_repair_nkla_diagnostic", "version": "NKLA_ATTRIBUTED_V3",
       "status": "DIAGNOSTIC ONLY -- the sealed packet was read, never modified",
       "why_this_supersedes_the_pulse010_table":
           "the earlier table listed cash_open_return_bps among the refusals without saying "
           "WHY. NKLA's quote is ALSO 553 days old, so that field was refused for its MID, "
           "not for the anchor. Reading it as anchor contamination is what made the return "
           "look self-contradictory. Every row now names the failing ingredient.",
       "composer_after": COMPOSER_VERSION,
       "refused_with_attribution": refused,
       "refused_because_the_ANCHOR_failed": sorted(by_anchor),
       "refused_because_the_QUOTE_failed": sorted(by_quote),
       "changed_but_not_attributable": sorted(artefact),
       "quote_age_s": {"q": a["quote_age_s"]["q"], "v": a["quote_age_s"]["v"]},
       "current_session_fields": {n: {"before": b.get(n, {}).get("q"), "after": a.get(n, {}).get("q")}
                                  for n in ("session_open", "session_high", "session_low",
                                            "session_vwap", "session_volume",
                                            "last_minute_volume")},
       "note_on_independence":
           "NKLA cannot demonstrate the independence rule, because BOTH its quote and its "
           "anchor are stale. The synthetic fixture in results/pulse010r_before_after.json "
           "(fresh quote, stale anchor) is what actually tests it, and there "
           "cash_open_return_bps, session_range_position and vwap_distance_bps stay VALID."}
json.dump(doc, open(R + "/pulse010r_nkla_attributed.json", "w"), indent=1)
for n, r in sorted(refused.items()):
    print("  %-24s %-6s %-11s -> %-6s | blames %-28s | %s"
          % (n, r["before_q"], r["before_v"], r["after_q"], r["failing_ingredients"], r["refused_by"][:34]))
print("anchor-caused:", sorted(by_anchor), "| quote-caused:", sorted(by_quote))
print("current-session:", doc["current_session_fields"])
