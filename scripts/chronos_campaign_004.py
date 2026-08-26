"""CHRONOS CAMPAIGN #004 — RESEARCH POWER CALIBRATION.

Can the scientist recognize real signal, while keeping every defense
that made it good at rejecting nonsense?

Eight predeclared families with ground truth fixed before the run:
seven carrying real structure of varying shape and strength, one
carrying nothing. The discovery process is never told which is which.

ALL CAMPAIGN #003 MACHINERY STAYS ON. Complexity-matched nulls, the
frozen p99 bar, exceedance-rank testing, tail-resolution refusal,
poison, and identity. Positive controls do not get an easier
scientist -- that would measure a different scientist.

THE SEARCH IS DELIBERATELY UNCHANGED IN SPIRIT but must be able to
express the shapes being planted: a marginal-only searcher would fail
INTERACTION_ONLY and SEQUENCE_EDGE by construction and teach us
nothing about power. So the search enumerates marginals, pairwise
products, regime-conditioned marginals and one transition feature --
and the null replicates enumerate the IDENTICAL space, so the extra
freedom is charged for, not smuggled in.

Every artifact: POSITIVE_CONTROL_ONLY. Nothing here can become
EdgeDNA. The lockbox is not touched -- positive-control calibration
does not need it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import CHRONOS_VERSION                      # noqa: E402
from apex.chronos.calibration import search_complexity        # noqa: E402
from apex.chronos.clock import CausalClock, KnowledgeHorizon  # noqa: E402
from apex.chronos.exam import (CONTROL_LABEL, FAMILIES,       # noqa: E402
                               ControlUniverse, grade,
                               power_report)
from apex.chronos.poison_suite import (plant_full_catalog,    # noqa: E402
                                       self_attack)
from apex.chronos.sequential import sequential_test           # noqa: E402
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

CODE_PATHS = ["scripts/chronos_campaign_004.py",
              "apex/chronos/exam.py", "apex/chronos/sequential.py",
              "apex/chronos/calibration.py"]

N_NULLS = 200
VALIDATION_FRAC = 0.2
ALPHA = 0.05


def candidate_space(features: dict, sessions: list, regimes: dict):
    """Every expression the search may consider. The null replicates
    walk this same space, so the added freedom is charged for."""
    keys = sorted(features[sessions[0]])
    space = []
    for k in keys:
        space.append(("MARGINAL", (k,)))
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            space.append(("PRODUCT", (a, b)))
    for k in keys:
        for reg in ("REGIME_A", "REGIME_B"):
            space.append((f"REGIME:{reg}", (k,)))
    for k in keys:
        space.append(("TRANSITION", (k,)))
    return space


def value_of(kind, feats, row, prev_rows, reg):
    if kind == "MARGINAL":
        return row[feats[0]]
    if kind == "PRODUCT":
        return row[feats[0]] * row[feats[1]]
    if kind.startswith("REGIME:"):
        want = kind.split(":", 1)[1]
        return row[feats[0]] if reg == want else None
    if kind == "TRANSITION":
        if len(prev_rows) < 2:
            return None
        p2, p1 = prev_rows[-2], prev_rows[-1]
        fired = (p2[feats[0]] > 0 and not p1[feats[0]] > 0
                 and row[feats[0]] > 0)
        return 1.0 if fired else 0.0
    return None


def best_of_search(universe, sessions, outcomes, space):
    """Top-quintile separation, over the whole declared space."""
    best = (None, 0.0, None)
    prev_rows = []
    series = {}
    for s in sessions:
        row = universe.features[s]
        reg = universe.regimes[s]
        for kind, feats in space:
            v = value_of(kind, feats, row, prev_rows, reg)
            if v is None:
                continue
            series.setdefault((kind, feats), []).append((v, outcomes[s]))
        prev_rows.append(row)
    for (kind, feats), pairs in series.items():
        if len(pairs) < 60:
            continue
        srt = sorted(pairs, key=lambda p: p[0])
        cut = len(srt) * 4 // 5
        top = [o for _v, o in srt[cut:]]
        rest = [o for _v, o in srt[:cut]]
        if len(top) < 20 or len(rest) < 20:
            continue
        sep = statistics.median(top) - statistics.median(rest)
        if abs(sep) > abs(best[1]):
            best = ((kind, feats), sep, len(pairs))
    return best


def null_scores(universe, sessions, space, n, seed):
    """Shuffled outcomes through the IDENTICAL search space."""
    rng = _Rng(seed)
    out = []
    base = [universe.outcomes[s] for s in sessions]
    for _ in range(n):
        vals = list(base)
        for i in range(len(vals) - 1, 0, -1):
            j = rng.randint(0, i)
            vals[i], vals[j] = vals[j], vals[i]
        shuffled = dict(zip(sessions, vals))
        _b, sep, _n = best_of_search(universe, sessions, shuffled,
                                     space)
        out.append(abs(sep))
    return out


def run_family(family: str, *, seed: int) -> dict:
    u = ControlUniverse(family=family, seed=seed)
    n_val = int(len(u.sessions) * VALIDATION_FRAC)
    disc, valid = u.sessions[:-n_val], u.sessions[-n_val:]

    # poison + self-attack: the exam does not relax the firewall
    clock = CausalClock(start="2020-01-02T09:30:00+00:00")
    hz = KnowledgeHorizon(clock=clock)
    plant_full_catalog(hz)
    attack = self_attack(hz, attacker=f"exam_{family}")

    space = candidate_space(u.features, disc, u.regimes)
    complexity = search_complexity(
        candidate_features_considered=len(space),
        transformations_considered=1, interaction_orders=2,
        thresholds_searched=1, horizons_searched=1,
        directions_searched=2, regimes_searched=2,
        expressions_searched=1)

    disc_out = {s: u.outcomes[s] for s in disc}
    best, sep, n_pairs = best_of_search(u, disc, disc_out, space)
    nulls = null_scores(u, disc, space, N_NULLS, seed + 7)
    seq = sequential_test(family=f"EXAM_{family}", attempt=1,
                          real_score=abs(sep), null_scores=nulls,
                          alpha=ALPHA)

    detected, det_feats, val_note = False, (), "not reached"
    if seq["verdict"] == "DISCOVERY" and best is not None:
        # frozen, then tested on unseen sessions
        kind, feats = best
        prev, pairs = [], []
        for s in u.sessions:
            row = u.features[s]
            v = value_of(kind, feats, row, prev, u.regimes[s])
            prev.append(row)
            if s in set(valid) and v is not None:
                pairs.append((v, u.outcomes[s]))
        if len(pairs) >= 40:
            srt = sorted(pairs, key=lambda p: p[0])
            cut = len(srt) * 4 // 5
            vsep = (statistics.median([o for _v, o in srt[cut:]])
                    - statistics.median([o for _v, o in srt[:cut]]))
            same_sign = (vsep > 0) == (sep > 0)
            detected = same_sign and abs(vsep) > 0
            det_feats = feats if detected else ()
            val_note = (f"validation sep {vsep:+.4f} vs discovery "
                        f"{sep:+.4f}")
        else:
            val_note = "insufficient validation pairs"

    g = grade(family=family, detected=detected,
              detected_features=tuple(det_feats),
              verdict=seq["verdict"])
    return {"family": family, "grade": g,
            "search_space": len(space),
            "total_search_space": complexity["total_search_space"],
            "best_expression": (f"{best[0]}{best[1]}" if best else None),
            "discovery_sep": round(sep, 5),
            "null_p_hat": seq.get("p_hat"),
            "null_best": round(max(nulls), 5),
            "sequential_verdict": seq["verdict"],
            "validation": val_note,
            "firewall": attack["verdict"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/chronos")
    ap.add_argument("--seed", type=int, default=4004)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = [run_family(f, seed=a.seed + i * 101)
            for i, f in enumerate(FAMILIES)]
    rep = power_report([r["grade"] for r in rows])
    payload = stamp({
        "kind": "CHRONOS_CAMPAIGN_004_RESEARCH_POWER",
        "version": CHRONOS_VERSION, "label": CONTROL_LABEL,
        "question": "can the scientist recognize real signal while "
                    "keeping the defenses that make it good at "
                    "rejecting nonsense?",
        "defenses_active": ["poison_suite", "complexity_matched_nulls",
                            "exceedance_rank_test",
                            "tail_resolution_refusal",
                            "frozen_then_validated"],
        "n_nulls_per_family": N_NULLS,
        "families": rows, "power_report": rep,
        "lockbox": "NOT_TOUCHED -- positive-control calibration does "
                   "not require it"}, CODE_PATHS)
    (out / "campaign_004_power.json").write_text(
        json.dumps(payload, indent=2, default=str))

    print(f"{'FAMILY':22} {'EFFECT':>7} {'SEP':>9} {'p_hat':>8}  OUTCOME")
    for r in rows:
        g = r["grade"]
        print(f"{r['family']:22} {g['effect_size_sd']:7.2f} "
              f"{r['discovery_sep']:+9.4f} "
              f"{str(r['null_p_hat']):>8}  {g['outcome']}")
    print()
    print(json.dumps({k: rep[k] for k in
                      ("true_positives", "false_negatives",
                       "detected_wrong_feature",
                       "false_positives_on_nulls",
                       "weak_family_outcome", "verdict")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
