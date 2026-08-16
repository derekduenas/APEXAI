"""LAB-07: cross-process enforcement of the forward quota reserve.

The reserve existed as a NUMBER and a helper function with zero callers.
`QuotaGovernor.used` starts at zero in every process, so each resume, each
worker, and each replayed day granted itself a fresh budget; the aggregate
"structural invariant" the fast runner printed was false, and one GMT day
consumed all 100,000 provider units — the 35k forward reserve included.

The reserve is only real if it is enforced at SPEND time, across every
process, against a counter that survives restarts. That is this module.

Two purposes, two ceilings:

    FORWARD  — the production clock. May spend into the reserve; that is
               what the reserve is FOR. Bounded only by the true limit.
    LAB      — replay, research, backfill. Bounded by limit - reserve, so
               a runaway campaign structurally cannot blind Monday.

The provider is the referee. The local counter can only undercount (a
request issued by some other tool never passed through here), so
reconciliation always takes the MAX of local and provider, never the
convenient minimum.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

FORWARD = "FORWARD"
LAB = "LAB"
PURPOSES = (FORWARD, LAB)

# Overridable so tests never write into the production governance artifact.
SPEND_DIR = Path(os.environ.get("APEX_QUOTA_LEDGER_DIR", "results/quota"))


class ReserveViolation(RuntimeError):
    """A LAB spender tried to reach into the forward reserve."""


def _gmt_date(now_utc=None) -> str:
    import pandas as pd
    ts = pd.Timestamp(now_utc) if now_utc is not None else pd.Timestamp.now(tz="UTC")
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return str(ts.tz_convert("UTC").date())


def _path(gmt_date: str) -> Path:
    return SPEND_DIR / f"spend_{gmt_date}.json"


def _blank(gmt_date: str) -> dict:
    return {"gmt_date": gmt_date, "units": 0,
            "by_purpose": {FORWARD: 0, LAB: 0},
            "provider_reconciled_units": None}


def read(now_utc=None) -> dict:
    """Current bucket. A missing file means zero — the GMT reset is a new
    file, never a mutated one, so an old bucket can never be mistaken for
    today's (the stale-counter trap, in local form)."""
    d = _gmt_date(now_utc)
    p = _path(d)
    if not p.exists():
        return _blank(d)
    try:
        rec = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return _blank(d)
    if rec.get("gmt_date") != d:                 # stale bucket on disk
        return _blank(d)
    return rec


def ceiling(purpose: str) -> int:
    """Units this purpose may consume in a GMT day."""
    from apex.intraday.eodhd import (DAILY_LIMIT_CALL_UNITS,
                                     FORWARD_RESERVE_CALL_UNITS)
    if purpose not in PURPOSES:
        raise ValueError(f"unknown quota purpose {purpose!r}")
    if purpose == FORWARD:
        return DAILY_LIMIT_CALL_UNITS
    return DAILY_LIMIT_CALL_UNITS - FORWARD_RESERVE_CALL_UNITS


def headroom(purpose: str, now_utc=None) -> int:
    return max(0, ceiling(purpose) - read(now_utc)["units"])


def spend(cost: int, purpose: str, now_utc=None) -> dict:
    """Atomically claim `cost` units, or refuse.

    Returns {"granted": bool, "units_after": int, "headroom": int,
             "reason": str|None}. Refusal is a RETURN, not an exception:
    exhaustion pauses a campaign, it does not crash one (the never-spin
    rule). ReserveViolation is raised only for a nonsense purpose.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown quota purpose {purpose!r}")
    cap = ceiling(purpose)
    d = _gmt_date(now_utc)
    SPEND_DIR.mkdir(parents=True, exist_ok=True)
    lock = SPEND_DIR / f".lock_{d}"
    with lock.open("a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)   # cross-process serialization
        try:
            rec = read(now_utc)
            if rec["units"] + cost > cap:
                return {"granted": False, "units_after": rec["units"],
                        "headroom": max(0, cap - rec["units"]),
                        "reason": (f"QUOTA_CEILING_{purpose}: "
                                   f"{rec['units']}+{cost} > {cap}"
                                   + (" (forward reserve is untouchable by "
                                      "the lab)" if purpose == LAB else ""))}
            rec["units"] += cost
            rec["by_purpose"][purpose] = rec["by_purpose"].get(purpose, 0) + cost
            tmp = _path(d).with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, sort_keys=True))
            os.replace(tmp, _path(d))             # atomic: no torn counter
            return {"granted": True, "units_after": rec["units"],
                    "headroom": max(0, cap - rec["units"]), "reason": None}
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def reconcile_with_provider(provider_units: int, provider_date: str,
                            now_utc=None) -> dict:
    """Raise the local counter to the provider's if the provider says more
    was spent. Never lowers it: a local claim already in flight has not yet
    reached the provider's accounting, and trusting the smaller number is
    how a reserve gets spent twice.

    A provider counter dated to a PRIOR bucket is ignored outright (the
    documented EODHD stale-counter behavior).
    """
    d = _gmt_date(now_utc)
    if provider_date != d:
        return {**read(now_utc), "reconciled": False,
                "note": "provider counter belongs to a prior GMT bucket"}
    SPEND_DIR.mkdir(parents=True, exist_ok=True)
    lock = SPEND_DIR / f".lock_{d}"
    with lock.open("a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            rec = read(now_utc)
            before = rec["units"]
            rec["units"] = max(before, int(provider_units))
            rec["provider_reconciled_units"] = int(provider_units)
            tmp = _path(d).with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, sort_keys=True))
            os.replace(tmp, _path(d))
            return {**rec, "reconciled": True, "local_before": before,
                    "raised": rec["units"] > before}
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def status(now_utc=None) -> dict:
    rec = read(now_utc)
    return {**rec,
            "lab_headroom_units": headroom(LAB, now_utc),
            "forward_headroom_units": headroom(FORWARD, now_utc),
            "lab_ceiling": ceiling(LAB), "forward_ceiling": ceiling(FORWARD)}
