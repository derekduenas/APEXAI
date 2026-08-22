#!/usr/bin/env python
"""CAPTAIN STRUCTURAL COUNTERFACTUAL (Predator v2 Phase 2 §14).

Combines, for each of the real Captain reviews:
    * the ACTUAL persisted review inputs (never modified)
    * SHADOW Attack Geometry entry_quality, recomputed from the bars
      that existed at that review's own timestamp
    * SHADOW Curve transition_quality from the newly-fed dimensions

and recomputes STRUCTURAL distance_to_SERIOUS.

WHAT THIS ANSWERS:
    "Would the decision architecture have become REACHABLE if the
     missing faculties had existed?"

WHAT IT DOES NOT ANSWER, and never will:
    "Would those trades have made money?"

LAWS: historical Captain states are NOT rewritten. Counterfactual
states are NOT decisions and are never labelled as such. No P&L is
resolved. No threshold is changed. No future bar is read -- geometry at
review time T sees only bars with event_time <= T.

    python scripts/captain_counterfactual.py

Writes results/frontier2/captain_counterfactual.json
"""
from __future__ import annotations

import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.frontier2 import curve  # noqa: E402
from apex.predators.equities import curve_feeds as cf  # noqa: E402
from apex.predators.equities.attack_geometry import (  # noqa: E402
    EquityAttackGeometry)

FORENSIC = Path("results/frontier2/serious_gate_forensic.jsonl")
BARS = Path("data/live/alpaca_fabric/bars")
OUT = Path("results/frontier2/captain_counterfactual.json")

ENG = EquityAttackGeometry()
_CACHE: dict = {}


def _bars_for(sym: str, day: str) -> list:
    k = (sym, day)
    if k not in _CACHE:
        p = BARS / f"{sym}_{day}.json"
        _CACHE[k] = ([x for x in json.load(open(p)).get("bars", [])
                      if x.get("close")] if p.exists() else [])
    return _CACHE[k]


def run() -> dict:
    import pandas as pd
    rows = [json.loads(x) for x in FORENSIC.read_text().splitlines()
            if x.strip()]
    days = sorted({Path(f).name.split("_")[1].replace(".json", "")
                   for f in glob.glob(str(BARS / "*_2026-*.json"))})

    actual = Counter()
    cf_dist = Counter()
    geom_q = Counter()
    trans_q = Counter()
    evaluated = 0
    no_bars = 0

    for r in rows:
        actual[r["actual_state"]] += 1
        sym = r.get("subject")
        as_of = r.get("as_of")
        if not sym or not as_of:
            continue
        now = pd.Timestamp(as_of)
        day = str(now.tz_convert("America/New_York").date())
        if day not in days:
            no_bars += 1
            continue
        bars = [b for b in _bars_for(sym, day)
                if pd.Timestamp(b["event_time_utc"]) <= now]
        market = [b for b in _bars_for(cf.MARKET_PROXY, day)
                  if pd.Timestamp(b["event_time_utc"]) <= now]
        if len(bars) < 40 or len(market) < 40:
            no_bars += 1
            continue
        evaluated += 1

        # --- SHADOW entry_quality (direction from the actual review)
        direction = "LONG" if r.get("curve_direction") == "UP" else "SHORT"
        g = ENG.compute(subject=sym, direction=direction, bars=bars,
                        now=now, known_from=str(now))
        geom_q[g.entry_quality] += 1

        # --- SHADOW transition_quality from newly fed dimensions
        feeds = {
            "price": [(pd.Timestamp(b["event_time_utc"]), b["close"])
                      for b in bars],
            "volatility": cf.volatility_points(bars),
            "correlation": cf.correlation_points(bars, market),
        }
        mk = {b["event_time_utc"]: b["close"] for b in market}
        feeds["relative_strength"] = [
            (pd.Timestamp(b["event_time_utc"]),
             b["close"] / mk[b["event_time_utc"]])
            for b in bars if mk.get(b["event_time_utc"])]
        dims = {n: curve.compute_dimension(
            n, feeds.get(n, []), now=now, known_from=str(now))
            for n in curve.DIMENSIONS}
        cls = curve._classify(dims, breadth_usable=False)
        tq = {"HIGH": "STRONG", "MODERATE": "MODERATE", "LOW": "WEAK",
              "NONE": "WEAK", "UNKNOWN": "UNKNOWN"}[
                  cls["transition_likelihood"]]
        trans_q[tq] += 1

        # --- structural distance, using the LIVE predicate set
        blockers = []
        if not r["predicate_pass_fail_map"]["not_lethal"]:
            blockers.append("not_lethal")
        if tq != "STRONG":
            blockers.append("transition_STRONG")
        if not r["predicate_pass_fail_map"]["direction_STRONG"]:
            blockers.append("direction_STRONG")
        if g.entry_quality not in ("STRONG", "GOOD"):
            blockers.append("entry_GOOD_or_STRONG")
        cf_dist[len(blockers)] += 1

    return {"kind": "captain_structural_counterfactual",
            "law": "structural reachability only; historical Captain "
                   "states unchanged; counterfactuals are NOT decisions; "
                   "no P&L resolved; no future bars read",
            "decision_power": "NONE",
            "reviews_total": len(rows),
            "reviews_evaluated": evaluated,
            "reviews_without_bar_coverage": no_bars,
            "actual_historical_states": dict(actual.most_common()),
            "ACTUAL_SERIOUS": actual.get("SERIOUS", 0),
            "shadow_entry_quality": dict(geom_q.most_common()),
            "shadow_transition_quality": dict(trans_q.most_common()),
            "counterfactual_distance_to_SERIOUS":
                {str(k): v for k, v in sorted(cf_dist.items())},
            "counterfactual_reachable_now": cf_dist.get(0, 0),
            "interpretation":
                "distance 0 means the architecture WOULD have been "
                "able to consider SERIOUS -- it says nothing whatever "
                "about whether such a trade would have profited"}


def main() -> int:
    rep = run()
    OUT.write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
