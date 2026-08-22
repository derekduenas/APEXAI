"""Durable non-fatal error artifact.

Some failures must NOT kill a live loop -- a ledger write that fails
should never take down the market sensor, and a health-artifact read
that fails should never abort a Frontier-2 cycle. But "must not crash"
is not the same as "may vanish". Before this, those handlers printed to
stdout and continued, which in a launchd-managed process means the
evidence lives only in a log nobody reads until something has already
gone wrong.

THE LAW: no critical error may exist only in stdout. A swallowed
exception still writes a durable, structured record here.

decision_power: NONE.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

LEDGER = Path("results/governance/ledger_errors.jsonl")
_PRODUCTION_LEDGER = LEDGER          # frozen; LEDGER may be monkeypatched

OPERATIONS = ("LEDGER_WRITE", "ARTIFACT_READ", "HEALTH_READ", "BIRTH_MINT",
              "PROGRESS_WRITE", "OTHER")


def _under_test_without_optin() -> bool:
    """Phase 17 (2026-08-20): six pytest rows sat in the PRODUCTION
    error ledger, indistinguishable from live incidents until a human
    noticed the /pytest-of-*/ paths inside them. Pytest sets
    PYTEST_CURRENT_TEST for the duration of every test; unless a test
    explicitly opts in (APEX_ALLOW_PROD_LEDGER_IN_TEST=1, for tests
    ABOUT this ledger that monkeypatch LEDGER to a tmp path anyway),
    writes to the production ledger are refused."""
    import os
    return (bool(os.environ.get("PYTEST_CURRENT_TEST"))
            and os.environ.get("APEX_ALLOW_PROD_LEDGER_IN_TEST") != "1")


def record(*, service: str, operation: str, exc: BaseException,
           ledger: str | None = None, cycle: int | None = None,
           known_from=None, input_refs: tuple = (),
           recovery_action: str = "loop continues; this operation is skipped"
           ) -> dict:
    """Never raises. A failure to record a failure must not cascade."""
    # Only the PRODUCTION ledger is protected: a test that monkeypatches
    # LEDGER to a tmp path is doing exactly the right thing and writes
    # normally. A test that (usually by accident, through a deep call
    # chain) reaches the real ledger is refused.
    if LEDGER == _PRODUCTION_LEDGER and _under_test_without_optin():
        return {"kind": "ledger_error", "suppressed": "TEST_CONTEXT",
                "service": service, "operation": operation}
    try:
        import pandas as pd
        now = str(pd.Timestamp.now(tz="UTC"))
    except Exception:                                       # noqa: BLE001
        now = None
    rec = {
        "kind": "ledger_error",
        "service": service,
        "operation": operation if operation in OPERATIONS else "OTHER",
        "ledger": ledger,
        "cycle": cycle,
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc()[-2000:],
        "known_from": str(known_from) if known_from is not None else now,
        "as_of": now,
        "input_refs": list(input_refs),
        "recovery_action": recovery_action,
        "decision_power": "NONE",
    }
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:                                       # noqa: BLE001
        pass
    return rec


def read_all(path: Path | None = None) -> list:
    p = path or LEDGER
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summarize(session_date: str | None = None, path: Path | None = None) -> dict:
    rows = read_all(path)
    if session_date:
        rows = [r for r in rows
                if str(r.get("as_of", "")).startswith(session_date)]
    by_service: dict = {}
    by_operation: dict = {}
    for r in rows:
        by_service[r.get("service")] = by_service.get(r.get("service"), 0) + 1
        by_operation[r.get("operation")] = by_operation.get(r.get("operation"), 0) + 1
    return {"kind": "ledger_error_summary", "total": len(rows),
            "by_service": dict(sorted(by_service.items())),
            "by_operation": dict(sorted(by_operation.items())),
            "decision_power": "NONE"}
