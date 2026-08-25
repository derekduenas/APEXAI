"""FALSE DISCOVERY CALIBRATION — the bar is set by garbage, in the
Discovery zone, and then frozen.

THE SEQUENCE, in law form:

    DISCOVERY DATA ONLY
      -> real features + shadow features + shuffled labels
      -> run the EXACT search procedure on N nonsense replicates
         drawn from the SAME COMPLEXITY CLASS as the real search
      -> the null distribution of best-of-search scores
      -> set the bar from that distribution
      -> FREEZE the bar (hashed)
      -> only then: validation, then sealed test

The bar may never be adjusted after seeing validation or test results.
Experiment 000 proved why: a fixed 0.12pp bar chosen by intuition sat
far below the measured noise floor, the moon phase out-discovered
every real feature, and the pipeline then manufactured +3.11R of
convincing alpha from what was almost certainly noise.

SAME COMPLEXITY CLASS. A 5-way interaction miner must not calibrate
against a toy single-feature control: each null replicate must carry
approximately the same degrees of freedom and search opportunity as
the real family. The replicate refuses to count otherwise.

THE SIGNATURE METRIC: RESEARCH HALLUCINATION RATE. Not LLM
hallucination -- alpha hallucination. Computed per search family,
never pooled across families, because families have different
false-discovery surfaces.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
import statistics

from apex.chronos.clock import ChronosViolation

NOT_ESTIMABLE = "NOT_ESTIMABLE"

COMPLEXITY_FIELDS = (
    "candidate_features_considered", "transformations_considered",
    "interaction_orders", "thresholds_searched", "horizons_searched",
    "directions_searched", "regimes_searched", "expressions_searched")


def search_complexity(**counts) -> dict:
    """Researcher-degrees-of-freedom pedigree, counted BEFORE freezing.

    Not a magical penalty -- a pedigree. A candidate emerging from 8
    hypotheses is a different object from one emerging from 800,000
    combinations, and the number rides with it forever."""
    missing = [f for f in COMPLEXITY_FIELDS if f not in counts]
    if missing:
        raise ChronosViolation(
            f"search complexity requires every axis counted, missing "
            f"{missing}: an uncounted degree of freedom is the one "
            f"that gets used")
    extra = [k for k in counts if k not in COMPLEXITY_FIELDS]
    if extra:
        raise ChronosViolation(f"undeclared complexity axes {extra}")
    total = 1
    for f in COMPLEXITY_FIELDS:
        n = counts[f]
        if not isinstance(n, int) or n < 1:
            raise ChronosViolation(
                f"{f} must be a positive integer count, got {n!r}")
        total *= n
    return {"kind": "search_complexity", **counts,
            "total_search_space": total,
            "law": "a candidate from 8 hypotheses is a different "
                   "object from one from 800,000 combinations; the "
                   "number rides with it forever",
            "decision_power": "NONE_RESEARCH"}


def null_distribution(*, family: str, real_complexity: dict,
                      null_replicates: list) -> dict:
    """The distribution of best-of-search scores this exact research
    process produces from garbage.

    null_replicates: [{"replicate_id": str,
                       "control_kind": str,
                       "complexity": search_complexity dict,
                       "best_abs_score": float}, ...]

    Every replicate must match the real search's complexity class:
    same total search space within a factor of 2. A null family with
    less opportunity than the real one understates the floor, which is
    the exact failure this module exists to prevent."""
    if len(null_replicates) < 20:
        raise ChronosViolation(
            f"{len(null_replicates)} null replicates cannot estimate "
            f"a tail; the floor of a distribution you barely sampled "
            f"is a guess wearing a percentile")
    real_space = real_complexity["total_search_space"]
    for r in null_replicates:
        ns = r["complexity"]["total_search_space"]
        if not (real_space / 2 <= ns <= real_space * 2):
            raise ChronosViolation(
                f"replicate {r['replicate_id']}: null search space "
                f"{ns} is not in the real family's complexity class "
                f"({real_space}); a toy control understates the floor")
        if not isinstance(r["best_abs_score"], (int, float)):
            raise ChronosViolation(
                f"replicate {r['replicate_id']} carries no score")
    scores = sorted(r["best_abs_score"] for r in null_replicates)
    n = len(scores)

    def q(p):
        return scores[min(n - 1, int(p * n))]

    return {"kind": "null_distribution", "family": family,
            "n_replicates": n,
            "by_control_kind": {
                k: sum(1 for r in null_replicates
                       if r["control_kind"] == k)
                for k in {r["control_kind"] for r in null_replicates}},
            "median_null": round(statistics.median(scores), 6),
            "p95_null": round(q(0.95), 6),
            "p99_null": round(q(0.99), 6),
            "best_null": round(scores[-1], 6),
            "scores": [round(s, 6) for s in scores],
            "decision_power": "NONE_RESEARCH"}


def freeze_bar(*, null_dist: dict, quantile: str = "p99_null",
               frozen_in_zone: str = "ZONE_A_DISCOVERY") -> dict:
    """Set the discovery bar from the null distribution and seal it.

    frozen_in_zone must be the discovery zone -- a bar frozen anywhere
    else has already seen the data it will judge."""
    if frozen_in_zone != "ZONE_A_DISCOVERY":
        raise ChronosViolation(
            f"the bar must be frozen inside the discovery zone, not "
            f"{frozen_in_zone}: a bar set after seeing validation or "
            f"test has already been adjusted by the answer")
    if quantile not in ("p95_null", "p99_null", "best_null"):
        raise ChronosViolation(f"unknown bar quantile {quantile!r}")
    bar = null_dist[quantile]
    body = {"kind": "frozen_discovery_bar",
            "family": null_dist["family"],
            "bar": bar, "quantile": quantile,
            "n_null_replicates": null_dist["n_replicates"],
            "frozen_in_zone": frozen_in_zone,
            "law": "never adjusted after validation or test results "
                   "are seen; a corrected scoreboard with the original "
                   "miss erased is how instruments learn to lie"}
    body["bar_hash"] = hashlib.sha256(json.dumps(
        {k: body[k] for k in ("family", "bar", "quantile",
                              "n_null_replicates")},
        sort_keys=True).encode()).hexdigest()
    return body


def verify_bar(frozen: dict, *, family: str, bar: float,
               quantile: str) -> dict:
    """Did anyone move the bar after freezing?"""
    h = hashlib.sha256(json.dumps(
        {"family": family, "bar": bar, "quantile": quantile,
         "n_null_replicates": frozen["n_null_replicates"]},
        sort_keys=True).encode()).hexdigest()
    if h == frozen["bar_hash"]:
        return {"verdict": "BAR_INTACT", "family": family}
    return {"verdict": "BAR_MOVED_AFTER_FREEZE", "family": family,
            "remedy": "the run is dead; a moved bar invalidates every "
                      "discovery judged against it",
            "decision_power": "NONE_RESEARCH"}


def research_hallucination_rate(*, family: str, null_dist: dict,
                                real_results: list,
                                frozen_bar: dict) -> dict:
    """THE SIGNATURE METRIC. How extraordinary is the best real
    discovery compared with what this exact process produces from
    garbage?

    Per family, never pooled: a single-feature search and a 5-way
    interaction miner have different false-discovery surfaces, and
    letting a huge search space grade itself against a toy control
    family is the laundering this refuses."""
    if frozen_bar["family"] != family or null_dist["family"] != family:
        raise ChronosViolation(
            f"family mismatch: hallucination rate is computed per "
            f"search family, never across them "
            f"({frozen_bar['family']!r} / {null_dist['family']!r} vs "
            f"{family!r})")
    bar = frozen_bar["bar"]
    real_scores = [abs(r["score"]) for r in real_results
                   if isinstance(r.get("score"), (int, float))]
    null_scores = null_dist["scores"]
    # STRICTLY GREATER. The bar is itself a null-distribution
    # quantile, so >= would let the null that DEFINES the bar clear
    # it tautologically -- a floor that always has one thing under it
    # measures nothing. Clearing the bar means exceeding it.
    null_over_bar = sum(1 for s in null_scores if s > bar)
    real_over_bar = sum(1 for s in real_scores if s > bar)
    best_real = max(real_scores) if real_scores else None
    excess = ((best_real - null_dist["best_null"])
              if best_real is not None else None)
    return {"kind": "research_hallucination_rate", "family": family,
            "null_searches_tested": len(null_scores),
            "real_searches_tested": len(real_scores),
            "bar": bar, "bar_quantile": frozen_bar["quantile"],
            "null_over_bar": null_over_bar,
            "null_over_bar_rate": round(
                null_over_bar / len(null_scores), 4),
            "real_over_bar": real_over_bar,
            "best_null_score": null_dist["best_null"],
            "p95_null_score": null_dist["p95_null"],
            "p99_null_score": null_dist["p99_null"],
            "best_real_score": (round(best_real, 6)
                                if best_real is not None
                                else NOT_ESTIMABLE),
            "real_vs_null_excess": (round(excess, 6)
                                    if excess is not None
                                    else NOT_ESTIMABLE),
            "false_discovery_restraint": (
                "DEMONSTRATED" if null_over_bar / len(null_scores)
                <= 0.02 else "FAILED"),
            "interpretation": (
                "REAL_EXCEEDS_GARBAGE" if isinstance(excess, float)
                and excess > 0 else
                "REAL_INDISTINGUISHABLE_FROM_GARBAGE"),
            "law": "how extraordinary is the best real discovery "
                   "compared with what this exact research process "
                   "produces from garbage? -- more meaningful than a "
                   "generic p-value, and computed per family",
            "decision_power": "NONE_RESEARCH"}
