#!/usr/bin/env python
"""Preregistered analysis for REPLAY-CAMPAIGN-V1 — written BEFORE the
campaign completed; the report shape is frozen in the campaign doc.

    python scripts/hunter_replay_analysis.py --tag campaign_v1

Everything here is EODHD_HISTORICAL_EXPLORATORY: findings, hypotheses
for future versions, never Epoch 1 changes. Cells under the sample floor
are labeled INSUFFICIENT and not interpreted.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.world.twin2 import load_spy_daily  # noqa: E402
from apex.world.state import classify_online  # noqa: E402

FLOOR_SESSIONS = 10
HORIZONS = (15, 30, 60, 90)


def stats(rows, h=60):
    rets = [r[f"ret_{h}m"] for r in rows if r.get(f"ret_{h}m") is not None]
    if not rets:
        return {"n": len(rows), "n_scored": 0}
    a = np.array(rets)
    out = {"n": len(rows), "n_scored": len(a),
           "ev": round(float(a.mean()), 5),
           "median": round(float(np.median(a)), 5),
           "hit": round(float((a > 0).mean()), 3),
           "p10_tail": round(float(np.quantile(a, 0.10)), 5)}
    mfe = [r[f"mfe_{h}m"] for r in rows if r.get(f"mfe_{h}m") is not None]
    mae = [r[f"mae_{h}m"] for r in rows if r.get(f"mae_{h}m") is not None]
    if mfe:
        out["mfe_med"] = round(float(np.median(mfe)), 5)
    if mae:
        out["mae_med"] = round(float(np.median(mae)), 5)
    sess = {r.get("session_date") for r in rows}
    out["n_sessions"] = len(sess)
    if len(sess) < FLOOR_SESSIONS:
        out["status"] = "INSUFFICIENT_DO_NOT_INTERPRET"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="campaign_v1")
    a = ap.parse_args()
    base = Path(f"results/hunter/replay_{a.tag}")
    rows = []
    for line in (base / "replay_ledger.jsonl").read_text().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by = {}
    for r in rows:
        by.setdefault(r.get("kind"), []).append(r)
    realized = {r["decision_id"]: r for r in by.get("realization", [])
                if r.get("resolvable")}
    dec = {d["decision_id"]: d for d in by.get("decision", [])}

    def merged(ids):
        return [{**dec[i], **realized[i]} for i in ids
                if i in dec and i in realized]

    pb_ids = [i for i, d in dec.items()
              if not d["playbook_id"].startswith("BASELINE-")]
    mom_ids = [i for i, d in dec.items()
               if d["playbook_id"] == "BASELINE-MOMENTUM"]
    reviews = by.get("assassin_review", [])
    clean = [r["decision_id"] for r in reviews
             if r.get("verdict") == "SURVIVED_CLEAN"]
    wounded = [r["decision_id"] for r in reviews
               if r.get("verdict") == "SURVIVED_WOUNDED"]
    caps = by.get("capital_decision", [])
    observe = [c["decision_id"] for c in caps
               if c.get("final_state") == "OBSERVE"]

    # session regime labels (online SPY classifier — world data, never
    # candidate outcomes)
    spy = load_spy_daily("2026-08-15", None)
    regime_of = {}
    sessions = sorted({r.get("session_date") for r in rows
                       if r.get("session_date")})
    if spy is not None:
        for d in sessions:
            try:
                regime_of[d] = classify_online(spy, d)["regime"]
            except Exception:                               # noqa: BLE001
                regime_of[d] = "UNKNOWN"

    def by_regime(ids):
        out = {}
        for reg in sorted(set(regime_of.values())):
            sub = [i for i in ids
                   if regime_of.get(dec[i]["session_date"]) == reg]
            out[reg] = stats(merged(sub))
        return out

    # post-hoc deterministic ablation: capital re-evaluated with Assassin
    # wounds zeroed (NO-ASSASSIN-CAUTION) on identical candidates
    from apex.hunter.capital import ForecastSlot, evaluate_candidate
    from apex.portfolio.risk import PortfolioState
    pf = PortfolioState(nav=100_000.0, positions={}, sector_weights={},
                        heat=0.0, drawdown_budget_left=1.0,
                        sleeve_correlations={})
    flips = Counter()
    for c in caps:
        d = dec.get(c["decision_id"])
        if d is None:
            continue
        uni_file = base.parent.parent / "hunter" / \
            f"scan_universe_{d['session_date']}.json"
        meta = {}
        if uni_file.exists():
            meta = json.loads(uni_file.read_text())["symbols"].get(
                d["symbol"], {})
        cd = evaluate_candidate(
            {**d, "forward_eligibility": "FORWARD_ELIGIBLE"},
            sector=meta.get("sector"),
            median_dollar_volume=meta.get("median_dollar_volume"),
            ann_vol=(d.get("chart_state") or {}).get("realized_vol_ann"),
            market_uncertain=(c.get("gates") or {}).get("regime_uncertain",
                                                        False),
            forecast=ForecastSlot(), portfolio=pf,
            disagreement_level=None, analog_support_low=False)
        flips[f"{c['final_state']}->{cd.final_state}"] += 1

    # A. REPLAY INTEGRITY FIRST — economics is not interpreted unless
    # these are clean (operator law)
    prev, chain_ok, torn = "GENESIS", True, 0
    for r in rows:
        if r.get("prev_hash") != prev:
            chain_ok = False
        if r.get("recovered_from_torn_tail"):
            torn += 1
        prev = r.get("entry_hash", prev)
    classes = {r.get("evidence_class") for r in rows}
    scan_by_day = Counter(r["session_date"] for r in by.get("scan", []))
    expected_ticks = 25                     # 09:45..15:45 every 15m = 25
    short_days = {d: n for d, n in scan_by_day.items()
                  if n < expected_ticks}
    swarm_ok_views = sum(
        1 for r in by.get("forecast_bundle", [])
        if (r.get("swarm_view") or {}).get("status") == "OK")
    prod_ledger = Path("results/hunter/forward_ledger.jsonl")
    hollow_days = sorted({s2["session_date"] for s2 in by.get("scan", [])
                          if s2.get("states_computed", 0) < 50})
    integrity = {
        "sessions_replayed": f"{len(sessions)} (predeclared ~92)",
        "hollow_days_states_lt_50": hollow_days or "none",
        "scan_ticks_short_days": short_days or "none",
        "ledger_chain_valid": chain_ok,
        "torn_tail_recoveries": torn,
        "rule_17_llm_views_in_replay": swarm_ok_views,
        "evidence_classes_present": sorted(c for c in classes if c),
        "class_pure_exploratory": classes <= {
            "EODHD_HISTORICAL_EXPLORATORY", None},
        "production_ledger_writes": (
            "NONE (file absent)" if not prod_ledger.exists()
            else f"file exists with {len(prod_ledger.read_text().splitlines())} lines — VERIFY none from replay"),
    }
    integrity["VERDICT"] = (
        "CLEAN — economics may be interpreted"
        if chain_ok and swarm_ok_views == 0
        and not hollow_days
        and integrity["class_pure_exploratory"]
        else "NOT CLEAN — do NOT interpret economics below")

    report = {
        "campaign": "REPLAY-CAMPAIGN-V1 (preregistered)",
        "0_integrity_first": integrity,
        "evidence": "EODHD_HISTORICAL_EXPLORATORY — laboratory only",
        "sessions": len(sessions),
        "regime_coverage": dict(Counter(regime_of.values())),
        "1_funnel": {
            "scout_baseline_momentum": stats(merged(mom_ids)),
            "hunter_matched": stats(merged(pb_ids)),
            "assassin_clean": stats(merged(clean)),
            "assassin_wounded": stats(merged(wounded)),
            "capital_observe": stats(merged(observe))},
        "2_assassin_brutal": {
            f"{h}m": {"clean": stats(merged(clean), h),
                      "wounded": stats(merged(wounded), h)}
            for h in HORIZONS},
        "3_baselines": {
            pid: stats(merged([i for i, d in dec.items()
                               if d["playbook_id"] == pid]))
            for pid in sorted({d["playbook_id"] for d in dec.values()
                               if d["playbook_id"].startswith("BASELINE-")})},
        "4_by_regime": {"hunter_matched": by_regime(pb_ids),
                        "scout_baseline": by_regime(mom_ids)},
        "5_edge_persistence_exploratory": {
            pid: {f"{h}m": stats(merged(
                [i for i in pb_ids
                 if dec[i]["playbook_id"] == pid]), h).get("ev")
                for h in HORIZONS}
            for pid in sorted({dec[i]["playbook_id"] for i in pb_ids})},
        "6_ablation_no_assassin_caution": {
            "capital_state_flips": dict(flips),
            "note": "identical candidates, wounds zeroed; flips show what "
                    "the Assassin's caution changed"},
        "7_concentration": {
            "by_symbol": dict(Counter(dec[i]["symbol"]
                                      for i in pb_ids).most_common(10)),
            "by_playbook": dict(Counter(dec[i]["playbook_id"]
                                        for i in pb_ids)),
            "by_hour_et": dict(Counter(
                pd.Timestamp(dec[i]["t_utc"]).tz_convert(
                    "America/New_York").hour for i in pb_ids)),
            "by_direction": dict(Counter(dec[i]["direction"]
                                         for i in pb_ids))},
        "discipline": "findings -> versioned hypotheses via governance; "
                      "Epoch 1 unchanged",
    }
    out = base / "CAMPAIGN-REPORT.json"
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report, indent=1, default=str))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
