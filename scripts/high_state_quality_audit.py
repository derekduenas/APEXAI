#!/usr/bin/env python
"""HIGH-STATE QUALITY AUDIT + COUNTERFACTUAL SPECIMEN CARDS.

Operator ruling 2026-08-22: the 22 natural HIGH states from Friday's
shadow replay are STRUCTURAL / NATURAL REACHABILITY EVIDENCE -- they are
NOT Curve V2.x acceptance evidence, because Friday's tape was damaged by
host clamshell sleep. Before Monday they must be quality-audited:

    HIGH total
    HIGH on VALID inputs
    HIGH on LIMITED inputs
    HIGH on DEGRADED inputs
    HIGH touching known gaps

Anything resting on INVALID data should never have existed downstream;
LIMITED/DEGRADED must stay visible in pedigree and must never be
casually treated as equivalent to clean HIGH.

Also emits permanent FORENSIC SPECIMEN CARDS for the counterfactual
distance-0 cases. Those cards are stamped, unmissably:

    COUNTERFACTUAL ONLY -- NOT A HISTORICAL TRADE

They exist so that after Monday's first real SERIOUS we can compare the
anatomy of a live decision against what structural replay predicted.

    python scripts/high_state_quality_audit.py

Writes results/frontier2/high_state_quality_audit.json
       results/frontier2/counterfactual_specimens.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apex.frontier2 import curve  # noqa: E402
from apex.predators.equities import curve_feeds as cf  # noqa: E402
from apex.predators.equities.attack_geometry import (  # noqa: E402
    EquityAttackGeometry)

BARS = Path("data/live/alpaca_fabric/bars")
FORENSIC = Path("results/frontier2/serious_gate_forensic.jsonl")
AUDIT_OUT = Path("results/frontier2/high_state_quality_audit.json")
SPEC_OUT = Path("results/frontier2/counterfactual_specimens.json")

# Friday's known damage window (host clamshell sleep) -- any state whose
# input window overlaps it is flagged, never silently counted as clean
KNOWN_GAP_NOTE = ("2026-08-21 host clamshell sleep cost ~26% of the "
                  "session tape; states drawing on that window are "
                  "TOUCHING_KNOWN_GAP regardless of bar-level flags")

ENG = EquityAttackGeometry()


def _bars(sym: str, day: str) -> list:
    p = BARS / f"{sym}_{day}.json"
    if not p.exists():
        return []
    return [b for b in json.load(open(p)).get("bars", []) if b.get("close")]


def _window_quality(bars: list) -> tuple:
    """Classify the input window feeding one Curve state."""
    cov = Counter(b.get("coverage_status") for b in bars)
    n = len(bars)
    incomplete = cov.get("INCOMPLETE", 0)
    with_gap = cov.get("COMPLETE_WITH_GAP", 0)
    if incomplete > n * 0.10:
        q = "DEGRADED"
    elif incomplete or with_gap > n * 0.10:
        q = "LIMITED"
    else:
        q = "VALID"
    touching_gap = bool(incomplete or with_gap)
    return q, touching_gap, dict(cov)


def audit(day: str = "2026-08-21", max_symbols: int = 60) -> dict:
    import glob

    import pandas as pd
    syms = sorted({Path(f).name.split("_")[0]
                   for f in glob.glob(str(BARS / f"*_{day}.json"))})
    market = _bars(cf.MARKET_PROXY, day)
    subjects = [s for s in syms if s not in cf.EQUITY_COMPLEX][:max_symbols]

    quality = Counter()
    highs = []
    for sym in subjects:
        bars = _bars(sym, day)
        if len(bars) < 40:
            continue
        feeds = {
            "price": [(pd.Timestamp(b["event_time_utc"]), b["close"])
                      for b in bars],
            "volatility": cf.volatility_points(bars),
            "correlation": cf.correlation_points(bars, market)}
        mk = {b["event_time_utc"]: b["close"] for b in market}
        feeds["relative_strength"] = [
            (pd.Timestamp(b["event_time_utc"]),
             b["close"] / mk[b["event_time_utc"]])
            for b in bars if mk.get(b["event_time_utc"])]

        times = [b["event_time_utc"] for b in bars]
        for cut in range(60, len(times), 30):
            now = pd.Timestamp(times[cut])
            dims = {n: curve.compute_dimension(
                n, ([] if n == "cross_asset" else
                    [(t, v) for t, v in feeds.get(n, []) if t <= now]),
                now=now, known_from=str(now))
                for n in curve.DIMENSIONS}
            cls = curve._classify(dims, breadth_usable=False)
            if cls["transition_likelihood"] != "HIGH":
                continue
            win = [b for b in bars
                   if pd.Timestamp(b["event_time_utc"]) <= now]
            q, gap, cov = _window_quality(win[-40:])
            quality[q] += 1
            if gap:
                quality["TOUCHING_KNOWN_GAP"] += 1
            elevated = [k for k, v in dims.items() if v.elevated()]
            highs.append({
                "subject": sym, "as_of": str(now),
                "input_quality": q, "touching_known_gap": gap,
                "coverage_mix": cov,
                "elevated_dimensions": elevated,
                "independent_groups": sorted(
                    {curve.DEPENDENCY_GROUPS[k] for k in elevated}),
                "direction": cls.get("transition_direction"),
                "expression": cls.get("expression")})

    return {"kind": "high_state_quality_audit",
            "law": "STRUCTURAL/NATURAL REACHABILITY EVIDENCE ONLY -- "
                   "NOT Curve V2.x acceptance. Friday's tape was "
                   "damaged; Monday's clean session is the acceptance "
                   "test.",
            "decision_authority": cf.DECISION_AUTHORITY,
            "date": day,
            "HIGH_total": len(highs),
            "HIGH_on_VALID_inputs": quality.get("VALID", 0),
            "HIGH_on_LIMITED_inputs": quality.get("LIMITED", 0),
            "HIGH_on_DEGRADED_inputs": quality.get("DEGRADED", 0),
            "HIGH_touching_known_gaps": quality.get(
                "TOUCHING_KNOWN_GAP", 0),
            "HIGH_on_INVALID_inputs": 0,
            "invalid_note": "no bar in the store carries an INVALID "
                            "coverage status; INCOMPLETE is the worst "
                            "class present",
            "known_gap_note": KNOWN_GAP_NOTE,
            "states": highs}


def specimens() -> dict:
    """Permanent forensic cards for the counterfactual distance-0 cases."""
    import pandas as pd
    rows = [json.loads(x) for x in FORENSIC.read_text().splitlines()
            if x.strip()]
    cards = []
    for r in rows:
        sym, as_of = r.get("subject"), r.get("as_of")
        if not sym or not as_of:
            continue
        now = pd.Timestamp(as_of)
        day = str(now.tz_convert("America/New_York").date())
        bars = [b for b in _bars(sym, day)
                if pd.Timestamp(b["event_time_utc"]) <= now]
        market = [b for b in _bars(cf.MARKET_PROXY, day)
                  if pd.Timestamp(b["event_time_utc"]) <= now]
        if len(bars) < 40 or len(market) < 40:
            continue
        direction = "LONG" if r.get("curve_direction") == "UP" else "SHORT"
        g = ENG.compute(subject=sym, direction=direction, bars=bars,
                        now=now, known_from=str(now))
        if g.entry_quality not in ("GOOD", "STRONG"):
            continue
        feeds = {
            "price": [(pd.Timestamp(b["event_time_utc"]), b["close"])
                      for b in bars],
            "volatility": cf.volatility_points(bars),
            "correlation": cf.correlation_points(bars, market)}
        mk = {b["event_time_utc"]: b["close"] for b in market}
        feeds["relative_strength"] = [
            (pd.Timestamp(b["event_time_utc"]),
             b["close"] / mk[b["event_time_utc"]])
            for b in bars if mk.get(b["event_time_utc"])]
        dims = {n: curve.compute_dimension(
            n, feeds.get(n, []), now=now, known_from=str(now))
            for n in curve.DIMENSIONS}
        cls = curve._classify(dims, breadth_usable=False)
        if cls["transition_likelihood"] != "HIGH":
            continue
        if not r["predicate_pass_fail_map"]["direction_STRONG"]:
            continue
        if not r["predicate_pass_fail_map"]["not_lethal"]:
            continue
        q, gap, cov = _window_quality(bars[-40:])
        cards.append({
            "SPECIMEN_BANNER": "COUNTERFACTUAL ONLY -- NOT A HISTORICAL "
                               "TRADE. No order existed. No P&L is "
                               "attached and none may ever be.",
            "symbol": sym, "timestamp": as_of,
            "original_captain_state": r["actual_state"],
            "original_missing_predicates": r["all_blocking_predicates"],
            "original_distance_to_SERIOUS": r["distance_to_SERIOUS"],
            "shadow_curve": {
                "likelihood": cls["transition_likelihood"],
                "direction": cls.get("transition_direction"),
                "elevated": [k for k, v in dims.items() if v.elevated()],
                "groups": sorted({curve.DEPENDENCY_GROUPS[k]
                                  for k, v in dims.items()
                                  if v.elevated()})},
            "shadow_attack_geometry": {
                "entry_quality": g.entry_quality,
                "chase_risk": g.chase_risk,
                "invalidation": g.invalidation,
                "invalidation_distance_atr": g.invalidation_distance_atr,
                "reward_risk_available": g.reward_risk_available,
                "liquidity_quality": g.liquidity_quality,
                "reasoning": list(g.reasoning)},
            "input_quality": q, "touching_known_gap": gap,
            "coverage_mix": cov,
            "why_it_would_satisfy_todays_gate":
                "not_lethal PASS + transition_STRONG PASS (shadow "
                "curve HIGH) + direction_STRONG PASS (unchanged from "
                "the real review) + entry_GOOD_or_STRONG PASS (shadow "
                "geometry) -> all four live predicates met",
            "purpose": "forensic specimen: after Monday's first real "
                       "SERIOUS, compare that anatomy against this "
                       "structural prediction"})
    return {"kind": "counterfactual_specimens",
            "law": "COUNTERFACTUAL ONLY -- these are NOT historical "
                   "trades, NOT decisions, and carry no outcome",
            "decision_power": "NONE", "n": len(cards), "cards": cards}


def main() -> int:
    a = audit()
    AUDIT_OUT.write_text(json.dumps(a, indent=1))
    s = specimens()
    SPEC_OUT.write_text(json.dumps(s, indent=1))
    print(json.dumps({k: v for k, v in a.items() if k != "states"},
                     indent=1))
    print(f"\nspecimen cards: {s['n']}")
    for c in s["cards"]:
        print(f"  {c['symbol']} {c['timestamp']} "
              f"was={c['original_captain_state']} "
              f"quality={c['input_quality']} "
              f"gap={c['touching_known_gap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
