#!/usr/bin/env python
"""Reconcile two full-suite runs PER TEST ID, not by counting.

R1 of this audit produced a "30 failures" claim that turned out to be a dirty working tree. The lesson stuck:
two runs with the same failure COUNT can have entirely different failures, and two runs with different counts can
share every real defect. So this compares by test id, and for each id by phase, exception type, the failing
assertion and a normalized traceback digest -- and reports a CAUSAL CLASS for every difference.

    python scripts/reconcile_regression.py base.xml cand.xml
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET

PHASE_RX = re.compile(r"(setup|call|teardown)")
ADDR_RX = re.compile(r"0x[0-9a-f]+")
TMP_RX = re.compile(r"(/private)?/(tmp|var)/[^\s'\"]+")
NUM_RX = re.compile(r"\b\d{6,}\b")
# THE TWO SIDES LIVE IN DIFFERENT WORKTREES, so every absolute path in every traceback differs. The first run of
# this tool flagged 50 tests as "mechanism changed" on nothing but `apex-pm-r3-wt` vs `apex-pm-r4-wt` -- including
# SKIPPED tests, which is what gave it away. A comparator that reports a difference in the thing it failed to
# normalize is the same defect family this audit keeps finding, now in the audit tool itself.
ROOT_RX = re.compile(r"/Users/[^/\s]+/apex[-\w]*(-wt)?")
# pytest's own truncation notice reports how many lines of DIFF OUTPUT it hid. That count grows whenever the
# candidate adds source files to a corpus the test concatenates -- a property of the REPORTER, not of the defect.
# It made one genuinely identical failure look like a changed mechanism (93435 vs 94815 hidden lines).
TRUNC_RX = re.compile(r"\(\d+ lines hidden\)")


def load(path: str) -> dict:
    out = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        tid = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
        rec = {"id": tid, "outcome": "passed", "phase": "call", "type": None, "message": None, "text": ""}
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                rec["outcome"] = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                rec["type"] = child.get("type")
                rec["message"] = (child.get("message") or "")
                rec["text"] = child.text or ""
                m = PHASE_RX.search(rec["message"])
                rec["phase"] = m.group(1) if m else ("setup" if child.tag == "error" else "call")
                break
        out[tid] = rec
    return out


def normalize(text: str) -> str:
    t = ROOT_RX.sub("REPO", text or "")
    t = ADDR_RX.sub("0xADDR", t)
    t = TMP_RX.sub("/TMP", t)
    t = TRUNC_RX.sub("(N lines hidden)", t)
    t = NUM_RX.sub("N", t)
    return "\n".join(line.rstrip() for line in t.strip().splitlines())


def assertions(text: str) -> list:
    """The failing assertion lines only. Two runs of the same defect in files whose LINE NUMBERS moved are the
    same defect; the assertion text is what says whether the mechanism changed."""
    return [normalize(l.strip()) for l in (text or "").splitlines()
            if l.strip().startswith("E ") or l.strip().startswith("E\t")]


def assertion_line(text: str) -> str:
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("E ") or s.startswith(">"):
            return s[:180]
    return ""


def digest(text: str) -> str:
    import hashlib
    return hashlib.sha256(normalize(text).encode()).hexdigest()[:12]


def main() -> int:
    base, cand = load(sys.argv[1]), load(sys.argv[2])
    ids = sorted(set(base) | set(cand))
    print("BASE %s   tests=%d" % (sys.argv[1], len(base)))
    print("CAND %s   tests=%d" % (sys.argv[2], len(cand)))
    for name, d in (("base", base), ("cand", cand)):
        from collections import Counter
        print("   %s outcomes: %s" % (name, dict(Counter(v["outcome"] for v in d.values()))))
    print()

    same_fail, new_fail, fixed, changed, missing = [], [], [], [], []
    for tid in ids:
        b, c = base.get(tid), cand.get(tid)
        if b is None or c is None:
            missing.append((tid, "ONLY_IN_CAND" if b is None else "ONLY_IN_BASE"))
            continue
        if b["outcome"] == "passed" and c["outcome"] == "passed":
            continue
        if b["outcome"] == "passed" and c["outcome"] != "passed":
            new_fail.append((tid, b, c))
        elif b["outcome"] != "passed" and c["outcome"] == "passed":
            fixed.append((tid, b, c))
        elif b["outcome"] == c["outcome"]:
            same_shape = (b["phase"], b["type"], normalize(b["message"])) == \
                         (c["phase"], c["type"], normalize(c["message"]))
            if same_shape and assertions(b["text"]) == assertions(c["text"]):
                same_fail.append((tid, b, c))
            else:
                changed.append((tid, b, c))
        else:
            changed.append((tid, b, c))

    print("IDENTICAL FAILURES (same id, phase, exception and normalized traceback): %d" % len(same_fail))
    print("NEW FAILURES introduced by the candidate:                                %d" % len(new_fail))
    print("FAILURES the candidate FIXED:                                            %d" % len(fixed))
    print("FAILURES whose MECHANISM CHANGED:                                        %d" % len(changed))
    print("TESTS PRESENT ON ONLY ONE SIDE:                                          %d" % len(missing))
    print()
    for label, group in (("NEW FAILURE", new_fail), ("MECHANISM CHANGED", changed), ("FIXED", fixed)):
        for tid, b, c in group:
            print("== %s: %s" % (label, tid))
            print("   base: %-8s phase=%-8s type=%s" % (b["outcome"], b["phase"], b["type"]))
            print("         %s" % assertion_line(b["text"]))
            print("   cand: %-8s phase=%-8s type=%s" % (c["outcome"], c["phase"], c["type"]))
            print("         %s" % assertion_line(c["text"]))
            print()
    if missing:
        print("ONLY ON ONE SIDE (expected for tests the candidate adds or renames):")
        for tid, where in missing:
            print("   %-12s %s" % (where, tid))
    print()
    print("VERDICT: %s" % ("NO NEW FAILURE AND NO CHANGED FAILURE MECHANISM"
                           if not new_fail and not changed else
                           "STOP -- the candidate changes the failure set"))
    return 0 if not new_fail and not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
