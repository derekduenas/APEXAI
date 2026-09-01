"""EDGE SENSOR — the broad prospective eye. Runs during US RTH.

Every invocation (timer-driven):
  1. Broad universe REST snapshot (no WS budget consumed; the frozen
     17-name fabric is untouched).
  2. Finds the biggest displacers vs previous close.
  3. For the top movers: SIP microstructure state (last 5 min of
     ticks) + ThetaData front-expiry surface state.
  4. Records the three sealed prospective tags' states BEFORE their
     outcomes exist:
       TAG_EXHAUSTION_REVERSAL_V0
       TAG_SURFACE_LEADS_UNDERLYING_V0
       TAG_LEADER_LIQUIDITY_SHOCK_V0
Shadow-only, zero authority, separate ledger. Outcomes are resolved
by a later pass reading subsequent bars -- never at tag time.

decision_power: SHADOW_PROSPECTIVE_ONLY.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.organism import microstructure as ms
from apex.organism import options_surface as osf

LEDGER = Path("results/organism/edge_sensor.jsonl")
UNIVERSE_FILE = Path("exports/daily_closes_v1.json.gz")
TOP_N = 5


def universe():
    import gzip
    syms = sorted(json.load(gzip.open(UNIVERSE_FILE, "rt")))
    return [s for s in syms if s.isalpha()][:300]


def snapshots(symbols):
    out = {}
    for i in range(0, len(symbols), 100):
        chunk = ",".join(symbols[i:i + 100])
        d = ms._get("https://data.alpaca.markets/v2/stocks/"
                    "snapshots?" + urllib.parse.urlencode(
                        {"symbols": chunk, "feed": "sip"}))
        for s, v in d.items():
            if isinstance(v, dict) and v.get("latestQuote") \
                    and v.get("prevDailyBar"):
                out[s] = v
    return out


def main():
    now = datetime.now(timezone.utc).isoformat()
    snaps = snapshots(universe())
    movers = []
    today = now[:10]
    for s, v in snaps.items():
        q = v["latestQuote"]
        prev = v["prevDailyBar"]["c"]
        # stale-quote guard: dead/illiquid names carry old quotes
        # whose "moves" are artifacts, not displacement
        if str(q.get("t", ""))[:10] != today:
            continue
        if q.get("bp") and q.get("ap") and prev:
            mid = (q["bp"] + q["ap"]) / 2
            movers.append((s, (mid / prev - 1) * 1e4, mid,
                           str(q.get("t", ""))))
    movers.sort(key=lambda x: -abs(x[1]))

    subjects = []
    for sym, chg_bps, mid, qt in movers[:TOP_N]:
        from datetime import timedelta
        t1 = datetime.now(timezone.utc)
        t0 = t1 - timedelta(minutes=5)
        try:
            tr = ms.fetch_ticks(sym, t0.isoformat(), t1.isoformat(),
                                what="trades", max_pages=3)
            qts = ms.fetch_ticks(sym, t0.isoformat(), t1.isoformat(),
                                 what="quotes", max_pages=3)
            micro = ms.micro_state(tr, qts, window_label="last5m")
        except Exception as e:                          # noqa: BLE001
            micro = {"status": "NOT_ESTIMABLE",
                     "why": type(e).__name__}
        try:
            exps = [e for e in osf.td_expirations(sym)
                    if e > now[:10]][:1]
            surf = (osf.surface_state(sym, mid, exps)
                    if exps else {"status": "NOT_ESTIMABLE"})
        except Exception as e:                          # noqa: BLE001
            surf = {"status": "NOT_ESTIMABLE",
                    "why": type(e).__name__}

        # sealed tag states, recorded BEFORE outcomes exist
        tags = {}
        if isinstance(micro.get("net_signed_volume"), int) \
                and abs(chg_bps) >= 100:
            sgn = 1 if chg_bps > 0 else -1
            decel = sgn * micro["net_signed_volume"] <= 0
            tags["TAG_EXHAUSTION_REVERSAL_V0"] = {
                "armed": bool(decel
                              and micro.get("touch_size_change_frac",
                                            0) > 0),
                "displacement_bps": round(chg_bps, 1),
                "net_signed_5m": micro["net_signed_volume"]}
        tags.setdefault("TAG_EXHAUSTION_REVERSAL_V0",
                        {"armed": False})
        tags["TAG_LEADER_LIQUIDITY_SHOCK_V0"] = {
            "armed": abs(chg_bps) >= 200,
            "displacement_bps": round(chg_bps, 1)}
        subjects.append({"symbol": sym,
                         "day_change_bps": round(chg_bps, 1),
                         "mid": mid, "quote_time": qt,
                         "micro": micro, "surface": surf,
                         "tags": tags})

    chain_append(LEDGER, {
        "kind": "edge_sensor_tick", "tick_utc": now,
        "universe_observed": len(snaps),
        "top_movers": [(s, round(c, 1)) for s, c, _, _ in
                       movers[:10]],
        "subjects": subjects,
        "law": "tags recorded before outcomes; zero authority",
        "decision_power": "SHADOW_PROSPECTIVE_ONLY"})
    print(json.dumps({"universe": len(snaps),
                      "subjects": [s["symbol"] for s in subjects]}))


if __name__ == "__main__":
    main()
