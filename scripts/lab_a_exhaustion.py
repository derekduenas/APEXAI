"""LAB A — LIQUIDITY / FLOW EXHAUSTION (sealed design, pre-outcome).

Registered EDGE-EXTRACTION-SPRINT-LABS-2026-08-30. All parameters are
the SEALED ones; nothing here was tuned after seeing outcomes.

Pipeline: minute bars find displacement episodes -> SIP ticks pulled
around each episode -> exhaustion state measured in the 3 minutes
after displacement -> forward mid returns at 5/15/30 min net of the
episode's own median spread.

decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import statistics
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.organism import microstructure as ms

SYMS = ("AAPL", "MSFT", "NVDA", "SPY", "QQQ", "IWM", "XLK", "XLF",
        "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE",
        "XLC")
SESSIONS_BACK = 20
DISP_BPS = 30.0
DISP_MULT = 3.0
GRAVE = Path("results/edge_atlas/lab_a_exhaustion.jsonl")


def bars(symbol, start, end):
    d = ms._get("https://data.alpaca.markets/v2/stocks/"
                f"{symbol}/bars?" + urllib.parse.urlencode(
                    {"start": start, "end": end, "timeframe": "1Min",
                     "feed": "sip", "limit": 10000}))
    return d.get("bars", [])


def sessions(n):
    out, d = [], datetime(2026, 8, 28, tzinfo=timezone.utc)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return sorted(out)


def main():
    days = sessions(SESSIONS_BACK)
    episodes = []
    prior_med: dict = {}
    for sym in SYMS:
        for day in days:
            bs = bars(sym, f"{day}T13:30:00Z", f"{day}T20:00:00Z")
            if len(bs) < 100:
                continue
            mids = [(b["t"], b["c"]) for b in bs]
            r5 = []
            for i in range(5, len(mids)):
                r = (mids[i][1] / mids[i - 5][1] - 1) * 1e4
                r5.append((mids[i][0], r, i))
            med = statistics.median(abs(r) for _, r, _ in r5)
            pm = prior_med.get(sym)
            prior_med[sym] = med
            if pm is None:
                continue
            # sealed: displacement vs PRIOR session median (causal)
            hits, last_i = [], -10
            for t, r, i in r5:
                if abs(r) >= DISP_BPS and abs(r) >= DISP_MULT * pm \
                        and i - last_i >= 10 and i < len(mids) - 35:
                    hits.append((t, r, i))
                    last_i = i
            for t, r, i in hits[:2]:        # cap per symbol-day
                episodes.append({"sym": sym, "day": day, "t_end": t,
                                 "disp_bps": round(r, 1),
                                 "i": i})
    print(json.dumps({"sessions": len(days),
                      "episodes": len(episodes)}), flush=True)

    rows = []
    for ep in episodes:
        t_end = datetime.fromisoformat(
            ep["t_end"].replace("Z", "+00:00"))
        t0 = (t_end - timedelta(minutes=5)).isoformat()
        t3 = (t_end + timedelta(minutes=3)).isoformat()
        try:
            tr_d = ms.fetch_ticks(ep["sym"], t0, t_end.isoformat(),
                                  what="trades", max_pages=4)
            qt_d = ms.fetch_ticks(ep["sym"], t0, t_end.isoformat(),
                                  what="quotes", max_pages=4)
            tr_a = ms.fetch_ticks(ep["sym"], t_end.isoformat(), t3,
                                  what="trades", max_pages=4)
            qt_a = ms.fetch_ticks(ep["sym"], t_end.isoformat(), t3,
                                  what="quotes", max_pages=4)
        except Exception as e:                          # noqa: BLE001
            continue
        d_state = ms.micro_state(tr_d, qt_d)
        a_state = ms.micro_state(tr_a, qt_a)
        if d_state.get("status") or a_state.get("status"):
            continue
        sgn = 1 if ep["disp_bps"] > 0 else -1
        d_flow = sgn * d_state["net_signed_volume"] \
            / max((5 * 60), 1)
        a_flow = sgn * a_state["net_signed_volume"] \
            / max((3 * 60), 1)
        exhausted = (a_flow <= 0.5 * d_flow if d_flow > 0
                     else False) and \
            a_state["touch_size_change_frac"] > 0
        # forward outcomes from bars of that day
        bs = bars(ep["sym"],
                  (t_end - timedelta(minutes=1)).isoformat(),
                  (t_end + timedelta(minutes=35)).isoformat())
        px = {b["t"]: b["c"] for b in bs}
        keys = sorted(px)
        if not keys:
            continue
        p0 = px[keys[0]]
        fwd = {}
        for m in (5, 15, 30):
            tgt = (t_end + timedelta(minutes=m)).strftime(
                "%Y-%m-%dT%H:%M:00Z")
            if tgt in px:
                # reversal convention: profit if price moves AGAINST
                # the displacement direction
                fwd[m] = round(-sgn * (px[tgt] / p0 - 1) * 1e4
                               - d_state["spread_bps_median"], 2)
        rows.append({"kind": "lab_a_episode", **ep,
                     "exhausted": exhausted,
                     "disp_flow_rate": round(d_flow, 1),
                     "after_flow_rate": round(a_flow, 1),
                     "touch_recovery":
                         a_state["touch_size_change_frac"],
                     "spread_bps": d_state["spread_bps_median"],
                     "reversal_net_bps": fwd})
        print(json.dumps({"ep": f"{ep['sym']} {ep['t_end']}",
                          "exhausted": exhausted,
                          "fwd": fwd}), flush=True)

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for r in rows:
            g.write(json.dumps(r) + "\n")

    # sealed cells: exhausted vs not x horizon
    for label, sub in (("EXHAUSTED", [r for r in rows
                                      if r["exhausted"]]),
                       ("NOT_EXHAUSTED", [r for r in rows
                                          if not r["exhausted"]])):
        for m in (5, 15, 30):
            vals = [r["reversal_net_bps"][m] for r in sub
                    if m in r["reversal_net_bps"]
                    or str(m) in r["reversal_net_bps"]]
            vals = [r["reversal_net_bps"].get(m,
                    r["reversal_net_bps"].get(str(m)))
                    for r in sub]
            vals = [v for v in vals if v is not None]
            rec = {"kind": "lab_a_cell",
                   "id": f"LABA_{label}_rev_{m}m", "n": len(vals)}
            if len(vals) >= 25:
                rec.update({
                    "mean_net_bps": round(statistics.mean(vals), 1),
                    "median_net_bps": round(
                        statistics.median(vals), 1),
                    "win": round(sum(1 for v in vals if v > 0)
                                 / len(vals), 3)})
            else:
                rec["verdict"] = "INSUFFICIENT_N"
            with GRAVE.open("a") as g:
                g.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
