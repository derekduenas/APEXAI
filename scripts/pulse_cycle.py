"""APEX PULSE — one cycle of the factual nervous system.

Observes what the market actually looks like right now and seals one
MARKET_TWIN_STATE_V0 per subject.

TWO TIERS, HONESTLY LABELLED. Tier 2 is a cheap factual scan of the
whole universe every minute. Tier 1 is expensive deep sensing for a
small set. A Tier-2 subject is never marked as carrying Tier-1 state
it does not have.

THIS IS NOT THE FROZEN :36/:46/:56 SENSOR. That regime is untouched
and must never be reinterpreted. PULSE is new infrastructure with its
own version and birth, and its observations are never pooled with it.

IT DOES NOT PREDICT. Enrichment decides where to spend API calls, not
what to trade.

NO FAKE BACKFILL. A missed cycle was missed.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append   # noqa: E402
from apex.intraday.sessions import Session, classify    # noqa: E402
from apex.organism import microstructure as ms          # noqa: E402
from apex.pulse import PULSE_VERSION                    # noqa: E402
from apex.pulse.compose import (TIER_1_DEEP,            # noqa: E402
                                TIER_2_BROAD, _dt, compose)
from apex.pulse.enrichment import (EnrichmentRecord,    # noqa: E402
                                   eligibility)
from apex.pulse.premarket import PremarketPath          # noqa: E402
from apex.pulse.rolling import RollingStore             # noqa: E402
from apex.pulse.universe import (Disposition,           # noqa: E402
                                 load_universe,
                                 universe_version)

RESULTS = Path("results/pulse")
LEDGER = RESULTS / "market_twin.jsonl"
CYCLE_LOG = RESULTS / "cycle_log.jsonl"
JOURNAL = RESULTS / "rolling_journal.jsonl"
PM_JOURNAL = RESULTS / "premarket_journal.jsonl"
UNIVERSE_FILE = Path("exports/daily_closes_v1.json.gz")

TIER_1 = ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA")
SNAPSHOT_CHUNK = 100
STALE_TOLERANCE_S = 900.0
# hard ceiling on deep-tape calls per cycle so a violent session
# cannot blow the one-minute budget
MAX_DEEP_PER_CYCLE = 10


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
            for s in chunk:
                errors[s] = type(e).__name__
    return out, errors


def deep_tape(symbol, now, *, minutes=5):
    """Tier-1 microstructure from the real SIP tape."""
    t0 = (now - timedelta(minutes=minutes)).isoformat()
    tr = ms.fetch_ticks(symbol, t0, now.isoformat(), what="trades",
                        max_pages=3)
    qs = ms.fetch_ticks(symbol, t0, now.isoformat(), what="quotes",
                        max_pages=3)
    st = ms.micro_state(tr, qs, window_label=f"last{minutes}m")
    st["as_of"] = now.isoformat()
    return st


def run_cycle(*, scheduled=None, tier1=TIER_1, persist=True,
              enable_deep=True) -> dict:
    t_sched = scheduled or _now().replace(second=0, microsecond=0)
    t_start = _now()
    session = classify(t_start)

    uni = load_universe(UNIVERSE_FILE, builder="daily_closes_cache.py")
    uv = universe_version(uni)
    symbols = [s for s in uni["symbols"] if s.isalpha()]

    t0 = time.monotonic()
    snaps, errors = snapshots(symbols)
    fetch_s = round(time.monotonic() - t0, 3)
    t_capture_end = _now()

    disp = Disposition()
    store = RollingStore(journal=JOURNAL if persist else None)
    pm = PremarketPath(journal=PM_JOURNAL if persist else None)
    if persist:
        store.restore()
        pm.restore()

    # ---- pass 1: cheap factual state + enrichment eligibility
    prelim, elig_map = {}, {}
    for sym in symbols:
        if sym in errors:
            disp.missing(sym, why=f"provider error {errors[sym]}")
            continue
        snap = snaps.get(sym)
        if not snap or not snap.get("latestQuote"):
            disp.missing(sym, why="no snapshot or no quote returned")
            continue
        q = snap["latestQuote"]
        qt = q.get("t")
        age = (t_start - _dt(qt)).total_seconds() if qt else None
        if age is not None and age > STALE_TOLERANCE_S:
            disp.stale(sym, age_s=age, tolerance_s=STALE_TOLERANCE_S,
                       as_of=qt)
        else:
            disp.resolved(sym, as_of=qt)
        prelim[sym] = snap
        prev = (snap.get("prevDailyBar") or {}).get("c")
        day = snap.get("dailyBar") or {}
        mid = ((q["bp"] + q["ap"]) / 2
               if q.get("bp") and q.get("ap") else None)
        move = ((mid / prev - 1) * 1e4 if (mid and prev) else None)
        relvol = (day["v"] / (snap.get("prevDailyBar") or {})["v"]
                  if day.get("v")
                  and (snap.get("prevDailyBar") or {}).get("v")
                  else None)
        elig_map[sym] = eligibility(sym, tier1=sym in tier1,
                                    move_bps=move,
                                    relative_volume=relvol,
                                    as_of=qt, known_from=qt)

    # ---- pass 2: staged enrichment, budget-capped
    eligible = [s for s in prelim if elig_map[s]["eligible"]]
    eligible.sort(key=lambda s: 0 if s in tier1 else 1)
    deep_budget = eligible[:MAX_DEEP_PER_CYCLE] if enable_deep else []

    packets = []
    t1 = time.monotonic()
    for sym, snap in prelim.items():
        rec = EnrichmentRecord(elig_map[sym])
        deep = None
        if sym in deep_budget:
            rec.request("deep_tape")
            try:
                deep = deep_tape(sym, _now())
                if deep.get("status") == "NOT_ESTIMABLE":
                    rec.unavailable("deep_tape",
                                    why=str(deep.get("why")))
                else:
                    rec.succeeded("deep_tape", as_of=deep["as_of"])
            except Exception as e:                      # noqa: BLE001
                rec.failed("deep_tape", why=type(e).__name__)
        elif elig_map[sym]["eligible"]:
            rec.request("deep_tape")
            rec.budget_exceeded("deep_tape",
                                rank=eligible.index(sym) + 1,
                                budget=MAX_DEEP_PER_CYCLE)
        if session in (Session.PREMARKET, Session.CLOSED):
            rec.unavailable("options",
                            why="US options do not trade in this "
                                "session -- EXPECTED_ABSENCE")
        st = compose(subject=sym, snapshot=snap,
                     scheduled_time=t_sched.isoformat(),
                     capture_start=t_start.isoformat(),
                     capture_end=t_capture_end.isoformat(),
                     complete_time=_now().isoformat(),
                     universe_version=uv, rolling=store,
                     premarket_path=pm, deep=deep,
                     enrichment=rec.record(),
                     tier=TIER_1_DEEP if (sym in tier1 or deep)
                     else TIER_2_BROAD)
        packets.append(st.seal())
    feat_s = round(time.monotonic() - t1, 3)

    t_done = _now()
    cycle = {
        "kind": "pulse_cycle", "pulse_version": PULSE_VERSION,
        "scheduled_time": t_sched.isoformat(),
        "capture_start": t_start.isoformat(),
        "capture_end": t_capture_end.isoformat(),
        "cycle_complete": t_done.isoformat(),
        "market_session": session.value,
        "universe": {"kind": "pulse_universe_provenance",
                     **{k: v for k, v in uni.items()
                        if k != "symbols"},
                     "universe_version": uv,
                     "disposition": disp.record(symbols)},
        "enrichment": {
            "eligible": len(eligible),
            "deep_attempted": len(deep_budget),
            "budget": MAX_DEEP_PER_CYCLE,
            "reasons": _count(elig_map)},
        "latency": {
            "provider_fetch_s": fetch_s, "feature_build_s": feat_s,
            "total_s": round((t_done - t_start).total_seconds(), 3),
            "budget_s": 60.0,
            "within_budget": (t_done - t_start).total_seconds() < 60.0},
        "api_calls": {
            "snapshot_requests": (len(symbols) + SNAPSHOT_CHUNK - 1)
            // SNAPSHOT_CHUNK,
            "deep_tape_requests": len(deep_budget) * 2,
            "symbols_requested": len(symbols)},
        "packets_sealed": len(packets),
        "law": "measurements only; PULSE does not predict and holds "
               "no capital authority",
        "decision_power": "NONE_STATE"}

    if persist:
        RESULTS.mkdir(parents=True, exist_ok=True)
        seen = set()
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines():
                if line.strip():
                    try:
                        seen.add(json.loads(line).get("state_id"))
                    except json.JSONDecodeError:
                        continue
        written = 0
        with LEDGER.open("a") as fh:
            for p in packets:
                if p["state_id"] in seen:
                    continue
                fh.write(json.dumps(p) + "\n")
                seen.add(p["state_id"])
                written += 1
        cycle["packets_written"] = written
        cycle["packets_deduplicated"] = len(packets) - written
        chain_append(CYCLE_LOG, cycle)
    return {"cycle": cycle, "packets": packets}


def _count(elig_map):
    out = {}
    for e in elig_map.values():
        out[e["reason"]] = out.get(e["reason"], 0) + 1
    return dict(sorted(out.items()))


if __name__ == "__main__":
    out = run_cycle(persist="--dry-run" not in sys.argv,
                    enable_deep="--no-deep" not in sys.argv)
    c = out["cycle"]
    print(json.dumps({"session": c["market_session"],
                      "universe_version":
                          c["universe"]["universe_version"],
                      "subjects": c["universe"]["disposition"]["counts"],
                      "enrichment": c["enrichment"],
                      "packets": c["packets_sealed"],
                      "written": c.get("packets_written"),
                      "latency": c["latency"],
                      "api_calls": c["api_calls"]}, indent=1))
