"""CHRONOS CAMPAIGN #001 — the organism lives through historical time.

Month by month, never all at once:

    epoch M: knowledge = everything before M
      discovery zone   = knowledge minus the last ~6 months
      validation zone  = the last ~6 months of knowledge
      1. plant the full poison catalog; SELF-ATTACK (must all die)
      2. measure the null distribution IN THE DISCOVERY ZONE:
         N nonsense replicates of the same complexity class
      3. freeze the bar from the null p99 -- before validation exists
      4. search real features; only bar-clearing candidates freeze
      5. frozen candidates meet validation; the dead stay dead
      6. survivors join the edge library, born at epoch start
      7. the library (edges born in EARLIER epochs only) trades M
         sealed; the month resolves; lifelines update; decay retires
      8. the epoch checkpoint seals what the organism believed

SUCCESS CRITERION #001 (not profitability): drive false-discovery
behavior materially below Experiment 000 (hallucination temperature
1.0) while still occasionally finding candidates that survive unseen
time. If it cannot distinguish reality from the moon phase, nothing
downstream matters.

Every artifact: HISTORICAL_REPLAY. Experiment 000 is never rerun or
replaced -- the corrected machinery is a new lineage, EXP 001+.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import CHRONOS_VERSION, EVIDENCE_LABEL     # noqa: E402
from apex.chronos.calibration import (freeze_bar,            # noqa: E402
                                      null_distribution,
                                      research_hallucination_rate,
                                      search_complexity)
from apex.chronos.clock import CausalClock, KnowledgeHorizon  # noqa: E402
from apex.chronos.epoch import (intelligence_trajectory,     # noqa: E402
                                write_epoch)
from apex.chronos.evolution import EdgeLifeline               # noqa: E402
from apex.chronos.poison_suite import (plant_full_catalog,    # noqa: E402
                                       self_attack)
from apex.chronos.scoring import classify_experiment          # noqa: E402
from apex.chronos.zones import (freeze_hypothesis,            # noqa: E402
                                lockbox_guard, seal_lockbox)
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

ALPACA = "https://data.alpaca.markets/v2"
CODE_PATHS = ["scripts/chronos_campaign.py",
              "apex/chronos/calibration.py", "apex/chronos/epoch.py",
              "apex/chronos/poison_suite.py", "apex/chronos/clock.py",
              "apex/chronos/zones.py", "apex/chronos/scoring.py",
              "apex/chronos/evolution.py"]

REAL_FEATURES = ("gap_pct", "prior_day_ret_pct", "vol20", "range5_pct")
N_NULL_REPLICATES = 60
VALIDATION_SESSIONS = 126           # ~6 months
MIN_DISCOVERY_SESSIONS = 400
DECAY_WINDOW = 10                   # rolling acts
RETIRE_AFTER_FLAGS = 2

FAMILY = "single_feature_top_quintile_v1"


def _get(url, k, s):
    r = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.loads(f.read().decode())


def code_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[1]
                              ).stdout.strip()
    except Exception:                                  # noqa: BLE001
        return "UNKNOWN"


def best_of_search(feats_by_day: dict, out_by_day: dict,
                   names) -> tuple:
    """The exact search procedure, reused verbatim for real and null
    runs -- a null replicate run through a DIFFERENT procedure
    calibrates nothing."""
    days = sorted(d for d in feats_by_day if d in out_by_day)
    best_name, best_sep = None, 0.0
    per = []
    for fname in names:
        pairs = [(feats_by_day[d].get(fname), out_by_day[d])
                 for d in days]
        pairs = [(f, o) for f, o in pairs
                 if isinstance(f, (int, float))
                 and isinstance(o, (int, float))]
        if len(pairs) < 40:
            continue
        srt = sorted(pairs, key=lambda p: p[0])
        cut = len(srt) * 4 // 5
        sep = (statistics.median([o for _f, o in srt[cut:]])
               - statistics.median([o for _f, o in srt[:cut]]))
        per.append({"feature": fname, "score": round(sep, 6)})
        if abs(sep) > abs(best_sep):
            best_name, best_sep = fname, sep
    return best_name, best_sep, per


def month_starts(sessions: list) -> list:
    seen, out = set(), []
    for d in sessions:
        m = d[:7]
        if m not in seen:
            seen.add(m)
            out.append(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--out", default="results/chronos")
    ap.add_argument("--max-epochs", type=int, default=1000)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    epochs_ledger = out / "campaign_001_epochs.jsonl"
    sha = code_sha()

    lockbox = seal_lockbox(start="2025-01-01T00:00:00+00:00",
                           end="2026-06-01T00:00:00+00:00",
                           sealed_by="operator_directive",
                           sealed_utc="2026-08-25T05:00:00+00:00")

    # ---------------- ingest (ends before the lockbox, guarded anyway)
    days = _get(f"{ALPACA}/stocks/SPY/bars?timeframe=1Day"
                f"&start=2018-01-01&end=2024-12-31&limit=10000"
                f"&feed=sip&adjustment=raw", a.key, a.secret)["bars"]
    feats, outcomes, sessions = {}, {}, []
    prev, ocr = None, []
    for b in days:
        d = b["t"][:10]
        lockbox_guard(lockbox, decision_time=f"{d}T09:30:00+00:00")
        if prev is not None:
            trail = ocr[-20:]
            rng5 = ocr[-5:]
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
    # first epoch needs discovery + validation history behind it
    first_i = next(i for i, d in enumerate(starts)
                   if sessions.index(d) >= MIN_DISCOVERY_SESSIONS
                   + VALIDATION_SESSIONS)

    complexity = search_complexity(
        candidate_features_considered=len(REAL_FEATURES),
        transformations_considered=1, interaction_orders=1,
        thresholds_searched=1, horizons_searched=1,
        directions_searched=2, regimes_searched=1,
        expressions_searched=1)

    library: dict = {}          # edge_id -> dict(spec/threshold/lifeline)
    retired: list = []
    edge_seq = 1
    sealed_decisions: list = []
    epoch_summaries: list = []

    for ei, ep_start in enumerate(starts[first_i:][: a.max_epochs]):
        idx = sessions.index(ep_start)
        knowledge = sessions[:idx]
        ep_end_i = (sessions.index(starts[first_i + ei + 1])
                    if first_i + ei + 1 < len(starts) else len(sessions))
        month = sessions[idx:ep_end_i]
        disc = knowledge[:-VALIDATION_SESSIONS]
        valid = knowledge[-VALIDATION_SESSIONS:]
        epoch_id = f"E{ei:03d}_{ep_start[:7]}"

        # ---- 1. poison + self-attack, per epoch, through the real door
        clock = CausalClock(start=f"{ep_start}T09:30:00+00:00")
        hz = KnowledgeHorizon(clock=clock)
        plant_full_catalog(hz, values={
            "future_return": outcomes[month[0]],
            "future_high": max(outcomes[d] for d in month),
            "future_low": min(outcomes[d] for d in month)})
        attack = self_attack(hz, attacker=f"campaign_001_{epoch_id}")

        # ---- 2. null distribution, DISCOVERY ZONE ONLY
        disc_feats = {d: feats[d] for d in disc}
        disc_out = {d: outcomes[d] for d in disc}
        rng = _Rng(1000 + ei)
        replicates = []
        for r in range(N_NULL_REPLICATES):
            if r % 2 == 0:
                # nonsense features, same count, same search
                nf = {d: {f"null_{j}": rng.normal()
                          for j in range(len(REAL_FEATURES))}
                      for d in disc}
                _n, sep, _p = best_of_search(
                    nf, disc_out, [f"null_{j}"
                                   for j in range(len(REAL_FEATURES))])
                kind = "RANDOM_FEATURES"
            else:
                # real features, shuffled outcomes
                vals = [disc_out[d] for d in disc]
                for i2 in range(len(vals) - 1, 0, -1):
                    j2 = rng.randint(0, i2)
                    vals[i2], vals[j2] = vals[j2], vals[i2]
                _n, sep, _p = best_of_search(
                    disc_feats, dict(zip(disc, vals)), REAL_FEATURES)
                kind = "SHUFFLED_LABELS"
            replicates.append({"replicate_id": f"{epoch_id}_r{r}",
                               "control_kind": kind,
                               "complexity": complexity,
                               "best_abs_score": abs(sep)})
        nd = null_distribution(family=FAMILY,
                               real_complexity=complexity,
                               null_replicates=replicates)
        bar = freeze_bar(null_dist=nd, quantile="p99_null")

        # ---- 3. real search against the frozen bar
        bname, bsep, per = best_of_search(disc_feats, disc_out,
                                          REAL_FEATURES)
        rh = research_hallucination_rate(
            family=FAMILY, null_dist=nd,
            real_results=[{"score": p["score"]} for p in per],
            frozen_bar=bar)

        births = []
        if bname is not None and abs(bsep) > bar["bar"]:
            direction = "LONG" if bsep > 0 else "SHORT"
            vals = sorted(feats[d][bname] for d in disc
                          if isinstance(feats[d].get(bname),
                                        (int, float)))
            thresh = vals[len(vals) * 4 // 5]
            sign = 1.0 if direction == "LONG" else -1.0
            # ---- 4. validation; the dead stay dead
            vacts = [sign * outcomes[d] for d in valid
                     if isinstance(feats[d].get(bname), (int, float))
                     and feats[d][bname] >= thresh]
            if len(vacts) >= 5 and statistics.median(vacts) > 0:
                eid = f"CEDGE_{edge_seq:03d}"
                edge_seq += 1
                frozen = freeze_hypothesis(
                    hypothesis_id=eid,
                    birth_time=f"{ep_start}T00:00:00+00:00",
                    spec={"variables": [bname], "direction": direction,
                          "threshold_family": "top_quintile_of_disc",
                          "mechanism": "single-feature conditional "
                                       "drift",
                          "horizon": "OPEN_TO_CLOSE",
                          "payoff_definition": "signed open-to-close "
                                               "pct"})
                library[eid] = {
                    "frozen": frozen, "feature": bname,
                    "threshold": thresh, "sign": sign,
                    "born_epoch": epoch_id, "acts": [],
                    "decay_flags": 0,
                    "lifeline": EdgeLifeline(
                        edge_id=eid,
                        born=f"{ep_start}T00:00:00+00:00",
                        frozen_hash=frozen["frozen_hash"])}
                births.append(eid)

        # ---- 5. SEALED month: only edges born in EARLIER epochs act
        month_R = 0.0
        for d in month:
            for eid, e in list(library.items()):
                if e["born_epoch"] == epoch_id:
                    continue                     # born this epoch: waits
                f = feats[d].get(e["feature"])
                if not isinstance(f, (int, float)) or f < e["threshold"]:
                    continue
                r_val = e["sign"] * outcomes[d]
                e["acts"].append(r_val)
                month_R += r_val
                sealed_decisions.append(
                    {"epoch": epoch_id, "session": d, "edge": eid,
                     "R": round(r_val, 4)})

        # ---- 6. lifelines: decay and retirement, causally
        for eid, e in list(library.items()):
            recent = e["acts"][-DECAY_WINDOW:]
            if len(recent) >= DECAY_WINDOW and \
                    statistics.median(recent) < 0:
                e["decay_flags"] += 1
                e["lifeline"].record(
                    event="DECAY_FLAGGED",
                    at=f"{month[-1]}T16:00:00+00:00",
                    evidence=f"rolling {DECAY_WINDOW}-act median "
                             f"{statistics.median(recent):.3f} < 0",
                    evidence_known_from=f"{month[-1]}T16:00:00+00:00")
                if e["decay_flags"] >= RETIRE_AFTER_FLAGS:
                    e["lifeline"].record(
                        event="RETIRED",
                        at=f"{month[-1]}T16:00:00+00:00",
                        evidence=f"decay persisted "
                                 f"{RETIRE_AFTER_FLAGS} review cycles",
                        evidence_known_from=f"{month[-1]}"
                                            f"T16:00:00+00:00")
                    retired.append({"edge": eid,
                                    "at": month[-1],
                                    "acts": len(e["acts"]),
                                    "total_R": round(sum(e["acts"]),
                                                     4)})
                    del library[eid]

        # ---- 7. the epoch seals what the organism believed
        write_epoch(epochs_ledger, epoch={
            "epoch_id": epoch_id,
            "knowledge_cutoff": f"{ep_start}T00:00:00+00:00",
            "code_sha": sha,
            "dataset_boundary": f"SPY daily {sessions[0]}..{knowledge[-1]}",
            "active_edge_library": sorted(library),
            "retired_edges": [r["edge"] for r in retired],
            "candidate_registry": births,
            "credibility_state": "EMPTY_V0",
            "world_source_authority": "EMPIRICAL_ONLY_V0",
            "research_hallucination_rate": {
                k: rh[k] for k in
                ("null_over_bar_rate", "false_discovery_restraint",
                 "best_real_score", "best_null_score",
                 "real_vs_null_excess", "bar")},
            "capital_policy_state": "NONE_RESEARCH",
            "self_attack": attack["verdict"],
            "bar_hash": bar["bar_hash"]})
        epoch_summaries.append(
            {"epoch": epoch_id, "bar": bar["bar"],
             "best_real": rh["best_real_score"],
             "restraint": rh["false_discovery_restraint"],
             "births": births, "month_R": round(month_R, 4),
             "library": len(library)})

    # ---------------- campaign verdict vs Experiment 000
    traj = intelligence_trajectory(epochs_ledger)
    restraints = [s["restraint"] for s in epoch_summaries]
    fail_rate = (restraints.count("FAILED") / len(restraints)
                 if restraints else None)
    all_R = [d["R"] for d in sealed_decisions]
    # SURVIVAL IS JUDGED AT THE FAMILY LEVEL. First-pass defect,
    # corrected: bool(retired) counted RETIREMENT as survival, and
    # per-edge survival would be survivorship anyway -- monthly
    # rebirths of the same hypothesis are clones, and cherry-picking
    # the positive clones while their siblings lose is the exact
    # laundering this campaign exists to catch. The family survived
    # unseen time only if the whole sealed stream did.
    survived_family = (len(all_R) >= 30 and sum(all_R) > 0
                       if all_R else None)
    classification = classify_experiment(
        economic_positive=(sum(all_R) > 0 if all_R else None),
        false_discovery_restraint=(
            "DEMONSTRATED" if fail_rate is not None and fail_rate <= 0.1
            else "FAILED" if fail_rate is not None else
            "INSUFFICIENT_EVIDENCE"),
        survived_unseen_time=survived_family)

    report = stamp({
        "kind": "chronos_campaign_001", "version": CHRONOS_VERSION,
        "evidence_label": EVIDENCE_LABEL, "family": FAMILY,
        "success_criterion": (
            "drive false-discovery behavior materially below "
            "Experiment 000 (temperature 1.0) while still occasionally "
            "finding candidates that survive unseen time"),
        "exp000_reference": {"hallucination_temperature": 1.0,
                             "note": "preserved, never rerun"},
        "n_epochs": len(epoch_summaries),
        "epoch_restraint_fail_rate": (round(fail_rate, 4)
                                      if fail_rate is not None
                                      else "NOT_ESTIMABLE"),
        "epochs": epoch_summaries,
        "sealed_decisions": len(sealed_decisions),
        "sealed_total_R": round(sum(all_R), 4) if all_R else 0.0,
        "edges_born": edge_seq - 1,
        "edges_retired": retired,
        "library_at_end": sorted(library),
        "intelligence_trajectory": {
            k: traj[k] for k in ("n_epochs", "becoming_harder_to_fool")
            if k in traj},
        "classification": classification,
        "known_multiplicity_gap": (
            "per-epoch null calibration controls nonsense WITHIN an "
            "epoch; it cannot see the same hypothesis reborn across "
            "epochs on overlapping data. Rebirth-as-descendant "
            "suppression is the registered defect for Campaign #002 "
            "-- a candidate whose frozen spec matches an active or "
            "recently retired edge is the same hypothesis, not a new "
            "discovery")}, CODE_PATHS)
    (out / "campaign_001.json").write_text(
        json.dumps(report, indent=1, default=str))
    print(json.dumps({
        "epochs": len(epoch_summaries),
        "restraint_fail_rate": report["epoch_restraint_fail_rate"],
        "exp000_temperature": 1.0,
        "edges_born": edge_seq - 1,
        "edges_retired": len(retired),
        "sealed_decisions": len(sealed_decisions),
        "sealed_total_R": report["sealed_total_R"],
        "classification": {k: classification[k] for k in
                           ("ECONOMIC_TEST_RESULT",
                            "SCIENTIFIC_VALIDITY", "EDGE_AUTHORITY")},
        "harder_to_fool": report["intelligence_trajectory"].get(
            "becoming_harder_to_fool")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
