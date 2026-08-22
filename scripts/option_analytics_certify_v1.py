"""APEX_OPTION_ANALYTICS_V1 certification — actually RUNS the
adversarial/property-based validation suite (never self-declares a
pass) and mints a certification record only on a real, clean run. This
is the one thing refusal.py's REFUSE_ANALYTICS_NOT_VALIDATED gate and
expression_engine.py's OPT-002/OPT-003 check trust.

Re-run this any time apex/option_analytics/*.py changes -- the
certification's own source_hash makes a stale certification (minted
before a later code change) automatically untrusted, so a code change
without re-running this script silently re-closes the OPT-002/OPT-003
gate rather than leaving a false pass in effect.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.option_analytics.validation_registry import record_certification

REPO = Path(__file__).resolve().parents[1]

TEST_FILES = (
    "tests/test_option_analytics_bsm.py",
    "tests/test_option_analytics_american.py",
    "tests/test_option_analytics_contracts.py",
    "tests/test_option_analytics_canonical_state.py",
    "tests/test_option_analytics_adversarial.py",
)

SUMMARY_RE = re.compile(r"(\d+) passed(?:, (\d+) failed)?")


def run_suite() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-q", "--tb=short"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600)
    output = proc.stdout + "\n" + proc.stderr
    m = SUMMARY_RE.search(output)
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2)) if (m and m.group(2)) else (0 if proc.returncode == 0 else -1)
    if failed == -1:
        # pytest exited nonzero without a clean "N passed, M failed" summary
        # (e.g. a collection error) -- treat every test as failed rather
        # than silently reporting zero.
        failed = 1
        passed = 0
    return {"returncode": proc.returncode, "passed": passed, "failed": failed,
           "raw_output_tail": output[-4000:]}


def main() -> dict:
    import pandas as pd
    result = run_suite()
    now = pd.Timestamp.now(tz="UTC")
    rec = record_certification(
        test_files=TEST_FILES, test_count=result["passed"] + result["failed"],
        passed_count=result["passed"], failed_count=result["failed"], now=now)
    return {"certification": rec.as_record(), "raw": result}


if __name__ == "__main__":
    out = main()
    print(json.dumps({"certified": out["certification"]["certified"],
                      "passed_count": out["certification"]["passed_count"],
                      "failed_count": out["certification"]["failed_count"],
                      "source_hash": out["certification"]["source_hash"][:16] + "...",
                      "certified_at": out["certification"]["certified_at"]}, indent=2))
    if not out["certification"]["certified"]:
        print("\n--- suite output tail ---\n" + out["raw"]["raw_output_tail"])
        sys.exit(1)
