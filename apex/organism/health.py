"""ORGANISM HEALTH — green requires actual work, and the right worker.

Implements SERVICE_IDENTITY_VALIDITY as running code: each component is
judged on (1) whether the expected executable is what systemd actually
runs -- argv, never description prose -- and (2) whether its canonical
artifact stream is advancing at the expected cadence. A component can
be active, described correctly, and writable, and still be FAILED here,
because a green light over a dead stream is the failure class that has
now bitten four times.

decision_power: NONE_OBSERVATIONAL.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

STATES = ("HEALTHY", "DEGRADED", "STALE", "FAILED", "UNKNOWN")

# component -> (unit, expected argv fragment, canonical artifact,
#               max staleness seconds DURING ACTIVE HOURS)
COMPONENTS = {
    "MARKET_DATA": ("apex-equity-fabric", "alpaca_fabric_daemon",
                    "results/intraday/alpaca_fabric_health.json", 300),
    "OPTIONS": ("apex-options-paper", "options_paper_session",
                "results/outbox/v1_decisions.jsonl", 1200),
    "EQUITY": ("apex-equity-shadow", "equity_shadow_session",
               "results/outbox/equity_shadow_decisions.jsonl", 1200),
    "BTC": ("apex-btc-paper", "btc_paper_session",
            "results/btc/paper_ledger.jsonl", 1800),
    "BTC_DERIVATIVES": ("apex-btc-derivatives",
                        "btc_derivatives_poller",
                        "results/btc/derivatives_health.json", 120),
    "CATALYST": ("apex-catalyst", "catalyst_service",
                 "results/catalyst/cycles.jsonl", 900),
    "CAPITAL_ARENA": ("apex-organism", "organism_service",
                      "results/organism/allocator_decisions.jsonl",
                      None),
    "PAPER_BOOK": (None, None, "results/organism/paper_book.jsonl",
                   None),
    "EXPERIENCE_GRAPH": (None, None,
                         "results/organism/experience_graph.jsonl",
                         None),
    # on-demand, operator-triggered: no unit, no cadence. Identity and
    # transport state come from aurelius.transport_health(); the
    # artifact here is the conversation chain it cannot rewrite.
    "AURELIUS": (None, None,
                 "results/organism/aurelius_conversations.jsonl",
                 None),
}


def _argv(unit: str) -> str:
    r = subprocess.run(["systemctl", "show", unit, "-p", "ExecStart",
                        "--value"], capture_output=True, text=True)
    return r.stdout.strip()


def _active(unit: str) -> str:
    r = subprocess.run(["systemctl", "is-active", unit],
                       capture_output=True, text=True)
    return r.stdout.strip()


def component_health(name: str, *, market_hours: bool = True,
                     root: Path = Path(".")) -> dict:
    unit, expected, artifact, staleness = COMPONENTS[name]
    out = {"component": name, "unit": unit, "checks": []}

    if unit is not None:
        active = _active(unit)
        out["checks"].append(f"systemd={active}")
        if active != "active":
            # a calendar-triggered service is SUPPOSED to be inactive
            # outside its hours -- the weekend readiness audit flagged
            # the options session FAILED for correctly not running on
            # a Saturday. Off-hours inactivity is idleness, not death.
            if not market_hours:
                out["state"] = "UNKNOWN"
                out["checks"].append("inactive off-hours "
                                     "(calendar-triggered: expected)")
                return out
            out["state"] = "FAILED"
            return out
        argv = _argv(unit)
        # a service launched through a shell wrapper (the secrets
        # launcher) shows the wrapper in argv; the real program lives
        # inside it. Follow the wrapper -- the same blind spot the
        # runtime path audit had, fixed the same way.
        if expected and expected not in argv:
            for tok in argv.replace("=", " ").split():
                if tok.endswith(".sh"):
                    try:
                        argv += " " + Path(tok).read_text()
                    except OSError:
                        pass
        if expected and expected not in argv:
            # the wrong-program failure: active, described correctly,
            # running something else entirely
            out["state"] = "FAILED"
            out["checks"].append(
                f"IDENTITY: expected {expected!r} in argv, absent")
            return out
        out["checks"].append("identity=ok")

    p = root / artifact
    if not p.exists():
        out["state"] = "UNKNOWN" if unit is None else "STALE"
        out["checks"].append("artifact=missing")
        return out
    age = time.time() - p.stat().st_mtime
    out["checks"].append(f"artifact_age={age:.0f}s")
    if staleness is not None and market_hours and age > staleness:
        out["state"] = "STALE"
        return out
    out["state"] = "HEALTHY"
    return out


def organism_health(*, market_hours: bool = True,
                    root: Path = Path(".")) -> dict:
    comps = {n: component_health(n, market_hours=market_hours,
                                 root=root)
             for n in COMPONENTS}
    worst = "HEALTHY"
    order = {s: i for i, s in enumerate(
        ("HEALTHY", "UNKNOWN", "DEGRADED", "STALE", "FAILED"))}
    for c in comps.values():
        if order[c["state"]] > order[worst]:
            worst = c["state"]
    return {"kind": "organism_health",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "overall": worst,
            "components": {n: c["state"] for n, c in comps.items()},
            "detail": comps,
            "law": "green requires actual work by the right program; "
                   "systemd active is necessary, never sufficient",
            "decision_power": "NONE_OBSERVATIONAL"}
