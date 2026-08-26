"""CHRONOS EXAM_001 — research power, with a sample-size-aware
selection statistic.

NEW BIRTH. EXAM_000 is frozen as a contaminated artifact: its raw
|median separation| argmax favored regime-conditioned expressions that
evaluate on half the sample, whose noisier separations won by chance.
Its FALSE_NEGATIVEs are uninterpretable. This exam does not
reinterpret EXAM_000; it replaces the instrument and starts over.

PREDECLARED SELECTION STATISTIC (2026-08-26, before any EXAM_001
outcome existed, and not adjustable in response to them):

    STUDENTIZED SEPARATION
    t = (mean_top - mean_rest) / sqrt(var_top/n_top + var_rest/n_rest)

  Welch-style, computed on the top-quintile split of each candidate
  expression. Means, not medians: a median difference has no cheap
  standard error, and an unstudentized statistic is exactly the defect
  being repaired. The same statistic scores REAL candidates and NULL
  replicates over the IDENTICAL search space, so small-n expressions
  are penalized identically on both sides of the comparison.

Everything else is unchanged from Campaign #004: the same eight
predeclared families with fixed ground truth, the same declared search
space (marginals, pairwise products, regime-conditioned marginals,
transitions), 200 shuffled-outcome nulls per family, exceedance-rank
sequential test at alpha=0.05, freeze-then-validate on unseen
sessions, poison planted and self-attacked, POSITIVE_CONTROL_ONLY.

The scientist being examined is the same scientist. Only the ruler
changed, and the ruler was the thing that was broken.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.chronos import CHRONOS_VERSION                      # noqa: E402
from apex.chronos.clock import CausalClock, KnowledgeHorizon  # noqa: E402
from apex.chronos.exam import (CONTROL_LABEL, FAMILIES,       # noqa: E402
                               ControlUniverse, grade,
                               power_report)
from apex.chronos.poison_suite import (plant_full_catalog,    # noqa: E402
                                       self_attack)
from apex.chronos.sequential import sequential_test           # noqa: E402
from apex.edgeforge.world_foundry import _Rng                 # noqa: E402
from apex.governance.verification import stamp                # noqa: E402

# reuse the identical declared search space from EXAM_000's runner
from scripts.chronos_campaign_004 import (candidate_space,    # noqa: E402
                                          value_of)

CODE_PATHS = ["scripts/chronos_exam_001.py", "apex/chronos/exam.py",
              "scripts/chronos_campaign_004.py",
              "apex/chronos/sequential.py"]

N_NULLS = 200
VALIDATION_FRAC = 0.2
ALPHA = 0.05
MIN_CELL = 20


def studentized(pairs):
    """The predeclared statistic. None when a cell is too thin to
    studentize -- refusal, not fake precision."""
    if len(pairs) < 3 * MIN_CELL:
        return None
    srt = sorted(pairs, key=lambda p: p[0])
    cut = len(srt) * 4 // 5
    top = [o for _v, o in srt[cut:]]
    rest = [o for _v, o in srt[:cut]]
    if len(top) < MIN_CELL or len(rest) < MIN_CELL:
        return None
    mt, mr = statistics.fmean(top), statistics.fmean(rest)
    vt = statistics.pvariance(top)
    vr = statistics.pvariance(rest)
    se = math.sqrt(vt / len(top) + vr / len(rest))
    if se == 0:
        return None
    return (mt - mr) / se


def best_of_search_t(universe, sessions, outcomes, space):
    """Argmax |t| over the declared space -- the corrected ruler."""
    best = (None, 0.0)
    prev_rows, series = [], {}
    for s in sessions:
        row = universe.features[s]
        reg = universe.regimes[s]
        for kind, feats in space:
            v = value_of(kind, feats, row, prev_rows, reg)
            if v is None:
                continue
            series.setdefault((kind, feats), []).append(
                (v, outcomes[s]))
        prev_rows.append(row)
    for expr, pairs in series.items():
        t = studentized(pairs)
        if t is not None and abs(t) > abs(best[1]):
            best = (expr, t)
    return best


def null_scores(universe, sessions, space, n, seed):
    rng = _Rng(seed)
    base = [universe.outcomes[s] for s in sessions]
    out = []
    for _ in range(n):
        vals = list(base)
        for i in range(len(vals) - 1, 0, -1):
            j = rng.randint(0, i)
            vals[i], vals[j] = vals[j], vals[i]
        _b, t = best_of_search_t(universe, sessions,
                                 dict(zip(sessions, vals)), space)
        out.append(abs(t))
    return out


def run_family(family: str, *, seed: int) -> dict:
    u = ControlUniverse(family=family, seed=seed)
    n_val = int(len(u.sessions) * VALIDATION_FRAC)
    disc, valid = u.sessions[:-n_val], u.sessions[-n_val:]

    clock = CausalClock(start="2020-01-02T09:30:00+00:00")
    hz = KnowledgeHorizon(clock=clock)
    plant_full_catalog(hz)
    attack = self_attack(hz, attacker=f"exam001_{family}")

    space = candidate_space(u.features, disc, u.regimes)
    disc_out = {s: u.outcomes[s] for s in disc}
    best, t_real = best_of_search_t(u, disc, disc_out, space)
    nulls = null_scores(u, disc, space, N_NULLS, seed + 7)
    seq = sequential_test(family=f"EXAM001_{family}", attempt=1,
                          real_score=abs(t_real), null_scores=nulls,
                          alpha=ALPHA)

    detected, det_feats, val_note = False, (), "not reached"
    if seq["verdict"] == "DISCOVERY" and best is not None:
        kind, feats = best
        prev, pairs = [], []
        for s in u.sessions:
            row = u.features[s]
            v = value_of(kind, feats, row, prev, u.regimes[s])
            prev.append(row)
            if s in set(valid) and v is not None:
                pairs.append((v, u.outcomes[s]))
        t_val = studentized(pairs)
        if t_val is None:
            val_note = "validation cell too thin to studentize"
        else:
            same_sign = (t_val > 0) == (t_real > 0)
            detected = same_sign and abs(t_val) > 1.0
            det_feats = feats if detected else ()
            val_note = f"validation t={t_val:+.2f} vs discovery " \
                       f"t={t_real:+.2f}"

    g = grade(family=family, detected=detected,
              detected_features=tuple(det_feats),
              verdict=seq["verdict"])
    return {"family": family, "grade": g,
            "best_expression": (f"{best[0]}{best[1]}" if best else None),
            "t_real": round(t_real, 3),
            "null_best_t": round(max(nulls), 3),
            "null_p_hat": seq.get("p_hat"),
            "sequential_verdict": seq["verdict"],
            "validation": val_note, "firewall": attack["verdict"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/chronos")
    ap.add_argument("--seed", type=int, default=1001)
    a = ap.parse_args()
    out = Path(a.out)
    rows = [run_family(f, seed=a.seed + i * 101)
            for i, f in enumerate(FAMILIES)]
    rep = power_report([r["grade"] for r in rows])
    payload = stamp({
        "kind": "CHRONOS_EXAM_001", "version": CHRONOS_VERSION,
        "label": CONTROL_LABEL, "lineage": "new birth; EXAM_000 frozen "
        "as contaminated (raw-separation argmax favored small-n "
        "regime cells)",
        "predeclared_statistic": "Welch studentized separation, "
        "declared 2026-08-26 before any EXAM_001 outcome existed",
        "n_nulls_per_family": N_NULLS,
        "families": rows, "power_report": rep,
        "lockbox": "NOT_TOUCHED"}, CODE_PATHS)
    (out / "exam_001_power.json").write_text(
        json.dumps(payload, indent=2, default=str))
    print(f"{'FAMILY':22} {'EFFECT':>7} {'t':>8} {'p_hat':>9}  "
          f"BEST -> OUTCOME")
    for r in rows:
        g = r["grade"]
        print(f"{r['family']:22} {g['effect_size_sd']:7.2f} "
              f"{r['t_real']:8.2f} {str(r['null_p_hat']):>9}  "
              f"{str(r['best_expression'])[:30]:32} {g['outcome']}")
    print()
    print(json.dumps({k: rep[k] for k in
                      ("true_positives", "false_negatives",
                       "detected_wrong_feature",
                       "false_positives_on_nulls",
                       "weak_family_outcome", "verdict")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
