"""Empty research-program namespaces -- destinations for future
commissioned deep research, not populated with invented content."""
from __future__ import annotations

from pathlib import Path

from apex.research_library import RESEARCH_LIBRARY_POWER

LEDGER = Path("results/research_library/programs.jsonl")

PROGRAM_STATUSES = ("NOT_STARTED", "RESEARCH_INGESTED", "IN_PROGRESS", "COMPLETE")

PROGRAMS = ("APEX_OPTIONS_RESEARCH_V1", "APEX_BTC_PERPS_RESEARCH_V1")


def register_program(name: str, *, now, status: str = "NOT_STARTED") -> dict:
    if status != "NOT_STARTED":
        raise RuntimeError(
            "programs may only be registered as NOT_STARTED -- populating "
            "one with real research is a separate, explicit ingestion act")
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = pd.Timestamp(now)
    entry = {"kind": "research_program", "program": name, "status": status,
             "document_count": 0, "registered_at": str(now),
             "decision_power": RESEARCH_LIBRARY_POWER}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, entry)


def _latest_program_row(name: str) -> dict | None:
    if not LEDGER.exists():
        return None
    import json
    latest = None
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("program") == name:
            latest = d
    return latest


def update_program_status(name: str, *, now, status: str,
                          document_count: int | None = None) -> dict:
    """Append-only: writes a NEW ledger row reflecting the program's
    current status; never rewrites a prior row. A program must already
    be registered before its status can move past NOT_STARTED, and
    document_count -- when supplied -- must never move backwards
    (documents are never un-ingested)."""
    if status not in PROGRAM_STATUSES:
        raise RuntimeError(f"unknown program status {status!r}")
    prior = _latest_program_row(name)
    if prior is None:
        raise RuntimeError(
            f"program {name!r} has never been registered -- call "
            f"register_program() first")
    prior_count = prior.get("document_count", 0)
    new_count = document_count if document_count is not None else prior_count
    if new_count < prior_count:
        raise RuntimeError("document_count may never decrease")
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import pandas as pd
    now = pd.Timestamp(now)
    entry = {"kind": "research_program", "program": name, "status": status,
             "document_count": new_count, "registered_at": prior.get("registered_at"),
             "updated_at": str(now), "decision_power": RESEARCH_LIBRARY_POWER}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, entry)
