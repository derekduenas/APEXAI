"""DISK GOVERNOR — free space is a sovereign resource, like API quota.

The law (identical doctrine to the EODHD forward reserve):

    FORWARD EQUITY > CRYPTO LABORATORY

Monday's clock, the event archive, and the nightly pull all need disk.
The crypto arena is a laboratory; it must voluntarily die before it can
threaten the exam. Browser-cache cleanup bought room — this makes the
protection structural.

Graduated response, checked before every archival write batch and every
daemon cycle:

    HEALTHY    -> full archival
    TRIM       -> stop raw event archival (book snapshots continue)
    MINIMAL    -> snapshots only at a slower cadence
    SUSPEND    -> the crypto daemon SELF-SUSPENDS (production untouched)

The reserves are declared, not guessed: production needs room for the
forward ledger + intraday cache growth on a heavy session; critical
services (OS, logs, git) need headroom to avoid a wedged machine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# declared reserves (bytes)
PRODUCTION_RESERVE = 2_000_000_000     # equity clock: ledger + cache growth
CRITICAL_SERVICE_RESERVE = 1_500_000_000   # OS/logs/git breathing room
CRYPTO_TRIM_BELOW = 800_000_000        # crypto's own comfort band
CRYPTO_MINIMAL_BELOW = 300_000_000
DISK_GOVERNOR_VERSION = "disk_governor_v1"


def disk_state(path: str = ".") -> dict:
    du = shutil.disk_usage(Path(path).resolve())
    reserved = PRODUCTION_RESERVE + CRITICAL_SERVICE_RESERVE
    available_crypto = du.free - reserved
    if available_crypto >= CRYPTO_TRIM_BELOW:
        mode = "HEALTHY"
    elif available_crypto >= CRYPTO_MINIMAL_BELOW:
        mode = "TRIM"
    elif available_crypto > 0:
        mode = "MINIMAL"
    else:
        mode = "SUSPEND"
    return {
        "governor": DISK_GOVERNOR_VERSION,
        "free_bytes": du.free,
        "free_gb": round(du.free / 1e9, 2),
        "production_reserve_bytes": PRODUCTION_RESERVE,
        "critical_service_reserve_bytes": CRITICAL_SERVICE_RESERVE,
        "available_crypto_bytes": available_crypto,
        "available_crypto_mb": round(available_crypto / 1e6, 1),
        "mode": mode,
        "law": "FORWARD EQUITY > CRYPTO LABORATORY: the arena suspends "
               "itself before production loses disk",
    }


def may_archive_raw(state: dict | None = None) -> bool:
    return (state or disk_state())["mode"] == "HEALTHY"


def may_snapshot(state: dict | None = None) -> bool:
    return (state or disk_state())["mode"] in ("HEALTHY", "TRIM", "MINIMAL")


def snapshot_interval_s(state: dict | None = None) -> int:
    mode = (state or disk_state())["mode"]
    return {"HEALTHY": 60, "TRIM": 60, "MINIMAL": 300}.get(mode, 10 ** 9)


def must_suspend(state: dict | None = None) -> bool:
    """True => the crypto daemon stops touching disk and exits. The
    production clocks are never asked to yield."""
    return (state or disk_state())["mode"] == "SUSPEND"
