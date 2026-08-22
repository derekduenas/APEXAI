"""Certification ledger — measured, not declared. OPT-002/OPT-003 stay
refused (see refusal.py's REFUSE_ANALYTICS_NOT_VALIDATED gate) until a
certification record exists showing the adversarial suite was actually
RUN and actually PASSED, on the CURRENT state of this package's source
-- a certification is automatically stale (and the gate re-closes) the
moment any apex/option_analytics/*.py file changes after it was minted,
exactly the same "no retroactive validation" law used by the births
elsewhere in this repo.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.option_analytics import OPTION_ANALYTICS_POWER

LEDGER = Path("results/option_analytics/certification.jsonl")
PACKAGE_DIR = Path(__file__).resolve().parent


class ValidationRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CertificationRecord:
    certified: bool
    test_files: tuple
    test_count: int
    passed_count: int
    failed_count: int
    source_hash: str
    certified_at: str
    decision_power: str = OPTION_ANALYTICS_POWER

    def __post_init__(self):
        if self.certified and (self.failed_count != 0 or self.passed_count != self.test_count
                               or self.passed_count == 0):
            raise ValidationRegistryError(
                "certified=True requires failed_count==0 and passed_count==test_count>0 "
                "-- a certification may never be declared over a partial or failing run")

    def as_record(self) -> dict:
        return {"kind": "option_analytics_certification", **asdict(self)}


def source_hash() -> str:
    """A content hash of every .py file in apex/option_analytics/ --
    used to detect code drift since the last certification."""
    files = sorted(PACKAGE_DIR.glob("*.py"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()


def record_certification(*, test_files: tuple, test_count: int, passed_count: int,
                         failed_count: int, now) -> CertificationRecord:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    certified = (failed_count == 0 and passed_count == test_count and passed_count > 0)
    rec = CertificationRecord(
        certified=certified, test_files=tuple(test_files), test_count=test_count,
        passed_count=passed_count, failed_count=failed_count, source_hash=source_hash(),
        certified_at=str(pd.Timestamp(now)))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _chain_append(LEDGER, rec.as_record())
    return rec


def latest_certification() -> dict | None:
    if not LEDGER.exists():
        return None
    import json
    latest = None
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            latest = json.loads(line)
        except json.JSONDecodeError:
            continue
    return latest


def is_adversarial_suite_certified() -> bool:
    """The one function refusal.py/expression_engine.py actually call.
    False (never a crash, never a guess) if no certification exists, if
    the latest one wasn't a clean pass, or if the package's source has
    changed since it was minted -- code drift silently invalidates a
    stale certification rather than leaving it trusted."""
    latest = latest_certification()
    if latest is None:
        return False
    if not latest.get("certified"):
        return False
    return latest.get("source_hash") == source_hash()
