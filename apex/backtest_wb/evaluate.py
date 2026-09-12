"""Evaluation of PILOT-REPLAY-001 records: exactly the planned comparisons in contract.py, nothing else."""
from __future__ import annotations

import math
import random

from scipy import stats

from apex.worldmodel_wb.tournament import calibration_report, paired_comparison, pit_t


def _net(v):
    return (v.get("pnl") or {}).get("net") if v else None


def per_scan_value(v):
    """The contract's per-SCAN economic outcome for one variant: a resolved TRADE contributes its net P&L, a legitimate WAIT
    contributes 0 (no incremental trading P&L), anything else (TRADE_UNRESOLVED, REFUSE, missing) is EXCLUDED and counted."""
    if not v:
        return None, "MISSING"
    d = v.get("decision")
    if d == "TRADE" and _net(v) is not None:
        return float(_net(v)), "TRADE"
    if d == "WAIT":
        return 0.0, "WAIT"
    return None, (d or "MISSING")


def paired_per_scan(scans: list, a: str, b: str, *, seed: int = 11, draws: int = 2000) -> dict:
    """Paired difference a - b on the COMMON SCAN population (both variants have a per-scan value), with a session-block
    bootstrap CI of the mean difference. Exclusions are reported per variant and reason, never silently dropped."""
    rows, excl = [], {a: {}, b: {}}
    for r in scans:
        va, ka = per_scan_value((r.get("variants") or {}).get(a))
        vb, kb = per_scan_value((r.get("variants") or {}).get(b))
        if va is None:
            excl[a][ka] = excl[a].get(ka, 0) + 1
        if vb is None:
            excl[b][kb] = excl[b].get(kb, 0) + 1
        if va is None or vb is None:
            continue
        rows.append((r["day"], va - vb, ka, kb))
    d = [x[1] for x in rows]
    by_day: dict = {}
    for day, diff, _, _ in rows:
        by_day.setdefault(day, []).append(diff)
    days = sorted(by_day); rng = random.Random(seed); means = []
    for _ in range(draws):
        pick = [rng.choice(days) for _ in days] if days else []
        vals = [x for dd in pick for x in by_day[dd]]
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    ci = [round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means)) - 1], 4)] if len(means) > 40 else None
    census = {}
    for _, _, ka, kb in rows:
        census["%s/%s" % (ka, kb)] = census.get("%s/%s" % (ka, kb), 0) + 1
    return {"population": "COMMON_SCANS (resolved TRADE = net, WAIT = 0; unresolved/refused excluded and counted)", "n_common_scans": len(rows),
            "n_sessions": len(days), "mean_diff_per_scan": (round(sum(d) / len(d), 4) if d else None),
            "sd_diff": (round(float(math.sqrt(sum((x - sum(d) / len(d)) ** 2 for x in d) / (len(d) - 1))), 4) if len(d) > 1 else None),
            "bootstrap_ci95": ci, "method": "session-block bootstrap, %d draws, seed %d" % (draws, seed), "pair_census": census, "excluded": excl,
            "conclusion": (None if ci is None else ("A_ABOVE_B_ON_THIS_SAMPLE" if ci[0] > 0 else "B_ABOVE_A_ON_THIS_SAMPLE" if ci[1] < 0 else "NOT_DISTINGUISHED"))}


