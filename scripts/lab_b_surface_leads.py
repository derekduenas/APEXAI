"""LAB B — OPTIONS / UNDERLYING DISAGREEMENT (sealed, pre-outcome).

Registered EDGE-EXTRACTION-SPRINT-LABS-2026-08-30. Sealed trigger:
15-min front-expiry ATM straddle mid change >= +10% while the
underlying's |15-min move| <= 0.5x the straddle-implied per-15-min
budget. Outcomes: underlying |move| and signed move next 30/60 min,
vs matched quiet windows in the same sessions without the jump.

Data: ThetaData v3 historical 5-min option NBBO (the recovered
feed), Alpaca minute bars for the underlying.
decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.organism import microstructure as ms
from apex.organism import options_surface as osf

SYM = "SPY"
N_SESSIONS = 60
JUMP = 0.10
QUIET_FRAC = 0.5
GRAVE = Path("results/edge_atlas/lab_b_surface_leads.jsonl")


def bars(day):
    d = ms._get("https://data.alpaca.markets/v2/stocks/"
                f"{SYM}/bars?" + urllib.parse.urlencode(
                    {"start": f"{day}T13:30:00Z",
                     "end": f"{day}T20:00:00Z",
                     "timeframe": "1Min", "feed": "sip",
                     "limit": 10000}))
    return {b["t"]: b["c"] for b in d.get("bars") or []}


def sessions(n):
    out, d = [], datetime(2026, 8, 28, tzinfo=timezone.utc)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return sorted(out)


def straddle_series(day, exp, strike):
    """5-min straddle mid series for one session."""
    legs = {}
    for right in ("C", "P"):
        rows = osf.td_history_quote(SYM, exp, strike, right, day,
                                    interval="5m")
        legs[right] = {r["t"]: (r["bid"] + r["ask"]) / 2
                       for r in rows}
    out = {}
    for t, c in legs.get("C", {}).items():
        p = legs.get("P", {}).get(t)
        if p and c > 0.05 and p > 0.05:
            out[t] = c + p
    return out


def main():
    days = sessions(N_SESSIONS)
    exps = osf.td_expirations(SYM)
    trig_rows, quiet_rows = [], []
    used = 0
    for day in days:
        px = bars(day)
        if len(px) < 300:
            continue
        keys = sorted(px)
        open_px = px[keys[0]]
        # front expiry strictly after the session; ATM = nearest
        # strike to the session open (integer for SPY)
        exp = next((e for e in exps if e > day), None)
        if not exp:
            continue
        strike = float(round(open_px))
        st = straddle_series(day, exp, strike)
        if len(st) < 30:
            continue
        used += 1
        stk = sorted(st)
        for i in range(3, len(stk) - 12):
            t0, t1 = stk[i - 3], stk[i]      # 15-min window
            s0, s1 = st[t0], st[t1]
            jump = s1 / s0 - 1
            # underlying move over same window + implied budget
            b0 = t0.replace(".000", "") + "Z"
            b1 = t1.replace(".000", "") + "Z"
            # ThetaData stamps ET local; convert to the bar keys
            def bar_at(ts):
                dt = datetime.fromisoformat(ts.split(".")[0])
                dt = dt + timedelta(hours=4)       # ET->UTC approx
                k = dt.strftime("%Y-%m-%dT%H:%M:00Z")
                return px.get(k)
            u0, u1 = bar_at(t0), bar_at(t1)
            if not u0 or not u1:
                continue
            umove = abs(u1 / u0 - 1) * 1e4
            budget = s1 / u1 * 1e4        # straddle as bps of spot
            per15 = budget / math.sqrt(26)  # ~26 15-min slots/day
            rec = None
            if jump >= JUMP and umove <= QUIET_FRAC * per15:
                rec = trig_rows
            elif abs(jump) < 0.02 and umove <= QUIET_FRAC * per15 \
                    and len(quiet_rows) < 4000:
                rec = quiet_rows
            if rec is not None:
                fwd = {}
                for m in (30, 60):
                    dt1 = datetime.fromisoformat(
                        t1.split(".")[0]) + timedelta(hours=4,
                                                      minutes=m)
                    k = dt1.strftime("%Y-%m-%dT%H:%M:00Z")
                    if k in px:
                        fwd[m] = {
                            "abs_bps": round(
                                abs(px[k] / u1 - 1) * 1e4, 2),
                            "signed_bps": round(
                                (px[k] / u1 - 1) * 1e4, 2)}
                if fwd:
                    rec.append({"day": day, "t": t1,
                                "straddle_jump": round(jump, 3),
                                "umove_bps": round(umove, 1),
                                "fwd": fwd})
    print(json.dumps({"sessions_used": used,
                      "triggers": len(trig_rows),
                      "quiet_controls": len(quiet_rows)}),
          flush=True)

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for r in trig_rows:
            g.write(json.dumps({"kind": "lab_b_trigger", **r})
                    + "\n")
    cells = []
    for label, sub in (("TRIGGER", trig_rows),
                       ("QUIET_CONTROL", quiet_rows)):
        for m in (30, 60):
            av = [r["fwd"][m]["abs_bps"] for r in sub
                  if m in r["fwd"]]
            sv = [r["fwd"][m]["signed_bps"] for r in sub
                  if m in r["fwd"]]
            rec = {"kind": "lab_b_cell",
                   "id": f"LABB_{label}_{m}m", "n": len(av)}
            if len(av) >= 25:
                rec.update({
                    "abs_move_mean_bps": round(
                        statistics.mean(av), 1),
                    "abs_move_median_bps": round(
                        statistics.median(av), 1),
                    "signed_mean_bps": round(
                        statistics.mean(sv), 1)})
            else:
                rec["verdict"] = "INSUFFICIENT_N"
            cells.append(rec)
            with GRAVE.open("a") as g:
                g.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
