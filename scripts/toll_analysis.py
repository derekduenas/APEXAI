"""LAYER A FULL ANALYSIS — movement, executable toll, and the ratio.

QUOTED SPREAD IS NOT THE TOLL (operator instruction). The executable
round-trip model, predeclared:

    RT_exec = 0.5 x entry_spread          (marketable entry vs mid)
            + 0.5 x exit_spread           (marketable exit vs mid)
            + FEES (0.05 bps, SEC/TAF sell side, zero commission)
            + ADVERSE ALLOWANCE (0.25 x mean(entry, exit) spread)

Reported alongside its FLOOR (half+half+fees, no allowance) and its
CEILING (full quoted spread both ways) so the allowance choice hides
nothing. Exit spreads come from a deterministic subsample of real
t+60m quotes (--exit-pass); where unavailable, exit_spread =
entry_spread is used and flagged EXIT_ASSUMED_ENTRY.

decision_power: NONE_TERRAIN_MEASUREMENT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OBS = Path("/apex-data/history-b/pit_singlename/"
           "movement_toll_obs.jsonl")
EXITQ = Path("/apex-data/history-b/pit_singlename/"
             "exit_quotes.jsonl")
FEES_BPS = 0.05
NY = ZoneInfo("America/New_York")


def _get(url):
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for a in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:                              # noqa: BLE001
            if a == 3:
                return {}
            time.sleep(1 + a)


def load_obs():
    out = []
    for l in OBS.read_text().splitlines():
        try:
            o = json.loads(l)
        except Exception:                              # noqa: BLE001
            continue
        if o.get("toll") and o.get("fwd60") is not None \
                and o.get("friction_provenance") == "OBSERVED_SIP_NBBO":
            out.append(o)
    return out


def exit_pass(n_target=2000):
    """Deterministic subsample: fetch the REAL quote at t+60m."""
    obs = load_obs()
    obs.sort(key=lambda o: hashlib.sha256(
        f"{o['symbol']}:{o['day']}:{o['slot']}".encode()).hexdigest())
    sample = obs[:n_target]
    done = set()
    if EXITQ.exists():
        for l in EXITQ.read_text().splitlines():
            try:
                r = json.loads(l)
                done.add((r["symbol"], r["day"], r["slot"]))
            except Exception:                          # noqa: BLE001
                continue
    with EXITQ.open("a") as fh:
        for i, o in enumerate(sample):
            key = (o["symbol"], o["day"], o["slot"])
            if key in done:
                continue
            hh, mm = int(o["slot"][:2]), int(o["slot"][3:])
            t0 = datetime(int(o["day"][:4]), int(o["day"][5:7]),
                          int(o["day"][8:]), hh, mm, tzinfo=NY)
            tx = (t0 + timedelta(minutes=60)) \
                .astimezone(ZoneInfo("UTC"))
            q = _get("https://data.alpaca.markets/v2/stocks/"
                     + o["symbol"] + "/quotes?"
                     + urllib.parse.urlencode(
                         {"start": (tx - timedelta(minutes=1))
                          .isoformat(), "end": tx.isoformat(),
                          "limit": 60, "feed": "sip"}))
            spreads = sorted(
                (x["ap"] - x["bp"]) / ((x["ap"] + x["bp"]) / 2)
                for x in (q.get("quotes") or [])
                if x.get("ap") and x.get("bp")
                and x["ap"] > x["bp"] > 0)
            fh.write(json.dumps(
                {"symbol": o["symbol"], "day": o["day"],
                 "slot": o["slot"], "cohort": o["cohort"],
                 "exit_spread": spreads[len(spreads) // 2]
                 if spreads else None}) + "\n")
            if (i + 1) % 200 == 0:
                fh.flush()
                print(json.dumps({"exit_quotes": i + 1}), flush=True)
    print("exit pass done")


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else None


def analyze():
    obs = load_obs()
    exitq = {}
    if EXITQ.exists():
        for l in EXITQ.read_text().splitlines():
            try:
                r = json.loads(l)
                if r.get("exit_spread"):
                    exitq[(r["symbol"], r["day"], r["slot"])] = \
                        r["exit_spread"]
            except Exception:                          # noqa: BLE001
                continue

    # exit/entry spread relationship from the measured subsample
    ratio_by_cohort = defaultdict(list)
    for o in obs:
        ex = exitq.get((o["symbol"], o["day"], o["slot"]))
        if ex:
            ratio_by_cohort[o["cohort"]].append(ex / o["toll"])
    exit_ratio = {c: round(st.median(v), 3)
                  for c, v in ratio_by_cohort.items() if v}

    def toll_exec(o):
        ex = exitq.get((o["symbol"], o["day"], o["slot"]))
        flag = "EXIT_MEASURED" if ex else "EXIT_ASSUMED_ENTRY"
        ex = ex if ex else o["toll"]
        s_in, s_out = o["toll"], ex
        floor = 0.5 * s_in + 0.5 * s_out + FEES_BPS / 1e4
        exec_ = floor + 0.25 * (s_in + s_out) / 2
        ceil = s_in + s_out
        return floor, exec_, ceil, flag

    report = {"generated": datetime.utcnow().isoformat(),
              "exit_spread_over_entry_median": exit_ratio,
              "cohorts": {}, "by_year": {}, "cuts": {}}
    for cohort in ("ETF", "SINGLE"):
        rows = [o for o in obs if o["cohort"] == cohort]
        if not rows:
            continue
        spreads = [o["toll"] * 1e4 for o in rows]
        execs = [toll_exec(o)[1] * 1e4 for o in rows]
        moves60 = [abs(o["fwd60"]) * 1e4 for o in rows]
        r60 = [abs(o["fwd60"]) / toll_exec(o)[1] for o in rows]
        r15 = [abs(o["fwd15"]) / toll_exec(o)[1] for o in rows
               if o.get("fwd15") is not None]
        # tail integrity
        total = sum(moves60)
        top5 = sum(sorted(moves60)[-max(1, len(moves60) // 20):])
        # spread/vol coupling: ratio by prior-vol tercile
        byvol = defaultdict(list)
        vols = sorted(o["prior_60m_absmove"] for o in rows)
        t1, t2 = pct(vols, 1 / 3), pct(vols, 2 / 3)
        for o in rows:
            v = o["prior_60m_absmove"]
            tier = "LOWVOL" if v <= t1 else \
                "MIDVOL" if v <= t2 else "HIGHVOL"
            byvol[tier].append(abs(o["fwd60"]) / toll_exec(o)[1])
        report["cohorts"][cohort] = {
            "n": len(rows),
            "quoted_spread_bps": {"med": round(st.median(spreads), 2),
                                  "p90": round(pct(spreads, .9), 2)},
            "executable_rt_bps": {"med": round(st.median(execs), 2),
                                  "p90": round(pct(execs, .9), 2)},
            "move60_bps_med": round(st.median(moves60), 1),
            "MT60": {p: round(pct(r60, q), 1) for p, q in
                     (("med", .5), ("p75", .75), ("p90", .9),
                      ("p95", .95))},
            "MT15": {p: round(pct(r15, q), 1) for p, q in
                     (("med", .5), ("p75", .75), ("p90", .9),
                      ("p95", .95))},
            "top5pct_share_of_movement": round(top5 / total, 3),
            "MT60_by_prior_vol": {k: round(st.median(v), 1)
                                  for k, v in sorted(byvol.items())},
        }
        yr = defaultdict(lambda: defaultdict(list))
        for o in rows:
            y = o["day"][:4]
            yr[y]["spread"].append(o["toll"] * 1e4)
            yr[y]["mt"].append(abs(o["fwd60"]) / toll_exec(o)[1])
        report["by_year"][cohort] = {
            y: {"spread_med": round(st.median(d["spread"]), 2),
                "MT60_med": round(st.median(d["mt"]), 1)}
            for y, d in sorted(yr.items())}
        bytod = defaultdict(list)
        for o in rows:
            bytod[o["slot"]].append(abs(o["fwd60"]) / toll_exec(o)[1])
        report["cuts"][cohort] = {
            "MT60_by_slot": {k: round(st.median(v), 1)
                             for k, v in sorted(bytod.items())}}
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--exit-pass", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    a = ap.parse_args()
    if a.exit_pass:
        exit_pass()
    if a.analyze:
        analyze()
