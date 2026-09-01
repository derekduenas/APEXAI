"""H5-SELECTOR-LAB-HS1 -- does frozen H5 information improve
SELECTION among candidates from a stronger causal mechanism?

Design sealed (H5-SELECTOR-LAB-HS1-2026-08-30). Implementation
notes vs the seal, recorded honestly:
  * "same 33 features" in the registration is the dataset width;
    the 8 forward columns (f15..t_mae) are obviously excluded from
    the feature set -- leakage law overrides wording. 25 causal
    state fields are used, ridge lambda=10, standardized, expanding
    walk-forward by year: the H5-challenger recipe unchanged.
  * dataset rows exist at tick 600 (10:00 ET); to avoid lookahead
    the candidate outcome is the 10:00-entry short leg
    (replay_inputs checkpoint "10:00"), not the 09:35 leg.

decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

NPZ = Path("/apex-data/core/alpha_discovery/dataset.npz")
INP = Path("exports/replay_inputs.jsonl")
GRAVE = Path("results/edge_atlas/h5_selector_hs1.jsonl")
LAM = 10.0
FWD_COLS = 8            # last 8 columns are forward/outcome fields


def main():
    d = np.load(NPZ, allow_pickle=True)
    X = d["X"]
    fields = list(d["fields"])
    day = d["day"].astype(str)
    sym = d["sym"].astype(str)
    tick = d["tick"]
    n_state = X.shape[1] - FWD_COLS
    feat = X[:, :n_state].astype(np.float64)
    y15 = X[:, fields.index("f15")].astype(np.float64)
    y60 = X[:, fields.index("f60")].astype(np.float64)
    year = np.array([s[:4] for s in day])
    ok = np.isfinite(feat).all(axis=1)
    print(json.dumps({"rows": int(len(X)),
                      "finite": int(ok.sum()),
                      "state_fields": fields[:n_state]}), flush=True)

    events = [json.loads(l) for l in INP.open()]
    events = [e for e in events if e["timing"] == "pm"
              and e["short_pnl_bps"].get("10:00") is not None]
    ev_key = {(e["symbol"], e["session"]): e for e in events}

    # index dataset rows at tick 600 for event (sym, day)
    at600 = (tick == 600) & ok
    row_of = {}
    idxs = np.where(at600)[0]
    for i in idxs:
        row_of[(sym[i], day[i])] = i

    matched = [(k, row_of[k]) for k in ev_key if k in row_of]
    print(json.dumps({"pm_events": len(ev_key),
                      "matched_rows": len(matched)}), flush=True)

    # expanding yearly ridge (frozen recipe), score matched events
    scores = {}
    years = sorted({k[1][:4] for k, _ in matched})
    for ty in years:
        tr = ok & (year < ty)
        if tr.sum() < 100_000:
            continue
        Xtr = feat[tr]
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        Xtr = (Xtr - mu) / sd
        A = Xtr.T @ Xtr + LAM * np.eye(n_state)
        w15 = np.linalg.solve(A, Xtr.T @ y15[tr])
        w60 = np.linalg.solve(A, Xtr.T @ y60[tr])
        for k, i in matched:
            if k[1][:4] == ty:
                z = (feat[i] - mu) / sd
                scores[k] = {"s15": float(z @ w15),
                             "s60": float(z @ w60)}
        print(json.dumps({"scored_year": ty,
                          "train_rows": int(tr.sum())}), flush=True)

    ledger = []
    per_event_dump = []

    def cell(cid, sub, note=""):
        vals = [(v, y) for v, y in sub]
        n = len(vals)
        rec = {"kind": "hs1_cell", "id": cid, "n": n, "note": note}
        if n >= 60:
            g = [v for v, _ in vals]
            yrs = defaultdict(list)
            for v, y in vals:
                yrs[y].append(v)
            ym = {y: round(statistics.mean(x), 1)
                  for y, x in sorted(yrs.items()) if len(x) >= 15}
            rec.update({"mean_net_bps": round(statistics.mean(g), 1),
                        "median_net_bps": round(
                            statistics.median(g), 1),
                        "win": round(sum(1 for v in g if v > 0) / n,
                                     3),
                        "pos_years": f"{sum(1 for v in ym.values() if v > 0)}"
                                     f"/{len(ym)}",
                        "by_year": ym})
        else:
            rec["verdict"] = "INSUFFICIENT_N"
        ledger.append(rec)
        return rec

    # rank within trailing 63-session windows (causal cross-section)
    scored_events = sorted(
        ((k, scores[k]) for k in scores),
        key=lambda kv: kv[0][1])
    sessions = sorted({k[1] for k, _ in scored_events})
    spos = {s: i for i, s in enumerate(sessions)}

    for variant in ("s15", "s60"):
        buckets = {"bearish": [], "middle": [], "bullish": []}
        for k, sc in scored_events:
            i = spos[k[1]]
            window = [v[variant] for kk, v in scored_events
                      if 0 <= i - spos[kk[1]] <= 63]
            if len(window) < 30:
                continue
            arr = sorted(window)
            lo = arr[int(len(arr) / 3)]
            hi = arr[int(2 * len(arr) / 3)]
            x = sc[variant]
            b = ("bearish" if x <= lo else
                 "bullish" if x >= hi else "middle")
            e = ev_key[k]
            rt = e.get("observed_rt_bps") or 10.0
            net = e["short_pnl_bps"]["10:00"] - rt
            buckets[b].append((net, k[1][:4]))
            per_event_dump.append({"variant": variant,
                                   "sym": k[0], "session": k[1],
                                   "bucket": b,
                                   "net": round(net, 1)})
        allv = [x for b in buckets.values() for x in b]
        base = cell(f"HS1_{variant}_ALL_mechanism_alone", allv)
        for b, sub in buckets.items():
            cell(f"HS1_{variant}_{b}", sub)
        if "mean_net_bps" in base:
            br = [r for r in ledger
                  if r.get("id") == f"HS1_{variant}_bearish"][-1]
            if "mean_net_bps" in br:
                # year-by-year improvement of bearish over ALL
                imp = {}
                for y in base["by_year"]:
                    if y in br.get("by_year", {}):
                        imp[y] = round(br["by_year"][y]
                                       - base["by_year"][y], 1)
                ledger.append({
                    "kind": "hs1_comparison", "variant": variant,
                    "improvement_bearish_minus_all_bps": round(
                        br["mean_net_bps"] - base["mean_net_bps"], 1),
                    "improvement_by_year": imp,
                    "pos_improvement_years":
                        f"{sum(1 for v in imp.values() if v > 0)}"
                        f"/{len(imp)}"})

    Path("results/edge_atlas/h5_selector_events.jsonl").write_text(
        "\n".join(json.dumps(x) for x in per_event_dump))
    GRAVE.parent.mkdir(parents=True, exist_ok=True)
    with GRAVE.open("w") as g:
        for rec in ledger:
            g.write(json.dumps(rec) + "\n")
    for rec in ledger:
        print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
