"""EQUITY SHADOW SESSION — the second sleeve, observing only.

Runs beside the Options combat sleeve and never touches it. It reads
the same market fabric, forms its OWN decisions, seals them before any
outcome exists, and emits neutral records for EdgeForge.

If this process dies, Options does not notice. That is the design.

decision_power: SHADOW_ONLY -- no orders, no capital, no authority.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.ops.heartbeat import Heartbeat  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402
from apex.ops.outbox import emit as outbox_emit  # noqa: E402
from apex.ops.timebase import ET  # noqa: E402
from apex.predators.equities import day_trader  # noqa: E402
from apex.predators.equities import shadow_resolution  # noqa: E402

SERVICE = "equity-shadow"
LEDGER = Path("results/equities/shadow_decisions.jsonl")
OUTCOMES = Path("results/equities/shadow_outcomes.jsonl")
OUTBOX = Path("results/outbox/equity_shadow_decisions.jsonl")
BARS_ROOT = Path(__import__("os").environ.get(
    "APEX_BARS_ROOT", "data/live/bars"))
SCAN_INTERVAL_S = 900          # matches the incumbent 15-minute cadence


def release_sha() -> str:
    p = Path("/opt/apex/current/RELEASE.json")
    try:
        return json.loads(p.read_text()).get("commit", "UNKNOWN")
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def load_bars(symbol: str, session: str) -> list:
    f = BARS_ROOT / f"{symbol}_{session}.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text()).get("bars", [])
    except (OSError, json.JSONDecodeError):
        return []


RTH_OPEN_UTC = "13:30"
RTH_CLOSE_UTC = "20:00"


def rth_only(bars: list) -> list:
    """Liquidity must be measured over the REGULAR SESSION.

    Measuring the median across the whole file drags in overnight and
    extended hours where volume is near zero, and the floor then
    rejects SPY -- the most liquid instrument on the tape. Caught by
    running it: the eligible universe collapsed to a single symbol.
    """
    return [b for b in bars
            if RTH_OPEN_UTC <= b["event_time_utc"][11:16] <= RTH_CLOSE_UTC]


def eligible_universe(session: str) -> dict:
    """Predeclared liquidity floor, measured over RTH. Reported BEFORE
    any decision."""
    ok, thin, missing = [], [], []
    if not BARS_ROOT.exists():
        return {"eligible": [], "thin": [], "missing": [],
                "why": f"no bar store at {BARS_ROOT}"}
    for f in sorted(BARS_ROOT.glob(f"*_{session}.json")):
        sym = f.name.split("_")[0]
        bars = rth_only(load_bars(sym, session))
        vols = [b.get("volume", 0) for b in bars]
        if len(bars) < day_trader.MIN_BARS:
            missing.append(sym)
            continue
        mv = st.median(vols) if vols else 0
        (ok if mv >= day_trader.MIN_MEDIAN_VOLUME_PER_MIN
         else thin).append(sym)
    return {"eligible": ok, "thin": thin, "missing": missing,
            "floor_shares_per_min": day_trader.MIN_MEDIAN_VOLUME_PER_MIN}


def sweep(session: str, *, beat=None, roots: dict | None = None) -> dict:
    r = roots or {}
    led = r.get("ledger", LEDGER)
    ob = r.get("outbox", OUTBOX)
    uni = eligible_universe(session)
    now = datetime.now(timezone.utc)
    decisions = []

    for sym in uni["eligible"]:
        bars = [b for b in load_bars(sym, session)
                if b["event_time_utc"] <= now.isoformat()]
        if not bars:
            continue
        vols = [b.get("volume", 0) for b in rth_only(bars)]
        try:
            d = day_trader.decide(
                symbol=sym, session=session, bars=bars,
                now=bars[-1]["event_time_utc"],
                known_from=bars[-1]["event_time_utc"],
                release_sha=release_sha(),
                median_volume=st.median(vols) if vols else None)
        except Exception as e:                          # noqa: BLE001
            # one symbol's failure is one symbol's failure
            decisions.append({"symbol": sym, "error":
                              f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        rec = d.as_record()
        chain_append(led, rec)
        outbox_emit(ob, kind="equity_shadow_decision", session=session,
                    source="scripts/equity_shadow_session.sweep",
                    known_from=d.known_from, payload=rec)
        decisions.append(rec)

    attacks = [d for d in decisions
               if d.get("decision") == "ATTACK_READY_SHADOW"]
    out = {"kind": "equity_shadow_sweep", "session": session,
           "swept_utc": now.isoformat(),
           "eligible_universe": uni["eligible"],
           "excluded_thin": uni["thin"],
           "evaluated": len(decisions),
           "attacks": len(attacks),
           "errors": [d for d in decisions if d.get("error")],
           "decision_power": "SHADOW_ONLY"}
    if beat is not None:
        beat.work(f"{len(decisions)} evaluated, {len(attacks)} shadow "
                  f"attacks", backlog=len(out["errors"]))
    return out


def resolve_session(session: str, *, roots: dict | None = None) -> dict:
    r = roots or {}
    led = r.get("ledger", LEDGER)
    outp = r.get("outcomes", OUTCOMES)
    if not Path(led).exists():
        return {"resolved": 0, "why": "no decisions"}
    b = session_bounds(session)
    if not b["trading_day"]:
        return {"resolved": 0, "why": "not a trading day"}
    close = b["close_utc"]
    # idempotent across restarts: a decision already resolved in the
    # outcomes ledger is never resolved twice -- a service restart
    # after the close must not duplicate outcome rows
    already = set()
    if Path(outp).exists():
        for line in Path(outp).read_text().splitlines():
            if line.strip():
                try:
                    already.add(json.loads(line).get("decision_id"))
                except json.JSONDecodeError:
                    continue
    done, skipped = 0, 0
    for line in Path(led).read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("session") != session:
            continue
        if d.get("decision_id") in already:
            skipped += 1
            continue
        res = shadow_resolution.resolve(
            decision=d, bars=load_bars(d["symbol"], session),
            close_utc=close)
        if res.get("resolvable"):
            chain_append(outp, res)
            done += 1
        else:
            skipped += 1
    return {"kind": "equity_shadow_resolution", "session": session,
            "resolved": done, "not_resolvable": skipped,
            "decision_power": "SHADOW_ONLY"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--session", default=None)
    ap.add_argument("--follow", action="store_true")
    a = ap.parse_args()
    session = a.session or datetime.now(timezone.utc).astimezone(ET) \
        .strftime("%Y-%m-%d")

    if a.universe:
        print(json.dumps(eligible_universe(session), indent=1))
        return 0
    if a.resolve:
        print(json.dumps(resolve_session(session), indent=1))
        return 0
    if a.once or not a.follow:
        print(json.dumps(sweep(session), indent=1))
        return 0

    beat = Heartbeat(SERVICE)
    last = 0.0
    resolved_session = None
    while True:
        session = datetime.now(timezone.utc).astimezone(ET) \
            .strftime("%Y-%m-%d")
        try:
            b = session_bounds(session)
            now = datetime.now(timezone.utc)
            in_rth = (b["trading_day"] and b["open_utc"] <= now
                      <= b["close_utc"])
            if in_rth and time.time() - last >= SCAN_INTERVAL_S:
                sweep(session, beat=beat)
                last = time.time()
            elif not in_rth:
                # post-close: resolve the session's sealed attacks once.
                # Without this trigger a funded shadow trade would sit
                # PENDING forever -- found while preparing for the first
                # natural attack (NVDA) to resolve.
                if (b["trading_day"] and b["close_utc"]
                        and now > b["close_utc"]
                        and resolved_session != session):
                    r = resolve_session(session)
                    resolved_session = session
                    beat.work(f"resolved {r.get('resolved', 0)} shadow "
                              f"attack(s) for {session}")
                beat.beat()
        except Exception as e:                          # noqa: BLE001
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
