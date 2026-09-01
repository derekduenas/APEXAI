"""Preprocess the replay input file for the Historical Monster
Diagnostic: one row per event with checkpoint short-PnLs (SPY-resid),
gap, first-30m sign, and the observed event-time RT where measured.
Pure outcome bookkeeping -- consumed by the strict-clock engine only
AFTER each decision is persisted. decision_power: NONE_DATA_PREP.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATASET = Path("exports/event_dataset.jsonl")
FRICTION = Path("results/event_sprint/event_friction_obs.jsonl")
SN = Path("/apex-data/history-b/pit_singlename/bars")
ETF = Path("/apex-data/history-b/etf_continuous/bars")
OUT = Path("exports/replay_inputs.jsonl")
NY = ZoneInfo("America/New_York")
CP = {"open": 570, "+1m": 571, "+5m": 575, "+15m": 585, "10:00": 600}


def rth(base, sym, d):
    try:
        bars = json.loads((base / f"{sym}_{d}.json").read_text())["bars"]
    except Exception:
        return None
    out = []
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            out.append((m, b))
    return out or None


def pxa(r, minute):
    for m, b in r:
        if m >= minute:
            return b["close"]
    return None


def main():
    fric = {}
    for l in FRICTION.read_text().splitlines():
        o = json.loads(l)
        if o.get("rt_exec_bps") is not None:
            fric[(o["symbol"], o["session"])] = o["rt_exec_bps"]
    spy = {}
    n = 0
    with OUT.open("w") as out:
        for l in DATASET.open():
            r = json.loads(l)
            d = r["reaction_session"]
            a = rth(SN, r["symbol"], d)
            if d not in spy:
                spy[d] = rth(ETF, "SPY", d)
            s = spy[d]
            if not a or not s:
                continue
            ac, sc = a[-1][1]["close"], s[-1][1]["close"]
            pnl = {}
            for k, m in CP.items():
                if k == "open":
                    e, se = a[0][1]["open"], s[0][1]["open"]
                else:
                    e, se = pxa(a, m), pxa(s, m)
                if e and se and e > 0:
                    pnl[k] = round(
                        -((ac / e - 1) - (sc / se - 1)) * 1e4, 2)
            out.write(json.dumps({
                "symbol": r["symbol"], "session": d,
                "timing": r["timing"],
                "surprise": ("NEGATIVE" if r["sue_price"] < 0 else
                             "POSITIVE" if r["sue_price"] > 0 else
                             "SMALL_NEUTRAL"),
                "gap_res": r.get("gap_res"),
                "r30_res": r.get("r30_res"),
                "short_pnl_bps": pnl,
                "observed_rt_bps": fric.get((r["symbol"], d))}) + "\n")
            n += 1
    print(json.dumps({"rows": n, "out": str(OUT)}))


if __name__ == "__main__":
    main()