def summarize(records: list, *, seed: int = 11, draws: int = 2000) -> dict:
    scans = [r for r in records if r.get("kind") == "replay_scan"]
    sessions = sorted({r["day"] for r in scans})
    out = {"study_id": "PILOT-REPLAY-001", "evidence_class": "HISTORICAL_DEVELOPMENT_REPLAY", "sessions": len(sessions), "scans": len(scans),
           "planned_comparisons_only": True}
    # decision census for the policy
    dec = {}
    for r in scans:
        d = r.get("decision") or "REFUSE"
        dec[d] = dec.get(d, 0) + 1
    out["policy_decisions"] = dec
    whys = {}
    for r in scans:
        w = (r.get("why") or "").split(":")[0]
        if r.get("decision") != "TRADE":
            whys[w] = whys.get(w, 0) + 1
    out["policy_non_trade_reasons"] = dict(sorted(whys.items(), key=lambda x: -x[1])[:12])
    # trades: per variant
    per = {}
    names = ["POLICY", "RANDOM_DIRECTION", "REVERSED_DIRECTION"] + sorted({n for r in scans for n in (r.get("variants") or {}) if n not in ("POLICY", "RANDOM_DIRECTION", "REVERSED_DIRECTION")})
    for name in names:
        nets = {r["day"] + ":%d" % r["scan"]: _net(r["variants"].get(name)) for r in scans if r.get("variants")}
        nets = {k: v for k, v in nets.items() if v is not None}
        gross = [r["variants"][name]["pnl"]["gross"] for r in scans if r.get("variants") and _net(r["variants"].get(name)) is not None]
        fees = [r["variants"][name]["pnl"]["fees"] for r in scans if r.get("variants") and _net(r["variants"].get(name)) is not None]
        spread = [r["variants"][name]["pnl"].get("spread_crossing_cost") for r in scans if r.get("variants") and _net(r["variants"].get(name)) is not None]
        unresolved = sum(1 for r in scans if r.get("variants") and r["variants"].get(name, {}).get("decision") == "TRADE_UNRESOLVED")
        per[name] = {"trades": len(nets), "unresolved_exits": unresolved, "sum_net": round(sum(nets.values()), 2),
                     "mean_net": (round(sum(nets.values()) / len(nets), 4) if nets else None),
                     "hit_rate": (round(sum(1 for v in nets.values() if v > 0) / len(nets), 4) if nets else None),
                     "sum_gross": round(sum(gross), 2), "sum_fees": round(sum(fees), 2),
                     "sum_spread_crossing": round(sum(s for s in spread if s is not None), 2),
                     "nets": nets}
    out["variants"] = {k: {kk: vv for kk, vv in v.items() if kk != "nets"} for k, v in per.items()}
    # 1. POLICY vs WAIT: session-block bootstrap of the mean net per trade
    pol = per["POLICY"]["nets"]
    by_day = {}
    for k, v in pol.items():
        by_day.setdefault(k.split(":")[0], []).append(v)
    days = sorted(by_day)
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pick = [rng.choice(days) for _ in days] if days else []
        vals = [x for d in pick for x in by_day[d]]
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    out["policy_vs_wait"] = {"mean_net_per_trade": per["POLICY"]["mean_net"], "n_trades": len(pol), "n_sessions_with_trades": len(days),
                             "bootstrap_ci95": ([round(means[int(0.025 * len(means))], 4), round(means[int(0.975 * len(means)) - 1], 4)] if len(means) > 40 else None),
                             "method": "session-block bootstrap, %d draws, seed %d" % (draws, seed),
                             "conclusion": None}
    ci = out["policy_vs_wait"]["bootstrap_ci95"]
    if ci is not None:
        out["policy_vs_wait"]["conclusion"] = ("DID_NOT_DEMONSTRATE_IMPROVEMENT_OVER_WAIT" if ci[0] <= 0 <= ci[1] or ci[1] < 0 else "ABOVE_WAIT_ON_THIS_SAMPLE")
    out["policy_vs_wait_per_scan"] = paired_per_scan([{**r, "variants": {**(r.get("variants") or {}), "WAIT": {"decision": "WAIT"}}} for r in scans if r.get("variants")],
                                                     "POLICY", "WAIT", seed=seed, draws=draws)
    # 2/3. paired comparisons on common rows
    for ctrl in ("RANDOM_DIRECTION", "REVERSED_DIRECTION"):
        out["policy_vs_" + ctrl.lower()] = paired_comparison(pol, per[ctrl]["nets"])
    if "FULL_FUNNEL" in per:
        ff = per["FULL_FUNNEL"]["nets"]
        out["full_funnel_vs_policy"] = paired_per_scan(scans, "FULL_FUNNEL", "POLICY", seed=seed, draws=draws)          # the contract's estimand: per SCAN
        out["full_funnel_vs_policy_trades_only"] = {**paired_comparison(ff, pol), "label": "SUPPLEMENTARY: completed trades both made; NOT the contract's estimand"}
        wait_rows = [{**r, "variants": {**(r.get("variants") or {}), "WAIT": {"decision": "WAIT"}}} for r in scans if r.get("variants")]
        out["full_funnel_vs_wait_per_scan"] = paired_per_scan(wait_rows, "FULL_FUNNEL", "WAIT", seed=seed, draws=draws)
        by_day_ff = {}
        for k, v in ff.items():
            by_day_ff.setdefault(k.split(":")[0], []).append(v)
        d2 = sorted(by_day_ff); mm = []
        for _ in range(draws):
            pick = [rng.choice(d2) for _ in d2] if d2 else []
            vals = [x for d in pick for x in by_day_ff[d]]
            if vals:
                mm.append(sum(vals) / len(vals))
        mm.sort()
        out["full_funnel_vs_wait"] = {"label": "SUPPLEMENTARY per-trade view (completed trades only)", "mean_net_per_trade": per["FULL_FUNNEL"]["mean_net"],
                                      "n_trades": len(ff), "n_sessions_with_trades": len(d2),
                                      "bootstrap_ci95": ([round(mm[int(0.025 * len(mm))], 4), round(mm[int(0.975 * len(mm)) - 1], 4)] if len(mm) > 40 else None)}
        ci2 = out["full_funnel_vs_wait"]["bootstrap_ci95"]
        out["full_funnel_vs_wait"]["conclusion"] = (None if ci2 is None else ("DID_NOT_DEMONSTRATE_IMPROVEMENT_OVER_WAIT" if ci2[0] <= 0 else "ABOVE_WAIT_ON_THIS_SAMPLE"))
        reasons = {}
        rights = {}
        for r in scans:
            v = (r.get("variants") or {}).get("FULL_FUNNEL")
            if not v:
                continue
            if v.get("decision") != "TRADE":
                w = (v.get("why") or "").split(":")[0]; reasons[w] = reasons.get(w, 0) + 1
            else:
                rt = (v.get("contract") or {}).get("right"); rights[rt] = rights.get(rt, 0) + 1
        out["full_funnel_non_trade_reasons"] = dict(sorted(reasons.items(), key=lambda x: -x[1])[:12])
        out["full_funnel_rights"] = rights
        # coverage on the common population: both systems had a forecast
        both = [r for r in scans if r.get("forecast") and (r.get("variants") or {}).get("FULL_FUNNEL")]
        out["full_funnel_coverage"] = {"scans_with_forecast": len(both), "policy_trades": sum(1 for r in both if r["variants"]["POLICY"].get("decision") == "TRADE"),
                                       "funnel_trades": sum(1 for r in both if r["variants"]["FULL_FUNNEL"].get("decision") == "TRADE"),
                                       "both_trade": sum(1 for r in both if r["variants"]["POLICY"].get("decision") == "TRADE" and r["variants"]["FULL_FUNNEL"].get("decision") == "TRADE")}
    # 4. friction share
    g, f, s = per["POLICY"]["sum_gross"], per["POLICY"]["sum_fees"], per["POLICY"]["sum_spread_crossing"]
    out["friction"] = {"sum_gross": g, "sum_fees": f, "sum_spread_crossing": s, "friction_total": round(f + s, 2),
                       "note": "spread crossing is the half-spread paid at entry and at exit (already inside the quoted sides); fees from the SYNTHETIC schedule"}
    # 5. calibration of the artifact on realized 15-minute returns (all scans with a forecast and a realized target)
    pits = [pit_t(r["realized_log_return_15m"], r["forecast"]["location"], r["forecast"]["scale"], r["forecast"]["nu"])
            for r in scans if r.get("forecast") and r.get("realized_log_return_15m") is not None]
    out["artifact_calibration"] = calibration_report(pits) if pits else {"n": 0}
    # direction label skill (the heuristic, not the distribution): sign agreement with the realized return
    agree = [(1 if (r["variants"]["POLICY"]["direction"] == "LONG") == (r["realized_log_return_15m"] > 0) else 0)
             for r in scans if r.get("variants") and r["variants"].get("POLICY", {}).get("direction") and r.get("realized_log_return_15m") not in (None, 0)]
    if agree:
        k = sum(agree); n = len(agree)
        out["direction_label"] = {"n": n, "sign_agreement": round(k / n, 4), "binomial_p_two_sided": float(stats.binomtest(k, n, 0.5).pvalue),
                                  "note": "the heuristic label's sign agreement with the realized 15-minute return; serial dependence across scans is not corrected here"}
    # 6. cap-free counterfactual on POLICY direction
    cf = {r["day"] + ":%d" % r["scan"]: (r["variants"]["POLICY"].get("pnl_counterfactual_no_cap") or {}).get("net")
          for r in scans if r.get("variants") and r["variants"].get("POLICY", {}).get("contract")}
    cf = {k: v for k, v in cf.items() if v is not None}
    out["cap_free_counterfactual"] = {"trades": len(cf), "sum_net": round(sum(cf.values()), 2), "mean_net": (round(sum(cf.values()) / len(cf), 4) if cf else None),
                                      "coverage_vs_policy": len(cf) - len(pol), "paired_on_common_rows": paired_comparison(pol, cf) if pol else None,
                                      "label": "COUNTERFACTUAL: envelope cap removed; recorded, never selected"}
    return out
