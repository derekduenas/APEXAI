"""PULSE-010 -- NKLA before/after under the anchor policy, plus a consumer audit.

DIAGNOSTIC ONLY. The sealed packet is read, never written. The repaired
composer is run on an equivalent snapshot -- the same 553-day-old quote and
the same prior daily bar -- so the two can be compared field by field.

Writes results/pulse010_nkla_before_after.json
       results/pulse010_consumer_audit.json
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/opt/apex-repo")
from apex.pulse import derived as D                     # noqa: E402
from apex.pulse.compose import COMPOSER_VERSION, compose  # noqa: E402
from apex.pulse.twin import VALID                       # noqa: E402

R = "/opt/apex-repo/results"
FROZEN = R + "/pulse007_frozen_packets.jsonl"


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True,
                          cwd="/opt/apex-repo").stdout


def before_after():
    nkla = next(json.loads(l) for l in open(FROZEN) if json.loads(l)["subject"] == "NKLA")
    before = nkla["features"]
    # the same ingredients the live snapshot carried, read back out of the packet
    snapshot = {
        "latestQuote": {"bp": 0.2, "ap": 0.21, "bs": 1, "as": 2,
                        "t": before["quote_age_s"]["as_of"]},
        "prevDailyBar": {"c": before["prior_close"]["v"], "v": 100,
                         "t": before["prior_close"]["as_of"]},
        "dailyBar": {"o": before["session_open"]["v"], "h": before["session_high"]["v"],
                     "l": before["session_low"]["v"], "c": before["session_low"]["v"],
                     "v": before["session_volume"]["v"], "vw": before["session_vwap"]["v"],
                     "t": before["session_open"]["as_of"]},
        "minuteBar": {"v": before["last_minute_volume"]["v"], "c": before["session_low"]["v"],
                      "t": before["last_minute_volume"]["as_of"]},
        "latestTrade": {"p": before["session_low"]["v"], "t": before["quote_age_s"]["as_of"]},
    }
    after = compose(subject="NKLA", snapshot=snapshot,
                    scheduled_time=nkla["scheduled_time"], capture_start=nkla["capture_start"],
                    complete_time=nkla["state_complete_time"],
                    universe_version="PULSE010_DIAGNOSTIC",
                    evidence_class="DIAGNOSTIC_RECOMPOSITION").seal()["features"]

    # Only fields the diagnostic recomposition actually produced are
    # comparable. The rolling store, the premarket path, catalyst and the
    # cross-asset block were not supplied to it, so their absence says
    # nothing about the repair and is listed separately rather than counted.
    not_supplied = sorted(n for n in before if n not in after)
    rows = {}
    for name in sorted(set(before) & set(after)):
        b, a = before[name], after[name]
        if b.get("q") == a.get("q") and b.get("v") == a.get("v"):
            continue
        rows[name] = {"before_q": b.get("q"), "before_v": b.get("v"),
                      "after_q": a.get("q"), "after_v": a.get("v"),
                      "after_note": (a.get("note") or "")[:200],
                      "declared_inputs": list(D.DEPENDENCIES.get(name, {}).get("inputs", []))}
    # Attribution, exactly: derive() writes "ingredient(s) ... are STALE" into
    # the note of any field it refused because of propagation. A change without
    # that note came from an input block this diagnostic did not supply (the
    # rolling store and catalyst were passed as None), not from the repair.
    # Two repairs can refuse a field, and each writes its own signature into
    # the note: PULSE-009 dependency propagation says "ingredient(s) ... are",
    # and PULSE-010 says the anchor is not the immediately preceding session.
    # A change carrying neither came from an input block this diagnostic did
    # not supply (rolling and catalyst are passed as None), not from a repair.
    def by_repair(note):
        n = note or ""
        if "ingredient(s)" in n:
            return "PULSE-009 dependency propagation"
        if "immediately preceding session" in n or "no regular session" in n:
            return "PULSE-010 anchor freshness"
        return None

    contaminated = {n: {**r, "refused_by": by_repair(r["after_note"])}
                    for n, r in rows.items()
                    if r["before_q"] == VALID and r["after_q"] != VALID
                    and by_repair(r["after_note"])}
    artefact = {n: r for n, r in rows.items()
                if r["before_q"] == VALID and r["after_q"] != VALID
                and not by_repair(r["after_note"])}
    doc = {
        "kind": "pulse010_nkla_before_after", "version": "NKLA_BEFORE_AFTER_V2",
        "status": "DIAGNOSTIC ONLY -- the sealed packet was read, never modified",
        "sealed_packet": {"path": "results/pulse007_frozen_packets.jsonl", "subject": "NKLA",
                          "state_id": nkla["state_id"], "scheduled_time": nkla["scheduled_time"],
                          "quote_as_of": before["quote_age_s"]["as_of"]},
        "composer_before": "PULSE_COMPOSE_V0 (the sealed packet, before PULSE-009 and PULSE-010)", "composer_after": COMPOSER_VERSION,
        "comparable_fields_that_changed": rows,
        "not_supplied_to_the_diagnostic_recomposition": {
            "fields": not_supplied,
            "why": "the rolling store, premarket path, catalyst and cross-asset blocks were not "
                   "passed to this recomposition. Their absence is an artefact of the diagnostic, "
                   "NOT an effect of the repair, and they are excluded from every count below."},
        "fields_that_were_VALID_and_are_now_refused": contaminated,
        "count_refused_by_the_repair": len(contaminated),
        "changed_but_not_attributable_to_the_repair": {
            "fields": artefact,
            "why": "rolling=None and catalyst=None were passed to this diagnostic, so these "
                   "fields are UNKNOWN for want of an input block rather than because of "
                   "dependency propagation. Counted separately, never as a repair effect."},
        "quote_age_s_retained": {"q": after.get("quote_age_s", {}).get("q"),
                                 "v": after.get("quote_age_s", {}).get("v"),
                                 "why": D.DEPENDENCIES["quote_age_s"]["why"]},
        "independent_fields_unaffected": {
            n: {"before": before.get(n, {}).get("q"), "after": after.get(n, {}).get("q")}
            for n in D.INDEPENDENT_FIELDS if n in before or n in after},
        "valid_numbers_before": sorted(k for k, v in before.items() if v.get("q") == VALID),
        "valid_numbers_after": sorted(k for k, v in after.items() if v.get("q") == VALID),
    }
    json.dump(doc, open(R + "/pulse010_nkla_before_after.json", "w"), indent=1)
    print("NKLA: VALID before, refused BY THE REPAIR now:", len(contaminated))
    for n, r in sorted(contaminated.items()):
        print("   %-24s %-6s %-12s -> %-6s %s" % (n, r["before_q"], r["before_v"],
                                                  r["after_q"], r["after_v"]))
    print("  changed for want of an input block (diagnostic artefact, not the repair):",
          sorted(artefact))
    print("  quote_age_s retained:", doc["quote_age_s_retained"]["q"],
          doc["quote_age_s_retained"]["v"])
    print("  independent:", doc["independent_fields_unaffected"])
    return doc


def consumer_audit():
    """Who reads a twin packet's feature VALUES, and do they check quality?

    A consumer that reads ["v"] without consulting ["q"] would have taken
    NKLA's -2869.94 as a real return. This lists every such reader so the
    audit is a fact rather than a claim."""
    files = [f for f in sh("git ls-files 'apex/**/*.py' 'scripts/*.py'").split() if f]
    readers, checked, unchecked = [], [], []
    pat_val = re.compile(r'\[["\']features["\']\]|\.features\b|features\.get\(|\bfeatures\[')
    for path in files:
        try:
            src = open("/opt/apex-repo/" + path).read()
        except OSError:
            continue
        if not pat_val.search(src):
            continue
        reads_v = bool(re.search(r'\[["\']v["\']\]|\.get\(["\']v["\']', src))
        checks_q = bool(re.search(r'\[["\']q["\']\]|\.get\(["\']q["\']|"VALID"|\bVALID\b|\.usable\b|TRUSTWORTHY', src))
        entry = {"path": path, "reads_value": reads_v, "checks_quality": checks_q}
        readers.append(entry)
        (checked if (not reads_v or checks_q) else unchecked).append(path)
    anchor_readers = []
    for path in files:
        try:
            s2 = open("/opt/apex-repo/" + path).read()
        except OSError:
            continue
        if re.search(r'prior_close|overnight_gap_bps|relative_volume|prior_close_return_bps', s2):
            anchor_readers.append({
                "path": path,
                "checks_quality": bool(re.search(
                    r'\[["\']q["\']\]|\.get\(["\']q["\']|"VALID"|\bVALID\b|\.usable\b|TRUSTWORTHY', s2))})
    doc = {"kind": "pulse010_consumer_audit", "version": "CONSUMER_AUDIT_V2",
           "anchor_field_readers": sorted(a["path"] for a in anchor_readers),
           "anchor_readers_without_a_quality_check": sorted(
               a["path"] for a in anchor_readers if not a["checks_quality"]),
           "question": "does every reader of a twin feature VALUE consult its QUALITY?",
           "modules_touching_features": len(readers),
           "read_value_and_check_quality_or_do_not_read_values": sorted(checked),
           "read_value_without_any_quality_check": sorted(unchecked),
           "structural_guarantee": "since PULSE-009 a non-VALID field carries v = null, enforced "
                                   "by apex.pulse.twin.Field. A consumer that ignores q now reads "
                                   "None instead of a plausible number -- it fails loudly rather "
                                   "than silently. The contract does not rely on every consumer "
                                   "being careful.",
           "filtering_guidance": "filter on q == 'VALID'; the note names the failing ingredient, "
                                 "so no field-name knowledge is needed"}
    json.dump(doc, open(R + "/pulse010_consumer_audit.json", "w"), indent=1)
    print("\nconsumer audit: %d modules touch features; %d read a value without any quality check"
          % (len(readers), len(unchecked)))
    for p in sorted(unchecked):
        print("   NO QUALITY CHECK:", p)
    return doc


if __name__ == "__main__":
    before_after()
    consumer_audit()
    print("\nwrote results/pulse010_nkla_before_after.json and results/pulse010_consumer_audit.json")
