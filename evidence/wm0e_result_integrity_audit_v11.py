"""WM-0E RESULT-INTEGRITY CLOSURE V1.1 -- read-only audit of the historical court
through the required-check REGISTRY (courts.result_audit).

Usage:
  python evidence/wm0e_result_integrity_audit_v11.py --trusted-root-v1 <sha256> [--trusted-root-v11 <sha256>]

Exit status: 0 PASS, 2 FAIL, 3 BLOCKED. The diagnostic report is written in
every case to evidence/result_integrity_v1/POST_HOC_AUDIT_SNAPSHOT_V1_1.json.

The trusted V1 root must come from somewhere the payload could not have
written -- for COURT-FINAL-f6ba5c856014 that is the RESULT_COMMITMENT_V1 root
recorded in POST_HOC_AUDIT_SNAPSHOT_V1.json at commit 9d1fca897 (2026-09-06),
the first result commitment ever computed for this court. It is a POST-HOC
anchor: it binds the artifacts from 2026-09-06 onward and says nothing about
the interval between the court's sealing (2026-09-05T20:16Z) and that commit.

NOT A STATISTICAL REPRODUCTION: no world, no forecast, no bootstrap is recomputed.
"""
import argparse
import json
import os
import sys
import time

ROOT = "/opt/apex-research/world-model-shadow"
sys.path.insert(0, ROOT)
from courts import result_audit as RA                     # noqa: E402

COURT = ROOT + "/evidence/final_court_v1"
OUT = ROOT + "/evidence/result_integrity_v1/POST_HOC_AUDIT_SNAPSHOT_V1_1.json"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--trusted-root-v1", default=None)
    ap.add_argument("--trusted-root-v11", default=None)
    ap.add_argument("--require", default=None, help="explicit commitment contract, e.g. V1,V1.1 (default: the versions whose trusted root is supplied)")
    ap.add_argument("--court", default=COURT)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    t0 = time.time()
    versions = tuple(v.strip() for v in a.require.split(",") if v.strip()) if a.require else None
    res = RA.run_audit(a.court, ROOT, trusted_root_v1=a.trusted_root_v1, trusted_root_v11=a.trusted_root_v11, commitment_versions=versions)
    res["LABEL"] = ("POST_HOC_AUDIT_SNAPSHOT -- created AFTER outcomes (%s). NOT a pre-outcome seal. The V1.1 commitment root below "
                    "is a NEW post-hoc anchor computed by this run; the V1 root it was verified against was anchored at commit "
                    "9d1fca897 on 2026-09-06. Neither establishes integrity during the earlier unanchored interval."
                    % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    res["elapsed_s"] = round(time.time() - t0, 1)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(res, open(a.out, "w"), indent=1, default=str)
    for cid, _ in RA.REQUIRED_CHECKS:
        c = res["checks"].get(cid, {"status": "BLOCKED"})
        ev = c.get("evidence", {})
        brief = ev.get("reason") or {k: v for k, v in ev.items() if isinstance(v, (bool, int, str)) and k not in ("recount",)}
        print("%-32s %-7s %s" % (cid, c["status"], str(brief)[:150]))
    rc = res.get("checks", {}).get("RECOUNT_MATCHES_STORED", {}).get("evidence", {}).get("recount", {})
    for k, v in rc.items():
        print("   %s det %2d dir %2d %s idx %s" % (k, v["detections"], v["direction"], v["verdict"], v["detected_indices"] if len(v["detected_indices"]) < 12 else "%d indices" % len(v["detected_indices"])))
    com = res.get("commitment", {})
    print("V1 root  (files):", com.get("v1", {}).get("root"))
    print("V1.1 root (files):", com.get("v11", {}).get("root"))
    print("OVERALL:", res["overall"], "| exit", res["exit_code"], "| statistical recomputation: NOT_PERFORMED | wrote", a.out)
    return res["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
