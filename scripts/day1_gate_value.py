"""GATE VALUE — resolve what APEX REFUSED, at the same horizon.

The first dataset that can eventually answer whether a gate earns its
keep. A funnel that refuses 123 times is only selective if the refusals
were worth making; otherwise it is an expensive filter on nothing.

Every cohort is resolved to the SAME causally-eligible boundary the
attacks used (official regular-session close), so ATTACKED and REFUSED
are compared on identical terms rather than convenient ones.

SAMPLE LAW, loudly. 86 WAIT_FOR_ENTRY observations from one session are
86 correlated views of one day. independent_session_count = 1. Nothing
here may move a gate; a single session cannot convict or acquit one.

decision_power: NONE -- descriptive.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.resolution_time import (               # noqa: E402
    eligible_window, to_utc)

ALPACA = "https://data.alpaca.markets/v2"
COHORTS = ("PAPER_ATTACKED", "WAIT_FOR_ENTRY", "NO_ATTACKABLE_EXPRESSION",
           "NO_DIRECTIONAL_THESIS", "FEED_DEGRADED")


def bars(symbol, key, sec):
    url = (f"{ALPACA}/stocks/{symbol}/bars?timeframe=1Min"
           f"&start=2026-08-24T13:00:00Z&end=2026-08-24T20:05:00Z"
           f"&limit=10000&feed=sip&adjustment=raw")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("bars", [])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-json",
                    default="results/day1_frozen/options_session.json")
    ap.add_argument("--out", default="results/day1_corrected")
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    a = ap.parse_args()

    d = json.loads(Path(a.session_json).read_text())
    scans = d.get("scans", [])
    cache, rows = {}, []

    for s in scans:
        sym, status, T = s.get("symbol"), s.get("status"), s.get("T")
        if not (sym and T and status):
            continue
        direction = s.get("direction")
        if sym not in cache:
            cache[sym] = bars(sym, a.key, a.secret)
        raw = cache[sym]
        if not raw:
            continue
        win = eligible_window(entry_ts=T, session="2026-08-24",
                              symbol=sym, option=False)
        e_utc, b_utc = to_utc(win["entry_utc"]), to_utc(win["boundary_utc"])
        prior = [b for b in raw if to_utc(b["t"], assume="UTC") <= e_utc]
        fwd = [b for b in raw if e_utc < to_utc(b["t"], assume="UTC")
               <= b_utc]
        if not prior or not fwd:
            continue
        ref = prior[-1]["c"]
        # sign the forward move by the view the sleeve actually held;
        # an undirected refusal is measured signed-agnostic and labelled
        sign = (1.0 if direction == "LONG" else
                -1.0 if direction == "SHORT" else None)
        fwd_pct = (fwd[-1]["c"] / ref - 1.0) * 100
        rows.append({
            "symbol": sym, "T": T, "cohort": status,
            "direction": direction or "NONE",
            "ref": ref,
            "forward_move_pct": round(fwd_pct, 4),
            "signed_forward_pct": (round(sign * fwd_pct, 4)
                                   if sign else "NOT_DIRECTIONAL"),
            "forward_mfe_pct": round(max(
                (sign * (b["c"] / ref - 1.0) * 100) for b in fwd), 4)
                if sign else "NOT_DIRECTIONAL",
            "forward_mae_pct": round(min(
                (sign * (b["c"] / ref - 1.0) * 100) for b in fwd), 4)
                if sign else "NOT_DIRECTIONAL",
            "minutes_to_boundary": len(fwd),
        })

    by = defaultdict(list)
    for r in rows:
        by[r["cohort"]].append(r)

    report = {"kind": "day1_gate_value", "session": "2026-08-24",
              "n_raw": len(rows),
              "independent_session_count": 1,
              "n_effective_lower_bound": 1,
              "sample_law": "86 observations from ONE session are 86 "
                            "correlated views of one day; this dataset "
                            "cannot convict or acquit any gate",
              "cohorts": {}}
    for c, rs in sorted(by.items()):
        signed = [r["signed_forward_pct"] for r in rs
                  if isinstance(r["signed_forward_pct"], float)]
        entry = {"n_raw": len(rs),
                 "symbols": sorted({r["symbol"] for r in rs})}
        if signed:
            entry.update({
                "signed_forward_median_pct": round(
                    statistics.median(signed), 4),
                "signed_forward_mean_pct": round(
                    sum(signed) / len(signed), 4),
                "favorable_fraction": round(
                    sum(1 for x in signed if x > 0) / len(signed), 3),
                "note": "signed by the sleeve's own directional view"})
        else:
            entry["note"] = ("no directional view was held, so a signed "
                             "forward move is NOT_ESTIMABLE for this "
                             "cohort")
        report["cohorts"][c] = entry

    out = Path(a.out) / "day1_gate_value.json"
    out.write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
