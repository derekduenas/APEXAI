"""Experience and error attribution from immutable joins (M5).

Inputs are persisted pilot records (forecast, intent, fill, outcome, refusal, decision) plus, when
available, the realized target (the 15-minute log return from bars available AFTER the target end)
and the entry/exit IV. The join is read-only: nothing is edited, nothing is re-scored in place.

Attribution classes, one primary per scan, AMBIGUOUS when the evidence does not separate them:
    DATA_AVAILABILITY_ERROR    the scan refused or stalled for data reasons (provider, stale, missing)
    FORECAST_LOCATION_ERROR    realized return on the wrong side and outside the central 50% of the forecast
    FORECAST_SCALE_ERROR       |PIT - 0.5| in the tails (PIT < 0.05 or > 0.95) with the sign consistent
    FORECAST_TAIL_ERROR        realized beyond the 99% band
    IV_SCENARIO_ERROR          exit IV moved against the position by more than the declared tolerance
    EXPRESSION_SELECTION_EFFECT chosen expression underperformed WAIT / an alternative in the recorded comparison
    SPREAD_LATENCY_FEES        costs exceeded the gross P&L in magnitude (the thesis was right on mid)
    SOFTWARE_FAILURE           ledger/refusal-persistence/provider exceptions of the software kind
    AMBIGUOUS                  more than one class fits, or the inputs to separate them are absent
The diagnosis may PROPOSE a challenger (a record with a digest); it never edits history or tunes a policy."""
from __future__ import annotations

from apex.options_pilot.records import is_real

import math

from scipy import stats

from apex.worldmodel_wb.contracts import digest

CLASSES = ("DATA_AVAILABILITY_ERROR", "FORECAST_LOCATION_ERROR", "FORECAST_SCALE_ERROR", "FORECAST_TAIL_ERROR", "IV_SCENARIO_ERROR",
           "EXPRESSION_SELECTION_EFFECT", "SPREAD_LATENCY_FEES", "SOFTWARE_FAILURE", "AMBIGUOUS", "NO_ERROR")
SOFTWARE_MARKERS = ("PERSISTENCE_FAILED", "REFUSAL_NOT_PERSISTED", "PROVIDER_FAILED", "ProviderUnavailable", "HTTP", "Traceback")
DATA_MARKERS = ("STALE", "FEATURE_UNAVAILABLE", "LIVE_DATA_DISABLED", "QUOTE_MISSING", "EXIT_QUOTE", "NOT_ESTIMABLE", "NO_SIZE")


def join_scan(rows: list, *, scan_id: str, realized_return: float | None = None, exit_iv: float | None = None, entry_iv: float | None = None,
              iv_tolerance: float = 0.10) -> dict:
    recs = [r for r in rows if r.get("scan_id") == scan_id]
    by = {}
    for r in recs:
        by.setdefault(r["kind"], []).append(r)
    fc = (by.get("pilot_forecast") or [None])[0]
    fills = by.get("pilot_fill") or []
    filled = next((f for f in fills if f.get("status") == "FILLED"), None)
    outcome = next((o for o in by.get("pilot_outcome", []) if o.get("discharges_position")), None)
    refusals = by.get("pilot_refusal") or []
    decision = (by.get("pilot_decision") or [None])[0]
    out = {"kind": "experience_join", "scan_id": scan_id, "records_joined": {k: len(v) for k, v in by.items()},
           "decision": decision.get("decision") if decision else None, "immutable": True, "edits": 0}
    classes, evidence = [], {}
    # software vs data failure
    for r in refusals + [f for f in fills if f.get("decision") in ("REFUSE", "WAIT")]:
        why = r.get("reason") or r.get("why") or ""
        if any(m in why for m in SOFTWARE_MARKERS):
            classes.append("SOFTWARE_FAILURE"); evidence["software"] = why[:160]
        elif any(m in why for m in DATA_MARKERS):
            classes.append("DATA_AVAILABILITY_ERROR"); evidence["data"] = why[:160]
    # forecast vs realized (pre-outcome forecast joined to the later realized target)
    if fc and realized_return is not None and fc.get("family") == "STUDENT_T":
        pit = float(stats.t.cdf(realized_return, fc["nu"], loc=fc["location"], scale=fc["scale"]))
        evidence["pit"] = pit
        if pit < 0.005 or pit > 0.995:
            classes.append("FORECAST_TAIL_ERROR")
        elif pit < 0.05 or pit > 0.95:
            classes.append("FORECAST_SCALE_ERROR")
        elif (pit < 0.25 or pit > 0.75) and is_real(fc.get("location")) and ((realized_return - fc["location"]) * fc["location"] < 0):
            classes.append("FORECAST_LOCATION_ERROR")
    # IV scenario
    if exit_iv is not None and entry_iv is not None and entry_iv > 0 and filled:
        rel = exit_iv / entry_iv - 1.0
        evidence["iv_change_rel"] = rel
        if rel < -iv_tolerance:                                             # long option hurt by falling IV
            classes.append("IV_SCENARIO_ERROR")
    # costs vs gross
    if outcome and outcome.get("status") == "RESOLVED" and filled:
        gross, net = outcome.get("gross_pnl"), outcome.get("pnl")
        evidence.update(gross_pnl=gross, net_pnl=net)
        if gross is not None and net is not None and gross > 0 >= net:
            classes.append("SPREAD_LATENCY_FEES")
    # an unknown P&L is NOT a non-negative outcome: it is UNSCORABLE and says so
    _pnl = (outcome or {}).get("pnl")
    if outcome is not None and not is_real(_pnl):
        return {"primary": "UNSCORABLE_UNKNOWN_PNL", "classes": sorted(classes),
                "why": "the outcome carries no usable net P&L (%r); an unknown result is not a non-negative one" % (_pnl,)}
    primary = "NO_ERROR" if not classes and outcome and _pnl >= 0 else \
        classes[0] if len(set(classes)) == 1 else ("AMBIGUOUS" if classes else "AMBIGUOUS")
    if not classes and not (outcome and _pnl >= 0):
        primary = "AMBIGUOUS"
    out.update(attribution={"primary": primary, "all": sorted(set(classes)), "evidence": evidence,
                            "note": "AMBIGUOUS is a legitimate result; no class is forced"})
    return out


def propose_challenger(*, from_join: dict, hypothesis: str, family: str, features: list) -> dict:
    """A PROPOSAL record. It registers nothing, changes nothing, and names its origin."""
    body = {"kind": "challenger_proposal", "origin_scan_id": from_join["scan_id"], "primary_attribution": from_join["attribution"]["primary"],
            "hypothesis": hypothesis, "family": family, "features": list(features), "status": "PROPOSED_NOT_REGISTERED",
            "authority": "NONE: a human registers challengers; no threshold is changed and no champion is replaced by this record"}
    body["proposal_digest"] = digest(body)
    return body
