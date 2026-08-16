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

# HYSTERESIS (2026-08-16). SUSPEND fires when crypto's budget hits zero.
# Resuming at that SAME boundary is what produced the observed sawtooth:
# the governor correctly suspended at 16:56 and 17:13, launchd's KeepAlive
# correctly restarted what looked like a crash, and the two correct
# controls fought each other every ~17 minutes -- each restart re-warming
# the fabric and breaking book continuity.
#
# The law: the condition required to RESTART must be materially healthier
# than the condition that caused suspension. Recovery therefore demands a
# full TRIM band of clear air, not one spare byte.
CRYPTO_RESUME_ABOVE = CRYPTO_TRIM_BELOW      # 800MB of crypto budget
DISK_GOVERNOR_VERSION = "disk_governor_v1.1"


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
        "resume_above_bytes": CRYPTO_RESUME_ABOVE,
        "may_resume": available_crypto >= CRYPTO_RESUME_ABOVE,
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
    """True => the crypto daemon stops touching disk. The production
    clocks are never asked to yield.

    NOTE: the daemon no longer EXITS on suspension -- exiting is
    indistinguishable from a crash to launchd, which then resurrects it
    into the same starved condition. It stays alive and idle instead; see
    may_resume().
    """
    return (state or disk_state())["mode"] == "SUSPEND"


def may_resume(state: dict | None = None) -> bool:
    """Hysteresis gate. A suspended daemon waits for this, NOT for the
    mere absence of must_suspend() -- otherwise it restarts at the exact
    boundary that killed it."""
    return (state or disk_state())["available_crypto_bytes"] \
        >= CRYPTO_RESUME_ABOVE
