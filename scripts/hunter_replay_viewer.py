#!/usr/bin/env python
"""Replay Viewer — watch one historical candidate unfold, stage by stage.
Aggregates hide stupidity; this shows it.

    python scripts/hunter_replay_viewer.py --tag smoke            # list
    python scripts/hunter_replay_viewer.py --tag smoke <decision_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402


def load(tag):
    rows = []
    for line in Path(f"results/hunter/replay_{tag}/replay_ledger.jsonl"
                     ).read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def et(ts):
    return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%H:%M")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="smoke")
    ap.add_argument("decision_id", nargs="?")
    a = ap.parse_args()
    rows = load(a.tag)
    dec = [r for r in rows if r.get("kind") == "decision"
           and not r["playbook_id"].startswith("BASELINE-")]
    if not a.decision_id:
        print(f"{len(dec)} candidates in replay_{a.tag}:")
        for d in dec:
            print(f"  {d['decision_id']}  {d['session_date']} "
                  f"{et(d['t_utc'])}ET  {d['symbol']:6s} "
                  f"{d['playbook_id']} {d['direction']}")
        return 0

    did = a.decision_id
    d = next((r for r in dec if r["decision_id"] == did), None)
    if d is None:
        print("not found"); return 1
    scans = [r for r in rows if r.get("kind") == "scan"
             and r.get("session_date") == d["session_date"]]
    first_seen = None
    for s in scans:
        if any(w["symbol"] == d["symbol"] for w in s.get("watchlist", [])):
            first_seen = s
            break
    fb = next((r for r in rows if r.get("kind") == "forecast_bundle"
               and r.get("candidate_id") == did), None)
    rev = next((r for r in rows if r.get("kind") == "assassin_review"
                and r.get("decision_id") == did), None)
    cap = next((r for r in rows if r.get("kind") == "capital_decision"
                and r.get("decision_id") == did), None)
    real = next((r for r in rows if r.get("kind") == "realization"
                 and r.get("decision_id") == did), None)

    cs = d.get("chart_state") or {}
    print(f"═══ {d['symbol']} {d['session_date']} — {d['playbook_id']} "
          f"{d['direction']} ═══")
    if first_seen:
        w = next(w for w in first_seen["watchlist"]
                 if w["symbol"] == d["symbol"])
        print(f"{et(first_seen['t_utc'])}  SCOUT notices: "
              f"{', '.join(w['signals'])} (rvol {w.get('rvol')})")
    print(f"{et(d['t_utc'])}  HUNTER fires: matched={d.get('matched')}")
    print(f"        entry {d['entry']}  stop {d['stop']}  "
          f"target {d['target']}  risk {d['risk_frac']:.3%}")
    ms = d.get("market_state") or {}
    print(f"        WORLD: SPY {ms.get('day_return'):+.3%} "
          f"above_vwap={ms.get('above_vwap')}  "
          f"vol={ms.get('realized_vol_ann')}")
    if fb:
        print(f"        ORACLE: analog={fb['analog_view'].get('status')} "
              f"ml={fb['ml_view'].get('status')} "
              f"dist={fb['distribution_source_status']} "
              f"disagreement={fb['disagreement'].get('level')}")
    if rev:
        landed = ", ".join(rev.get("landed", [])) or "none landed"
        print(f"        ASSASSIN: {rev['verdict']} ({landed})")
        for at in rev.get("attempts", []):
            print(f"          - {at['mechanism']}: "
                  f"{'LANDED' if at['landed'] else 'missed'} "
                  f"({at.get('detail')})")
    if cap:
        print(f"        CAPITAL: {cap['final_state']} "
              f"reasons={list(cap.get('reason_codes', []))}")
    if real:
        print("        ▶ MARKET UNFOLDS:")
        for h in (15, 30, 60, 90):
            r = real.get(f"ret_{h}m")
            if r is not None:
                print(f"          +{h}m: {r:+.3%}  "
                      f"(mfe {real.get(f'mfe_{h}m'):+.3%} / "
                      f"mae {real.get(f'mae_{h}m'):+.3%})")
        print(f"          target_before_stop={real.get('target_before_stop')}"
              f"  close={real.get('closing_return'):+.3%}")
    print("═══ evidence: HISTORICAL_EXPLORATORY — laboratory only ═══")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
