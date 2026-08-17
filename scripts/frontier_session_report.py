#!/usr/bin/env python
"""FRONTIER vs EPOCH-1 — the Monday comparison. Consumer only.

    python scripts/frontier_session_report.py [--date 2026-08-17]

Observational comparison of the two desks on the same unseen future.
Day-1 law: do NOT optimize from this. Latency deltas are observations;
"frontier saw it earlier" is not yet "frontier is better".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402


def _rows(p):
    if not Path(p).exists():
        return []
    out = []
    for line in Path(p).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=str(pd.Timestamp.now(
        tz="America/New_York").date()))
    a = ap.parse_args()
    day = a.date

    official = [r for r in _rows("results/hunter/forward_ledger.jsonl")
                if str(r.get("t_utc", "")).startswith(day)
                or r.get("session_date") == day]
    fw = [r for r in _rows("results/hunter/fastwatch_ledger.jsonl")
          if str(r.get("observed_at", "")).startswith(day)]
    bus = [r for r in _rows("results/frontier/event_bus.jsonl")
           if str(r.get("known_from", "")).startswith(day)]
    boards = [r for r in _rows("results/frontier/opportunity_board.jsonl")]
    cards = []
    cdir = Path(f"results/decision_cards/{day}")
    if cdir.exists():
        cards = [json.loads(p.read_text()) for p in cdir.glob("*.json")]

    scans = [r for r in official if r.get("kind") == "scan"]
    decs = [r for r in official if r.get("kind") == "decision"
            and not str(r.get("playbook_id", "")).startswith("BASELINE-")]

    L = [f"FRONTIER vs EPOCH-1 — {day}", "=" * 46, "",
         f"{'':24}{'EPOCH-1':<12}FRONTIER", "-" * 46,
         f"{'observations':<24}{len(scans):<12}{len(fw)}",
         f"{'typed events':<24}{'n/a':<12}{len(bus)}",
         f"{'candidates':<24}{len(decs):<12}{len(cards)}",
         f"{'board snapshots':<24}{'(frozen)':<12}{len(boards)}", ""]

    # per-candidate latency: fastwatch first condition vs official t
    for payload in cards:
        c = payload.get("before", {})
        did = c.get("decision_id")
        t_off = (c.get("timing") or {}).get("official_detection")
        t_fw = (c.get("timing") or {}).get("fastwatch_first_condition")
        delta = None
        if t_off and t_fw:
            delta = round((pd.Timestamp(t_off)
                           - pd.Timestamp(t_fw)).total_seconds(), 1)
        L.append(f"{did}: official={t_off} fastwatch_first={t_fw} "
                 f"latency_delta_s={delta if delta is not None else 'UNKNOWN'}")
        vis = c.get("visual") or {}
        L.append(f"  visual: {vis.get('entry_geometry', 'UNKNOWN')} | "
                 f"catalyst: {(c.get('catalyst') or {}).get('status')} | "
                 f"dislocations: "
                 f"{len((c.get('dislocation') or {}).get('observations', []))}")
        if "after" in payload:
            o = payload["after"]["outcome"]
            L.append(f"  outcome: 15m={o.get('ret_15m')} 60m={o.get('ret_60m')} "
                     f"mfe={o.get('mfe')} mae={o.get('mae')}")
        else:
            L.append("  outcome: UNRESOLVED")
    if not cards:
        L.append("no decision cards — either no candidates (legal) or the "
                 "frontier loop did not run (check mission control)")
    L += ["", "DAY-1 LAW: observational only. Nothing here tunes anything."]
    text = "\n".join(L)
    print(text)
    out = Path(f"results/frontier/COMPARISON_{day}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
