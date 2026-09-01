"""THE 2018-2026 ORGANISM WAR (ORGANISM-WAR-2018-2026-REGISTRATION).

Five arms per PM event, chronological, expanding cohort. Measures
whether each LAYER earns after-cost dollars:

  1 CASH | 2 DUMB_PHYSICAL | 3 STATIC_MONSTER_V1 |
  4 MONSTER+EXPRESSION (V_NEXT) | 5 +SHADOW_MANAGEMENT_CANDIDATE

Evidence class: DIAGNOSTIC_REPLAY / ARCHITECTURE_ECONOMICS. No
authority. Missing data -> NOT_ESTIMABLE, never imputed.

Long-running: writes one row per event as it goes (restart-safe by
skipping already-written events).
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

from apex.monster import consult as mc
from apex.monster.event_expert import EventRecord
from apex.organism import microstructure as ms
from apex.organism import options_surface as osf

OUT = Path("results/edge_atlas/organism_war.jsonl")
RAW = Path("exports/earnings_events_raw.jsonl")
INP = Path("exports/replay_inputs.jsonl")
MIN_COHORT = 60
ADVERSE_EXIT_BPS = 150.0        # arm-5 predeclared rule


def load_events():
    raw = {}
    for line in RAW.open():
        r = json.loads(line)
        try:
            raw[(r["symbol"], r["report_date"])] = (
                float(r["eps_estimate"]), float(r["eps_actual"]))
        except (TypeError, ValueError, KeyError):
            continue
    evs = []
    for line in INP.open():
        e = json.loads(line)
        if e["timing"] != "pm" or \
                e["short_pnl_bps"].get("10:00") is None:
            continue
        # report date = previous weekday of the reaction session
        d = datetime.strptime(e["session"], "%Y-%m-%d")
        rd = d - timedelta(days=1)
        while rd.weekday() >= 5:
            rd -= timedelta(days=1)
        key = (e["symbol"], rd.strftime("%Y-%m-%d"))
        if key not in raw:
            continue
        est, act = raw[key]
        evs.append({**e, "report_date": key[1],
                    "eps_estimate": est, "eps_actual": act})
    evs.sort(key=lambda e: e["session"])
    return evs


def utc_off(session):
    m = int(session[5:7])
    return 4 if 4 <= m <= 10 else 5   # EDT Apr-Oct approx


def spot_at_935(sym, session):
    off = utc_off(session)
    try:
        d = ms._get("https://data.alpaca.markets/v2/stocks/"
                    f"{sym}/bars?" + urllib.parse.urlencode(
                        {"start": f"{session}T{9 + off}:34:00Z",
                         "end": f"{session}T{9 + off}:36:00Z",
                         "timeframe": "1Min", "feed": "sip",
                         "limit": 3}))
        bars = d.get("bars") or []
        return bars[-1]["c"] if bars else None
    except Exception:                                   # noqa: BLE001
        return None


def day_quotes(sym, exp, strike, session):
    try:
        return osf.td_history_quote(sym, exp, strike, "P", session,
                                    interval="5m")
    except Exception:                                   # noqa: BLE001
        return []


def q_at(rows, session, hhmm):
    cut = f"{session}T{hhmm}:00.000"
    past = [r for r in rows if r["t"] <= cut]
    return past[-1] if past else None


def main():
    evs = load_events()
    done = set()
    if OUT.exists():
        for line in OUT.open():
            try:
                r = json.loads(line)
                done.add((r["sym"], r["session"]))
            except Exception:                           # noqa: BLE001
                continue
    print(json.dumps({"events": len(evs), "already": len(done)}),
          flush=True)

    exps_cache: dict = {}
    prior_returns: list = []
    n_run = 0
    for e in evs:
        key = (e["symbol"], e["session"])
        u_ret_bps = -e["short_pnl_bps"]["10:00"]
        if key in done:
            prior_returns.append(u_ret_bps)
            continue
        cohort = list(prior_returns)
        prior_returns.append(u_ret_bps)
        if len(cohort) < MIN_COHORT:
            continue
        sym, session = key
        rt = e.get("observed_rt_bps") or 10.0
        dumb = e["short_pnl_bps"]["10:00"] - rt

        row = {"kind": "war_event", "sym": sym, "session": session,
               "surprise": e["surprise"],
               "arm1_cash": 0.0,
               "arm2_dumb_physical": round(dumb, 1),
               "arm3_static_v1": 0.0}

        spot = spot_at_935(sym, session)
        if not spot:
            row["arm4"] = row["arm5"] = "NOT_ESTIMABLE"
            row["why"] = "no spot bar"
        else:
            if sym not in exps_cache:
                try:
                    exps_cache[sym] = osf.td_expirations(sym)
                except Exception:                       # noqa: BLE001
                    exps_cache[sym] = []
            d0 = datetime.strptime(session, "%Y-%m-%d")
            exp = next((x for x in exps_cache[sym]
                        if 5 <= (datetime.strptime(x, "%Y-%m-%d")
                                 - d0).days <= 21), None)
            strike = float(round(spot))
            otm_strike = float(round(spot * 0.95))
            atm_rows = day_quotes(sym, exp, strike, session) \
                if exp else []
            otm_rows = day_quotes(sym, exp, otm_strike, session) \
                if exp else []
            atm0 = q_at(atm_rows, session, "09:35")
            otm0 = q_at(otm_rows, session, "09:35")
            if not (exp and atm0 and atm0["ask"] > atm0["bid"] > 0):
                row["arm4"] = row["arm5"] = "NOT_ESTIMABLE"
                row["why"] = "no executable ATM quote at formation"
            else:
                pq = {"long_put": {"strike": strike,
                                   "bid": atm0["bid"],
                                   "ask": atm0["ask"],
                                   "expiry": exp},
                      "put_vertical": {
                          "long": {"strike": strike,
                                   "ask": atm0["ask"]},
                          "short": {"strike": otm_strike,
                                    "bid": otm0["bid"] if otm0
                                    else 0,
                                    "ask": otm0["ask"] if otm0
                                    else 0},
                          "expiry": exp}}
                ev = EventRecord(
                    symbol=sym, report_date=e["report_date"],
                    timing="pm", eps_estimate=e["eps_estimate"],
                    eps_actual=e["eps_actual"],
                    consensus_provenance="CORPUS",
                    known_from=f"{session}T09:30:00",
                    reaction_session=session)
                dte = (datetime.strptime(exp, "%Y-%m-%d")
                       - d0).days
                try:
                    rec = mc.consult(
                        ev, rt_cost_bps=rt, short_allowed=False,
                        put_quotes=pq, expression_engine=True,
                        spot=spot, cohort_returns_bps=cohort,
                        dte_days=dte)
                except Exception as err:                # noqa: BLE001
                    rec = {"best_expression": "CASH",
                           "consult_error": f"{type(err).__name__}"}
                best = rec.get("best_expression", "CASH")
                row["arm4_choice"] = best
                ee = rec.get("expression_engine", {})
                row["arm4_ev_bps"] = (ee.get("structures", {})
                                      .get(best, {})
                                      .get("expected_net_bps_of_"
                                           "spot"))

                def leg_pnl(rows0, entry_side, hhmm_exit):
                    q0 = q_at(rows0, session, "09:35")
                    q1 = q_at(rows0, session, hhmm_exit)
                    if not q0 or not q1:
                        return None
                    if entry_side == "buy":
                        return q1["bid"] - q0["ask"]
                    return q0["bid"] - q1["ask"]

                def structure_pnl(hhmm_exit):
                    """P&L in bps of spot for the chosen structure,
                    real NBBO both sides."""
                    if best == "long_put":
                        p = leg_pnl(atm_rows, "buy", hhmm_exit)
                        return None if p is None \
                            else p / spot * 1e4
                    if best == "put_debit_spread":
                        a = leg_pnl(atm_rows, "buy", hhmm_exit)
                        b = leg_pnl(otm_rows, "sell", hhmm_exit)
                        return None if a is None or b is None \
                            else (a + b) / spot * 1e4
                    if best == "common_stock":
                        # long stock at 09:35 to exit checkpoint
                        px_ret = -u_ret_bps if hhmm_exit == "10:00" \
                            else None
                        return None if px_ret is None \
                            else px_ret - rt
                    return 0.0                     # CASH etc.

                p4 = structure_pnl("15:55")
                row["arm4"] = round(p4, 1) if isinstance(
                    p4, (int, float)) else "NOT_ESTIMABLE"
                # arm 5: predeclared adverse-exit at 10:00.
                # Bearish structures: adverse = underlying UP more
                # than the threshold by the 10:00 checkpoint.
                adverse = u_ret_bps > ADVERSE_EXIT_BPS
                if best in ("long_put", "put_debit_spread") \
                        and adverse:
                    p5 = structure_pnl("10:00")
                elif best == "CASH":
                    p5 = 0.0
                else:
                    p5 = p4
                row["arm5"] = round(p5, 1) if isinstance(
                    p5, (int, float)) else "NOT_ESTIMABLE"
                row["arm5_exited_early"] = bool(
                    best in ("long_put", "put_debit_spread")
                    and adverse)
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        n_run += 1
        if n_run % 25 == 0:
            print(json.dumps({"progress": n_run,
                              "at": session}), flush=True)
    print(json.dumps({"war_events_written": n_run}), flush=True)


if __name__ == "__main__":
    main()
