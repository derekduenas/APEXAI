#!/usr/bin/env python
"""Record a completed full-suite run as a measured artifact.

    python scripts/record_full_suite.py /tmp/suite_definitive.log

Mission Control's FULL SUITE row reads this file — result, count, age,
and the commit it certified. An absent or stale artifact reads as such;
this script refuses a log that has no final pytest summary line, so a
crashed run can never be recorded as PASS.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd


def main() -> int:
    log = Path(sys.argv[1])
    text = log.read_text()
    m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", text.splitlines()[-1])
    failed = re.search(r"(\d+) failed", text.splitlines()[-1])
    if not m:
        print("no final pytest summary in the log — refusing to record")
        return 1
    commit = subprocess.run(["git", "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    rec = {"result": "FAIL" if failed else "PASS",
           "passed": int(m.group(1)),
           "skipped": int(m.group(2) or 0),
           "failed": int(failed.group(1)) if failed else 0,
           "finished_utc": str(pd.Timestamp.now(tz="UTC")),
           "commit": commit, "log": str(log)}
    out = Path("results/readiness/full_suite.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2))
    print(json.dumps(rec, indent=2))
    return 0 if rec["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
