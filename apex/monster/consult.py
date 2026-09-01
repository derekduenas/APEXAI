"""The Monster consult surface -- many mechanisms, one opportunity,
disagreement preserved. SHADOW ONLY.

Two related event experts compete without blurring:

  EVENT_PM_FADE (A1)         every causally valid PM earnings event;
                             never consults the actual EPS.
  EVENT_NEG_SURPRISE (A2)    negative surprises only; claims ONLY the
                             increment over A1 and may never inherit
                             credit for the generic PM effect.

Expert states (never numbers invented to fill an interface):
  ACTIVE / NOT_IMPLEMENTED / NOT_CONSULTED / NOT_ESTIMABLE / REFUSED
"""
from __future__ import annotations

from datetime import datetime, timezone

from apex.capital.arena import Candidate, PortfolioState, compete
from apex.monster import event_expert, pm_fade_expert
from apex.monster.event_expert import EventRecord

AGREEMENT_STATES = ("STRONG_AGREEMENT", "MODERATE_AGREEMENT",
                    "HIGH_DISAGREEMENT", "INSUFFICIENT_EVIDENCE",
                    "NO_EDGE", "NOT_ESTIMABLE",
                    "RELATED_EXPERTS_NOT_INDEPENDENT")

ABSENT = {
    "STATISTICAL_H5": ("NOT_CONSULTED",
                       "H5 historically refuted economically at both "
                       "frozen and measured costs (sealed verdicts)"),
    "CONTINUATION": ("NOT_IMPLEMENTED", "no governed expert exists"),
    "REVERSAL": ("NOT_IMPLEMENTED", "no governed expert exists"),
    "PROPAGATION": ("NOT_IMPLEMENTED",
                    "PARALLAX observes prospectively; no validated "
                    "forward model yet"),
    "LIQUIDITY": ("NOT_IMPLEMENTED", "no governed expert exists"),
    "FORCED_FLOW": ("NOT_ESTIMABLE",
                    "BTC predator does not opine on single equities"),
}


def _expressions(gross_bps, *, short_allowed, put_quotes, rt_cost_bps):
    rows = {}
    net = (gross_bps - rt_cost_bps) \
        if isinstance(rt_cost_bps, (int, float)) else "NOT_ESTIMABLE"
    rows["SHORT_STOCK_BENCHMARK"] = {
        "expected_net_bps": net,
        "broker_eligible": bool(short_allowed),
        "note": "physical-economic benchmark"
        + ("" if short_allowed else
           " -- current Agentic broker CANNOT short equities")}
    if put_quotes:
        rows["LONG_PUT"] = {"status": "QUOTED",
                            "quotes": put_quotes.get("long_put")}
        rows["PUT_VERTICAL"] = {"status": "QUOTED",
                                "quotes": put_quotes.get("put_vertical")}
    else:
        rows["LONG_PUT"] = {"status": "NOT_ESTIMABLE",
                            "why": "no executable option quotes at "
                                   "formation; IV never guessed"}
        rows["PUT_VERTICAL"] = dict(rows["LONG_PUT"])
    rows["CASH"] = {"expected_net_bps": 0.0, "loss": 0.0,
                    "friction": 0.0, "optionality": "FULL"}
    executable = [k for k, v in rows.items()
                  if k != "CASH"
                  and v.get("broker_eligible") is not False
                  and v.get("status") != "NOT_ESTIMABLE"
                  and isinstance(v.get("expected_net_bps"),
                                 (int, float))
                  and v["expected_net_bps"] > 0]
    return rows, (executable[0] if executable else "CASH")


