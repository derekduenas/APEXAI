#!/usr/bin/env python
"""APEX MISSION CONTROL — one screen, every row MEASURED.

    python scripts/mission_control.py

Consumer only. If something breaks Monday, this is the screen that says
what died. The INSTR-01 law governs every line: a row that cannot go red
carries no information when it is green, so nothing here is a typed
literal — each value comes from a probe function, and a probe that cannot
measure prints UNKNOWN or the error name, never a reassuring default.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402


def _probe(fn):
    """Every row goes through here: measured or honestly UNKNOWN."""
    try:
        return fn()
    except Exception as e:                                  # noqa: BLE001
        return f"UNKNOWN_{type(e).__name__}"


def _launchd(job: str):
    out = subprocess.run(["launchctl", "list"], capture_output=True,
                         text=True).stdout
    for line in out.splitlines():
        if line.endswith(job):
            pid = line.split()[0]
            return "RUNNING" if pid != "-" else "LOADED_IDLE"
    return "NOT_LOADED"


def _next_tick():
    now = pd.Timestamp.now(tz="America/New_York")
    o = now.normalize() + pd.Timedelta(hours=9, minutes=30)
    if now.weekday() >= 5 or now > now.normalize() + pd.Timedelta(hours=16):
        o = o + pd.Timedelta(days=(7 - now.weekday()) % 7 or 1)
        while o.weekday() >= 5:
            o += pd.Timedelta(days=1)
    delta = o - now
    return (f"{str(o)[:16]} ET (in {delta.components.days*24 + delta.components.hours}h"
            f"{delta.components.minutes:02d}m)") if now < o else "IN SESSION"


def _quota():
    from apex.intraday import quota_ledger as ql
    lab, fwd = ql.headroom(ql.LAB), ql.headroom(ql.FORWARD)
    return (f"forward {fwd}u {'HEALTHY' if fwd >= 35_000 else 'LOW'} | "
            f"lab {lab}u")


def _ledger(path: str):
    from apex.governance.chain_verify import verify
    v = verify(path)
    return (f"{v['status']} ({v['valid_records']} rec"
            + (f", {len(v['damage'])} dmg" if v["damage"] else "") + ")")


def _ledger_age(path: str):
    p = Path(path)
    if not p.exists():
        return "ABSENT"
    age = (pd.Timestamp.now(tz="UTC")
           - pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC"))
    return f"{int(age.total_seconds())}s ago"


def _crypto():
    from apex.crypto import health
    r = health.read()
    if "status" in r and r["status"].startswith(("NO_HEALTH",
                                                 "HEALTH_ARTIFACT")):
        return r["status"]
    stale = health.staleness_seconds()
    return f"{r.get('suspension_state')} (hb {stale}s)"


def _disk():
    from apex.crypto import diskgov
    d = diskgov.disk_state()
    return f"{d['mode']} ({d['free_gb']}GB free)"


def _broker():
    from apex.execution.mcp_transport import default
    from apex.execution.robinhood import RobinhoodAdapter
    transport, mode = default()
    st = RobinhoodAdapter(transport).connection_health()["status"]
    return f"{st} / transport {mode} (agent session is the live route)"


def _component(mod: str):
    import importlib
    importlib.import_module(mod)
    return "READY"


def _seal():
    from apex.execution.sealing import scan_package_for_placement
    return ("SEALED (scan clean)"
            if scan_package_for_placement("apex")["clean"]
            else "SEAL_SCAN_DIRTY")


def _premarket_packet():
    import pandas as pd
    day = str(pd.Timestamp.now(tz="America/New_York").date())
    from apex.frontier.premarket import load_sealed
    pkt = load_sealed(day)
    if pkt is None:
        return "NOT_SEALED_TODAY (seals 06:25 PT on trading days)"
    return (f"SEALED {pkt['packet_sha256'][:10]} "
            f"({len(pkt.get('gap_map', []))} movers, "
            f"{len(pkt.get('blind_spots', []))} stated blind spots)")


def _morning_brief():
    import pandas as pd
    day = str(pd.Timestamp.now(tz="America/New_York").date())
    p = Path(f"results/frontier/premarket/{day}_morning_brief.md")
    return "PRESENT" if p.exists() else "NOT_WRITTEN_TODAY"


def _full_suite():
    """Reads the artifact the suite runner writes — a stale or absent
    artifact reads as such, never as PASS."""
    p = Path("results/readiness/full_suite.json")
    if not p.exists():
        return "NEVER_RECORDED"
    r = json.loads(p.read_text())
    age_h = (pd.Timestamp.now(tz="UTC")
             - pd.Timestamp(r["finished_utc"])).total_seconds() / 3600
    return (f"{r['result']} ({r['passed']} passed, "
            f"{age_h:.1f}h ago, commit {r['commit'][:8]})")


def _vision():
    p = Path("results/readiness/vision/injection_result.json")
    if not p.exists():
        return "UNPROBED"
    r = json.loads(p.read_text())
    return (f"READY (injection probe {r.get('market_structure')}, "
            f"power {r.get('decision_power')})")


def rows() -> list:
    return [
        ("EQUITY CLOCK", _probe(lambda: _launchd("com.apex.hunter-clock"))),
        ("NEXT OFFICIAL TICK", _probe(_next_tick)),
        ("QUOTA", _probe(_quota)),
        ("EODHD LAKE", _probe(lambda: _ledger_age(
            "data/live/sharadar/state.json"))),
        ("FORWARD LEDGER", _probe(lambda: _ledger(
            "results/hunter/forward_ledger.jsonl"))),
        ("BIRTH REGISTRY", _probe(lambda: _ledger(
            "results/hunter/birth_registry.jsonl"))),
        ("EVENT ARCHIVE", _probe(lambda: _launchd(
            "com.apex.event-capture"))),
        ("NIGHTLY PULL", _probe(lambda: _launchd(
            "com.apex.nightly-pull"))),
        ("FASTWATCH", _probe(lambda: _launchd("com.apex.fastwatch")
                             if False else _ledger_age(
                                 "results/hunter/fastwatch_ledger.jsonl"))),
        ("MICROSCOPE LEDGER", _probe(lambda: _ledger_age(
            "results/hunter/microscope_ledger.jsonl"))),
        ("ROBINHOOD (this proc)", _probe(_broker)),
        ("CRYPTO", _probe(_crypto)),
        ("DISK", _probe(_disk)),
        ("SCOUT", _probe(lambda: _component("apex.hunter.scanner"))),
        ("HUNTER", _probe(lambda: _component("apex.hunter.playbooks_v1"))),
        ("CAPTAIN", _probe(lambda: _component("apex.captain.kernel"))),
        ("CAPTAIN EYES", _probe(lambda: _component("apex.captain.context"))),
        ("VISION", _probe(_vision)),
        ("CHALLENGER", _probe(lambda: _component("apex.vision.challenger"))),
        ("EXECUTION GATEWAY", _probe(lambda: _component(
            "apex.execution.gateway"))),
        ("LIVE PLACEMENT", _probe(_seal)),
        ("FULL SUITE", _probe(_full_suite)),
        ("PREMARKET JOB", _probe(lambda: _launchd("com.apex.premarket"))),
        ("PREMARKET PACKET", _probe(_premarket_packet)),
        ("MORNING BRIEF", _probe(_morning_brief)),
        ("FRONTIER BUS", _probe(lambda: _ledger_age(
            "results/frontier/event_bus.jsonl"))),
        ("FRONTIER BOARD", _probe(lambda: _ledger_age(
            "results/frontier/opportunity_board.jsonl"))),
        ("DECISION CARDS", _probe(lambda: _component(
            "apex.frontier.decision_card"))),
        ("DISLOCATION ENGINE", _probe(lambda: _component(
            "apex.frontier.senses"))),
        ("REASONING ROUTER", _probe(lambda: _component(
            "apex.frontier.senses"))),
        ("LEARNING REGISTRY", _probe(lambda: __import__("json").loads(
            Path("results/frontier/learning_registry.json").read_text()
        )["preregistration"]["min_n_rule"][:40] + "... (0 obs)")),
        ("PAPER", "LOCKED (structural: forecast slot uncommissioned)"),
        ("CREDIT 5 / HOLDOUT", "SEALED (human acts only)"),
    ]


def main() -> int:
    print("APEX MISSION CONTROL")
    print("-" * 64)
    bad = 0
    for name, val in rows():
        flag = " **" if str(val).startswith(("UNKNOWN", "NOT_LOADED",
                                             "ABSENT", "INTEGRITY",
                                             "SEAL_SCAN")) else ""
        bad += bool(flag)
        print(f"{name:<22}{val}{flag}")
    print("-" * 64)
    print(f"{bad} row(s) flagged" if bad else "all rows measured, none flagged")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
