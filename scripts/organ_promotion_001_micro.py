"""ORGAN PROMOTION #001 -- SIP_MICROSTRUCTURE as ALPHA_SELECTOR.

Registered ORGAN-PROMOTION-001-SIP-MICROSTRUCTURE (sealed before
any result was viewed). Stages 0-2 here; battery is separate.

BASELINE  : APEX_PROFIT_BASELINE_V1 = war arm 4 per-event P&L.
CANDIDATE : same, except a bearish opportunity the baseline would
            attack is SUPPRESSED to CASH when net signed volume
            over 09:30:00-09:34:59 ET is POSITIVE (tape buying
            against the short thesis). Sign only. One variant.

Production is untouched: this reads sealed war rows and historical
ticks, and writes only its own shadow ledger.
decision_power: RESEARCH_DISCOVERY_ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from apex.organism import microstructure as ms

WAR = Path("results/edge_atlas/organism_war.jsonl")
OUT = Path("results/edge_atlas/organ001_micro_shadow.jsonl")


def utc_off(session: str) -> int:
    m = int(session[5:7])
    return 4 if 4 <= m <= 10 else 5      # EDT Apr-Oct, else EST


def main():
    war = [json.loads(l) for l in WAR.open() if l.strip()]
    war = [r for r in war if r.get("kind") == "war_event"]
    attacked = [r for r in war
                if r.get("arm4_choice") not in (None, "CASH")
                and isinstance(r.get("arm4"), (int, float))]
    print(json.dumps({"stage0_war_rows": len(war),
                      "stage0_attacked": len(attacked)}), flush=True)

    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                r = json.loads(line)
                done.add((r["sym"], r["session"]))
            except Exception:                           # noqa: BLE001
                continue

    n = 0
    for r in attacked:
        key = (r["sym"], r["session"])
        if key in done:
            continue
        off = utc_off(r["session"])
        start = f"{r['session']}T{9 + off:02d}:30:00Z"
        end = f"{r['session']}T{9 + off:02d}:34:59Z"
        row = {"kind": "organ001_shadow", "sym": r["sym"],
               "session": r["session"],
               "arm4_choice": r["arm4_choice"],
               "baseline_pnl_bps": r["arm4"]}
        try:
            tr = ms.fetch_ticks(r["sym"], start, end,
                                what="trades", max_pages=3)
            qt = ms.fetch_ticks(r["sym"], start, end,
                                what="quotes", max_pages=3)
            st = ms.micro_state(tr, qt, window_label="0930_0935")
        except Exception as e:                          # noqa: BLE001
            st = {"status": "NOT_ESTIMABLE",
                  "why": type(e).__name__}
        if st.get("status"):
            row["micro"] = st.get("status")
            row["suppressed"] = None       # organ cannot speak
            row["candidate_pnl_bps"] = r["arm4"]
        else:
            flow = st["net_signed_volume"]
            # bearish thesis: positive (buy) flow opposes it
            supp = flow > 0
            row["net_signed_volume"] = flow
            row["spread_bps"] = st["spread_bps_median"]
            row["trade_intensity_per_s"] = st[
                "trade_intensity_per_s"]
            row["suppressed"] = supp
            row["candidate_pnl_bps"] = 0.0 if supp else r["arm4"]
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        n += 1
        if n % 25 == 0:
            print(json.dumps({"progress": n,
                              "at": r["session"]}), flush=True)
    print(json.dumps({"rows_written": n}), flush=True)


if __name__ == "__main__":
    main()
