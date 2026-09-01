"""ORGAN PROMOTION #003 -- CAPTAIN_IN_FLIGHT_V0.

Two jobs, no new hypothesis:
  A) EQUIVALENCE: re-run the sealed Arm-5 economics through the
     minimal Captain adapter (production contracts) and check it
     reproduces the sealed war outcome.
  B) OWED DELAY STRESS: for every triggered event, exit instead at
     the first valid causal option bid at/after 10:05 and 10:10,
     using REAL ThetaData NBBO. No midpoints, no theoretical
     values; a missing quote is NOT_ESTIMABLE.

Search budget: ZERO new variants. The rule is frozen.
decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from pathlib import Path

from apex.organism import captain_minimal as cap
from apex.organism import microstructure as ms
from apex.organism import options_surface as osf

WAR = Path("results/edge_atlas/organism_war.jsonl")
OUT = Path("results/edge_atlas/organ003_captain_shadow.jsonl")


def utc_off(session):
    m = int(session[5:7])
    return 4 if 4 <= m <= 10 else 5


def bars(sym, session):
    off = utc_off(session)
    try:
        d = ms._get("https://data.alpaca.markets/v2/stocks/"
                    f"{sym}/bars?" + urllib.parse.urlencode(
                        {"start": f"{session}T{9 + off}:30:00Z",
                         "end": f"{session}T{16 + off}:05:00Z",
                         "timeframe": "1Min", "feed": "sip",
                         "limit": 10000}))
        return {b["t"]: b["c"] for b in d.get("bars") or []}, off
    except Exception:                                   # noqa: BLE001
        return {}, off


def px_at(px, session, off, hhmm):
    h, m = int(hhmm[:2]), int(hhmm[3:])
    return px.get(f"{session}T{h + off:02d}:{m:02d}:00Z")


def q_at(rows, session, hhmm, side="bid"):
    """First valid two-sided quote at/after hhmm (causal)."""
    cut = f"{session}T{hhmm}:00.000"
    fwd = [r for r in rows if r["t"] >= cut
           and r["ask"] > r["bid"] > 0]
    return fwd[0] if fwd else None


def q_atbefore(rows, session, hhmm):
    cut = f"{session}T{hhmm}:00.000"
    past = [r for r in rows if r["t"] <= cut
            and r["ask"] > r["bid"] > 0]
    return past[-1] if past else None


def main():
    war = [json.loads(l) for l in WAR.open() if l.strip()]
    war = [r for r in war if r.get("kind") == "war_event"]
    attacked = [r for r in war
                if r.get("arm4_choice") not in (None, "CASH")
                and isinstance(r.get("arm4"), (int, float))]
    attacked.sort(key=lambda r: r["session"])
    print(json.dumps({"attacked": len(attacked),
                      "sealed_triggered": sum(
                          1 for r in attacked
                          if r.get("arm5_exited_early"))}),
          flush=True)

    exps: dict = {}
    rows_out = []
    for i, r in enumerate(attacked):
        sym, session = r["sym"], r["session"]
        px, off = bars(sym, session)
        row = {"kind": "organ003_shadow", "sym": sym,
               "session": session,
               "expression": r["arm4_choice"],
               "sealed_arm4": r["arm4"],
               "sealed_arm5": r.get("arm5"),
               "sealed_triggered": bool(
                   r.get("arm5_exited_early"))}
        spot = px_at(px, session, off, "09:35")
        if not spot:
            row["adapter"] = "NOT_ESTIMABLE_NO_SPOT"
            rows_out.append(row)
            continue
        if sym not in exps:
            try:
                exps[sym] = osf.td_expirations(sym)
            except Exception:                           # noqa: BLE001
                exps[sym] = []
        d0 = datetime.strptime(session, "%Y-%m-%d")
        exp = next((x for x in exps[sym]
                    if 5 <= (datetime.strptime(x, "%Y-%m-%d")
                             - d0).days <= 21), None)
        u10 = px_at(px, session, off, "10:00")
        move = ((u10 / spot - 1) * 1e4
                if (u10 and spot) else None)

        # ---- the minimal Captain speaks (read-only)
        atm_rows = otm_rows = []
        if exp:
            try:
                atm_rows = osf.td_history_quote(
                    sym, exp, float(round(spot)), "P", session,
                    interval="5m")
                if r["arm4_choice"] == "put_debit_spread":
                    otm_rows = osf.td_history_quote(
                        sym, exp, float(round(spot * 0.95)), "P",
                        session, interval="5m")
            except Exception:                           # noqa: BLE001
                atm_rows = []
        q10 = q_at(atm_rows, session, "10:00") if atm_rows else None
        verdict = cap.evaluate(
            expression=r["arm4_choice"], thesis_direction="SHORT",
            underlying_move_bps_from_entry=move,
            checkpoint="10:00",
            exit_quote_available=bool(q10))
        row["underlying_move_bps_10am"] = (round(move, 1)
                                           if move is not None
                                           else None)
        row["captain_action"] = verdict["action"]
        row["captain_why"] = verdict["why"]

        # ---- counterfactual P&L at each exit time (real NBBO)
        entry = q_atbefore(atm_rows, session, "09:35") \
            if atm_rows else None
        legs = {}
        if entry and atm_rows:
            for label, hhmm in (("10:00", "10:00"),
                                ("10:05", "10:05"),
                                ("10:10", "10:10"),
                                ("15:55", "15:55")):
                q = q_at(atm_rows, session, hhmm)
                if not q:
                    legs[label] = None
                    continue
                pnl = q["bid"] - entry["ask"]
                if r["arm4_choice"] == "put_debit_spread" \
                        and otm_rows:
                    e2 = q_atbefore(otm_rows, session, "09:35")
                    q2 = q_at(otm_rows, session, hhmm)
                    if e2 and q2:
                        pnl += (e2["bid"] - q2["ask"])
                    else:
                        legs[label] = None
                        continue
                legs[label] = round(pnl / spot * 1e4, 1)
        row["pnl_bps_by_exit"] = legs
        rows_out.append(row)
        if (i + 1) % 25 == 0:
            print(json.dumps({"progress": i + 1,
                              "at": session}), flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for row in rows_out:
            f.write(json.dumps(row) + "\n")
    print(json.dumps({"rows_written": len(rows_out)}), flush=True)


if __name__ == "__main__":
    main()
