#!/usr/bin/env python
"""APEX Hunter health report — "is the machine seeing the market
correctly?", never "did we make money?"

    python scripts/hunter_week_report.py            # all sessions to date

Pure aggregation over the one forward ledger, in the operator's frozen
report shape. Every number is mechanical; nothing here can retune
anything (WEEK1-OBSERVATION-FREEZE law).
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

from hunter_scoreboard import build_scoreboard, load_ledger  # noqa: E402

OUT = Path("results/hunter")


def fmt(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x:+.2%}" if pct else str(x)


def build_report() -> str:
    kinds = load_ledger()
    sb = build_scoreboard(kinds)
    states, scans = kinds["forward_state"], kinds["scan"]
    decisions = kinds["decision"]
    pb = [d for d in decisions
          if not d["playbook_id"].startswith("BASELINE-")]
    sessions = sorted({s["session_date"] for s in scans}
                      | {d["session_date"] for d in decisions})
    zero_cycles = sum(1 for s in scans if not s.get("watchlist"))
    # forecast_bundle is not in the scoreboard's kinds; read raw
    import json

    from hunter_scoreboard import LEDGER
    analog_support = Counter()
    bundles = []
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("kind") == "forecast_bundle":
                    bundles.append(r)
    for b in bundles:
        analog_support[(b.get("analog_view") or {}).get("status", "?")] += 1
    health_fail = [h for s in states for h in s.get("data_health", [])
                   if h != "OK"]
    cap = sb["capital"]
    matches = Counter(d["playbook_id"] for d in pb)
    svr = sb["selected_vs_rejected"]

    L = ["APEX HUNTER HEALTH REPORT", "=" * 40, "",
         f"Sessions observed          {len(sessions)}"
         f"   ({', '.join(sessions) if sessions else 'none yet'})",
         f"State snapshots            {len(states)}",
         f"Scan cycles                {len(scans)}",
         f"Universe observations      "
         f"{sum(s.get('states_computed', 0) for s in scans)}",
         f"Scanner abnormalities      "
         f"{sum(s.get('abnormal', 0) for s in scans)}",
         f"Watchlist candidates       "
         f"{sb['funnel']['watchlist_symbols_seen']}",
         f"ZERO-candidate cycles      "
         f"{zero_cycles}/{len(scans)}"
         + (f" ({zero_cycles / len(scans):.0%})" if scans else ""), ""]
    L += [f"{p:26s} {n}" for p, n in sorted(matches.items())] or \
        ["(no playbook matches yet)"]
    L += ["",
          f"Forward eligible           {sb['decisions_forward_eligible']}",
          f"Ineligible                 {sb['decisions_ineligible']}",
          f"Scored                     {sb['decisions_scored']}",
          f"N_effective (playbooks)    "
          f"{sb['effective_sample_playbooks']['n_effective']}", "",
          "ANALOG SUPPORT (from bundles)"]
    L += [f"  {k:24s} {v}" for k, v in analog_support.most_common()] or \
        ["  (no bundles yet)"]
    L += ["", "ML                         UNTRAINED (by law until 40 eff)",
          "WORLD SIM                  diagnostic only",
          "SWARM                      BLOCKED_EXTERNAL_AUTH", "",
          "CAPITAL"]
    L += [f"  {k:24s} {v}" for k, v in
          sorted(cap["final_states"].items())] or ["  (none yet)"]
    L += [f"  reason codes: {dict(cap['reason_codes'])}", "", "SCOREBOARD"]
    for pid, e in sb["scoreboard"].items():
        h60 = e["horizons"].get("60m") or {}
        L.append(f"  {pid:24s} {e['status']:11s} n={e['n_raw']:3d} "
                 f"neff={e['n_effective']:3d} 60m hit={h60.get('hit_rate')} "
                 f"mean={h60.get('mean_ret')}")
    L += ["", "SELECTED vs REJECTED (same instrument, BASELINE-MOMENTUM)"]
    for h in ("15m", "30m", "60m", "90m"):
        s_, r_ = svr["selected_cohort"].get(h), svr["rejected_cohort"].get(h)
        L.append(f"  {h}: selected "
                 f"{(s_ or {}).get('mean_ret')} (n={(s_ or {}).get('n', 0)})"
                 f"  rejected {(r_ or {}).get('mean_ret')} "
                 f"(n={(r_ or {}).get('n', 0)})")
    L += ["", f"Data failures ({len(health_fail)}):"]
    L += [f"  {h}" for h in health_fail[:15]] or ["  none"]
    L += ["", "Read as FINDINGS. Nothing above is a knob "
          "(WEEK1-OBSERVATION-FREEZE)."]
    return "\n".join(L)


def main() -> int:
    report = build_report()
    OUT.mkdir(parents=True, exist_ok=True)
    import datetime as dt
    path = OUT / f"health_report_{dt.date.today()}.md"
    path.write_text(report + "\n")
    print(report)
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
