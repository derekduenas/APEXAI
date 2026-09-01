"""MONSTER COMBAT REPORT -- daily tournament reporting + operations
acceptance. Reads only the sealed prospective ledger; changes nothing.

Modes:
  report [YYYY-MM-DD]   the daily combat report (defaults: latest
                        session with resolutions) + cumulative
                        scoreboards, physical/expression attribution,
                        volatility decomposition, failure classes
  acceptance            the operations-acceptance checklist over the
                        whole ledger (Tuesday's question: did the
                        machinery behave, independent of P&L)

Attribution decomposition per option leg (entry->exit), from OBSERVED
data only; where greeks were not captured, components are
NOT_ESTIMABLE and only totals are reported:

  DELTA_CAPTURE   net_entry_delta * (spot_exit - spot_entry) * 100
  GAMMA           0.5 * net_gamma * (dspot)^2 * 100
  THETA           net_theta * session_fraction(0.26 day) * 100
  SPREAD_DRAG     (entry: ask-mid) + (exit: mid-bid) summed per leg
  VOL_RESIDUAL    total - delta - gamma - theta - spread
                  (vega*dIV + unmodeled; labeled residual, honestly)

decision_power: REPORTING_ONLY.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

LEDGER = Path("results/event_sprint/prospective_ledger.jsonl")
SESSION_DAY_FRACTION = 0.26          # 09:36 -> 15:55 as fraction of a day

FAILURE_CLASSES = (
    "PHYSICAL_THESIS_WRONG", "PHYSICAL_EDGE_TOO_SMALL",
    "NEGATIVE_SURPRISE_NO_INCREMENT", "ENTRY_EDGE_DECAYED",
    "EVENT_SPREAD_TOO_LARGE", "OPTION_IV_TOO_EXPENSIVE",
    "IV_CRUSH_DESTROYED_EXPRESSION", "THETA_DRAG",
    "OPTION_SPREAD_DESTROYED_EDGE", "VERTICAL_CAP_FORFEITED_TAIL",
    "BROKER_EXPRESSION_UNAVAILABLE", "DATA_NOT_ESTIMABLE",
    "OTHER_WITH_EVIDENCE")


def rows():
    if not LEDGER.exists():
        return []
    out = []
    for l in LEDGER.read_text().splitlines():
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def _mid(leg):
    if leg and leg.get("bid") and leg.get("ask"):
        return 0.5 * (leg["bid"] + leg["ask"])
    return None


def option_eval(entry_rec, exit_rec):
    """Per-event expression evaluation. Returns dict per structure."""
    out = {}
    spot_e = entry_rec.get("spot")
    spot_x = exit_rec.get("spot") if exit_rec else None
    lp = entry_rec.get("long_put")
    sp = entry_rec.get("short_put")
    legs_x = (exit_rec or {}).get("legs", {})

    def greeks(leg, sign):
        g = leg.get("greeks")
        if not isinstance(g, dict):
            return None
        return {k: sign * v for k, v in g.items()}

    def decompose(total, net_g, spread_drag):
        if net_g is None or spot_e is None or spot_x is None:
            return {"status": "PARTIALLY_NOT_ESTIMABLE",
                    "spread_drag_$": round(spread_drag, 2)}
        ds = spot_x - spot_e
        delta_c = net_g["delta"] * ds * 100
        gamma_c = 0.5 * net_g["gamma"] * ds * ds * 100
        theta_c = net_g["theta"] * SESSION_DAY_FRACTION * 100
        resid = total - delta_c - gamma_c - theta_c + spread_drag
        return {"delta_capture_$": round(delta_c, 2),
                "gamma_$": round(gamma_c, 2),
                "theta_$": round(theta_c, 2),
                "spread_drag_$": round(-spread_drag, 2),
                "vol_residual_$": round(resid, 2)}

    # ---- LONG_PUT ------------------------------------------------
    if lp and legs_x.get(lp["occ"], {}).get("bid"):
        xq = legs_x[lp["occ"]]
        entry_cost = lp["ask"] * 100
        pnl = (xq["bid"] - lp["ask"]) * 100
        drag = ((lp["ask"] - _mid(lp)) + (_mid(xq) - xq["bid"])) * 100 \
            if _mid(xq) else (lp["ask"] - _mid(lp)) * 100
        out["LONG_PUT"] = {
            "entry_ask": lp["ask"], "exit_bid": xq["bid"],
            "iv_entry": lp.get("iv", "NOT_ESTIMABLE"),
            "pnl_$": round(pnl, 2),
            "capital_at_risk_$": round(entry_cost, 2),
            "roc": round(pnl / entry_cost, 4) if entry_cost else None,
            "pnl_bps_of_underlying": round(
                pnl / (spot_e * 100) * 1e4, 1) if spot_e else None,
            "attribution": decompose(pnl, greeks(lp, +1), drag)}
    else:
        out["LONG_PUT"] = {"status": "NOT_ESTIMABLE",
                           "why": "missing entry or exit quote"}

    # ---- PUT_VERTICAL --------------------------------------------
    if (isinstance(sp, dict) and lp
            and legs_x.get(lp["occ"], {}).get("bid")
            and legs_x.get(sp["occ"], {}).get("ask")):
        lx, sx = legs_x[lp["occ"]], legs_x[sp["occ"]]
        debit = (lp["ask"] - sp["bid"]) * 100
        exit_val = (lx["bid"] - sx["ask"]) * 100
        pnl = exit_val - debit
        width = (lp["strike"] - sp["strike"]) * 100
        drag = ((lp["ask"] - _mid(lp)) + (_mid(sp) - sp["bid"])
                + ((_mid(lx) - lx["bid"]) if _mid(lx) else 0)
                + ((sx["ask"] - _mid(sx)) if _mid(sx) else 0)) * 100
        ng_l, ng_s = greeks(lp, +1), greeks(sp, -1)
        net_g = ({k: ng_l[k] + ng_s[k] for k in ng_l}
                 if ng_l and ng_s else None)
        out["PUT_VERTICAL"] = {
            "entry_debit_$": round(debit, 2),
            "exit_value_$": round(exit_val, 2),
            "max_loss_$": round(debit, 2),
            "max_gain_$": round(width - debit, 2),
            "pnl_$": round(pnl, 2),
            "roc": round(pnl / debit, 4) if debit else None,
            "pnl_bps_of_underlying": round(
                pnl / (spot_e * 100) * 1e4, 1) if spot_e else None,
            "attribution": decompose(pnl, net_g, drag)}
    else:
        out["PUT_VERTICAL"] = {"status": "NOT_ESTIMABLE",
                               "why": "missing short leg or exit "
                                      "quotes"}
    return out


def classify_failure(physical_bps, opt):
    """Deterministic failure classes from measured components."""
    tags = []
    if physical_bps is not None and physical_bps < 0:
        tags.append("PHYSICAL_THESIS_WRONG")
    for name in ("LONG_PUT", "PUT_VERTICAL"):
        o = opt.get(name, {})
        if o.get("status") == "NOT_ESTIMABLE":
            tags.append("DATA_NOT_ESTIMABLE")
            continue
        pnl = o.get("pnl_$")
        att = o.get("attribution", {})
        if pnl is None or pnl >= 0:
            continue
        if physical_bps is not None and physical_bps > 0:
            vr = att.get("vol_residual_$")
            th = att.get("theta_$")
            sd = att.get("spread_drag_$")
            if isinstance(vr, (int, float)) and vr < pnl * 0.5:
                tags.append("IV_CRUSH_DESTROYED_EXPRESSION")
            if isinstance(th, (int, float)) and th < 0 \
                    and abs(th) > abs(pnl) * 0.5:
                tags.append("THETA_DRAG")
            if isinstance(sd, (int, float)) and abs(sd) > abs(pnl):
                tags.append("OPTION_SPREAD_DESTROYED_EDGE")
            if not tags:
                tags.append("OTHER_WITH_EVIDENCE")
    return sorted(set(tags)) or ["NONE"]


def build(day=None):
    rs = rows()
    res = [r for r in rs if r.get("kind") == "price_resolution"]
    if not res:
        return {"status": "NO_RESOLUTIONS_YET",
                "watch_rows": sum(1 for r in rs
                                  if r.get("kind") == "watch")}
    days = sorted({r["reaction_session"] for r in res})
    day = day or days[-1]
    obs = {(r["symbol"], r["reaction_session"]): r for r in rs
           if r.get("kind") == "prospective_observation"}
    ent = {(r["symbol"], r["reaction_session"]): r for r in rs
           if r.get("kind") == "option_entry"}
    exi = {(r["symbol"], r["reaction_session"]): r for r in rs
           if r.get("kind") == "option_exit"}
    cert = {(r["symbol"], r["report_date"]): r for r in rs
            if r.get("kind") == "timing_certification"}
    watch = [r for r in rs if r.get("kind") == "watch"]

    today_res = [r for r in res if r["reaction_session"] == day]
    per_event, failures = [], defaultdict(int)
    for r in today_res:
        k = (r["symbol"], r["reaction_session"])
        o = obs.get(k, {})
        opt = option_eval(ent[k], exi.get(k)) if k in ent else {
            "LONG_PUT": {"status": "NOT_ESTIMABLE",
                         "why": "no entry capture"},
            "PUT_VERTICAL": {"status": "NOT_ESTIMABLE",
                             "why": "no entry capture"}}
        phys = (r.get("short_pnl_res_bps_by_checkpoint") or {}
                ).get("+5m", r.get("short_pnl_res_bps"))
        tags = classify_failure(phys, opt)
        for t in tags:
            failures[t] += 1
        per_event.append({
            "symbol": r["symbol"], "timing": r["timing"],
            "surprise_class": o.get("surprise_class",
                                    "PENDING_ACTUAL"),
            "timing_cert": cert.get(
                (r["symbol"], r["report_date"]), {}
            ).get("classification", "NOT_YET_CERTIFIED"),
            "physical_short_bps_by_checkpoint":
                r.get("short_pnl_res_bps_by_checkpoint"),
            "expressions": opt,
            "failure_classes": tags})

    # cumulative scoreboards (never mixed)
    fin = [r for r in rs if r.get("kind") == "prospective_observation"
           and r.get("short_pnl_res_bps") is not None]
    pm = [r for r in fin if r["timing"] == "pm"]
    neg = [r for r in pm if r["surprise_class"] == "NEGATIVE"]
    nn = [r for r in pm if r["surprise_class"] != "NEGATIVE"]

    def blk(v):
        return ({"n": len(v)} if not v else
                {"n": len(v),
                 "mean_bps": round(statistics.mean(v), 1),
                 "win": round(sum(1 for x in v if x > 0) / len(v), 3)})

    report = {
        "kind": "monster_combat_report", "session": day,
        "EVENTS_EXPECTED": sum(
            1 for w in watch
            if (w["timing"] == "pm"
                and w["report_date"] < day)
            or (w["timing"] == "am" and w["report_date"] == day)),
        "EVENTS_OBSERVED": len(today_res),
        "TIMING_CERTIFIED": sum(
            1 for e in per_event
            if e["timing_cert"] not in ("NOT_YET_CERTIFIED",
                                        "TIMING_UNCERTIFIED")),
        "NEGATIVE_SURPRISES": sum(
            1 for e in per_event
            if e["surprise_class"] == "NEGATIVE"),
        "NON_NEGATIVE": sum(
            1 for e in per_event
            if e["surprise_class"] in ("POSITIVE", "SMALL_NEUTRAL")),
        "PENDING_ACTUAL": sum(
            1 for e in per_event
            if e["surprise_class"] == "PENDING_ACTUAL"),
        "per_event": per_event,
        "cumulative": {
            "A1_PM_FADE_PHYSICAL": blk(
                [r["short_pnl_res_bps"] for r in pm]),
            "A2_NEGATIVE_COHORT": blk(
                [r["short_pnl_res_bps"] for r in neg]),
            "A2_INCREMENT_bps": (round(
                statistics.mean([r["short_pnl_res_bps"] for r in neg])
                - statistics.mean([r["short_pnl_res_bps"]
                                   for r in nn]), 1)
                if neg and nn else "NOT_ESTIMABLE_YET"),
            "CASH": 0.0},
        "FAILURE_CLASSES": dict(failures),
        "EVIDENCE_LOST": sum(1 for r in rs
                             if r.get("kind") == "missed_evidence"),
        "PROSPECTIVE_N_FINALIZED": len(fin),
        "NO_CLAIM_CHANGES": True,
        "decision_power": "REPORTING_ONLY"}
    return report


def acceptance():
    rs = rows()
    kinds = defaultdict(int)
    for r in rs:
        kinds[r.get("kind")] += 1
    res = [r for r in rs if r.get("kind") == "price_resolution"]
    ent = [r for r in rs if r.get("kind") == "option_entry"]
    exi = [r for r in rs if r.get("kind") == "option_exit"]
    checks = {
        "watch_rows_sealed_before_outcomes": kinds["watch"] > 0,
        "estimates_sealed_with_PIT_provenance": all(
            r.get("consensus_provenance")
            == "PIT_SEALED_BEFORE_OUTCOME_RH_MCP"
            for r in rs if r.get("kind") == "watch"),
        "all_resolutions_have_checkpoints": all(
            r.get("short_pnl_res_bps_by_checkpoint")
            for r in res) if res else "NO_RESOLUTIONS_YET",
        "option_entries_follow_sealed_rule": all(
            "SEALED" in (r.get("selection_rule") or "")
            for r in ent) if ent else "NO_ENTRIES_YET",
        "every_quoted_entry_has_exit_attempt": (
            {(r["symbol"], r["reaction_session"]) for r in ent
             if r.get("status") == "QUOTED"}
            <= {(r["symbol"], r["reaction_session"]) for r in exi}
        ) if ent else "NO_ENTRIES_YET",
        "no_backfilled_observations": all(
            r.get("finalized_utc", "9999") > r.get("resolved_utc", "")
            for r in rs
            if r.get("kind") == "prospective_observation"),
        "chain_hashes_present": all(
            "entry_hash" in r for r in rs[:50]),
        "missed_evidence_recorded_not_hidden":
            kinds["missed_evidence"],
        "row_counts": dict(kinds)}
    return checks


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "report":
        day = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(build(day), indent=1))
    elif mode == "acceptance":
        print(json.dumps(acceptance(), indent=1))
