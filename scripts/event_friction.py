"""D. EVENT-TIME EXECUTION FRICTION -- real NBBO around reactions.

For every negative-surprise event (and an every-5th sample of the
remaining events), fetch actual historical SIP NBBO quotes at the
executable entry window (09:34:30-09:35:30 ET, matching the +5m
characterization point) and the exit window (15:54:30-15:55:30 ET) of
the reaction session. Report entry spread, exit spread, and the
executable round trip under the sealed model
(0.5*entry + 0.5*exit + fees + 0.25*adverse allowance).
friction_provenance: OBSERVED_SIP_NBBO. No trading, no tuning.
"""
from __future__ import annotations

import json
import os
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATASET = Path("exports/event_dataset.jsonl")
OUT = Path("results/event_sprint/event_friction.json")
API = "https://data.alpaca.markets/v2/stocks/{sym}/quotes"
NY = ZoneInfo("America/New_York")
FEES_BPS = 0.05
ADVERSE_MULT = 0.25


def _get(url):
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if a == 3:
                return None
            import time
            time.sleep(1.5 ** a)


def spread_bps(sym, date, et_hm):
    """median NBBO relative spread (bps) in a 60s window."""
    h, m = et_hm
    start = datetime(int(date[:4]), int(date[5:7]), int(date[8:10]),
                     h, m, 30, tzinfo=NY)
    end = start.replace(second=59)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    q = {"start": start.astimezone(timezone.utc).strftime(fmt),
         "end": end.astimezone(timezone.utc).strftime(fmt),
         "limit": 500, "feed": "sip"}
    d = _get(API.format(sym=sym) + "?" + urllib.parse.urlencode(q))
    if not d or not d.get("quotes"):
        return None
    vals = []
    for x in d["quotes"]:
        bp, ap = x.get("bp"), x.get("ap")
        if bp and ap and ap > bp > 0:
            mid = 0.5 * (ap + bp)
            vals.append((ap - bp) / mid * 1e4)
    return statistics.median(vals) if vals else None


def main():
    rows = [json.loads(l) for l in DATASET.open()]
    neg = [r for r in rows if r["sue_price"] < 0]
    others = [r for r in rows if r["sue_price"] >= 0][::5]
    obs = []
    for tag, group in (("NEG", neg), ("OTHER_SAMPLE", others)):
        for i, r in enumerate(group):
            e = spread_bps(r["symbol"], r["reaction_session"], (9, 35))
            x = spread_bps(r["symbol"], r["reaction_session"], (15, 55))
            rec = {"tag": tag, "symbol": r["symbol"],
                   "session": r["reaction_session"],
                   "timing": r["timing"],
                   "entry_spread_bps": round(e, 2) if e else None,
                   "exit_spread_bps": round(x, 2) if x else None}
            if e is not None and x is not None:
                adverse = 0.5 * e            # declared allowance basis
                rec["rt_exec_bps"] = round(
                    0.5 * e + 0.5 * x + FEES_BPS
                    + ADVERSE_MULT * adverse, 2)
            obs.append(rec)
            if (i + 1) % 100 == 0:
                print(json.dumps({"tag": tag, "done": i + 1}),
                      flush=True)

    def summ(group_tag, timing=None):
        rts = [o["rt_exec_bps"] for o in obs
               if o["tag"] == group_tag and o.get("rt_exec_bps")
               and (timing is None or o["timing"] == timing)]
        es = [o["entry_spread_bps"] for o in obs
              if o["tag"] == group_tag and o.get("entry_spread_bps")
              and (timing is None or o["timing"] == timing)]
        xs = [o["exit_spread_bps"] for o in obs
              if o["tag"] == group_tag and o.get("exit_spread_bps")
              and (timing is None or o["timing"] == timing)]
        if len(rts) < 10:
            return {"n": len(rts), "verdict": "INSUFFICIENT_N"}
        pct = lambda v, p: sorted(v)[int(p * len(v))]     # noqa: E731
        return {"n": len(rts),
                "entry_spread_median_bps": round(
                    statistics.median(es), 2),
                "exit_spread_median_bps": round(
                    statistics.median(xs), 2),
                "rt_base_median_bps": round(statistics.median(rts), 2),
                "rt_base_mean_bps": round(statistics.mean(rts), 2),
                "rt_base_p90_bps": round(pct(rts, 0.9), 2),
                "rt_stress2x_median_bps": round(
                    2 * statistics.median(rts), 2)}

    report = {"kind": "event_time_friction",
              "id": "EVENT-TIME-FRICTION-2026-08-30",
              "friction_provenance": "OBSERVED_SIP_NBBO",
              "entry_window_et": "09:35:30-09:35:59",
              "exit_window_et": "15:55:30-15:55:59",
              "model": "0.5*entry + 0.5*exit + 0.05 fees + "
                       "0.25*(0.5*entry) adverse",
              "NEG_all": summ("NEG"),
              "NEG_pm_only": summ("NEG", "pm"),
              "OTHER_SAMPLE": summ("OTHER_SAMPLE"),
              "coverage": {
                  "neg_requested": len(neg),
                  "neg_with_both_quotes": sum(
                      1 for o in obs if o["tag"] == "NEG"
                      and o.get("rt_exec_bps") is not None)}}
    OUT.write_text(json.dumps(report, indent=1))
    Path("results/event_sprint/event_friction_obs.jsonl").write_text(
        "\n".join(json.dumps(o) for o in obs))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
