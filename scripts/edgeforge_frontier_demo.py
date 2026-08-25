"""EDGEFORGE FRONTIER — first full-stack demonstration.

Runs the whole research loop on real SPY history: genome, hypotheses,
analog worlds with quality reporting, causal-resampled worlds, a fitted
conditional generator with validation and a memorization test, a
triangulated multiverse, an attack tournament against baselines, the
adversary, residual search, self-critique, scaling, capital paths, and
a frontier report that leads with what failed.

The deliverable is the MACHINE, not an edge. A NULL_RESULT here is a
success; a confident discovery on one analog family would be a warning.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.edgeforge import EDGEFORGE_VERSION                # noqa: E402
from apex.edgeforge.adversary import (                      # noqa: E402
    attack_candidate, delayed_entry, entry_slippage, exit_friction,
    iv_shock)
from apex.edgeforge.attack_lab import (                     # noqa: E402
    CandidateAttack, evaluate_common, summarize_attack)
from apex.edgeforge.baselines import arena, build_baselines  # noqa: E402
from apex.edgeforge.challenger import (                     # noqa: E402
    reproducibility_manifest, value_of_information)
from apex.edgeforge.discovery import residual_search        # noqa: E402
from apex.edgeforge.factory import (                        # noqa: E402
    ResearchRun, frontier_report, world_budget)
from apex.edgeforge.genome import MarketStateGenome         # noqa: E402
from apex.edgeforge.hypotheses import (                     # noqa: E402
    HypothesisTournament, MarketHypothesis)
from apex.edgeforge.multiverse import (                     # noqa: E402
    branches_from_analogs, select_analogs)
from apex.edgeforge.observatory import analog_quality       # noqa: E402
from apex.edgeforge.outcome_intel import gate_value         # noqa: E402
from apex.edgeforge.registry import (                       # noqa: E402
    record_result, register_discovery)
from apex.edgeforge.scaling import (                        # noqa: E402
    scale_response, simulate_capital_paths)
from apex.edgeforge.self_critic import critique             # noqa: E402
from apex.edgeforge.world_foundry import (                  # noqa: E402
    ConditionalStateSpaceGenerator, causal_resampled_worlds,
    generative_health, memorization_test, results_by_class,
    triangulate, validate_generated_worlds, world_set_hash)
from apex.governance.verification import stamp              # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
SESSION, T_ET = "2026-08-24", "09:55"
CODE_PATHS = ["scripts/edgeforge_frontier_demo.py"] + [
    f"apex/edgeforge/{m}" for m in
    ("genome.py", "hypotheses.py", "multiverse.py", "attack_lab.py",
     "world_foundry.py", "adversary.py", "baselines.py", "discovery.py",
     "self_critic.py", "scaling.py", "observatory.py",
     "outcome_intel.py", "factory.py", "challenger.py")]


def _get(url, k, s):
    r = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode())


def et(iso):
    return f"{int(iso[11:13]) - 4:02d}:{iso[14:16]}"


def day_bars(d, k, s):
    return _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Min"
                f"&start={d}T13:25:00Z&end={d}T20:05:00Z&limit=10000"
                f"&feed=sip&adjustment=raw", k, s).get("bars", [])


def prestate(mins, prior_close):
    rth = [b for b in mins if "09:30" <= et(b["t"]) < "16:00"]
    pre = [b for b in rth if et(b["t"]) < T_ET]
    if len(pre) < 20 or not prior_close:
        return None
    o, last = pre[0]["o"], pre[-1]["c"]
    hi, lo = max(b["h"] for b in pre), min(b["l"] for b in pre)
    vw = sum(b["c"] * b["v"] for b in pre) / (sum(b["v"] for b in pre) or 1)
    return ({"gap_pct": (o / prior_close - 1) * 100,
             "open_drift_pct": (last / o - 1) * 100,
             "open_range_pct": (hi - lo) / o * 100,
             "vwap_dist_pct": (last - vw) / o * 100,
             "close_pos_in_range": ((last - lo) / (hi - lo)
                                    if hi > lo else 0.5)}, last, rth)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/edgeforge")
    ap.add_argument("--coarse", type=int, default=160)
    ap.add_argument("--k", type=int, default=45)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = out / "discovery_registry.jsonl"
    run = ResearchRun(session=SESSION, tier="SMOKE")

    register_discovery(
        reg, discovery_id="EFFRONTIER_SPY_20260824",
        research_question=("does the 09:55 SPY pre-state carry short-"
                           "side asymmetry that survives triangulated "
                           "worlds, baselines and the adversary?"),
        feature_set=["gap_pct", "open_drift_pct", "open_range_pct",
                     "vwap_dist_pct", "close_pos_in_range"],
        interaction_form="joint_prestate_similarity",
        dataset_boundary="DAY1_CORRECTED + alpaca_sip_2018_2026",
        search_method="frontier_full_stack_v1",
        multiple_testing_family="edgeforge_demo_family")

    # ---------- INGEST + GENOME
    days = _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
                f"&start=2018-01-01&end=2026-08-22&limit=10000"
                f"&feed=sip&adjustment=raw", a.key, a.secret)["bars"]
    idx = {b["t"][:10]: i for i, b in enumerate(days)}
    ps, spot, _rth = prestate(day_bars(SESSION, a.key, a.secret),
                              days[-1]["c"])
    g = MarketStateGenome(subject="SPY", T=f"{SESSION} {T_ET}",
                          session=SESSION,
                          source_lineage="DAY1_CORRECTED")
    for kk, v in ps.items():
        g.add("UNDERLYING", kk, round(v, 4), known_from=T_ET,
              source="alpaca_sip_1min", pedigree="OBSERVED")
    run.stage("BUILD_GENOMES", {"state_hash": g.state_hash()})

    # ---------- HYPOTHESES
    tour = HypothesisTournament(state_hash=g.state_hash())
    for hid, mech, fals in (
        ("H1_CONTINUATION", "opening downside impulse continues",
         ("reclaim of opening VWAP",)),
        ("H2_ORDINARY_VOL", "ordinary opening two-way rotation",
         ("sustained one-sided drift beyond the opening range",)),
        ("H3_FAILED_IMPULSE", "trap; early shorts fuel a squeeze",
         ("new session lows after 10:30",))):
        tour.enter(MarketHypothesis(hypothesis_id=hid, birth_time=g.T,
                                    mechanism=mech, falsifiers=fals))
    run.stage("UPDATE_HYPOTHESES", tour.standings())

    # ---------- ANALOGS + QUALITY
    coarse = sorted(((abs((days[i]["o"] / days[i - 1]["c"] - 1) * 100
                          - ps["gap_pct"]), s)
                     for s, i in idx.items()
                     if s < SESSION and i > 5), key=lambda x: x[0])
    pre_feats, futures, regimes, series = {}, {}, {}, {}
    for _d, sess in coarse[:a.coarse]:
        try:
            r = prestate(day_bars(sess, a.key, a.secret),
                         days[idx[sess] - 1]["c"])
            if r is None:
                continue
            f, ref, rth = r
            pre_feats[sess] = {k2: round(v, 4) for k2, v in f.items()}
            fut = [b for b in rth if T_ET <= et(b["t"]) < "16:00"]
            if len(fut) > 300:
                futures[sess] = tuple((i, b["c"])
                                      for i, b in enumerate(fut))
                rets = [fut[i]["c"] / fut[i - 1]["c"] - 1
                        for i in range(1, len(fut))]
                rng_pct = f["open_range_pct"]
                reg_lbl = ("HIGH_VOL" if rng_pct > 0.8 else
                           "QUIET" if rng_pct < 0.3 else "NORMAL")
                regimes[sess] = reg_lbl
                series.setdefault(reg_lbl, []).append(rets)
        except Exception:                                # noqa: BLE001
            continue

    sel = select_analogs(current_features=ps, candidates=pre_feats,
                         k=a.k)
    aq = analog_quality(sel, regime_of=regimes)
    bf = branches_from_analogs(selection=sel, futures=futures,
                               parent_state_hash=g.state_hash())

    from apex.edgeforge.multiverse import WorldBranch
    empirical = []
    for w in bf["branches"]:
        ref = w.path[0][1]
        empirical.append(WorldBranch(
            branch_id=w.branch_id, parent_state_hash=w.parent_state_hash,
            hypothesis_condition=w.hypothesis_condition,
            generation_method="EMPIRICAL_HISTORICAL_ANALOG",
            generation_pedigree="[EMPIRICAL_ANALOG] " +
            w.generation_pedigree + "; normalized to Monday spot",
            path=tuple((t, round(spot * px / ref, 4))
                       for t, px in w.path),
            source_session=w.source_session))

    # ---------- RESAMPLED + GENERATIVE
    pool = [r for s in series.get("NORMAL", []) for r in s]
    resampled = causal_resampled_worlds(
        returns_pool=pool or [0.0001, -0.0001], n_worlds=40,
        horizon=min(360, len(empirical[0].path) if empirical else 360),
        start_price=spot, parent_state_hash=g.state_hash(), seed=17,
        regime_label="NORMAL") if pool else []

    gen_model = ConditionalStateSpaceGenerator()
    fit = gen_model.fit(series_by_regime=series)
    generated, gval, gmem = [], {}, {}
    if "NORMAL" in fit["regimes"]:
        generated = gen_model.sample(
            regime="NORMAL", n_worlds=40,
            horizon=min(360, len(empirical[0].path) if empirical else 360),
            start_price=spot, parent_state_hash=g.state_hash(), seed=23)
        gval = validate_generated_worlds(generated=generated,
                                         real=empirical)
        gmem = memorization_test(
            generated=generated,
            training_paths=[w.path for w in empirical[:25]])
    ghealth = generative_health(
        validation=gval or {"verdict": "INSUFFICIENT_DATA"},
        memorization=gmem or {"verdict": "INSUFFICIENT_DATA"},
        regime_coverage={r: len(v) for r, v in series.items()})
    if ghealth["generative_world_eligibility"] == "SUSPENDED":
        generated = []

    worlds = empirical + resampled + generated
    tri = triangulate({"EMPIRICAL_ANALOG": empirical,
                       "CAUSAL_RESAMPLED": resampled,
                       "LEARNED_GENERATIVE": generated})
    run.stage("GENERATE_WORLDS", {**tri, "world_set_hash":
                                  world_set_hash(worlds)})

    # ---------- TOURNAMENT + BASELINES
    put = CandidateAttack(
        attack_id="incumbent_long_put_2dte", kind="INCUMBENT",
        expression="LONG_PUT",
        params={"entry_premium": 2.79, "strike": 763.0,
                "option_type": "put", "iv": 0.146, "dte_days": 2,
                "contracts": 1, "exit_friction_per_contract": 1.0},
        evaluator_name="long_option_bsm",
        execution_pedigree="MODELLED_BSM_REPRICE", declared_1R=279.0)
    tourney = evaluate_common(attacks=[put], worlds=worlds)
    put_summary = summarize_attack(tourney, put)
    by_class = results_by_class(tourney, worlds, put.attack_id)
    ar = arena(candidate=put, baselines=build_baselines(entry=spot),
               worlds=worlds, evaluate_common=evaluate_common,
               summarize_attack=summarize_attack)
    run.stage("ATTACK_TOURNAMENT", {"summary": put_summary,
                                    "by_class": by_class})

    # ---------- ADVERSARY
    adv = attack_candidate(
        attack=put, worlds=worlds, evaluate_common=evaluate_common,
        stress_grid={
            "ENTRY_SLIPPAGE": [(0.05, entry_slippage(0.05)),
                               (0.20, entry_slippage(0.20))],
            "IV_SHOCK": [(-0.01, iv_shock(-0.01)),
                         (-0.03, iv_shock(-0.03))],
            "SPREAD_EXPANSION": [(2.0, exit_friction(2.0)),
                                 (10.0, exit_friction(10.0))],
            "DELAYED_ENTRY": [(15, delayed_entry(15)),
                              (60, delayed_entry(60))]})
    run.stage("ADVERSARY", {"verdict": adv["verdict"],
                            "fragile_under": adv["fragile_under"]})

    # ---------- RESIDUAL SEARCH over the analog population
    pop = []
    for m in sel["analogs"]:
        fut = futures.get(m.session)
        if not fut:
            continue
        ref = fut[0][1]
        pop.append({**pre_feats[m.session],
                    "regime": regimes.get(m.session, "UNKNOWN"),
                    "session": m.session,
                    "outcome_R": (fut[-1][1] / ref - 1) * -100})
    resid = residual_search(
        observations=pop, incumbent_equivalence=("regime",),
        candidate_variables=("gap_pct", "open_range_pct",
                             "vwap_dist_pct", "close_pos_in_range"),
        outcome_key="outcome_R", family="VOLATILITY_TRANSITIONS")
    run.stage("RUN_FRONTIER_DISCOVERY", {
        "verdict": resid["verdict"],
        "comparisons": resid["search_accounting"][
            "family_wise_search_count"]})

    # ---------- SELF-CRITIC
    crit = critique(
        discovery={"dataset_boundary": "DAY1_CORRECTED",
                   "falsifiers": ("reclaim of opening VWAP",),
                   "competing_explanations": ("H2", "H3")},
        analog_quality=aq, adversary=adv, arena=ar,
        world_class_split=by_class,
        family={"n_experiments": 2, "n_null_or_dead": 1},
        prospective_n=0)

    # ---------- SCALING + CAPITAL
    scale = scale_response(
        base_edge_per_unit=max(put_summary.get("median_pnl", 0.0), 0.0),
        touch_liquidity=60.0, spread=0.01, unit_notional=279.0)
    rmults = []
    for bid, o in tourney["outcomes"][put.attack_id].items():
        if isinstance(o.get("pnl"), (int, float)):
            rmults.append(o["pnl"] / 279.0)
    caps = simulate_capital_paths(
        r_multiples=rmults or [0.0], risk_fraction=0.02,
        trades_per_path=200, n_paths=300, starting_equity=10_000,
        seed=31) if rmults else {}

    # ---------- REPORT
    nulls, killed, inferior = [], [], []
    if ar["verdict"] == "INFERIOR_TO_A_SIMPLE_BASELINE":
        inferior.append({"candidate": put.attack_id,
                         "lost_to": ar["lost_to"]})
    if adv["verdict"] == "FRAGILE":
        killed.append({"candidate": put.attack_id,
                       "fragile_under": adv["fragile_under"]})
    if put_summary.get("favorable_world_fraction", 0) < 0.5:
        nulls.append({"candidate": put.attack_id,
                      "favorable_world_fraction":
                      put_summary["favorable_world_fraction"]})

    repro = reproducibility_manifest(
        code_sha="see provenance stamp",
        dataset_boundary="DAY1_CORRECTED + alpaca_sip_2018_2026",
        source_registry="apex.governance.evidence_registry",
        genome_hash=g.state_hash(),
        experiment_id="EFFRONTIER_SPY_20260824",
        world_generator_version=EDGEFORGE_VERSION,
        world_set_hash=world_set_hash(worlds),
        candidate_attack_definition=put.attack_id,
        correction_lineage="results/day1_corrected/day1_corrections.jsonl")

    voi = value_of_information(
        feed_name="level2_equity_depth", decisions_changed=0,
        decisions_observed=0, losses_avoided="NOT_ESTIMABLE",
        opportunities_found="NOT_ESTIMABLE",
        discrimination_delta="NOT_ESTIMABLE",
        execution_delta="NOT_ESTIMABLE", cost_monthly=0,
        latency_ms=0, complexity="unknown", new_failure_modes=())

    rep = frontier_report(
        run, discoveries=resid["findings"][:3], nulls=nulls,
        killed_by_adversary=killed, inferior_to_baseline=inferior,
        disagreements=[tour.standings()],
        gate_value=gate_value(
            cohorts={"PAPER_ATTACKED": [-0.19], "WAIT_FOR_ENTRY": [0.04]},
            horizon_note="Day-1 session close (n_eff=1)"),
        edge_health_warnings=[], world_model_health=ghealth,
        sample_sufficiency={"analog_quality": aq["verdict"],
                            "concerns": aq["concerns"],
                            "prospective_sessions": 0},
        research_debt=["prospective sessions required before any "
                       "candidate may advance past RESEARCH_CANDIDATE"])

    record_result(reg, discovery_id="EFFRONTIER_SPY_20260824",
                  status="NULL_RESULT",
                  result={"favorable_world_fraction":
                          put_summary.get("favorable_world_fraction"),
                          "adversary": adv["verdict"],
                          "arena": ar["verdict"]},
                  why="full-stack demonstration; one analog family and "
                      "zero prospective sessions establish no edge")

    payload = {"kind": "edgeforge_frontier_demo",
               "version": EDGEFORGE_VERSION,
               "genome": g.as_record(),
               "hypotheses": tour.standings(),
               "analog_quality": aq, "triangulation": tri,
               "generator_fit": fit, "generative_validation": gval,
               "memorization": gmem, "generative_health": ghealth,
               "attack_summary": put_summary, "by_world_class": by_class,
               "baseline_arena": ar, "adversary": adv,
               "residual_search": resid, "self_critique": crit,
               "scale_response": scale, "capital_paths": caps,
               "value_of_information": voi,
               "reproducibility": repro, "frontier_report": rep}
    (out / "frontier_demo.json").write_text(
        json.dumps(stamp(payload, CODE_PATHS), indent=1, default=str))

    print(json.dumps({
        "worlds": tri["class_shares"], "n_worlds": tri["n_worlds"],
        "analog_quality": aq["verdict"], "concerns": aq["concerns"],
        "generator": fit["eligibility"],
        "gen_validation": gval.get("verdict"),
        "memorization": gmem.get("verdict"),
        "gen_eligibility": ghealth["generative_world_eligibility"],
        "put_favorable": put_summary.get("favorable_world_fraction"),
        "by_class": by_class["per_class"], "class_flag": by_class["flag"],
        "arena": ar["verdict"], "adversary": adv["verdict"],
        "fragile_under": adv["fragile_under"],
        "residual": resid["verdict"],
        "critique": crit["research_confidence"],
        "critique_concerns": crit["concerns"],
        "scale": scale["verdict"],
        "risk_of_ruin": caps.get("risk_of_ruin"),
        "repro": repro["verdict"],
        "negative_findings": rep["n_negative_findings"]},
        indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
