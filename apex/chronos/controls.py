"""ANTI-OVERFITTING WEAPONRY — negative controls and shadow features.

NEGATIVE CONTROLS. Periodically hand the discovery engine data where
there is nothing to find -- shuffled labels, permuted features -- and
watch what it does. A discovery engine that finds "edge" in randomized
labels is not unlucky; it is TOO PERMISSIVE, and every real discovery
it has ever produced inherits that doubt.

SHADOW FEATURES. Inject synthetic nonsense with honest names --
moon_phase_mod_7, random_gaussian_14, hash_of_timestamp -- into the
candidate pool. Not to trade them: to measure the pipeline's propensity
to hallucinate alpha. The shadow hit rate is the research machine's
measured false-discovery temperature, updated continuously.

EFFECTIVE SAMPLE SIZE. 20,000 intraday states is not 20,000
independent observations. Every CHRONOS report carries n_raw AND
n_effective_lower_bound AND session/regime/cluster concentration --
the same discipline the live system uses, because replay abundance is
the exact place where fake sample size does the most damage.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import statistics

from apex.chronos.clock import ChronosViolation
from apex.edgeforge.world_foundry import _Rng

NOT_ESTIMABLE = "NOT_ESTIMABLE"

SHADOW_FEATURES = ("moon_phase_mod_7", "random_gaussian_14",
                   "hash_of_timestamp")


def shadow_feature_values(name: str, timestamps: list,
                          *, seed: int = 0) -> list:
    """Deterministic nonsense. Deterministic so a shadow 'discovery'
    can be reproduced exactly and studied; nonsense by construction so
    any edge found in it is a measurement of the pipeline, not of the
    market."""
    if name not in SHADOW_FEATURES:
        raise ChronosViolation(
            f"unknown shadow feature {name!r}; shadows are declared, "
            f"never improvised, so the nonsense census stays complete")
    if name == "moon_phase_mod_7":
        # sha256, NOT builtin hash(): str hashing is salted per process
        # (PYTHONHASHSEED), and an irreproducible shadow would violate
        # the very law it exists to enforce.
        return [int(hashlib.sha256(str(t).encode()).hexdigest(), 16) % 7
                for t in timestamps]
    if name == "hash_of_timestamp":
        return [int(hashlib.sha256(str(t).encode()).hexdigest()[:8], 16)
                % 1000 / 1000.0 for t in timestamps]
    rng = _Rng(seed)
    return [rng.normal() for _ in timestamps]


def inject_shadows(features_by_time: dict, *, seed: int = 0) -> dict:
    """Add every declared shadow to a feature table. Returns the new
    table plus the census of what was injected, so no later stage can
    claim it didn't know which columns were nonsense."""
    ts = sorted(features_by_time)
    out = {t: dict(features_by_time[t]) for t in ts}
    for name in SHADOW_FEATURES:
        vals = shadow_feature_values(name, ts, seed=seed)
        for t, v in zip(ts, vals):
            out[t][name] = v
    return {"features": out, "injected": list(SHADOW_FEATURES),
            "law": "shadows exist to be found; finding one is a "
                   "measurement of the pipeline's permissiveness"}


def shuffle_labels(labels: list, *, seed: int) -> list:
    """The classic negative control: same features, destroyed truth."""
    rng = _Rng(seed)
    out = list(labels)
    for i in range(len(out) - 1, 0, -1):
        j = rng.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def false_discovery_calibration(*, control_runs: list) -> dict:
    """How often does the engine find 'edge' where none can exist?

    control_runs: [{"control_kind": "SHUFFLED_LABELS"|"SHADOW_FEATURE",
                    "target": str, "discovered": bool,
                    "strength": float|None}, ...]

    The output is a TEMPERATURE, not a pass/fail: some rate of noise
    hits is statistically inevitable, and pretending zero is achievable
    would just teach the engine to hide them. What matters is that the
    rate is measured, tracked, and subtracted from our confidence in
    everything else the engine reports."""
    if not control_runs:
        return {"kind": "false_discovery_calibration",
                "verdict": "NO_CONTROLS_RUN",
                "why": "an engine that has never been fed nonsense has "
                       "an unmeasured hallucination rate, which is not "
                       "the same as a low one",
                "decision_power": "NONE_RESEARCH"}
    by_kind = {}
    for r in control_runs:
        k = r["control_kind"]
        d = by_kind.setdefault(k, {"n": 0, "hits": 0, "strengths": []})
        d["n"] += 1
        if r.get("discovered"):
            d["hits"] += 1
            if isinstance(r.get("strength"), (int, float)):
                d["strengths"].append(r["strength"])
    rows = {}
    worst = 0.0
    for k, d in by_kind.items():
        rate = d["hits"] / d["n"]
        worst = max(worst, rate)
        rows[k] = {"n_controls": d["n"], "hits": d["hits"],
                   "hit_rate": round(rate, 4),
                   "median_false_strength": (
                       round(statistics.median(d["strengths"]), 4)
                       if d["strengths"] else NOT_ESTIMABLE)}
    return {"kind": "false_discovery_calibration",
            "by_control": rows,
            "hallucination_temperature": round(worst, 4),
            "verdict": ("PIPELINE_TOO_PERMISSIVE" if worst >= 0.2
                        else "CALIBRATION_MEASURED"),
            "law": "every real discovery inherits the doubt this "
                   "temperature measures; a discovery engine is only "
                   "as credible as its performance on nonsense",
            "decision_power": "NONE_RESEARCH"}


def effective_sample(*, observations: list, session_key: str,
                     regime_key: str | None = None) -> dict:
    """n_raw vs the number that deserves statistical respect.

    The lower bound here is deliberately crude: independent sessions.
    Within-session observations of overlapping horizons are treated as
    one unit of evidence until someone PROVES more independence, not
    the other way around."""
    n_raw = len(observations)
    sessions = {}
    for o in observations:
        s = o.get(session_key)
        if s is None:
            raise ChronosViolation(
                "observation without a session key cannot enter the "
                "effective-sample accounting")
        sessions.setdefault(s, 0)
        sessions[s] += 1
    n_sessions = len(sessions)
    top = max(sessions.values()) if sessions else 0
    regimes = {}
    if regime_key:
        for o in observations:
            r = o.get(regime_key, "UNLABELLED")
            regimes[r] = regimes.get(r, 0) + 1
    return {"kind": "effective_sample",
            "n_raw": n_raw,
            "n_effective_lower_bound": n_sessions,
            "independent_sessions": n_sessions,
            "top_session_share": (round(top / n_raw, 4) if n_raw
                                  else NOT_ESTIMABLE),
            "regime_counts": regimes,
            "law": "20,000 intraday states is not 20,000 independent "
                   "observations; abundance is where fake sample size "
                   "does the most damage",
            "decision_power": "NONE_RESEARCH"}
