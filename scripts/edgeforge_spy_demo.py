"""EDGEFORGE V0 — FIRST DEMONSTRATION: SPY 2026-08-24 09:55 ET.

The question is NOT "should APEX have taken the SPY put" -- one session
answers nothing. The deliverable is proof of the RESEARCH MACHINE:
genome -> competing hypotheses -> causal analogs -> empirical multiverse
-> common-world attack lab -> adversarial stress -> edge surface ->
WHY_SMALL_WINS -> draft EdgeDNA, end to end, on corrected real data.

CAUSAL DISCIPLINE. EdgeForge receives SPY at 09:55 knowing nothing
after 09:55. Analog membership is fixed from pre-state features
computed identically at each historical morning; only then are those
mornings' actual afternoons revealed as world branches.

Data: Alpaca SIP daily + minute bars (run on the cloud host).
Incumbent facts: the frozen Day-1 card + CORRECTED resolution lineage.
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
from apex.edgeforge.attack_lab import (                     # noqa: E402
    CandidateAttack, evaluate_common, summarize_attack)
from apex.edgeforge.edge_dna import (                       # noqa: E402
    EdgeDNA, SmallWinsAssessment, capital_accelerant_assessment)
from apex.edgeforge.edge_surface import AxisSpec, sweep     # noqa: E402
from apex.edgeforge.genome import MarketStateGenome         # noqa: E402
from apex.edgeforge.hypotheses import (                     # noqa: E402
    DisagreementState, HypothesisTournament, MarketHypothesis)
from apex.edgeforge.multiverse import (                     # noqa: E402
    adversarial_branch, branches_from_analogs, select_analogs)
from apex.edgeforge.registry import (                       # noqa: E402
    record_result, register_discovery)
from apex.governance.verification import stamp              # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
SESSION = "2026-08-24"
T_ET = "09:55"
CODE_PATHS = ["scripts/edgeforge_spy_demo.py",
              "apex/edgeforge/genome.py", "apex/edgeforge/hypotheses.py",
              "apex/edgeforge/multiverse.py",
              "apex/edgeforge/attack_lab.py",
              "apex/edgeforge/edge_surface.py",
              "apex/edgeforge/edge_dna.py", "apex/edgeforge/registry.py"]


def _get(url, key, sec):
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def daily_bars(key, sec):
    out, token = [], None
    while True:
        url = (f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
               f"&start=2018-01-01&end=2026-08-22&limit=10000&feed=sip"
               f"&adjustment=raw")
        if token:
            url += f"&page_token={token}"
        d = _get(url, key, sec)
        out += d.get("bars", [])
        token = d.get("next_page_token")
        if not token:
            return out


def minute_day(day, key, sec):
    url = (f"{ALPACA}/stocks/SPY/bars?timeframe=1Min"
           f"&start={day}T13:25:00Z&end={day}T20:05:00Z&limit=10000"
           f"&feed=sip&adjustment=raw")
    return _get(url, key, sec).get("bars", [])


def et_hm(iso):
    """UTC iso -> ET HH:MM (EDT assumption for the RTH months used)."""
    h = int(iso[11:13]) - 4
    return f"{h:02d}:{iso[14:16]}"


def prestate(mins, prior_close):
    """Pre-09:55 features, computed identically for every morning."""
    rth = [b for b in mins if "09:30" <= et_hm(b["t"]) < "16:00"]
    pre = [b for b in rth if et_hm(b["t"]) < T_ET]
    if len(pre) < 20 or not prior_close:
        return None
    o = pre[0]["o"]
    last = pre[-1]["c"]
    hi = max(b["h"] for b in pre)
    lo = min(b["l"] for b in pre)
    vwap_n = sum(b["c"] * b["v"] for b in pre)
    vwap_d = sum(b["v"] for b in pre) or 1
    vwap = vwap_n / vwap_d
    return {
        "gap_pct": (o / prior_close - 1.0) * 100,
        "open_drift_pct": (last / o - 1.0) * 100,
        "open_range_pct": (hi - lo) / o * 100,
        "vwap_dist_pct": (last - vwap) / o * 100,
        "close_pos_in_range": (last - lo) / (hi - lo) if hi > lo else 0.5,
    }, last, rth


def future_path(rth, ref):
    fut = [b for b in rth if T_ET <= et_hm(b["t"]) < "16:00"]
    return tuple((i, b["c"]) for i, b in enumerate(fut)), \
        [(b["c"] / ref - 1.0) * 100 for b in fut]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/edgeforge")
    ap.add_argument("--coarse", type=int, default=150)
    ap.add_argument("--k", type=int, default=40)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = out / "discovery_registry.jsonl"

    # ---- register BEFORE any result exists
    register_discovery(
        reg, discovery_id="EFDEMO_SPY_20260824",
        research_question=(
            "was the 09:55 SPY state a favorable short-attack pre-state "
            "historically, and how fragile is a 2-DTE long put there?"),
        feature_set=["gap_pct", "open_drift_pct", "open_range_pct",
                     "vwap_dist_pct", "close_pos_in_range"],
        interaction_form="joint_prestate_similarity",
        dataset_boundary="DAY1_CORRECTED + alpaca_sip_2018_2026",
        search_method="causal_historical_analogs_v0",
        multiple_testing_family="edgeforge_demo_family")

    # ================= A. THE FROZEN GENOME AT 09:55 =================
    days = daily_bars(a.key, a.secret)
    idx = {b["t"][:10]: i for i, b in enumerate(days)}
    mon_mins = minute_day(SESSION, a.key, a.secret)
    # the daily query deliberately ends BEFORE the session (2026-08-22),
    # so Monday's prior close is simply the last daily bar -- and Monday
    # itself can never appear in its own analog candidate pool
    prior_close = days[-1]["c"]
    ps, spot, mon_rth = prestate(mon_mins, prior_close)

    g = MarketStateGenome(subject="SPY", T=f"{SESSION} {T_ET}:04",
                          session=SESSION,
                          source_lineage="DAY1_CORRECTED")
    for k, v in ps.items():
        g.add("UNDERLYING", k, round(v, 4), known_from=f"{T_ET} ET",
              source="alpaca_sip_1min", pedigree="OBSERVED",
              authority="SENSOR")
    g.add("TIME", "time_from_open_min", 25.0, known_from=f"{T_ET} ET",
          source="clock", pedigree="OBSERVED")
    g.add("OPTIONS", "atm_iv", 0.146, known_from=f"{T_ET} ET",
          source="day1_sealed_card", pedigree="COMMISSIONED",
          authority="OPTIONS_FACULTY")
    g.add("PREDATOR_OUTPUT", "entry_quality", "GOOD",
          known_from=f"{T_ET} ET", source="day1_sealed_card",
          pedigree="COMMISSIONED", authority="EQUITY_FACULTY")
    g.add("PREDATOR_OUTPUT", "direction_view", "SHORT",
          known_from=f"{T_ET} ET", source="day1_sealed_card",
          pedigree="COMMISSIONED", authority="EQUITY_FACULTY")
    genome_rec = g.as_record()

    # ================= B. COMPETING HYPOTHESES =======================
    tourney = HypothesisTournament(state_hash=g.state_hash())
    tourney.enter(MarketHypothesis(
        hypothesis_id="H1_DOWNSIDE_CONTINUATION", birth_time=g.T,
        mechanism="opening downside impulse continues as early longs "
                  "are forced out",
        participants=("trapped_open_buyers", "momentum_sellers"),
        supporting_evidence=("negative open drift", "SHORT view from "
                             "the commissioned faculty"),
        falsifiers=("reclaim and hold above opening VWAP",
                    "breach of the declared thesis level 763.82"),
        expected_path_characteristics=("early follow-through",
                                       "MFE front-loaded"),
        expected_volatility_behavior="stays bid"))
    tourney.enter(MarketHypothesis(
        hypothesis_id="H2_ORDINARY_OPEN_VOL", birth_time=g.T,
        mechanism="the first 25 minutes are ordinary opening two-way "
                  "volatility with no directional information",
        participants=("market_makers", "flow_traders"),
        supporting_evidence=("25 minutes is inside normal opening "
                             "rotation",),
        falsifiers=("sustained one-sided drift beyond the opening "
                    "range",),
        expected_path_characteristics=("mean reversion to VWAP",
                                       "chop"),
        expected_volatility_behavior="decays after the open"))
    tourney.enter(MarketHypothesis(
        hypothesis_id="H3_FAILED_IMPULSE_TRAP", birth_time=g.T,
        mechanism="the downside impulse is a trap; early shorts fuel an "
                  "afternoon squeeze",
        participants=("early_shorts", "responsive_buyers"),
        supporting_evidence=("shallow drift relative to range",),
        falsifiers=("new session lows after 10:30",),
        expected_path_characteristics=("early adverse move for shorts",
                                       "grind higher"),
        expected_volatility_behavior="compresses"))
    tourney_rec = tourney.standings()

    disagreement = DisagreementState(
        state_hash=g.state_hash(),
        faculty_a="equity_faculty", reading_a="SHORT, entry GOOD",
        faculty_b="thesis_level",
        reading_b="invalidation only 0.42 (0.05%) above entry",
        inputs_redundancy="HIGHLY_REDUNDANT",
        why=("both derive from the same bar geometry; their agreement "
             "is an echo, and the tight invalidation is the same "
             "geometry restated",)).as_record()

    # ================= C. CAUSAL ANALOG RETRIEVAL ====================
    # coarse pass on daily features (knowable pre-open), then full
    # pre-state features from each candidate's own morning minutes
    cands_coarse = []
    for s, i in idx.items():
        if s >= SESSION or i < 6 or s < "2018-02-01":
            continue
        pc = days[i - 1]["c"]
        gap_proxy = (days[i]["o"] / pc - 1.0) * 100
        cands_coarse.append((abs(gap_proxy - ps["gap_pct"]), s))
    cands_coarse.sort()
    shortlist = [s for _d, s in cands_coarse[:a.coarse]]

    pre_feats, futures = {}, {}
    for s in shortlist:
        try:
            mins = minute_day(s, a.key, a.secret)
            r = prestate(mins, days[idx[s] - 1]["c"])
            if r is None:
                continue
            f, ref, rth = r
            pre_feats[s] = {k: round(v, 4) for k, v in f.items()}
            path, _pct = future_path(rth, ref)
            if len(path) > 300:
                futures[s] = path
        except Exception:                                # noqa: BLE001
            continue

    sel = select_analogs(current_features=ps, candidates=pre_feats,
                         k=a.k)
    sel_rec = {k: v for k, v in sel.items() if k != "analogs"}
    sel_rec["analog_sessions"] = [m.session for m in sel["analogs"]]

    # ================= D. EMPIRICAL MULTIVERSE =======================
    bf = branches_from_analogs(selection=sel, futures=futures,
                               parent_state_hash=g.state_hash())
    worlds = bf["branches"]
    # normalize every analog path to Monday's spot so attacks are
    # evaluated in Monday's coordinates (pct paths applied to 763.40)
    from apex.edgeforge.multiverse import WorldBranch
    norm_worlds = []
    for w in worlds:
        ref = w.path[0][1]
        norm = tuple((t, round(spot * (px / ref), 4)) for t, px in w.path)
        norm_worlds.append(WorldBranch(
            branch_id=w.branch_id, parent_state_hash=w.parent_state_hash,
            hypothesis_condition=w.hypothesis_condition,
            generation_method=w.generation_method,
            generation_pedigree=w.generation_pedigree + "; path "
            "pct-normalized to Monday's 09:55 spot",
            path=norm, source_session=w.source_session))
    worlds = norm_worlds

    # ================= E/F. ATTACK LAB ON COMMON WORLDS ==============
    put = CandidateAttack(
        attack_id="incumbent_long_put_2dte", kind="INCUMBENT",
        expression="LONG_PUT",
        params={"entry_premium": 2.79, "strike": 763.0,
                "option_type": "put", "iv": 0.146, "dte_days": 2,
                "contracts": 1, "exit_friction_per_contract": 1.0},
        evaluator_name="long_option_bsm",
        execution_pedigree="MODELLED_BSM_REPRICE", declared_1R=279.0)
    short_stock = CandidateAttack(
        attack_id="short_stock_100", kind="SYNTHETIC",
        expression="SHORT_STOCK",
        params={"direction": "SHORT", "entry": spot, "shares": 100,
                "round_trip_friction": 2.0},
        evaluator_name="stock",
        execution_pedigree="MODELLED_EXECUTION", declared_1R=279.0)
    flat = CandidateAttack(
        attack_id="no_trade", kind="WAIT", expression="NO_TRADE",
        params={}, evaluator_name="no_trade",
        execution_pedigree="NONE", declared_1R=None)

    run = evaluate_common(attacks=[put, short_stock, flat],
                          worlds=worlds)
    summaries = {x.attack_id: summarize_attack(run, x)
                 for x in (put, short_stock, flat)}

    # ================= G. ADVERSARIAL STRESSES =======================
    stress_specs = [
        ("ENTRY_SLIPPAGE", lambda p: [(t, px + 0.05) for t, px in p],
         "underlying entry 5c against the short"),
        ("DELAYED_ENTRY", lambda p: p[15:] if len(p) > 30 else p,
         "entry 15 minutes late; early path lost"),
        ("GAP_THROUGH_INVALIDATION",
         lambda p: [(t, px + (0.5 if i < 30 else 0.0))
                    for i, (t, px) in enumerate(p)],
         "first half hour marked 50c against the short"),
    ]
    stress_worlds = []
    for kind, fn, note in stress_specs:
        for w in worlds[:10]:
            stress_worlds.append(adversarial_branch(
                base=w, kind=kind, transform=fn, note=note))
    # IV stresses act on the option, not the path
    iv_variants = []
    for shift, name in ((-0.02, "IV_CRUSH"), (+0.02, "IV_EXPANSION")):
        iv_variants.append(CandidateAttack(
            attack_id=f"put_{name}", kind="SYNTHETIC",
            expression="LONG_PUT",
            params={**put.params, "iv_shift": shift},
            evaluator_name="long_option_bsm",
            execution_pedigree="MODELLED_BSM_REPRICE",
            declared_1R=279.0))
    stress_run = evaluate_common(
        attacks=[put] + iv_variants, worlds=worlds + stress_worlds)
    stress_summary = {
        x.attack_id: summarize_attack(stress_run, x)
        for x in [put] + iv_variants}

    # ================= H. EDGE SURFACE ===============================
    surface = sweep(
        base_params=dict(put.params),
        axes=[AxisSpec(name="entry_premium",
                       values=(2.59, 2.79, 2.99, 3.19),
                       mechanism_reason="how much worse can the paid "
                                        "premium get before the edge "
                                        "region flips"),
              AxisSpec(name="iv_shift", values=(-0.02, 0.0, 0.02),
                       mechanism_reason="a 2-DTE long option's value is "
                                        "hostage to IV; the mechanism "
                                        "must survive repricing")],
        worlds=worlds,
        make_attack=lambda p: CandidateAttack(
            attack_id=f"put_e{p['entry_premium']}_iv{p.get('iv_shift', 0)}",
            kind="SYNTHETIC", expression="LONG_PUT", params=p,
            evaluator_name="long_option_bsm",
            execution_pedigree="MODELLED_BSM_REPRICE",
            declared_1R=p["entry_premium"] * 100),
        evaluate_common=evaluate_common,
        summarize_attack=summarize_attack)
    surface_slim = {k: v for k, v in surface.items() if k != "cells"}
    surface_slim["cells"] = surface["cells"]

    # ================= I. WHY_SMALL_WINS =============================
    small = SmallWinsAssessment.build(
        reason="UNKNOWN",
        giant_competition_risk="HIGH").as_record()
    small["honest_note"] = (
        "a 2-DTE ATM SPY put on a 25-minute open drift is the most "
        "institutionally contested terrain in the equity complex; no "
        "small-capital advantage was identified, and the assessment "
        "says so rather than inventing one")

    # ================= J. DRAFT EDGE DNA =============================
    dna = EdgeDNA(
        edge_id="EDGE_CANDIDATE_00001",
        birth_timestamp=datetime.now(timezone.utc).isoformat(),
        discovery_origin="monday_case_study_spy_0955",
        mechanism="short opening downside-drift continuation via short-"
                  "dated long premium",
        required_state={"open_drift_pct": "negative",
                        "entry_quality": "GOOD",
                        "time_from_open_min": "~25"},
        supporting_evidence=(f"analog multiverse of "
                             f"{len(worlds)} real afternoons",),
        contradicting_evidence=("Monday's own corrected outcome: "
                                "THESIS_WRONG, thesis broke at "
                                "+6 minutes",),
        competing_explanations=("ordinary opening volatility (H2)",
                                "failed-impulse trap (H3)"),
        path_profile={"summary": summaries["incumbent_long_put_2dte"]},
        execution_profile={"pedigree": "MODELLED_BSM_REPRICE",
                           "live_entry_friction_observed": "1.1% of "
                           "premium (Day-1)"},
        best_known_expression=NOT_ESTIMABLE_BEST(summaries),
        failure_surface={"region_counts": surface["region_counts"],
                         "boundaries": surface["decision_boundaries"]},
        signal_half_life="NOT_ESTIMABLE",
        capacity_suitability="NOT_ESTIMABLE",
        our_expected_footprint="negligible (1 contract vs SPY ATM book)",
        crowding="NOT_ESTIMABLE",
        tail_asymmetry="NOT_ESTIMABLE",
        why_small_wins=small,
        capital_accelerant=capital_accelerant_assessment(
            explicit_downside=True,
            favorable_tail_evidence="NOT_ESTIMABLE",
            holding_period="intraday",
            capital_efficiency="NOT_ESTIMABLE",
            footprint="negligible",
            mechanism_credibility="CONTESTED (three live hypotheses)",
            execution_survivability="NOT_ESTIMABLE"),
        historical_support={
            "n_raw": sel["n_raw"],
            "n_effective_lower_bound": sel["n_effective_lower_bound"],
            "years": sel["years"]},
        edge_health="BIRTH")

    result = {
        "kind": "edgeforge_spy_demo",
        "version": EDGEFORGE_VERSION,
        "A_genome": genome_rec,
        "B_hypotheses": tourney_rec,
        "B2_disagreement": disagreement,
        "C_analog_selection": sel_rec,
        "D_multiverse": {"n_worlds": len(worlds),
                         "missing_futures": bf["missing_futures"],
                         "note": bf["note"]},
        "EF_attack_lab": summaries,
        "G_adversarial": stress_summary,
        "H_edge_surface": surface_slim,
        "I_why_small_wins": small,
        "J_edge_dna": dna.as_record(),
    }
    record_result(reg, discovery_id="EFDEMO_SPY_20260824",
                  status="CANDIDATE_EDGE" if False else "NULL_RESULT",
                  result={"see": "spy_demo.json"},
                  why="demonstration of the machine; one session and "
                      "one analog family establish no edge")
    (out / "spy_demo.json").write_text(json.dumps(
        stamp(result, CODE_PATHS), indent=1, default=str))
    print(json.dumps({"worlds": len(worlds),
                      "attack_lab": summaries,
                      "surface_regions": surface["region_counts"],
                      "why_small_wins": small["reason"],
                      "flag": small.get("flag")}, indent=1, default=str))
    return 0


def NOT_ESTIMABLE_BEST(summaries: dict) -> str:
    """Best expression is NOT crowned from one analog family; report
    the comparison, withhold the verdict."""
    return ("WITHHELD -- expressions compared on common worlds; no "
            "winner from one analog family")


NOT_ESTIMABLE = "NOT_ESTIMABLE"

if __name__ == "__main__":
    raise SystemExit(main())