def consult(ev: EventRecord, *, rt_cost_bps=None, short_allowed=False,
            put_quotes=None, portfolio=None,
            expression_engine=False, spot=None,
            cohort_returns_bps=None, dte_days=None) -> dict:
    """expression_engine=False preserves V1 semantics byte-for-byte
    (the frozen Lane-A path). True = MONSTER V_NEXT: the wind-tunnel
    expression defect fix -- options receive genuine expected values
    from apex/expression/engine via the bridge."""
    now = datetime.now(timezone.utc).isoformat()

    fade_opp, fade_op = pm_fade_expert.evaluate(
        symbol=ev.symbol, report_date=ev.report_date,
        timing=ev.timing, known_from=ev.known_from,
        reaction_session=ev.reaction_session, rt_cost_bps=rt_cost_bps)
    neg_opp, neg_op = event_expert.evaluate(ev, rt_cost_bps=rt_cost_bps)

    experts = {
        "EVENT_PM_FADE": {"state": "ACTIVE" if fade_opp else "REFUSED",
                          "opinion": fade_op},
        "EVENT_NEG_SURPRISE_INCREMENT": {
            "state": "ACTIVE" if neg_opp else "REFUSED",
            "opinion": neg_op},
        "OPTIONS_VOL": ({"state": "ACTIVE", "note": "real quotes"}
                        if put_quotes else
                        {"state": "NOT_ESTIMABLE",
                         "why": "no executable option quotes"}),
    }
    for name, st in ABSENT.items():
        experts[name] = {"state": st[0], "why": st[1]}

    if fade_opp and neg_opp:
        agreement = "RELATED_EXPERTS_NOT_INDEPENDENT"
        disagreement = ("both bearish, but A2 conditions on a subset "
                        "of A1's events -- their agreement carries no "
                        "independent confirmation value")
    elif fade_opp or neg_opp:
        agreement = "INSUFFICIENT_EVIDENCE"
        disagreement = "NOT_ESTIMABLE (single informative expert)"
    else:
        agreement = "NO_EDGE"
        disagreement = "NOT_ESTIMABLE"

    record = {"kind": "monster_consult", "evaluated_utc": now,
              "subject": ev.symbol,
              "experts": experts,
              "mechanism_agreement": agreement,
              "mechanism_disagreement": disagreement,
              "decision_power": "SHADOW"}

    if fade_opp is None and neg_opp is None:
        record.update({"physical_thesis": "NONE", "final": "NO_TRADE",
                       "final_reason": fade_op.get("refusal")
                       or neg_op.get("refusal")})
        return record

    base_gross = (fade_opp.forecast_pedigree["expected_gross_bps"]
                  if fade_opp else 0.0)
    incr = (neg_opp.forecast_pedigree[
        "expected_incremental_gross_bps"] if neg_opp else 0.0)
    gross = base_gross + incr
    net = (gross - rt_cost_bps) \
        if isinstance(rt_cost_bps, (int, float)) else "NOT_ESTIMABLE"
    record["physical_thesis"] = {
        "direction": "SHORT", "horizon": "session close",
        "base_pm_fade_gross_bps": base_gross,
        "neg_surprise_incremental_gross_bps":
            incr if neg_opp else "NOT_APPLICABLE",
        "incremental_status": "UNPROVEN" if neg_opp else
            "NOT_APPLICABLE",
        "combined_gross_bps": gross,
        "rt_cost_bps": rt_cost_bps if rt_cost_bps is not None
        else "NOT_ESTIMABLE",
        "expected_net_bps": net,
        "uncertainty": "HIGH -- A1 thin vs costs, A2 increment CI "
                       "spans zero; the tournament decides"}

    exprs, best = _expressions(gross, short_allowed=short_allowed,
                               put_quotes=put_quotes,
                               rt_cost_bps=rt_cost_bps)
    record["expressions"] = exprs
    record["best_expression"] = best

    # ---- MONSTER V_NEXT: real expression economics (default OFF;
    # the V1/Lane-A path above is untouched when the flag is False)
    if expression_engine and spot and put_quotes \
            and cohort_returns_bps is not None and dte_days:
        from apex.monster import expression_bridge
        lp = put_quotes.get("long_put") or {}
        pv = (put_quotes.get("put_vertical") or {})
        otm = pv.get("short")
        scored = expression_bridge.score_expressions(
            spot=spot, dte_days=dte_days,
            atm_put={"strike": lp.get("strike"),
                     "bid": lp.get("bid"), "ask": lp.get("ask")},
            otm_put=(otm and {"strike": otm.get("strike"),
                              "bid": otm.get("bid"),
                              "ask": otm.get("ask", 0)}) or None,
            cohort_returns_bps=cohort_returns_bps,
            rt_cost_bps=rt_cost_bps if isinstance(
                rt_cost_bps, (int, float)) else 10.0)
        record["expression_engine"] = scored
        if scored.get("status") == "SCORED":
            record["best_expression"] = scored["best_expression"]
            best = scored["best_expression"]

    if best != "CASH":
        cand = Candidate(candidate_id=f"EVENT:{ev.symbol}:"
                                      f"{ev.reaction_session}",
                         symbol=ev.symbol, direction="SHORT",
                         expression=best, declared_risk=100.0,
                         edge_pedigree="REPLAY_ONLY",
                         entry_quality="UNKNOWN")
        record["arena"] = compete(
            candidates=[cand],
            portfolio=portfolio
            or PortfolioState(available_capital=600.0))
        final = "WATCH"
        reason = ("positive after cost in SHADOW, but authority "
                  "OBSERVE_ONLY and prospective evidence pending")
    else:
        record["arena"] = {"verdict": "CASH_PREFERRED",
                           "why": "no expression preserved positive "
                                  "after-cost edge"}
        final = "NO_TRADE"
        reason = "cash dominated every executable expression"

    record["risk_kernel"] = {"consulted": False,
                             "why": "no capital authority exists"}
    record["final"] = final
    record["final_reason"] = reason
    return record
