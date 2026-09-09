#!/usr/bin/env python3
"""EXP-002 synthetic qualification: five worlds, five arms, no market data.

Records realised outcomes against the DECLARED expectations, and a blocking
verdict. One seeded realisation per world establishes behaviour on that
fixture; it is not a detection-power estimate."""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from apex.world_model.exp002 import controls as CW
from apex.world_model.exp002.registration import FIT_BUDGET, registration_hash
from apex.world_model.exp002.run import tournament


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-sessions", type=int, default=750)
    ap.add_argument("--dev-sessions", type=int, default=250)
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    worlds, fits, blocking_failures = {}, 0, []
    for name in CW.WORLDS:
        w = CW.make_world(name, n_fit_sessions=a.fit_sessions, n_dev_sessions=a.dev_sessions)
        rec = tournament(w["fit"], w["dev"], seed=w["spec"]["seed"], tag=name,
                         bootstrap_resamples=a.resamples)
        fits += rec.get("fit", {}).get("fits_performed", 0)
        realised = {}
        for gname, c in rec.get("comparisons", {}).items():
            realised[tuple(c["pair"])] = c["hac"]["verdict"]
        checks = []
        for pair, expected in CW.EXPECTED.get(name, {}).items():
            got = realised.get(pair)
            blocking = pair in CW.BLOCKING.get(name, [])
            ok = got == expected
            checks.append({"pair": "%s-%s" % pair, "expected": expected, "realised": got,
                           "ok": ok, "blocking": blocking})
            if blocking and not ok:
                blocking_failures.append("%s %s-%s expected %s got %s" % (name, *pair, expected, got))
        # blocking checks must also pass BOTH inferences where a SIGNAL is expected
        for pair in CW.BLOCKING.get(name, []):
            for gname, c in rec.get("comparisons", {}).items():
                if tuple(c["pair"]) == pair and CW.EXPECTED[name].get(pair) == "SIGNAL_DETECTED":
                    if not c["both_pass"]:
                        blocking_failures.append("%s %s-%s SIGNAL not confirmed by both inferences" % (name, *pair))
        worlds[name] = {"role": w["spec"]["role"], "generator": w["generator"],
                        "status": rec.get("status"), "fit": rec.get("fit"),
                        "n_dev": rec.get("n_dev"), "admission": rec.get("admission"),
                        "checks": checks, "null_control": rec.get("null_control"),
                        "calibration": rec.get("calibration"),
                        "comparisons": {k: {"pair": v["pair"], "t": v["hac"]["t"], "mean": v["hac"]["mean"],
                                            "hac": v["hac"]["verdict"], "boot5_p": v["bootstrap"]["5"]["p_one_sided"],
                                            "boot1_p": v["bootstrap"]["1"]["p_one_sided"],
                                            "boot10_p": v["bootstrap"]["10"]["p_one_sided"],
                                            "both_pass": v["both_pass"],
                                            "inference_disagreement": v["inference_disagreement"],
                                            "sensitivity_disagreement": v["sensitivity_disagreement"]}
                                        for k, v in rec.get("comparisons", {}).items()},
                        "elapsed_s": rec.get("elapsed_s")}
        print("%-16s %-36s fits=%d" % (name, rec.get("status"), rec.get("fit", {}).get("fits_performed", 0)), file=sys.stderr)
    out = {"qualification": "EXP002_SYNTHETIC_QUALIFICATION", "registration_hash": registration_hash(),
           "market_data_fits": 0, "synthetic_control_fits": fits,
           "budget": FIT_BUDGET, "within_budget": fits <= FIT_BUDGET["synthetic_control_fits"],
           "blocking_failures": blocking_failures, "QUALIFIED": not blocking_failures and fits <= FIT_BUDGET["synthetic_control_fits"],
           "worlds": worlds, "elapsed_s": round(time.time() - t0, 1),
           "peak_rss_self_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
           "note": "one seeded realisation per world establishes behaviour on that fixture, not general detection power"}
    Path(a.out).write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: out[k] for k in ("QUALIFIED", "blocking_failures", "synthetic_control_fits", "elapsed_s")}, indent=1))
    return 0 if out["QUALIFIED"] else 3


if __name__ == "__main__":
    sys.exit(main())
