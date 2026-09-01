"""EVENT-ALPHA-SPRINT-V1 -- experiment engine.

Runs the registered hypotheses over the event dataset:

  E1A UNDERREACTION: position in the DIRECTION of the surprise at the
      first tradable moment after the information is public (reaction
      open; multi-session legs enter at reaction close).
  E1B OVERREACTION:  fade the initial residual gap.

Every examined cell (hypothesis x horizon x bucket x tail) is sealed
to the graveyard with event-count denominators. Costs are per-event
measured executable round trips from the Layer A observed-NBBO
surface (per-symbol-year median, singles cohort), BASE = measured,
STRESS = 2x. No thresholds tuned on P&L; buckets and horizons were
pre-registered. decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

DATASET = Path("exports/event_dataset.jsonl")
TOLL_OBS = Path("/apex-data/history-b/pit_singlename/"
                "movement_toll_obs.jsonl")
GRAVE = Path("results/event_sprint/experiments.jsonl")
UPLIFT = 1.34            # sealed executable uplift over quoted median
FEES_BPS = 0.05

OPEN_H = ("r30_res", "r60_res", "r_close_res")
CLOSE_H = ("r1s_res", "r2s_res", "r5s_res", "r10s_res", "r20s_res")
ALL_H = OPEN_H + CLOSE_H
BUCKETS = (1.00, 0.50, 0.25, 0.10, 0.05)


def load_toll_surface():
    per = defaultdict(list)          # (sym, year) -> [toll]
    per_year = defaultdict(list)     # year -> [toll]
    for l in TOLL_OBS.open():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("cohort") != "SINGLE" or r.get("toll") is None:
            continue
        y = r["day"][:4]
        per[(r["symbol"], y)].append(r["toll"])
        per_year[y].append(r["toll"])
    surf = {k: statistics.median(v) for k, v in per.items()
            if len(v) >= 20}
    yr = {y: statistics.median(v) for y, v in per_year.items()}
    return surf, yr


def rt_bps(surf, yr_med, sym, year):
    t = surf.get((sym, year))
    if t is None:
        t = yr_med.get(year)
    if t is None:
        t = statistics.median(yr_med.values()) if yr_med else 1.9e-4
    # quoted spread = 2 x half-spread toll; executable = x uplift + fee
    return 2.0 * t * UPLIFT * 1e4 + FEES_BPS


ledger = []


def cell(cid, rows, direction_fn, horizon, note=""):
    """Seal one examined cell. rows carry ('dir', outcome, rt)."""
    obs = []
    for r in rows:
        d = direction_fn(r)
        v = r.get(horizon)
        if d == 0 or v is None:
            continue
        gross = d * v * 1e4
        obs.append((gross, gross - r["_rt"], gross - 2 * r["_rt"],
                    r["reaction_session"][:4]))
    n = len(obs)
    rec = {"kind": "event_cell", "id": cid, "horizon": horizon,
           "n_events": n, "note": note}
    if n >= 30:
        g = [o[0] for o in obs]
        nb = [o[1] for o in obs]
        ns = [o[2] for o in obs]
        yrs = defaultdict(list)
        for o in obs:
            yrs[o[3]].append(o[1])
        ymeans = {y: round(statistics.mean(v), 1)
                  for y, v in sorted(yrs.items()) if len(v) >= 10}
        rec.update({
            "gross_mean_bps": round(statistics.mean(g), 1),
            "gross_median_bps": round(statistics.median(g), 1),
            "net_base_mean_bps": round(statistics.mean(nb), 1),
            "net_stress_mean_bps": round(statistics.mean(ns), 1),
            "win_rate_net_base": round(
                sum(1 for x in nb if x > 0) / n, 3),
            "base_pos_years": f"{sum(1 for v in ymeans.values() if v > 0)}"
                              f"/{len(ymeans)}",
            "net_base_by_year": ymeans})
    else:
        rec["verdict"] = "INSUFFICIENT_N"
    ledger.append(rec)
    return rec


def main():
    rows = [json.loads(l) for l in DATASET.open()]
    surf, yr_med = load_toll_surface()
    for r in rows:
        r["_rt"] = rt_bps(surf, yr_med, r["symbol"],
                          r["reaction_session"][:4])

    rts = [r["_rt"] for r in rows]
    print(json.dumps({"events": len(rows),
                      "rt_base_bps_median": round(
                          statistics.median(rts), 2),
                      "rt_base_bps_p90": round(
                          sorted(rts)[int(0.9 * len(rts))], 2)}),
          flush=True)

    # ---- E1A: drift in the direction of the surprise --------------
    sgn = lambda x: (x > 0) - (x < 0)                      # noqa: E731
    ranked = sorted(rows, key=lambda r: abs(r["sue_price"]),
                    reverse=True)
    for frac in BUCKETS:
        sub = ranked[:max(1, int(frac * len(ranked)))]
        for hz in ALL_H:
            cell(f"E1A_drift_top{int(frac*100)}pct", sub,
                 lambda r: sgn(r["sue_price"]), hz,
                 "long positive surprise / short negative")
        for tail, keep in (("pos", 1), ("neg", -1)):
            tsub = [r for r in sub if sgn(r["sue_price"]) == keep]
            for hz in ALL_H:
                cell(f"E1A_drift_top{int(frac*100)}pct_{tail}", tsub,
                     lambda r: sgn(r["sue_price"]), hz)

    # ---- E1B: fade the initial residual gap -----------------------
    granked = sorted((r for r in rows if r.get("gap_res") is not None),
                     key=lambda r: abs(r["gap_res"]), reverse=True)
    for frac in BUCKETS:
        sub = granked[:max(1, int(frac * len(granked)))]
        for hz in ALL_H:
            cell(f"E1B_fadegap_top{int(frac*100)}pct", sub,
                 lambda r: -sgn(r["gap_res"]), hz,
                 "fade the residual overnight reaction")
        for tail, keep in (("gapup", 1), ("gapdn", -1)):
            tsub = [r for r in sub if sgn(r["gap_res"]) == keep]
            for hz in ALL_H:
                cell(f"E1B_fadegap_top{int(frac*100)}pct_{tail}", tsub,
                     lambda r: -sgn(r["gap_res"]), hz)

    # ---- E1A-conditional: drift only when gap UNDER-responds ------
    # surprise positive but residual gap small: market slow to move?
    for frac in (0.25, 0.10):
        sub = ranked[:max(1, int(frac * len(ranked)))]
        slow = [r for r in sub if r.get("gap_res") is not None
                and abs(r["gap_res"]) < 0.01]
        for hz in ALL_H:
            cell(f"E1A_muted_gap_top{int(frac*100)}pct", slow,
                 lambda r: sgn(r["sue_price"]), hz,
                 "big surprise, muted (<1pct) residual gap")

    # ---- baselines -----------------------------------------------
    for hz in ALL_H:
        cell("BASE_momentum20", rows,
             lambda r: sgn(r["mom20"]) if r.get("mom20") is not None
             else 0, hz, "no event knowledge")
    # raw surprise direction with zero selectivity == E1A_top100 (dup
    # by construction; recorded above). cash == 0 by definition.

    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for rec in ledger:
            g.write(json.dumps(rec) + "\n")

    scored = [r for r in ledger if "net_base_mean_bps" in r]
    scored.sort(key=lambda r: r["net_base_mean_bps"], reverse=True)
    print(json.dumps({"cells_examined": len(ledger),
                      "cells_scored": len(scored)}), flush=True)
    print("TOP 12 BY NET BASE:", flush=True)
    for r in scored[:12]:
        print(json.dumps(r), flush=True)
    print("BOTTOM 4:", flush=True)
    for r in scored[-4:]:
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
