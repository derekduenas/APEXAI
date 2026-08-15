#!/usr/bin/env python
"""THE DISCOVERY EXERCISE: FULL APEX, online at every historical T.

    python scripts/discovery_exercise.py

Governed by APEX-PROFIT-MACHINE-EXERCISE-SPEC.md (frozen 589c6d92...).
DEVELOPMENT ONLY: in-sample, zero credits, holdout sealed. Every decision
is frozen at T before its outcome is looked at; the outcome is recorded
beside it and the artifact is never revised. Ablation decisions are
computed AFTER the FULL decision (code order enforces the freeze).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nightly_pull import _chain_append  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.distribution.estimator import EstimatorError, empirical_conditional  # noqa: E402
from apex.experiments import apex003  # noqa: E402
from apex.features.factory import build_features  # noqa: E402
from apex.features.registry import built_specs  # noqa: E402
from apex.opportunity.engine import evaluate_opportunity  # noqa: E402
from apex.portfolio.risk import PortfolioState  # noqa: E402
from apex.world.state import classify_online  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
SPEC_HASH = "589c6d92daf434151132f48489337460982e12b92b96d54dfaedae494b839778"
MEMORY = Path("results/research_memory.jsonl")
OUT_JSON = Path("results/discovery_exercise_results.json")

NAV, WEIGHT = 500_000.0, 0.03
SPREAD, TURNOVER = 0.003, 1.6
TRAIL_DAYS, MIN_OBS = 750, 100
EVERY_NTH = 6
CAUSAL_RUNG = {"feature": "MECHANISM_SUPPORTED", "composite": "ASSOCIATIONAL"}


def progress(m):
    print(f"  [{time.strftime('%H:%M:%S')}] {m}", file=sys.stderr, flush=True)


def main() -> int:  # noqa: C901
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    in_start, in_end = cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    assert pd.Timestamp(in_end) < pd.Timestamp(cfg.period("validation")["start"])

    progress("loading in-sample panel (registered small-cap band, slim)")
    panel, _ = build_production_panel(ROOT, cfg, cfg.get("calendar.lake_start"),
                                      in_end, slim_high_low=True)
    output, _ = apex003.build_gp_output(panel, cfg, ROOT)
    eligible = output.universe.eligible
    fwd = output.forward_returns.excess          # 20d fwd excess, PIT-formed
    sector = panel.meta["sector"]

    grid_all = output.calendar.grid_formation_dates(in_start, in_end)
    grid_all = pd.DatetimeIndex([d for d in grid_all
                                 if eligible.loc[d].sum() >= 200])

    progress("building the mechanism-tagged feature library (batched: the "
             "all-at-once build OOM-killed at 14 full-height frames; one "
             "feature at a time, sliced to grid rows, then freed)")
    specs = [s for s in built_specs()]
    grid_values: dict = {}
    for s in specs:
        v, _k, _r = build_features(ROOT, panel, (s,))
        grid_values[s.feature_id] = v[s.feature_id].loc[grid_all].copy()
        del v, _k
        progress(f"  built {s.feature_id}")

    # candidate set per frozen spec: signed features + H3 composite
    candidates, refused_at_generation = {}, []
    for s in specs:
        if s.directionality == "higher_better":
            candidates[s.feature_id] = (grid_values[s.feature_id], "feature", s)
        elif s.directionality == "lower_better":
            candidates[s.feature_id] = (-grid_values[s.feature_id], "feature", s)
        else:
            refused_at_generation.append(
                {"candidate": s.feature_id,
                 "reason": "unsigned directionality: no mechanism-backed "
                           "directional prediction; refused at generation"})
    elig_grid = eligible.loc[grid_all]
    r_gp = grid_values["prof_gross_profitability"].where(elig_grid).rank(axis=1, pct=True)
    r_val = grid_values["val_book_to_market"].where(elig_grid).rank(axis=1, pct=True)
    candidates["qv_composite_h3"] = ((r_gp + r_val) / 2, "composite", None)
    dates = grid_all[::EVERY_NTH]
    progress(f"{len(candidates)} candidates x {len(dates)} dates "
             f"(denominator {len(candidates) * len(dates)})")

    spy = panel.benchmark_tr
    uvol = panel.close_adj.pct_change().mean(axis=1)          # EW universe daily
    addv = panel.dollar_volume.rolling(60, min_periods=1).mean().loc[grid_all]
    gp_rank = r_gp

    # analogue state vectors, prior-only z-distance
    def state_vec(t):
        s = spy.loc[:t].dropna()
        r = s.pct_change().dropna()
        return np.array([s.iloc[-1] / s.tail(200).mean() - 1,
                         r.tail(20).std() * np.sqrt(252),
                         s.iloc[-1] / s.max() - 1])

    rows, portfolio_positions = [], []      # (expiry_index, sector, heat)
    heat, sectors_w = 0.02, {}
    Path(MEMORY).parent.mkdir(parents=True, exist_ok=True)

    for di, T in enumerate(dates):
        state = classify_online(spy, T)
        vol_ann = float(uvol.loc[:T].tail(60).std() * np.sqrt(252)) * 1.0
        # decay expired positions
        portfolio_positions = [p for p in portfolio_positions if p[0] > di]
        heat = 0.02 + sum(p[2] for p in portfolio_positions)
        sectors_w = {}
        for p in portfolio_positions:
            sectors_w[p[1]] = sectors_w.get(p[1], 0.0) + WEIGHT

        # analogue diagnostic (prior dates only)
        vecs = np.array([state_vec(t) for t in dates[:di]]) if di >= 8 else None
        analogue = None
        if vecs is not None:
            z = (vecs - vecs.mean(0)) / (vecs.std(0) + 1e-9)
            me = (state_vec(T) - vecs.mean(0)) / (vecs.std(0) + 1e-9)
            near = np.argsort(((z - me) ** 2).sum(1))[:5]
            outs = [float(fwd.loc[dates[j]].where(eligible.loc[dates[j]]).mean())
                    for j in near]
            analogue = {"dates": [str(dates[j].date()) for j in near],
                        "subsequent_universe_excess_mean": round(float(np.mean(outs)), 5),
                        "n": len(outs), "diagnostic_only": True}

        for name, (sig, kind, spec) in candidates.items():
            ranks_T = sig.loc[T].where(eligible.loc[T]).rank(pct=True)
            bucket = ranks_T[ranks_T >= 0.9].index
            # trailing conditional observations: resolved before T
            hist_dates = [d for d in grid_all
                          if d <= T - pd.Timedelta(days=30)
                          and d >= T - pd.Timedelta(days=TRAIL_DAYS * 1.5)]
            obs = []
            for d in hist_dates:
                rk = sig.loc[d].where(eligible.loc[d]).rank(pct=True)
                b = rk[rk >= 0.9].index
                obs.append(fwd.loc[d, b].dropna().to_numpy())
            obs = np.concatenate(obs) if obs else np.array([])

            est, refuse_reason = None, None
            try:
                est = empirical_conditional(
                    obs, 20, signal=name,
                    conditioning={"universe": "smallcap", "bucket": "top decile"},
                    estimation_window=f"trailing {TRAIL_DAYS}d to T-30d")
            except EstimatorError as e:
                refuse_reason = f"insufficient evidence: {e}"

            bucket_sector = (sector.reindex(bucket).mode().iat[0]
                             if len(bucket) else "UNKNOWN")
            bucket_addv = float(addv.loc[T, bucket].median()) if len(bucket) else 0.0
            port = PortfolioState(nav=NAV, positions={}, sector_weights=dict(sectors_w),
                                  heat=heat, drawdown_budget_left=0.20,
                                  sleeve_correlations={})
            common = dict(
                name=f"{name}@{T.date()}",
                hypothesis_lineage=f"registry:{name} ({kind}); mechanism="
                                   f"{(spec.transformation if spec else 'quality-value interaction')[:60]}",
                signal={"candidate": name, "kind": kind,
                        "redundancy_corr_vs_gp": round(float(
                            ranks_T.corr(gp_rank.loc[T])), 3) if name != "prof_gross_profitability" else 1.0,
                        "causal_rung": CAUSAL_RUNG[kind]},
                chain=(), spot=100.0,
                expression_config=load_config("expression"),
                weight=WEIGHT, ann_vol=vol_ann, sector=bucket_sector,
                target_notional=WEIGHT * NAV, addv_usd=max(bucket_addv, 1.0),
                relative_spread=SPREAD, annual_turnover=TURNOVER)

            # FULL decision FIRST (frozen before ablations, before outcome)
            if refuse_reason:
                from apex.opportunity.engine import _no_trade
                full = _no_trade(common["name"], [refuse_reason],
                                 common["hypothesis_lineage"], state,
                                 common["signal"], "REFUSED")
                decision = "REFUSED"
            else:
                full = evaluate_opportunity(market_state=state, estimate=est,
                                            portfolio=port, **common)
                decision = full.decision
                if decision == "NO-TRADE" and len(full.reasons) == 1 \
                        and "insufficient expected net edge" in full.reasons[0]:
                    bar = 0.02 * (1.5 if state.get("uncertain") else 1.0)
                    import re
                    m = re.search(r"([+-]\d+\.\d+)%", full.reasons[0])
                    if m and float(m.group(1)) / 100 > bar - 0.01:
                        decision = "WATCH"

            tier = None
            if decision == "TRADE":
                p_neg = float(est.probs[est.returns < 0].sum())
                tier = "A" if (full.expected_net_annual >= 0.08
                               and p_neg <= 0.45 and len(obs) >= 300
                               and not state.get("uncertain")
                               and full.capacity_usd >= 3 * WEIGHT * NAV) else "B"
                portfolio_positions.append((di + 1, bucket_sector,
                                            WEIGHT * vol_ann))

            # ablations (AFTER the frozen FULL decision)
            fresh = PortfolioState(nav=NAV, positions={}, sector_weights={},
                                   heat=0.02, drawdown_budget_left=0.20,
                                   sleeve_correlations={})
            abl = {}
            if est is not None:
                abl["A_raw_signal"] = "TRADE"
                abl["B_no_uncertainty"] = evaluate_opportunity(
                    market_state=dict(state, uncertain=False), estimate=est,
                    portfolio=port, **common).decision
                abl["F_no_risk"] = evaluate_opportunity(
                    market_state=state, estimate=est, portfolio=fresh,
                    **{**common, "weight": 0.01}).decision
                abl["H_no_costs"] = evaluate_opportunity(
                    market_state=state, estimate=est, portfolio=port,
                    **{**common, "relative_spread": 0.0,
                       "annual_turnover": 0.0}).decision
                abl["J_no_portfolio_ctx"] = evaluate_opportunity(
                    market_state=state, estimate=est, portfolio=fresh,
                    **common).decision
            else:
                abl = {k: "REFUSED" for k in
                       ("A_raw_signal", "B_no_uncertainty", "F_no_risk",
                        "H_no_costs", "J_no_portfolio_ctx")}
                abl["A_raw_signal"] = "TRADE" if len(bucket) else "REFUSED"

            # realization AFTER the frozen decisions
            realized = float(fwd.loc[T, bucket].dropna().mean()) if len(bucket) else float("nan")
            period_cost = TURNOVER * (2 * SPREAD / 2) / (252 / 20)
            row = {
                "date": str(T.date()), "candidate": name, "kind": kind,
                "state": state["regime"], "uncertain": state["uncertain"],
                "stress": state["stress"],
                "decision": decision, "tier": tier,
                "reasons": list(full.reasons),
                "expected_net_annual": full.expected_net_annual,
                "n_obs": int(len(obs)),
                "redundancy_corr_vs_gp": common["signal"]["redundancy_corr_vs_gp"],
                "causal_rung": common["signal"]["causal_rung"],
                "realized_20d_excess": round(realized, 5) if realized == realized else None,
                "realized_net_20d": round(realized - period_cost, 5)
                                    if realized == realized else None,
                "ablations": abl,
                "analogue": analogue,
                "spec_hash": SPEC_HASH,
            }
            rows.append(row)
            _chain_append(MEMORY, {"kind": "discovery_decision", **row})
        progress(f"{T.date()}: {sum(1 for r in rows if r['date'] == str(T.date()) and r['decision'] == 'TRADE')} trades "
                 f"of {len(candidates)}")

    OUT_JSON.write_text(json.dumps(
        {"spec_hash": SPEC_HASH, "dates": len(dates),
         "candidates": len(candidates),
         "refused_at_generation": refused_at_generation,
         "denominator": {"candidate_dates": len(rows),
                         "horizons_considered": 1, "model_fits": 0},
         "rows": rows}, indent=2) + "\n")
    progress(f"wrote {OUT_JSON} ({len(rows)} decisions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
