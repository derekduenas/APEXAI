"""Operational health artifact for the crypto daemon.

Written because the daemon log went stale at 17:13 while the process was
alive and still appending to the ledger at 18:19 -- an operator surface
lying by omission. Monitoring must never infer liveness from whether the
last human-readable log line happens to be recent.

Atomic overwrite; the reader either sees the previous complete state or
the new complete state, never a half-written one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

HEALTH_PATH = Path("results/crypto/crypto_health.json")


def write(**fields) -> dict:
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    rec = {"artifact": "crypto_health_v1", **fields}
    tmp = HEALTH_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=2, default=str))
    os.replace(tmp, HEALTH_PATH)          # atomic
    return rec


def read() -> dict:
    if not HEALTH_PATH.exists():
        return {"status": "NO_HEALTH_ARTIFACT",
                "note": "the daemon has never written health; absence is "
                        "UNKNOWN, not healthy"}
    try:
        return json.loads(HEALTH_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "HEALTH_ARTIFACT_UNREADABLE",
                "error": type(e).__name__}


def staleness_seconds(now=None) -> float | None:
    """Age of the last heartbeat. None when unknown -- never 0."""
    import pandas as pd
    rec = read()
    hb = rec.get("last_heartbeat")
    if not hb:
        return None
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    return round((now - pd.Timestamp(hb)).total_seconds(), 1)
