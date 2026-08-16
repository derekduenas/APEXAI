"""THE SEAL — structural barriers to live placement, plus a tripwire.

`live_enabled = False` is not safety; it is a sentence. ERD-1 uses four
independent barriers, any ONE of which would stop a live order:

  1. ABSENCE — the adapter defines no placement method; there is
     nothing to call, nothing to flip, nothing to override usefully.
  2. ALLOW-LIST — the adapter's transport refuses any tool not in its
     read/review list, and refuses mutating tool NAMES outright, so an
     MCP that offers placement cannot be reached through APEX's door.
  3. UNCONSTRUCTABLE AUTHORIZATION — LiveExecutionAuthorization cannot
     be instantiated in this phase: its constructor always raises. Any
     future placement path would have to accept one, so the path cannot
     even be typed today.
  4. TRIPWIRE — assert_no_placement_surface() scans a live object graph
     for reachable placement callables and raises on discovery; the
     gateway calls it before every readiness evaluation, and tests scan
     the whole package.
"""

from __future__ import annotations

import inspect

PLACEMENT_MARKERS = ("place_order", "place_equity_order",
                     "place_option_order", "submit_order", "execute_order",
                     "send_order", "buy_shares", "sell_shares")
SEALING_VERSION = "execution_sealing_v1"


class LiveExecutionSealed(RuntimeError):
    """Raised whenever anything tries to reach live placement."""


class LiveExecutionAuthorization:
    """Barrier 3: cannot exist in ERD-1. A future live path must accept
    one of these, which means the path cannot be constructed today —
    unsealing requires a dated governance change to THIS file."""

    def __init__(self, *_a, **_k):
        raise LiveExecutionSealed(
            "LiveExecutionAuthorization cannot be constructed in ERD-1: "
            "real money is SEALED. Unsealing is a dated governance "
            "change plus an explicit operator act, never a code flag.")


def assert_no_placement_surface(obj, label: str = "object") -> dict:
    """Barrier 4: scan a live object for reachable placement callables."""
    found = []
    for name in dir(obj):
        if name.startswith("__"):
            continue
        low = name.lower()
        if any(m in low for m in PLACEMENT_MARKERS):
            attr = getattr(obj, name, None)
            if callable(attr) or inspect.iscoroutinefunction(attr):
                found.append(name)
    if found:
        raise LiveExecutionSealed(
            f"TRIPWIRE: {label} exposes placement surface {found}; ERD-1 "
            f"forbids a reachable live-order path")
    return {"scanned": label, "placement_surface": "ABSENT",
            "version": SEALING_VERSION}


def scan_package_for_placement(package_dir: str = "apex") -> dict:
    """Repo-level scan: no module APEX runtime imports may DEFINE a
    placement function (the sealed abstract broker's disabled stubs are
    exempt — they exist precisely to raise)."""
    from pathlib import Path
    offenders = []
    for f in Path(package_dir).rglob("*.py"):
        if f.name == "sealing.py" or f.parts[-2:] == ("hunter", "broker.py"):
            continue
        src = f.read_text()
        for marker in PLACEMENT_MARKERS:
            if f"def {marker}" in src:
                offenders.append(f"{f}:{marker}")
    return {"offenders": offenders, "clean": not offenders,
            "version": SEALING_VERSION}
