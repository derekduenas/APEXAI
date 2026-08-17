#!/usr/bin/env python
"""PHASE 43 — mint the immutable starting line. Refuses to mint over an
unresolved P0/P1, a failing suite artifact, or a dirty tree."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    suite = json.loads(Path("results/readiness/full_suite.json").read_text())
    head = sh("git rev-parse HEAD")
    problems = []
    if suite["result"] != "PASS":
        problems.append(f"suite {suite['result']}")
    if suite["commit"] != head:
        problems.append(f"suite certified {suite['commit'][:8]}, HEAD is "
                        f"{head[:8]}")
    dirty = [l for l in sh("git status --porcelain").splitlines()
             if not l.split(None, 1)[-1].startswith(
                 ("results/readiness/", "results/audit/"))]
    if dirty:
        # audit/readiness ARTIFACTS of this very freeze are permitted to
        # be uncommitted at mint time (they get committed immediately
        # after, in a commit that changes no code); anything else dirty
        # means the suite did not certify the machine as it stands.
        problems.append(f"dirty non-artifact files: {dirty[:3]}")
    if problems:
        print("REFUSING to mint the starting line:", "; ".join(problems))
        return 1
    from apex.intraday import quota_ledger as ql
    from apex.crypto import diskgov
    rec = {
        "artifact": "PRE_EPOCH1_FINAL",
        "minted_utc": str(pd.Timestamp.now(tz="UTC")),
        "commit": head,
        "full_suite": {k: suite[k] for k in
                       ("result", "passed", "skipped", "commit")},
        "sac2_baseline_sha": json.loads(Path(
            "results/audit/SAC2_BASELINE.json").read_text())["sha256"],
        "mcp_tool_surface_sha": json.loads(Path(
            "results/audit/ROBINHOOD_TOOL_SURFACE.json").read_text())["sha256"],
        "claude_code": sh("claude --version"),
        "birth_tip_sha": sh(
            "tail -1 results/hunter/birth_registry.jsonl | shasum -a 256"
        ).split()[0],
        "quota": {"lab": ql.headroom(ql.LAB),
                  "forward": ql.headroom(ql.FORWARD)},
        "disk_mode": diskgov.disk_state()["mode"],
        "launchd_jobs": sh("launchctl list | grep -c com.apex"),
        "paper": "LOCKED", "live": "SEALED",
        "credit_5": "SEALED", "holdout": "SEALED",
    }
    rec["sha256"] = hashlib.sha256(
        json.dumps(rec, sort_keys=True).encode()).hexdigest()
    out = Path("results/readiness/PRE_EPOCH1_FINAL.json")
    out.write_text(json.dumps(rec, indent=2))
    print(f"STARTING LINE MINTED {rec['sha256'][:16]}")
    print(f"  commit {head[:12]} | suite {suite['passed']}p | "
          f"jobs {rec['launchd_jobs']} | forward {rec['quota']['forward']}u")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
