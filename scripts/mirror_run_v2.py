"""MIRROR_RUN_V2 -- the live/replay mirror over FIXED packets, fail-closed.

WHY V2 EXISTS. scripts/mirror_run.py (V0) had three properties that could
turn an unfinished run into a green one, and one that made a run
unrepeatable:

  1. a reconstruction that raised was caught, printed and `continue`d, so
     the failed subject simply vanished from the result set;
  2. the overall line was `MIRROR_CONSISTENT if not bad` over whatever
     survived -- with every subject skipped, zero results printed
     MIRROR_CONSISTENT;
  3. a comparison in which history reconstructed NOTHING (every field
     LIVE_ONLY / NOT_AVAILABLE) raised no violation and therefore counted
     as consistent. On 2026-09-01 that is exactly what NKLA did;
  4. `pick()` chose `by[subject][-1]` from a ledger that keeps growing, so
     the same command compared different packets on different days, and
     the same packet could satisfy two subject classes at once.

V2 takes a FROZEN manifest of packets, requires every expected comparison to
produce a result, and reports three independent statuses. Nothing is
inferred from what happens to have survived.

  MIRROR_COVERAGE   every expected subject class produced a comparison AND
                    that comparison actually compared fields on BOTH sides.
                    Zero comparisons, a missing class, a reconstruction
                    failure or an all-LIVE_ONLY result is INCOMPLETE.
  ANCHOR_STATUS     the anchor fields alone (prior_close and the three
                    features derived from the anchors) under their ORIGINAL
                    declarations.
  MIRROR_UNDER_ORIGINAL_DECLARATIONS
                    every compared field under the ORIGINAL parity matrix
                    and the ORIGINAL tolerances. No declaration is relaxed
                    here; a proposed change is written as a PROPOSAL and
                    does not affect this status.

Exit: 0 only when coverage is COMPLETE and the full mirror passes; 2 on
FAIL; 3 on BLOCKED or INCOMPLETE coverage.

decision_power: NONE_STATE. This is a measurement, not an admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Credentials are read from the operator's secret files into this process
# only, and never printed or written to an artifact.
for _v, _f in (("APCA_API_KEY_ID", "ALPACA_API_KEY_ID"),
               ("APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY")):
    if not os.environ.get(_v):
        _p = "/home/apex/.apex-secrets/" + _f
        if os.path.exists(_p):
            os.environ[_v] = open(_p).read().strip()

from apex.pulse import anchors                              # noqa: E402
from apex.pulse.historical import FACTORY_VERSION, twin_as_of   # noqa: E402
from apex.pulse.mirror import CORE_FIELDS, MIRROR_VERSION, mirror  # noqa: E402
from apex.pulse.parity import MATRIX                        # noqa: E402

RUNNER_VERSION = "MIRROR_RUN_V2"
ANCHOR_FIELDS = ("prior_close", "prior_close_return_bps",
                 "cash_open_return_bps", "overnight_gap_bps")
COMPARED = ("SEMANTICALLY_EQUIVALENT", "APPROXIMATE")
PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"
COMPLETE, INCOMPLETE = "COMPLETE", "INCOMPLETE"
EXIT = {PASS: 0, FAIL: 2, BLOCKED: 3}


def load_frozen(manifest_path, packets_path):
    man = json.load(open(manifest_path))
    packets = {}
    for line in open(packets_path):
        if line.strip():
            r = json.loads(line)
            packets[(r["subject"], r["scheduled_time"])] = (r, line)
    expected = []
    for m in man:
        key = (m["subject"], m["scheduled_time"])
        if key not in packets:
            expected.append({**m, "packet": None, "load_error": "packet absent from the frozen file"})
            continue
        r, line = packets[key]
        got = hashlib.sha256(line.encode()).hexdigest()
        err = None
        if m.get("line_sha256") and got != m["line_sha256"]:
            err = "frozen packet bytes changed: manifest %s != file %s" % (m["line_sha256"][:12], got[:12])
        if m.get("state_id") and r.get("state_id") != m["state_id"]:
            err = "state_id mismatch"
        expected.append({**m, "packet": r, "load_error": err})
    return sorted(expected, key=lambda e: e["subject_class"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--packets", required=True)
    ap.add_argument("--out", required=True, help="versioned destination; refuses to overwrite")
    ap.add_argument("--label", default="PULSE007_POST_REPAIR")
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        print("refusing to overwrite existing evidence:", a.out)
        return EXIT[BLOCKED]
    t0 = time.time()
    expected = load_frozen(a.manifest, a.packets)

    results, failures = [], []
    for e in expected:
        cls, sym, t = e["subject_class"], e["subject"], e["scheduled_time"]
        if e["load_error"] or e["packet"] is None:
            failures.append({"subject_class": cls, "subject": sym, "scheduled_time": t,
                             "stage": "FROZEN_INPUT", "error": e["load_error"]})
            print("%-16s %-5s INPUT UNUSABLE: %s" % (cls, sym, e["load_error"]))
            continue
        try:
            replay = twin_as_of(sym, t)
        except Exception as ex:                              # noqa: BLE001
            failures.append({"subject_class": cls, "subject": sym, "scheduled_time": t,
                             "stage": "RECONSTRUCTION", "error": "%s: %s" % (type(ex).__name__, ex)})
            print("%-16s %-5s RECONSTRUCTION FAILED %s: %s" % (cls, sym, type(ex).__name__, ex))
            continue
        m = mirror(e["packet"], replay, fields=CORE_FIELDS)
        m["subject_class"] = cls
        m["frozen_state_id"] = e.get("state_id")
        m["original_verdict"] = e.get("original_verdict")
        m["original_violations"] = e.get("original_violations")
        m["replay_anchor_provenance"] = next(
            (n for n in (replay.get("notes") or []) if str(n).startswith("anchor_provenance:")), None)
        counts = m["classification_counts"]
        m["fields_compared_on_both_sides"] = sum(counts.get(k, 0) for k in COMPARED)
        m["anchor_rows"] = {r["field"]: {"live": r["live_value"], "replay": r["replay_value"],
                                         "declared": r["declared"], "observed": r["observed"],
                                         "difference": r.get("difference"),
                                         "relative_difference": r.get("relative_difference")}
                            for r in m["rows"] if r["field"] in ANCHOR_FIELDS}
        m["anchor_violations"] = [v for v in m["declaration_violations"]
                                  if v.split(":")[0] in ANCHOR_FIELDS]
        results.append(m)
        print("%-16s %-5s compared_both_sides=%-2d %s" % (cls, sym, m["fields_compared_on_both_sides"], m["verdict"]))
        for f, r in sorted(m["anchor_rows"].items()):
            print("     %-24s live=%-10s replay=%-10s %s" % (f, r["live"], r["replay"], r["observed"]))
        for v in m["declaration_violations"]:
            print("     VIOLATION %s" % v)

    # ---- coverage: every expected class, and every one actually comparing
    empty = [m["subject_class"] for m in results if m["fields_compared_on_both_sides"] == 0]
    coverage = COMPLETE if (len(results) == len(expected) and not failures
                            and results and not empty) else INCOMPLETE
    cov_reasons = []
    if failures:
        cov_reasons.append("%d comparison(s) never produced a result" % len(failures))
    if empty:
        cov_reasons.append("%s reconstructed nothing comparable -- an all-LIVE_ONLY "
                           "comparison is a coverage hole, not a consistency result" % empty)
    if not results:
        cov_reasons.append("zero comparisons executed")
    if len(results) + len(failures) != len(expected):
        cov_reasons.append("expected %d comparisons, accounted for %d" % (len(expected), len(results) + len(failures)))

    anchor_viol = {m["subject_class"]: m["anchor_violations"] for m in results if m["anchor_violations"]}
    all_viol = {m["subject_class"]: m["declaration_violations"] for m in results if m["declaration_violations"]}
    anchor_status = (BLOCKED if coverage == INCOMPLETE else (FAIL if anchor_viol else PASS))
    mirror_status = (BLOCKED if coverage == INCOMPLETE else (FAIL if all_viol else PASS))

    doc = {"kind": "pulse_mirror_run", "runner": RUNNER_VERSION, "mirror": MIRROR_VERSION,
           "factory": FACTORY_VERSION, "anchor_contract": anchors.ANCHOR_CONTRACT,
           "label": a.label, "utc": datetime.now(timezone.utc).isoformat(),
           "frozen_manifest": a.manifest, "frozen_packets": a.packets,
           "manifest_sha256": hashlib.sha256(open(a.manifest, "rb").read()).hexdigest(),
           "packets_sha256": hashlib.sha256(open(a.packets, "rb").read()).hexdigest(),
           "expected_comparisons": len(expected), "executed_comparisons": len(results),
           "reconstruction_failures": failures,
           "empty_comparisons": empty,
           "MIRROR_COVERAGE": coverage, "coverage_reasons": cov_reasons,
           "ANCHOR_STATUS": anchor_status, "anchor_violations": anchor_viol,
           "MIRROR_UNDER_ORIGINAL_DECLARATIONS": mirror_status, "declaration_violations": all_viol,
           "declarations_used": {f: MATRIX.get(f, {}).get("status", "UNDECLARED") for f in CORE_FIELDS},
           "law": "coverage, anchor correctness and full mirror consistency are three "
                  "different questions; no declaration was changed by this run",
           "decision_power": "NONE_STATE",
           "results": results, "elapsed_s": round(time.time() - t0, 1)}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "w") as fh:
        json.dump(doc, fh, indent=1, default=str)

    print("\nMIRROR_COVERAGE:                     %s %s" % (coverage, cov_reasons or ""))
    print("ANCHOR_STATUS:                       %s %s" % (anchor_status, list(anchor_viol) or ""))
    print("MIRROR_UNDER_ORIGINAL_DECLARATIONS:  %s %s" % (mirror_status, list(all_viol) or ""))
    print("wrote", a.out)
    overall = BLOCKED if coverage == INCOMPLETE else mirror_status
    return EXIT[overall]


if __name__ == "__main__":
    sys.exit(main())
