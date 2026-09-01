"""LAB C — CROSS-DOMAIN INFORMATION SHOCK (sealed, pre-outcome).

Registered EDGE-EXTRACTION-SPRINT-LABS-2026-08-30. Predicts the
LEADER only; peer-following as a trade stays KILLED (E-P1).

Sealed: leader 30-min |move| >= 2% within a SIC-4 group (>=2
members); joint state = (peer confirmation at episode time) x
(leader liquidity proxy = episode relative volume). Outcomes: leader
forward 60-min and close returns net of the observed toll surface.

IMPLEMENTATION DISCLOSURE (performance, not tuning): symbol-days are
prescanned with the daily-closes cache, and only days where the
leader's |close-to-close| >= 1.5% are read at minute level. A 30-min
2% move on a <1.5% day is possible (full round trip); those episodes
are missed and the miss is a stated corpus limitation, chosen before
outcomes were seen.

decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import gzip
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SN = Path("/apex-data/history-b/pit_singlename/bars")
PEERS = Path("exports/peer_map_v1.json")
CLOSES = Path("exports/daily_closes_v1.json.gz")
TOLL = Path("/apex-data/history-b/pit_singlename/"
            "movement_toll_obs.jsonl")
GRAVE = Path("results/edge_atlas/lab_c_leader_shock.jsonl")
NY = ZoneInfo("America/New_York")
MOVE = 200.0            # 30-min bps threshold, sealed
PRESCAN = 0.015         # disclosed performance preselection


def minute_closes(sym, day):
    f = SN / f"{sym}_{day}.json"
    if not f.exists():
        return None
    try:
        bars = json.loads(f.read_text())["bars"]
    except Exception:                                   # noqa: BLE001
        return None
    px, vol = {}, {}
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            px[m] = b["close"]
            vol[m] = b.get("volume", 0)
    return px, vol


def main():
    pm = json.loads(PEERS.read_text())["map"]
    groups = defaultdict(list)
    for s, m in pm.items():
        groups[m["sic4"]].append(s)
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    member = {s: k for k, v in groups.items() for s in v}

    closes = json.load(gzip.open(CLOSES, "rt"))

    per = defaultdict(list)
    for line in TOLL.open():
        try:
            r = json.loads(line)
        except Exception:                               # noqa: BLE001
            continue
        if r.get("cohort") == "SINGLE" and r.get("toll") is not None:
            per[r["symbol"]].append(r["toll"])
    toll_med = {s: statistics.median(v) for s, v in per.items()
                if len(v) >= 20}
    all_toll = statistics.median(
        [t for v in per.values() for t in v]) if per else 0.0005

    def rt_bps(sym):
        return 2 * toll_med.get(sym, all_toll) * 1.34 * 1e4 + 0.05

    # prescan candidate leader-days
    cands = []
    for sym in member:
        cs = closes.get(sym)
        if not cs:
            continue
        days = sorted(cs)
        for a, b in zip(days, days[1:]):
            if abs(math.log(cs[b] / cs[a])) >= PRESCAN:
                cands.append((sym, b))
    print(json.dumps({"groups": len(groups),
                      "candidate_leader_days": len(cands)}),
          flush=True)

    episodes = []
    day_cache = {}
    for sym, day in cands:
        got = minute_closes(sym, day)
        if not got:
            continue
        px, vol = got
        ms_ = sorted(px)
        if len(ms_) < 200:
            continue
        # first qualifying 30-min move, episodes end by 14:30 ET
        ep = None
        for m in ms_:
            m0 = m - 30
            if m0 in px and m <= 870 and 600 <= m:
                r = math.log(px[m] / px[m0]) * 1e4
                if abs(r) >= MOVE:
                    ep = (m, r)
                    break
        if not ep:
            continue
        m_end, disp = ep
        sgn = 1 if disp > 0 else -1
        # liquidity proxy: episode volume vs same-day pre-episode
        v_ep = sum(v for k, v in vol.items() if m_end - 30 <= k < m_end)
        v_pre = sum(v for k, v in vol.items() if 570 <= k < m_end - 30)
        rvol = v_ep / max(v_pre / max((m_end - 600), 1) * 30, 1)
        # peer confirmation at episode end
        confirms, n_peers = 0, 0
        for peer in groups[member[sym]]:
            if peer == sym:
                continue
            key = (peer, day)
            if key not in day_cache:
                day_cache[key] = minute_closes(peer, day)
            got_p = day_cache[key]
            if not got_p:
                continue
            ppx = got_p[0]
            if m_end in ppx and (m_end - 30) in ppx:
                pr = math.log(ppx[m_end] / ppx[m_end - 30]) * 1e4
                n_peers += 1
                if sgn * pr >= 50:
                    confirms += 1
        if n_peers == 0:
            continue
        conf = confirms / n_peers >= 0.5
        hi_liq_stress = rvol >= 3.0
        # outcomes: continuation convention (same direction as disp)
        fwd = {}
        if m_end + 60 in px:
            fwd["60m"] = round(sgn * math.log(
                px[m_end + 60] / px[m_end]) * 1e4 - rt_bps(sym), 1)
        fwd["close"] = round(sgn * math.log(
            px[ms_[-1]] / px[m_end]) * 1e4 - rt_bps(sym), 1)
        episodes.append({"sym": sym, "day": day, "year": day[:4],
                         "disp_bps": round(disp, 1),
                         "peer_confirmed": conf,
                         "rvol_stress": hi_liq_stress,
                         "n_peers": n_peers, "fwd": fwd})
    print(json.dumps({"episodes": len(episodes)}), flush=True)

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for e in episodes:
            g.write(json.dumps({"kind": "lab_c_episode", **e})
                    + "\n")
    for conf in (True, False):
        for stress in (True, False):
            sub = [e for e in episodes
                   if e["peer_confirmed"] == conf
                   and e["rvol_stress"] == stress]
            for h in ("60m", "close"):
                vals = [e["fwd"][h] for e in sub if h in e["fwd"]]
                rec = {"kind": "lab_c_cell",
                       "id": f"LABC_conf{int(conf)}_"
                             f"stress{int(stress)}_cont_{h}",
                       "n": len(vals)}
                if len(vals) >= 40:
                    yrs = defaultdict(list)
                    for e in sub:
                        if h in e["fwd"]:
                            yrs[e["year"]].append(e["fwd"][h])
                    ym = {y: round(statistics.mean(v), 1)
                          for y, v in sorted(yrs.items())
                          if len(v) >= 10}
                    rec.update({
                        "mean_net_bps": round(
                            statistics.mean(vals), 1),
                        "median_net_bps": round(
                            statistics.median(vals), 1),
                        "win": round(sum(1 for v in vals if v > 0)
                                     / len(vals), 3),
                        "pos_years": f"{sum(1 for v in ym.values() if v > 0)}"
                                     f"/{len(ym)}",
                        "by_year": ym})
                else:
                    rec["verdict"] = "INSUFFICIENT_N"
                with GRAVE.open("a") as g:
                    g.write(json.dumps(rec) + "\n")
                print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
