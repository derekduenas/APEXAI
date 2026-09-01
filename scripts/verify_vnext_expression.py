"""MONSTER V_NEXT verification replay (DIAGNOSTIC_REPLAY_ONLY).

Re-runs the wind-tunnel event sessions (COIN disaster, HIMS trend
winner, SBUX chop) through consult with expression_engine=True.
Acceptance: every option expression receives a genuine expected
value; CASH wins or loses FOR A STATED ECONOMIC REASON, never by
forfeit. The cohort pmf is EXPANDING: only PM events strictly
before each event's session feed its distribution.
"""
from __future__ import annotations

import json
from pathlib import Path

from apex.monster import consult as mc
from apex.monster.event_expert import EventRecord
from apex.organism import options_surface as osf

CASES = [
    {"sym": "COIN", "session": "2026-02-13", "rd": "2026-02-12",
     "est": 1.05, "act": 0.66, "rt": 16.21, "exp": "2026-02-20",
     "strike": 150.0, "otm": 142.0, "spot": 149.63, "dte": 7},
    {"sym": "HIMS", "session": "2025-11-04", "rd": "2025-11-03",
     "est": 0.10, "act": 0.09, "rt": 9.34, "exp": "2025-11-14",
     "strike": 41.0, "otm": 39.0, "spot": 41.0, "dte": 10},
    {"sym": "SBUX", "session": "2025-07-30", "rd": "2025-07-29",
     "est": 0.65, "act": 0.50, "rt": 6.51, "exp": "2025-08-08",
     "strike": 90.0, "otm": 86.0, "spot": 90.0, "dte": 9},
]

events = [json.loads(l) for l in
          Path("exports/replay_inputs.jsonl").open()]
PM = [e for e in events if e["timing"] == "pm"
      and e["short_pnl_bps"].get("10:00") is not None]


def cohort_before(session):
    """Expanding: underlying 10:00-horizon returns (bps) of PM
    events strictly before this session."""
    return [-e["short_pnl_bps"]["10:00"] for e in PM
            if e["session"] < session]


def quotes_at(sym, exp, strike, day, hhmm="09:35"):
    rows = osf.td_history_quote(sym, exp, strike, "P", day,
                                interval="5m")
    cut = f"{day}T{hhmm}:00.000"
    past = [r for r in rows if r["t"] <= cut]
    return past[-1] if past else None


def main():
    for c in CASES:
        atm = quotes_at(c["sym"], c["exp"], c["strike"],
                        c["session"])
        otm = quotes_at(c["sym"], c["exp"], c["otm"], c["session"])
        if not atm:
            print(json.dumps({"sym": c["sym"],
                              "status": "NO_ATM_QUOTE"}))
            continue
        pq = {"long_put": {"strike": c["strike"],
                           "bid": atm["bid"], "ask": atm["ask"],
                           "expiry": c["exp"]},
              "put_vertical": {"long": {"strike": c["strike"],
                                        "ask": atm["ask"]},
                               "short": {"strike": c["otm"],
                                         "bid": otm["bid"] if otm
                                         else 0,
                                         "ask": otm["ask"] if otm
                                         else 0},
                               "expiry": c["exp"]}}
        ev = EventRecord(
            symbol=c["sym"], report_date=c["rd"], timing="pm",
            eps_estimate=c["est"], eps_actual=c["act"],
            consensus_provenance="BROKER_REPORTED_CONSENSUS_RH_MCP",
            known_from=f"{c['session']}T09:30:00",
            reaction_session=c["session"])
        rec = mc.consult(ev, rt_cost_bps=c["rt"],
                         short_allowed=False, put_quotes=pq,
                         expression_engine=True, spot=c["spot"],
                         cohort_returns_bps=cohort_before(
                             c["session"]),
                         dte_days=c["dte"])
        ee = rec.get("expression_engine", {})
        print(json.dumps({
            "sym": c["sym"], "session": c["session"],
            "engine_status": ee.get("status"),
            "cohort_n": ee.get("cohort_n"),
            "structures": ee.get("structures"),
            "best_expression": rec.get("best_expression"),
            "cash_verdict_reason": ee.get("cash_verdict_reason"),
            "final": rec["final"]}, default=str), flush=True)


if __name__ == "__main__":
    main()
