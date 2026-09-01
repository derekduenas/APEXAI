"""APEX PULSE — one cycle of the factual nervous system.

Observes what the market actually looks like right now and seals one
MARKET_TWIN_STATE_V0 per adequately-observed subject.

WHAT THIS IS NOT: it is not the frozen :36/:46/:56 prospective sensor,
whose regime is untouched and must never be reinterpreted. PULSE is
NEW infrastructure with its own version and its own birth.

IT DOES NOT PREDICT. There is no tag here that means buy, sell,
attack, or avoid. Attention -- deciding which subjects deserve deeper
sensing -- is an OPERATIONAL question about where to spend API calls,
never a claim about returns.

NO FAKE BACKFILL. If a cycle is missed, it was missed. A later request
is never written as though it were the observation that did not
happen.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append   # noqa: E402
from apex.intraday.sessions import Session, classify    # noqa: E402
from apex.organism import microstructure as ms          # noqa: E402
from apex.pulse import PULSE_VERSION                    # noqa: E402
from apex.pulse.compose import (TIER_1_DEEP, TIER_2_BROAD,  # noqa: E402
                                compose)
from apex.pulse.rolling import RollingStore             # noqa: E402
from apex.pulse.universe import (Disposition,           # noqa: E402
                                 load_universe,
                                 universe_version)

LEDGER = Path("results/pulse/market_twin.jsonl")
CYCLE_LOG = Path("results/pulse/cycle_log.jsonl")
JOURNAL = Path("results/pulse/rolling_journal.jsonl")
UNIVERSE_FILE = Path("exports/daily_closes_v1.json.gz")

# Tier 1 is the continuously-deep set. Kept small on purpose: deep
# sensing is expensive and its cost must stay visible.
TIER_1 = ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA")
SNAPSHOT_CHUNK = 100
# a subject whose quote predates this is reported STALE, not dropped
STALE_TOLERANCE_S = 900.0


def _now():
    return datetime.now(timezone.utc)


def snapshots(symbols):
    out, errors = {}, {}
    for i in range(0, len(symbols), SNAPSHOT_CHUNK):
        chunk = symbols[i:i + SNAPSHOT_CHUNK]
        try:
            d = ms._get("https://data.alpaca.markets/v2/stocks/"
                        "snapshots?" + urllib.parse.urlencode(
                            {"symbols": ",".join(chunk),
                             "feed": "sip"})) or {}
            out.update({s: v for s, v in d.items()
                        if isinstance(v, dict)})
        except Exception as e:                          # noqa: BLE001
            # a provider failure is RECORDED, never silently an empty
            # market
            for s in chunk:
                errors[s] = type(e).__name__
    return out, errors


def run_cycle(*, scheduled=None, tier1=TIER_1, persist=True) -> dict:
    t_sched = scheduled or _now().replace(second=0, microsecond=0)
    t_start = _now()
    session = classify(t_start)

    uni = load_universe(UNIVERSE_FILE, builder="daily_closes_cache.py")
    uv = universe_version(uni)
    symbols = [s for s in uni["symbols"] if s.isalpha()]

    t_fetch0 = time.monotonic()
    snaps, errors = snapshots(symbols)
    fetch_s = round(time.monotonic() - t_fetch0, 3)

    disp = Disposition()
    store = RollingStore(journal=JOURNAL if persist else None)
    if persist:
        store.restore()

    packets, sealed = [], 0
    t_feat0 = time.monotonic()
    for sym in symbols:
        if sym in errors:
            disp.missing(sym, why=f"provider error {errors[sym]}")
            continue
        snap = snaps.get(sym)
        if not snap or not snap.get("latestQuote"):
            disp.missing(sym, why="no snapshot or no quote returned")
            continue
        qt = (snap.get("latestQuote") or {}).get("t")
        age = ((t_start - _dtp(qt)).total_seconds()
               if qt else None)
        if age is not None and age > STALE_TOLERANCE_S:
            disp.stale(sym, age_s=age, tolerance_s=STALE_TOLERANCE_S,
                       as_of=qt)
        else:
            disp.resolved(sym, as_of=qt)
        st = compose(subject=sym, snapshot=snap,
                     scheduled_time=t_sched.isoformat(),
                     capture_start=t_start.isoformat(),
                     complete_time=_now().isoformat(),
                     universe_version=uv, rolling=store,
                     tier=TIER_1_DEEP if sym in tier1
                     else TIER_2_BROAD)
        packets.append(st.seal())
    feat_s = round(time.monotonic() - t_feat0, 3)

    t_done = _now()
    universe_record = {
        "kind": "pulse_universe_provenance",
        **{k: v for k, v in uni.items() if k != "symbols"},
        "universe_version": uv,
        "disposition": disp.record(symbols)}

    cycle = {
        "kind": "pulse_cycle",
        "pulse_version": PULSE_VERSION,
        "scheduled_time": t_sched.isoformat(),
        "capture_start": t_start.isoformat(),
        "cycle_complete": t_done.isoformat(),
        "market_session": session.value,
        "universe": universe_record,
        "latency": {
            "provider_fetch_s": fetch_s,
            "feature_build_s": feat_s,
            "total_s": round((t_done - t_start).total_seconds(), 3),
            "budget_s": 60.0,
            "within_budget": (t_done - t_start).total_seconds() < 60.0},
        "api_calls": {
            "snapshot_requests": (len(symbols) + SNAPSHOT_CHUNK - 1)
            // SNAPSHOT_CHUNK,
            "symbols_requested": len(symbols)},
        "packets_sealed": len(packets),
        "law": "measurements only; PULSE does not predict and holds "
               "no capital authority",
        "decision_power": "NONE_STATE"}

    if persist:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines():
                if line.strip():
                    try:
                        seen.add(json.loads(line).get("state_id"))
                    except json.JSONDecodeError:
                        continue
        with LEDGER.open("a") as fh:
            for p in packets:
                # IDENTITY, not execution: a duplicate timer or a
                # restart recomputes the same economic observation and
                # must not create a second authoritative state
                if p["state_id"] in seen:
                    continue
                fh.write(json.dumps(p) + "\n")
                seen.add(p["state_id"])
                sealed += 1
        cycle["packets_written"] = sealed
        cycle["packets_deduplicated"] = len(packets) - sealed
        chain_append(CYCLE_LOG, cycle)
    return {"cycle": cycle, "packets": packets}


def _dtp(ts):
    from apex.pulse.compose import _dt
    return _dt(ts)


if __name__ == "__main__":
    out = run_cycle(persist="--dry-run" not in sys.argv)
    c = out["cycle"]
    print(json.dumps({
        "session": c["market_session"],
        "universe_version": c["universe"]["universe_version"],
        "symbols": c["universe"]["disposition"]["counts"],
        "packets": c["packets_sealed"],
        "written": c.get("packets_written"),
        "latency": c["latency"]}, indent=1))
