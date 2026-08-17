#!/usr/bin/env python
"""PREOPEN GATE — the single consumer-only go/no-go. SAC-2 Phase 41.

    python scripts/preopen_gate.py

Every row measured; UNKNOWN is a failure at this gate (unlike Mission
Control's dashboard, a preopen gate that shrugs is not a gate). Exits 0
only on READY_FOR_EPOCH1 + READY_FOR_FRONTIER. It cannot authorize
capital — there is nothing in it that touches authorization state.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

CHECKS: list = []


def check(name, fn, *, frontier_only=False):
    try:
        ok, detail = fn()
    except Exception as e:                                  # noqa: BLE001
        ok, detail = False, f"UNKNOWN_{type(e).__name__}: {e}"
    CHECKS.append({"check": name, "ok": bool(ok), "detail": str(detail)[:90],
                   "frontier_only": frontier_only})


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    now = pd.Timestamp.now(tz="America/New_York")

    check("git tree clean", lambda: (sh("git status --porcelain") == "",
                                     sh("git rev-parse HEAD")[:12]))
    check("full suite artifact", lambda: (
        (lambda r: (r["result"] == "PASS"
                    and r["commit"] == sh("git rev-parse HEAD"),
                    f"{r['result']} {r['passed']}p @ {r['commit'][:8]}"))(
            json.loads(Path("results/readiness/full_suite.json").read_text()))))

    def _ledgers():
        from apex.governance.chain_verify import verify_all
        r = verify_all([p for p in ("results/hunter/birth_registry.jsonl",
                                    "results/crypto/arena_ledger.jsonl")
                        if Path(p).exists()])
        return r["overall"] in ("VALID", "VALID_WITH_DAMAGE"), r["overall"]
    check("ledgers verify", _ledgers)

    def _calendar():
        import sys as _s
        _s.path.insert(0, "scripts")
        from nightly_pull import is_trading_day
        d = str(now.date())
        return is_trading_day(d), f"{d} trading_day={is_trading_day(d)}"
    check("market calendar (today trades)", _calendar)

    def _quota():
        from apex.intraday import quota_ledger as ql
        fwd = ql.headroom(ql.FORWARD)
        return fwd >= 35_000, f"forward headroom {fwd}u (need >=35k)"
    check("forward quota reserve", _quota)

    def _disk():
        from apex.crypto import diskgov
        d = diskgov.disk_state()
        # crypto may be suspended; PRODUCTION needs its reserve intact
        return d["free_bytes"] > d["production_reserve_bytes"], \
            f"{d['free_gb']}GB free, mode {d['mode']}"
    check("disk above production reserve", _disk)

    def _jobs():
        out = sh("launchctl list | grep com.apex")
        need = ("hunter-clock", "event-capture", "nightly-pull")
        missing = [j for j in need if j not in out]
        return not missing, f"missing={missing}" if missing else "core loaded"
    check("core launchd jobs", _jobs)

    def _fjobs():
        out = sh("launchctl list | grep com.apex")
        need = ("fastwatch", "sensory-loop")
        missing = [j for j in need if j not in out]
        return not missing, f"missing={missing}" if missing else \
            "frontier jobs loaded"
    check("frontier launchd jobs", _fjobs, frontier_only=True)

    def _sleep():
        pm = sh("pmset -g")
        held = "sleep prevented" in pm or " 0 " in [
            l for l in pm.splitlines() if l.strip().startswith("sleep")][0]
        return held, ("sleep held off (assertion or setting)" if held else
                      "MAC WILL SLEEP — enable prevent-sleep-on-AC")
    check("host will not sleep", _sleep)

    def _clock_sync():
        out = sh("sntp time.apple.com 2>/dev/null | tail -1")
        try:
            off = abs(float(out.split()[0]))
            return off < 2.0, f"offset {off:.2f}s"
        except (ValueError, IndexError):
            return False, f"unmeasurable: {out[:40]}"
    check("system clock sync", _clock_sync)

    def _surface():
        r = json.loads(Path(
            "results/audit/ROBINHOOD_TOOL_SURFACE.json").read_text())
        return r["n_tools"] == 54, f"{r['n_tools']} tools, {r['sha256'][:12]}"
    check("MCP tool surface recorded", _surface, frontier_only=True)

    def _cert():
        led = Path("results/execution/certification.jsonl")
        last = None
        for line in led.read_text().splitlines():
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
        return (last or {}).get("seal_intact") is True, \
            f"broker {(last or {}).get('broker_status')}, seal intact"
    check("broker certification (seal intact)", _cert, frontier_only=True)

    def _learning():
        from apex.frontier.learning import estimate
        r = estimate("H_VISUAL")
        return (r["status"] == "NOT_YET_ESTIMABLE"
                and r["resolved_cards"] == 0,
                f"{r['status']}, {r['resolved_cards']} pre-market cards")
    check("learning registries pristine", _learning, frontier_only=True)

    def _seal():
        from apex.execution.sealing import scan_package_for_placement
        return scan_package_for_placement("apex")["clean"], "placement scan"
    check("live placement sealed", _seal)

    epoch_ok = all(c["ok"] for c in CHECKS if not c["frontier_only"])
    frontier_ok = all(c["ok"] for c in CHECKS)

    print("PREOPEN GATE")
    print("-" * 64)
    for c in CHECKS:
        mark = "PASS" if c["ok"] else "FAIL"
        scope = " [frontier]" if c["frontier_only"] else ""
        print(f"{mark:<6}{c['check']:<34}{c['detail']}{scope}")
    print("-" * 64)
    print(f"READY_FOR_EPOCH1   {'YES' if epoch_ok else 'NO'}")
    print(f"READY_FOR_FRONTIER {'YES' if frontier_ok else 'NO'}")
    print("READY_FOR_PAPER    NO (structural)")
    print("READY_FOR_LIVE     NO (sealed)")
    Path("results/readiness/preopen_gate.json").write_text(json.dumps(
        {"checked_utc": str(pd.Timestamp.now(tz="UTC")), "checks": CHECKS,
         "ready_for_epoch1": epoch_ok, "ready_for_frontier": frontier_ok},
        indent=2))
    return 0 if (epoch_ok and frontier_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
