"""CHRONOS CAMPAIGN #003 — roster multiplicity (scientific dimension).

Same battlefield, same epochs, lockbox sealed. NOTHING searched
harder. The question: can the scientist control false discovery
across an EVOLVING POPULATION of hypothesis families?

TWO ROSTERS, identical process:

  REAL roster     the same best-of-4 search as Campaign #002, now
                  charged by the predeclared HIERARCHICAL schedule
                  (mechanism -> family -> attempt, ALPHA_GLOBAL=0.10)
  CONTROL roster  N persistent NONSENSE research lanes, each with its
                  own four deterministic gaussian features and a
                  declared nonsense mechanism, pushed through the
                  IDENTICAL birth / sequential / validation process
                  with matched search complexity (4 features, 2
                  directions)

Measured: false families admitted, false mechanisms admitted, and
hallucination at three levels -- spec, family, mechanism -- never
pooled. Also reported honestly: the hierarchical schedule itself
limits how many mechanisms can EVER receive a resolvable test at the
capped null budget; small denominators are stated, not hidden.

Every artifact: HISTORICAL_REPLAY. Campaign #002 is preserved;
differences are attributable to the changed (hierarchical) charging.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import CHRONOS_VERSION, EVIDENCE_LABEL     # noqa: E402
from apex.chronos.clock import CausalClock, KnowledgeHorizon  # noqa: E402
from apex.chronos.identity import LifetimeLedger              # noqa: E402
from apex.chronos.poison_suite import (plant_full_catalog,    # noqa: E402
                                       self_attack)
from apex.chronos.roster import (HypothesisRoster,            # noqa: E402
                                 three_level_hallucination)
from apex.chronos.scoring import campaign_status              # noqa: E402
from apex.chronos.sequential import sequential_test           # noqa: E402
from apex.chronos.zones import lockbox_guard, seal_lockbox    # noqa: E402
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
CODE_PATHS = ["scripts/chronos_campaign_003.py",
              "apex/chronos/roster.py", "apex/chronos/sequential.py",
              "apex/chronos/identity.py", "apex/chronos/scoring.py"]

REAL_FEATURES = ("gap_pct", "prior_day_ret_pct", "vol20", "range5_pct")
MECHANISMS = {
    "gap_pct": "overnight repricing gaps continue intraday because "
               "the information that moved the overnight auction is "
               "still being absorbed by daytime participants",
    "prior_day_ret_pct": "prior-day directional persistence: "
                         "incremental buyers or sellers present "
                         "yesterday remain present today",
    "vol20": "elevated trailing volatility conditions the next "
             "session's open-to-close drift through risk budgets",
    "range5_pct": "recent range expansion marks participant "
                  "disagreement that resolves directionally",
}
N_CONTROL_LANES = 6
VALIDATION_SESSIONS = 126
MIN_DISCOVERY_SESSIONS = 400


def _get(url, k, s):
    r = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode())


def nonsense_value(lane: int, feat: int, day: str) -> float:
    h = hashlib.sha256(f"lane{lane}|f{feat}|{day}".encode()).hexdigest()
    return int(h[:12], 16) / float(1 << 48) - 0.5


def best_of_search(feats_by_day, out_by_day, names):
    days = sorted(d for d in feats_by_day if d in out_by_day)
    best_name, best_sep = None, 0.0
    for fname in names:
        pairs = [(feats_by_day[d].get(fname), out_by_day[d])
                 for d in days]
        pairs = [(f, o) for f, o in pairs
                 if isinstance(f, (int, float))
                 and isinstance(o, (int, float))]
        if len(pairs) < 40:
            continue
        srt = sorted(pairs, key=lambda p2: p2[0])
        cut = len(srt) * 4 // 5
        sep = (statistics.median([o for _f, o in srt[cut:]])
               - statistics.median([o for _f, o in srt[:cut]]))
        if abs(sep) > abs(best_sep):
            best_name, best_sep = fname, sep
    return best_name, best_sep


def null_scores_for(disc, disc_feats, disc_out, n_nulls, seed):
    rng = _Rng(seed)
    scores = []
    for r in range(n_nulls):
        if r % 2 == 0:
            nf = {d: {f"n{j}": rng.normal() for j in range(4)}
                  for d in disc}
            _n, sep = best_of_search(nf, disc_out,
                                     [f"n{j}" for j in range(4)])
        else:
            vals = [disc_out[d] for d in disc]
            for i2 in range(len(vals) - 1, 0, -1):
                j2 = rng.randint(0, i2)
                vals[i2], vals[j2] = vals[j2], vals[i2]
            _n, sep = best_of_search(disc_feats,
                                     dict(zip(disc, vals)),
                                     list(disc_feats[disc[0]]))
        scores.append(abs(sep))
    return scores


def month_starts(sessions):
    seen, out = set(), []
    for d in sessions:
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def run_lane(*, label, feats, outcomes, disc, valid, roster, ledger,
             feature_names, mech_of, ep_start, seed):
    """One research lane, one epoch: search, classify, charge, test,
    validate. Identical for real and nonsense lanes."""
    disc_feats = {d: feats[d] for d in disc}
    disc_out = {d: outcomes[d] for d in disc}
    bname, bsep = best_of_search(disc_feats, disc_out, feature_names)
    if bname is None:
        return {"lane": label, "event": "NO_SEARCHABLE_FEATURE"}
    direction = "LONG" if bsep > 0 else "SHORT"
    spec = {"variables": [bname], "direction": direction,
            "threshold_family": "top_quintile_of_disc",
            "mechanism": "single-feature conditional drift",
            "horizon": "OPEN_TO_CLOSE",
            "payoff_definition": "signed open-to-close pct"}
    mech = mech_of(bname)
    birth = ledger.classify_birth(spec=spec, mechanism=mech,
                                  at=f"{ep_start}T00:00:00+00:00")
    if birth["classification"] == "CLONE_BLOCKED":
        return {"lane": label, "event": "CLONE_BLOCKED",
                "family": birth["family_id"]}
    pos = roster.register_attempt_position(
        mechanism=birth["mechanism_id"], family=birth["family_id"])
    if pos["null_budget"] is None:
        ledger.record_attempt(spec=spec, mechanism=mech,
                              at=f"{ep_start}T00:00:00+00:00",
                              outcome="NULL_RESULT")
        return {"lane": label, "event": "TEST_NOT_ESTIMABLE",
                "reason": "NULL_TAIL_RESOLUTION",
                "family_closed": pos["family_closed"],
                "closure_reason": pos["closure_reason"],
                "alpha": pos["alpha"], "family": birth["family_id"]}
    nulls = null_scores_for(disc, disc_feats, disc_out,
                            pos["null_budget"], seed)
    seq = sequential_test(family=birth["family_id"],
                          attempt=pos["attempt"],
                          real_score=abs(bsep), null_scores=nulls,
                          alpha=pos["alpha"])
    if seq["verdict"] != "DISCOVERY":
        roster.record_outcome(family=birth["family_id"],
                              admitted=False)
        ledger.record_attempt(spec=spec, mechanism=mech,
                              at=f"{ep_start}T00:00:00+00:00",
                              outcome="DISCOVERY_FAILURE")
        return {"lane": label, "event": seq["verdict"],
                "p_hat": seq.get("p_hat"), "alpha": pos["alpha"],
                "family": birth["family_id"]}
    vals = sorted(feats[d][bname] for d in disc
                  if isinstance(feats[d].get(bname), (int, float)))
    thresh = vals[len(vals) * 4 // 5]
    sign = 1.0 if direction == "LONG" else -1.0
    vacts = [sign * outcomes[d] for d in valid
             if isinstance(feats[d].get(bname), (int, float))
             and feats[d][bname] >= thresh]
    admitted = len(vacts) >= 5 and statistics.median(vacts) > 0
    roster.record_outcome(family=birth["family_id"], admitted=admitted)
    ledger.record_attempt(
        spec=spec, mechanism=mech, at=f"{ep_start}T00:00:00+00:00",
        outcome=("BIRTHED" if admitted else "VALIDATION_FAILURE"),
        edge_id=(f"{label}_{birth['family_id'][:10]}" if admitted
                 else None))
    return {"lane": label,
            "event": "ADMITTED" if admitted else "VALIDATION_KILL",
            "feature": bname, "direction": direction,
            "attempt": pos["attempt"], "alpha": pos["alpha"],
            "p_hat": seq["p_hat"], "family": birth["family_id"],
            "mechanism": birth["mechanism_id"],
            "spec_admitted": admitted}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/chronos")
    a = ap.parse_args()
    out = Path(a.out)

    lockbox = seal_lockbox(start="2025-01-01T00:00:00+00:00",
                           end="2026-06-01T00:00:00+00:00",
                           sealed_by="operator_directive",
                           sealed_utc="2026-08-25T07:00:00+00:00")
    days = _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
                f"&start=2018-01-01&end=2024-12-31&limit=10000"
                f"&feed=sip&adjustment=raw", a.key, a.secret)["bars"]
    feats, outcomes, sessions = {}, {}, []
    prev, ocr = None, []
    for b in days:
        d = b["t"][:10]
        lockbox_guard(lockbox, decision_time=f"{d}T09:30:00+00:00")
        if prev is not None:
            trail, rng5 = ocr[-20:], ocr[-5:]
            feats[d] = {
                "gap_pct": round((b["o"] / prev["c"] - 1) * 100, 4),
                "prior_day_ret_pct": round(
                    (prev["c"] / prev["o"] - 1) * 100, 4),
                "vol20": (round(statistics.pstdev(trail), 4)
                          if len(trail) >= 20 else None),
                "range5_pct": (round(max(rng5) - min(rng5), 4)
                               if len(rng5) >= 5 else None)}
            outcomes[d] = round((b["c"] / b["o"] - 1) * 100, 4)
            sessions.append(d)
        ocr.append((b["c"] / b["o"] - 1) * 100)
        prev = b

    starts = month_starts(sessions)
    first_i = next(i for i, d in enumerate(starts)
                   if sessions.index(d) >= MIN_DISCOVERY_SESSIONS
                   + VALIDATION_SESSIONS)

    real_roster = HypothesisRoster(label="REAL")
    ctrl_roster = HypothesisRoster(label="CONTROL_NONSENSE")
    real_ledger, ctrl_ledger = LifetimeLedger(), LifetimeLedger()
    control_admissions, events = [], []

    # nonsense lane features are deterministic; mechanisms declared
    lane_feats = {}
    lane_mech = {}
    for lane in range(1, N_CONTROL_LANES + 1):
        names = tuple(f"lane{lane}_f{j}" for j in range(4))
        lane_feats[lane] = names
        for nm in names:
            lane_mech[nm] = (f"synthetic nonsense stream {nm}: "
                             f"deterministic hash noise with no "
                             f"causal relationship to any market")

    for ei, ep_start in enumerate(starts[first_i:]):
        idx = sessions.index(ep_start)
        knowledge = sessions[:idx]
        disc = knowledge[:-VALIDATION_SESSIONS]
        valid = knowledge[-VALIDATION_SESSIONS:]
        epoch_id = f"C3E{ei:03d}_{ep_start[:7]}"

        clock = CausalClock(start=f"{ep_start}T09:30:00+00:00")
        hz = KnowledgeHorizon(clock=clock)
        plant_full_catalog(hz)
        self_attack(hz, attacker=f"campaign_003_{epoch_id}")

        ev = run_lane(label="REAL", feats=feats, outcomes=outcomes,
                      disc=disc, valid=valid, roster=real_roster,
                      ledger=real_ledger,
                      feature_names=REAL_FEATURES,
                      mech_of=lambda n: MECHANISMS[n],
                      ep_start=ep_start, seed=3000 + ei)
        ev["epoch"] = epoch_id
        events.append(ev)

        for lane in range(1, N_CONTROL_LANES + 1):
            names = lane_feats[lane]
            lf = {d: {nm: nonsense_value(lane, j, d)
                      for j, nm in enumerate(names)}
                  for d in knowledge}
            cev = run_lane(label=f"NONSENSE_L{lane}", feats=lf,
                           outcomes=outcomes, disc=disc, valid=valid,
                           roster=ctrl_roster, ledger=ctrl_ledger,
                           feature_names=names,
                           mech_of=lambda n: lane_mech[n],
                           ep_start=ep_start,
                           seed=5000 + ei * 10 + lane)
            cev["epoch"] = epoch_id
            events.append(cev)
            if cev.get("event") in ("ADMITTED", "VALIDATION_KILL"):
                control_admissions.append(
                    {"spec_admitted": cev.get("spec_admitted", False),
                     "family": cev["family"],
                     "mechanism": cev["mechanism"]})

    hall = three_level_hallucination(
        control_roster=ctrl_roster,
        control_admissions=control_admissions)
    status = campaign_status(
        process_qualified=(hall["verdict"] ==
                           "ROSTER_MULTIPLICITY_CONTROLLED"),
        economic_edge_proven=False)
    counts = {}
    for e in events:
        counts[e["event"]] = counts.get(e["event"], 0) + 1

    report = stamp({
        "kind": "CHRONOS_CAMPAIGN_003_ROSTER",
        "version": CHRONOS_VERSION,
        "evidence_label": EVIDENCE_LABEL,
        "n_epochs": len(starts[first_i:]),
        "n_control_lanes": N_CONTROL_LANES,
        "event_counts": counts,
        "real_roster": real_roster.accounting(),
        "control_roster": ctrl_roster.accounting(),
        "three_level_hallucination": hall,
        "denominator_honesty": (
            "the hierarchical schedule itself limits how many "
            "mechanisms can ever receive a resolvable test at the "
            "capped null budget; late lanes are refused as "
            "TEST_NOT_ESTIMABLE without ever being scored, so the "
            "hallucination denominators are small and stated"),
        "campaign_status": status,
        "events": events}, CODE_PATHS)
    (out / "campaign_003_roster.json").write_text(
        json.dumps(report, indent=1, default=str))
    print(json.dumps({
        "epochs": report["n_epochs"],
        "event_counts": counts,
        "real_roster": {k: report["real_roster"][k] for k in
                        ("mechanisms_ever_tested",
                         "families_ever_born", "families_closed")},
        "control_roster": {k: report["control_roster"][k] for k in
                           ("mechanisms_ever_tested",
                            "families_ever_born", "families_closed",
                            "total_attempts")},
        "hallucination": {k: hall.get(k) for k in
                          ("SPEC_HALLUCINATION_RATE",
                           "FAMILY_HALLUCINATION_RATE",
                           "MECHANISM_HALLUCINATION_RATE",
                           "false_families_admitted", "verdict")},
        "campaign_status": {k: status[k] for k in
                            ("SCIENTIFIC_PROCESS_AUTHORITY",
                             "ECONOMIC_EDGE_STATUS",
                             "TRADING_AUTHORITY")}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
