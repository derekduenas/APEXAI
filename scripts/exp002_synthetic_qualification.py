#!/usr/bin/env python3
"""EXP-002 synthetic qualification, revision 2: six worlds, five arms, no market
data. Attributable: the process records the identity of every apex.* module it
imported, the registration hash, its environment, every generator parameter and
seed, and re-checks source identity at completion. One seeded realisation per
world establishes behaviour on that fixture, not general detection power."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

from apex.world_model.exp002 import controls as CW
from apex.world_model.exp002.registration import (FIT_BUDGET, QUALIFICATION_REVISION,
                                                  QUALIFICATION_REVISION_NOTE, BOOT_P_ESTIMATOR,
                                                  registration_hash)
from apex.world_model.exp002.run import tournament


def _sha(p: str) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def capture_source_identity() -> dict:
    """Every apex.* module currently imported, by file path and sha256, plus the
    git identity of the working tree they came from. Captured BY THE PROCESS."""
    mods = {}
    for name, m in sorted(sys.modules.items()):
        f = getattr(m, "__file__", None)
        if name.startswith("apex") and f and f.endswith(".py"):
            mods[name] = {"file": f, "sha256": _sha(f)}
    cwd = os.getcwd()
    def git(*a):
        r = subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else "unavailable: %s" % r.stderr.strip()[:80]
    return {"modules": mods, "n_modules": len(mods),
            "git_head": git("rev-parse", "HEAD"),
            "git_dirty_files": git("status", "--porcelain").count("\n") + (1 if git("status", "--porcelain") else 0),
            "cwd": cwd, "PYTHONPATH": os.environ.get("PYTHONPATH"),
            "python": sys.version.split()[0], "executable": sys.executable,
            "platform": platform.platform(),
            "numpy": __import__("numpy").__version__,
            "registration_hash": registration_hash(),
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-sessions", type=int, default=750)
    ap.add_argument("--dev-sessions", type=int, default=250)
    ap.add_argument("--resamples", type=int, default=10000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    t0 = time.time()
    identity_start = capture_source_identity()
    worlds, fits, blocking_failures, diagnostics = {}, 0, [], {}
    for name in CW.WORLDS:
        w = CW.make_world(name, n_fit_sessions=a.fit_sessions, n_dev_sessions=a.dev_sessions)
        rec = tournament(w["fit"], w["dev"], seed=w["spec"]["seed"], tag=name,
                         bootstrap_resamples=a.resamples)
        fits += rec.get("fit", {}).get("fits_performed", 0)
        realised = {tuple(c["pair"]): c for c in rec.get("comparisons", {}).values()}
        checks = []
        for pair, expected in CW.EXPECTED.get(name, {}).items():
            c = realised.get(pair)
            got = c["hac"]["verdict"] if c else None
            blocking = pair in CW.BLOCKING.get(name, [])
            ok = got == expected
            both = bool(c and c["both_pass"]) if expected == "SIGNAL_DETECTED" else None
            checks.append({"pair": "%s-%s" % pair, "expected": expected, "realised_hac": got,
                           "both_inferences" : both, "ok": ok, "blocking": blocking})
            if blocking and not ok:
                blocking_failures.append("%s %s-%s expected %s got %s" % (name, *pair, expected, got))
            if blocking and expected == "SIGNAL_DETECTED" and c and not c["both_pass"]:
                blocking_failures.append("%s %s-%s SIGNAL not confirmed by both inferences" % (name, *pair))
        for pair in CW.DIAGNOSTIC_ONLY.get(name, []):
            c = realised.get(pair)
            if c:
                diagnostics["%s %s-%s" % (name, *pair)] = {
                    "hac_t": c["hac"]["t"], "hac": c["hac"]["verdict"],
                    "boot5": {k: c["bootstrap"]["5"][k] for k in ("exceedances", "resamples", "p_one_sided", "p_estimator", "pass")},
                    "inference_disagreement": c["inference_disagreement"], "authority": "NONE (diagnostic)"}
        worlds[name] = {
            "role": w["spec"]["role"], "generator": w["generator"], "seed": w["spec"]["seed"], "r2": w["spec"]["r2"],
            "status": rec.get("status"), "fit": rec.get("fit"), "n_dev": rec.get("n_dev"), "admission": rec.get("admission"),
            "checks": checks, "null_control": rec.get("null_control"), "calibration": rec.get("calibration"),
            "comparisons": {k: {"pair": v["pair"], "authority": v["promotion_authority"],
                                "hac_t": v["hac"]["t"], "hac_mean": v["hac"]["mean"], "hac": v["hac"]["verdict"],
                                "hac_p_one_sided": v["hac"]["p_one_sided"],
                                "boot5": {kk: v["bootstrap"]["5"][kk] for kk in ("exceedances", "resamples", "p_one_sided", "p_estimator", "pass")},
                                "boot1_p": v["bootstrap"]["1"]["p_one_sided"], "boot10_p": v["bootstrap"]["10"]["p_one_sided"],
                                "both_pass": v["both_pass"], "inference_disagreement": v["inference_disagreement"],
                                "sensitivity_disagreement": v["sensitivity_disagreement"],
                                "holm_adjusted_p": v.get("holm_adjusted_p")}
                            for k, v in rec.get("comparisons", {}).items()},
            "elapsed_s": rec.get("elapsed_s")}
        print("%-16s %-36s fits=%d" % (name, rec.get("status"), rec.get("fit", {}).get("fits_performed", 0)), file=sys.stderr)
    identity_end = capture_source_identity()
    unchanged = all(identity_end["modules"].get(k, {}).get("sha256") == v["sha256"]
                    for k, v in identity_start["modules"].items())
    out = {"qualification": "EXP002_SYNTHETIC_QUALIFICATION", "revision": QUALIFICATION_REVISION,
           "revision_note": QUALIFICATION_REVISION_NOTE,
           "registration_hash": registration_hash(),
           "source_identity_at_start": identity_start,
           "source_identity_unchanged_at_completion": unchanged,
           "source_identity_at_completion_git_head": identity_end["git_head"],
           "bootstrap_p_estimator": BOOT_P_ESTIMATOR,
           "market_data_fits": 0, "synthetic_control_fits": fits, "budget": FIT_BUDGET,
           "within_budget": fits <= FIT_BUDGET["synthetic_control_fits"],
           "blocking_failures": blocking_failures, "diagnostics_no_authority": diagnostics,
           "QUALIFIED": (not blocking_failures) and fits <= FIT_BUDGET["synthetic_control_fits"] and unchanged,
           "worlds": worlds, "elapsed_s": round(time.time() - t0, 1),
           "peak_rss_self_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
           "note": "one seeded realisation per world establishes behaviour on that fixture, not general detection power"}
    outp = Path(a.out)
    outp.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n")
    outp.with_suffix(outp.suffix + ".sha256").write_text(_sha(str(outp)) + "  " + outp.name + "\n")
    print(json.dumps({k: out[k] for k in ("QUALIFIED", "blocking_failures", "synthetic_control_fits",
                                          "source_identity_unchanged_at_completion", "elapsed_s")}, indent=1))
    return 0 if out["QUALIFIED"] else 3


if __name__ == "__main__":
    sys.exit(main())
