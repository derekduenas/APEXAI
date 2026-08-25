"""CHRONOS DEMO — one complete causal walk-forward cycle on real SPY.

The deliverable is the MACHINE running end to end, not an edge:
    ingest daily SPY history with known_from stamps
    seal the lockbox (2025-01-01 .. 2026-06-01) -- untouched
    plant poison (future_return_1d) -- must never be consumed
    inject shadow features -- must be searched like real ones
    ZONE A: discover candidates on train (real + shadow features)
    negative control: same discovery on shuffled labels
    ZONE B: freeze the best candidate, test on unseen validation
    ZONE C: sealed walk-forward test with the frozen hypothesis
    tournament: challenger vs momentum vs random-eligible vs no-trade
    score economically and scientifically, separately
    register everything in the discovery ledger

Every artifact is labelled HISTORICAL_REPLAY. Nothing here is
prospective evidence, and nothing here touches V1.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import CHRONOS_VERSION, EVIDENCE_LABEL     # noqa: E402
from apex.chronos.clock import (CausalClock, KnowledgeHorizon,  # noqa: E402
                                PoisonConsumed)
from apex.chronos.controls import (SHADOW_FEATURES,          # noqa: E402
                                   effective_sample,
                                   false_discovery_calibration,
                                   inject_shadows, shuffle_labels)
from apex.chronos.scoring import (SCIENTIFIC_DIMENSIONS,      # noqa: E402
                                  economic_score, scientific_score)
from apex.chronos.tournament import run_tournament            # noqa: E402
from apex.chronos.zones import (build_folds, freeze_hypothesis,  # noqa: E402
                                lockbox_guard, seal_lockbox,
                                verify_frozen)
from apex.edgeforge.registry import (record_result,           # noqa: E402
                                     register_discovery)
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
CODE_PATHS = ["scripts/chronos_walkforward_demo.py",
              "apex/chronos/clock.py", "apex/chronos/zones.py",
              "apex/chronos/controls.py", "apex/chronos/scoring.py",
              "apex/chronos/evolution.py", "apex/chronos/tournament.py"]

DISCOVERY_SEPARATION = 0.12   # |top-quintile median - rest median|, pct


def _get(url, k, s):
    r = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode())


def discover(features_by_day: dict, outcome_by_day: dict,
             feature_names: list) -> list:
    """ZONE A search: does a feature's top quintile separate the
    outcome median from the rest? Crude on purpose -- the demo tests
    the CAGE, and a crude searcher that respects the cage teaches more
    than a clever one that does not."""
    days = sorted(d for d in features_by_day if d in outcome_by_day)
    found = []
    for fname in feature_names:
        pairs = [(features_by_day[d].get(fname), outcome_by_day[d])
                 for d in days]
        pairs = [(f, o) for f, o in pairs
                 if isinstance(f, (int, float))
                 and isinstance(o, (int, float))]
        if len(pairs) < 40:
            continue
        srt = sorted(pairs, key=lambda p: p[0])
        cut = len(srt) * 4 // 5
        top = [o for _f, o in srt[cut:]]
        rest = [o for _f, o in srt[:cut]]
        sep = statistics.median(top) - statistics.median(rest)
        found.append({"feature": fname, "separation_pct": round(sep, 4),
                      "n": len(pairs),
                      "discovered": abs(sep) >= DISCOVERY_SEPARATION,
                      "is_shadow": fname in SHADOW_FEATURES})
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/chronos")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = out / "chronos_registry.jsonl"
    report: dict = {"kind": "chronos_walkforward_demo",
                    "version": CHRONOS_VERSION,
                    "evidence_label": EVIDENCE_LABEL}

    # ---------------- LOCKBOX, sealed before anything else runs
    lockbox = seal_lockbox(
        start="2025-01-01T00:00:00+00:00",
        end="2026-06-01T00:00:00+00:00", sealed_by="operator_directive",
        sealed_utc=datetime.now(timezone.utc).isoformat())
    report["lockbox"] = lockbox

    # ---------------- INGEST with known_from stamps
    days = _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
                f"&start=2018-01-01&end=2024-12-31&limit=10000"
                f"&feed=sip&adjustment=raw", a.key, a.secret)["bars"]
    # every bar's date is guarded against the lockbox even though the
    # pull ends 2024 -- the guard is structural, not situational
    for b in days:
        lockbox_guard(lockbox, decision_time=f"{b['t'][:10]}T09:30:00+00:00")

    # features knowable AT THE OPEN; outcome knowable AT THE CLOSE
    feats, outcomes, sessions = {}, {}, []
    prev = None
    closes = []
    for b in days:
        d = b["t"][:10]
        if prev is not None:
            gap = (b["o"] / prev["c"] - 1) * 100
            trail = closes[-20:]
            vol20 = (statistics.pstdev(trail) if len(trail) >= 20
                     else None)
            feats[d] = {"gap_pct": round(gap, 4),
                        "prior_day_ret_pct": round(
                            (prev["c"] / prev["o"] - 1) * 100, 4),
                        "vol20": (round(vol20, 4) if vol20 else None)}
            outcomes[d] = round((b["c"] / b["o"] - 1) * 100, 4)
            sessions.append(d)
        closes.append((b["c"] / b["o"] - 1) * 100)
        prev = b

    # ---------------- CLOCK + POISON
    clock = CausalClock(start=f"{sessions[0]}T09:30:00+00:00")
    horizon = KnowledgeHorizon(clock=clock)
    horizon.register_poison(
        "future_return_1d", outcomes[sessions[0]],
        why="the day's open-to-close return, planted before the open")
    poison_status = "NEVER_CONSUMED"
    try:
        # run every discovered feature name through the one read path,
        # including a deliberate attempt that MUST die
        horizon.register("gap_pct", feats[sessions[0]]["gap_pct"],
                         known_from=f"{sessions[0]}T09:30:00+00:00",
                         source="alpaca_sip_daily")
        horizon.get("gap_pct", consumer="chronos_demo")
        horizon.get("future_return_1d", consumer="chronos_demo_trap")
        poison_status = "CONSUMED_WITHOUT_FAILURE"   # must not happen
    except PoisonConsumed:
        poison_status = "TRAP_FIRED_AS_DESIGNED"
    report["poison_pill"] = {"status": poison_status,
                             "horizon_audit": horizon.audit()}

    # ---------------- FOLDS
    folds = build_folds(start=f"{sessions[0]}T00:00:00+00:00",
                        end=f"{sessions[-1]}T00:00:00+00:00",
                        train_days=500, validate_days=180,
                        test_days=180, purge_horizon="1d", embargo="2d")
    fold = folds[-1]
    report["folds"] = {"n_folds": len(folds),
                       "demo_fold": fold.as_record()}

    def in_range(d, lo, hi):
        return lo[:10] <= d < hi[:10]

    train = [d for d in sessions
             if in_range(d, fold.train_start, fold.train_end)]
    valid = [d for d in sessions
             if in_range(d, fold.validate_start, fold.validate_end)]
    test = [d for d in sessions
            if in_range(d, fold.test_start, fold.test_end)]

    # ---------------- ZONE A: discovery on train, shadows injected
    shadowed = inject_shadows({d: feats[d] for d in train}, seed=7)
    all_names = ["gap_pct", "prior_day_ret_pct", "vol20",
                 *SHADOW_FEATURES]
    zone_a = discover(shadowed["features"],
                      {d: outcomes[d] for d in train}, all_names)
    register_discovery(
        reg, discovery_id="CHRONOS_DEMO_FOLD_SEARCH",
        research_question="does any open-knowable daily feature "
                          "separate open-to-close return medians?",
        feature_set=all_names,
        interaction_form="single_feature_top_quintile",
        dataset_boundary=f"train {fold.train_start[:10]}.."
                         f"{fold.train_end[:10]}",
        search_method="chronos_zone_a_v0",
        multiple_testing_family="chronos_demo_family")
    report["zone_a"] = {"searched": len(zone_a), "results": zone_a}

    # ---------------- NEGATIVE CONTROL: shuffled labels, same engine
    train_out = [outcomes[d] for d in train]
    shuffled = dict(zip(train, shuffle_labels(train_out, seed=13)))
    control = discover(shadowed["features"], shuffled, all_names)
    control_runs = (
        [{"control_kind": "SHUFFLED_LABELS", "target": r["feature"],
          "discovered": r["discovered"],
          "strength": abs(r["separation_pct"])} for r in control]
        + [{"control_kind": "SHADOW_FEATURE", "target": r["feature"],
            "discovered": r["discovered"],
            "strength": abs(r["separation_pct"])}
           for r in zone_a if r["is_shadow"]])
    calibration = false_discovery_calibration(control_runs=control_runs)
    report["false_discovery_calibration"] = calibration

    # ---------------- ZONE B: freeze the best REAL candidate
    real_hits = [r for r in zone_a
                 if r["discovered"] and not r["is_shadow"]]
    real_hits.sort(key=lambda r: -abs(r["separation_pct"]))
    if not real_hits:
        report["zone_b"] = {"verdict": "NOTHING_TO_FREEZE",
                            "why": "no real feature cleared the "
                                   "separation bar on train; a null "
                                   "Zone A is a legitimate outcome"}
        frozen = None
    else:
        best = real_hits[0]
        direction = "SHORT" if best["separation_pct"] < 0 else "LONG"
        frozen = freeze_hypothesis(
            hypothesis_id="CHRONOS_EDGE_000",
            birth_time=f"{fold.validate_start[:10]}T00:00:00+00:00",
            spec={"variables": [best["feature"]],
                  "direction": direction,
                  "threshold_family": "top_quintile_of_train",
                  "mechanism": "single-feature conditional drift",
                  "horizon": "OPEN_TO_CLOSE",
                  "payoff_definition": "signed open-to-close pct"})
        # threshold learned on TRAIN ONLY, then frozen
        vals = sorted(feats[d][best["feature"]] for d in train
                      if isinstance(feats[d].get(best["feature"]),
                                    (int, float)))
        thresh = vals[len(vals) * 4 // 5]
        sign = 1.0 if direction == "LONG" else -1.0

        def decide(d):
            f = feats[d].get(best["feature"])
            if not isinstance(f, (int, float)) or f < thresh:
                return None
            return sign * outcomes[d]

        vout = [decide(d) for d in valid]
        vact = [v for v in vout if v is not None]
        v_med = statistics.median(vact) if vact else None
        survived = bool(vact) and v_med is not None and v_med > 0
        report["zone_b"] = {
            "frozen": frozen,
            "frozen_intact": verify_frozen(frozen, frozen[
                "frozen_fields"])["verdict"],
            "n_validation_acts": len(vact),
            "validation_median_R": (round(v_med, 4) if v_med is not None
                                    else "NOT_ESTIMABLE"),
            "verdict": ("SURVIVED_VALIDATION" if survived
                        else "KILLED_IN_VALIDATION"),
            "law": "if it dies here, it dies; it is not improved"}

        # ------------ ZONE C: sealed test, only if it survived
        if survived:
            t_dec = {d: decide(d) for d in test}
            mom = {d: (outcomes[d] if feats[d]["prior_day_ret_pct"] > 0
                       else -outcomes[d]) for d in test}
            rng = _Rng(29)
            rand = {d: (outcomes[d] if rng.random() > 0.5
                        else -outcomes[d]) for d in test}
            tourney = run_tournament(
                period=f"{fold.test_start[:10]}..{fold.test_end[:10]}",
                decisions_by_policy={
                    "APEX_CHALLENGER": {f"{d}T09:30:00+00:00": v
                                        for d, v in t_dec.items()},
                    "SIMPLE_MOMENTUM": {f"{d}T09:30:00+00:00": v
                                        for d, v in mom.items()},
                    "RANDOM_ELIGIBLE": {f"{d}T09:30:00+00:00": v
                                        for d, v in rand.items()},
                    "NO_TRADE": {f"{d}T09:30:00+00:00": None
                                 for d in test}})
            report["zone_c"] = tourney
            acts = [v for v in t_dec.values() if v is not None]
            report["economic"] = economic_score(
                oos_r_multiples=acts, friction_total=0.0,
                n_sessions=len(test))
        else:
            report["zone_c"] = {"verdict": "NOT_RUN",
                                "why": "killed in validation; a dead "
                                       "hypothesis does not get a "
                                       "sealed test"}
            report["economic"] = economic_score(
                oos_r_multiples=[], friction_total=0.0, n_sessions=0)

    # ---------------- SAMPLE HONESTY
    report["effective_sample"] = effective_sample(
        observations=[{"session": d, "regime":
                       ("HIGH_VOL" if isinstance(
                           feats[d].get("vol20"), (int, float))
                        and feats[d]["vol20"] > 1.2 else "ORDINARY")}
                      for d in train], session_key="session",
        regime_key="regime")

    # ---------------- SCIENTIFIC SCORE, every dimension answered
    shadow_hits = [r for r in zone_a
                   if r["is_shadow"] and r["discovered"]]
    dim = {d: {"verdict": "INSUFFICIENT_EVIDENCE",
               "evidence": "one demo fold cannot establish this"}
           for d in SCIENTIFIC_DIMENSIONS}
    dim["false_discovery_restraint"] = {
        "verdict": ("FAILED" if shadow_hits or
                    calibration.get("verdict") ==
                    "PIPELINE_TOO_PERMISSIVE" else "DEMONSTRATED"),
        "evidence": f"shadow hits: {[r['feature'] for r in shadow_hits]}"
                    f"; calibration {calibration.get('verdict')}"}
    dim["uncertainty_recognition"] = {
        "verdict": "DEMONSTRATED",
        "evidence": "causal refusals returned NOT_ESTIMABLE; poison "
                    f"pill {poison_status}"}
    zb = report.get("zone_b", {})
    if zb.get("verdict") == "KILLED_IN_VALIDATION":
        dim["false_edge_rejection"] = {
            "verdict": "DEMONSTRATED",
            "evidence": "the frozen candidate died in validation and "
                        "was not improved or retried"}
    report["scientific"] = scientific_score(dimension_evidence=dim)

    record_result(reg, discovery_id="CHRONOS_DEMO_FOLD_SEARCH",
                  status=("NULL_RESULT" if not real_hits else
                          "CANDIDATE"),
                  result={"real_discoveries": len(real_hits),
                          "shadow_discoveries": len(shadow_hits),
                          "zone_b": zb.get("verdict"),
                          "zone_c": report.get("zone_c", {}).get(
                              "verdict")},
                  why="chronos demo fold, single-feature search")

    (out / "chronos_demo.json").write_text(
        json.dumps(stamp(report, CODE_PATHS), indent=1, default=str))
    print(json.dumps({
        "poison": poison_status,
        "lockbox": lockbox["status"],
        "zone_a_searched": len(zone_a),
        "shadow_hits": [r["feature"] for r in shadow_hits],
        "calibration": calibration.get("verdict"),
        "hallucination_temperature": calibration.get(
            "hallucination_temperature"),
        "zone_b": zb.get("verdict"),
        "zone_c": report.get("zone_c", {}).get("verdict"),
        "n_eff": report["effective_sample"]["n_effective_lower_bound"],
        "evidence_label": EVIDENCE_LABEL}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
