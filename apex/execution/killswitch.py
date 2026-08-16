"""EXECUTION KILL SWITCH — global, file-backed, Claude-independent.

Engaging it is a filesystem act (a marker file), not a service call, an
LLM decision, or an in-memory flag: it survives process restarts, works
when Python is wedged, and can be thrown from a shell in one second:

    touch ops/EXECUTION_KILLED          # engage
    rm    ops/EXECUTION_KILLED          # release (deliberate act)

When engaged: no OrderIntent may advance, in-flight previews are inert,
the cockpit shows KILLED, and every check is ledgered. Nothing about
this depends on Claude, the Captain, or any model being available.
"""

from __future__ import annotations


from pathlib import Path

KILL_MARKER = Path("ops/EXECUTION_KILLED")
KILL_LEDGER = Path("results/execution/kill_switch.jsonl")
KILLSWITCH_VERSION = "execution_kill_switch_v1"


def engaged() -> bool:
    return KILL_MARKER.exists()


def state() -> dict:
    if not engaged():
        return {"kill_switch": "ARMED_NOT_ENGAGED", "engaged": False,
                "version": KILLSWITCH_VERSION,
                "engage_command": f"touch {KILL_MARKER}"}
    try:
        reason = KILL_MARKER.read_text().strip()[:400]
    except Exception:                                       # noqa: BLE001
        reason = ""
    return {"kill_switch": "ENGAGED_ALL_EXECUTION_HALTED", "engaged": True,
            "reason": reason or "(no reason recorded)",
            "version": KILLSWITCH_VERSION,
            "release_command": f"rm {KILL_MARKER}"}


def engage(reason: str = "") -> dict:
    KILL_MARKER.parent.mkdir(parents=True, exist_ok=True)
    KILL_MARKER.write_text(reason)
    return _ledger({"event": "ENGAGED", "reason": reason[:400]})


def release(reason: str = "") -> dict:
    KILL_MARKER.unlink(missing_ok=True)
    return _ledger({"event": "RELEASED", "reason": reason[:400]})


def _ledger(rec: dict) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from nightly_pull import _chain_append
    import pandas as pd
    KILL_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(KILL_LEDGER, {"kind": "kill_switch",
                                       "t_utc": str(pd.Timestamp.now(
                                           tz="UTC")), **rec})


def record_check(context: str) -> None:
    """Every consultation while ENGAGED is ledgered — a halted desk
    should leave evidence of what it refused."""
    if engaged():
        try:
            _ledger({"event": "BLOCKED_ADVANCE", "context": context[:200]})
        except Exception:                                   # noqa: BLE001
            pass

