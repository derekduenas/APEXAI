"""Scoring and attribution populations (contract §4.4, §5.1).

CRPS is exact from the simulated sample (no kernel, no bandwidth). The finite-ensemble reference for the rank is
the DISCRETE uniform on {1..N+1}, assessed by a chi-square on the rank histogram — not a continuous-uniform KS.
Executability is scored separately by a Brier score and is not a fill probability. Every forecast-quality result
carries SCORED_POPULATION_CONDITIONAL whenever ANY exclusion occurred; restricting every comparator to the same
subset does NOT eliminate selection bias, and the observed-worst calculation is a SENSITIVITY, not a bound."""
from __future__ import annotations

import math

import numpy as np

from .inference import session_block_bootstrap

POPULATION_LABEL = ("SCORED_POPULATION_CONDITIONAL: the scored population excludes contracts that some comparator "
                    "could not price; restricting every comparator to the same subset does not eliminate selection "
                    "bias, because the subset is chosen by an outcome-correlated event")
SENSITIVITY_LABEL = ("EXCLUSION_SENSITIVITY_OBSERVED_WORST: a SENSITIVITY, not a bound — an unobserved score can "
                     "exceed every observed one")


def crps(sample: np.ndarray, y: float) -> float:
    """(1/N)Σ|x_i − y| − (1/(2N²))ΣΣ|x_i − x_j|, computed in O(N log N) from the sorted sample."""
    x = np.sort(np.asarray(sample, dtype=float))
    n = len(x)
    if n == 0 or not math.isfinite(y):
        return float("nan")
    term1 = float(np.abs(x - y).mean())
    i = np.arange(1, n + 1)
    term2 = float((2.0 * np.sum((2 * i - n - 1) * x)) / (2.0 * n * n))
    return term1 - term2


def rank_of(sample: np.ndarray, y: float, *, rng: np.random.Generator) -> int:
    """Rank of the realization among the N+1 values; ties broken by mid-rank randomization (§5.1)."""
    x = np.asarray(sample, dtype=float)
    below = int((x < y).sum())
    ties = int((x == y).sum())
    return below + (int(rng.integers(0, ties + 1)) if ties else 0) + 1


def rank_uniformity(ranks: list, *, n_ensemble: int, bins: int | None = None) -> dict:
    """Chi-square against the DISCRETE uniform on {1..N+1} with declared equal-width bins."""
    from scipy.stats import chisquare
    m = n_ensemble + 1
    b = bins or min(20, m)
    edges = np.linspace(0.5, m + 0.5, b + 1)
    obs, _ = np.histogram(np.asarray(ranks, dtype=float), bins=edges)
    exp = np.full(b, len(ranks) / b)
    st = chisquare(obs, exp)
    return {"reference": "DISCRETE uniform on {1..N+1} under exchangeability (not continuous uniform)",
            "bins": b, "bin_rule": "equal width over [0.5, N+1.5]; remainder to the lowest bins",
            "observed": obs.tolist(), "expected_per_bin": len(ranks) / b,
            "chi2": float(st.statistic), "p": float(st.pvalue), "n": len(ranks)}


def brier(prob: list, outcome: list) -> dict:
    p = np.asarray(prob, dtype=float); o = np.asarray(outcome, dtype=float)
    return {"brier": float(np.mean((p - o) ** 2)), "n": len(p),
            "note": "a forecast score for executability; NOT a fill probability"}


def per_scan_value(variant: dict, *, entry_ask=None, fees_in=None) -> tuple:
    """§5.1 primary estimand: resolved TRADE = net, WAIT = 0, unresolved TRADE = the conservative obligation."""
    d = (variant or {}).get("decision")
    if d == "WAIT":
        return 0.0, "WAIT"
    if d == "TRADE" and (variant.get("pnl") or {}).get("net") is not None:
        return float(variant["pnl"]["net"]), "TRADE"
    if d in ("TRADE_UNRESOLVED", "UNRESOLVED"):
        a = variant.get("entry_ask", entry_ask)
        f = variant.get("fees_in", fees_in)
        if a is None or f is None:
            return None, "UNRESOLVED_NO_TERMS"
        return -100.0 * float(a) - float(f), "UNRESOLVED_CONSERVATIVE"
    return None, (d or "MISSING")


def economics(scans: list, comparator: str, *, seed: int = 11, draws: int = 2000) -> dict:
    """Per-SCAN decision economics on the common population, with the three declared estimands."""
    by_session, census = {}, {}
    primary, excluded_secondary, optimistic = [], [], []
    for r in scans:
        v = (r.get("variants") or {}).get(comparator)
        val, kind = per_scan_value(v)
        census[kind] = census.get(kind, 0) + 1
        if val is None:
            continue
        by_session.setdefault(r["session"], []).append(val)
        primary.append(val)
        if kind != "UNRESOLVED_CONSERVATIVE":
            excluded_secondary.append(val)
        optimistic.append(v.get("optimistic_net", val) if kind == "UNRESOLVED_CONSERVATIVE" else val)
    boot = session_block_bootstrap(by_session, draws=draws, seed=seed)
    return {"comparator": comparator, "primary": boot, "census": census,
            "secondary_unresolved_excluded": (float(np.mean(excluded_secondary)) if excluded_secondary else None),
            "secondary_unresolved_optimistic": (float(np.mean(optimistic)) if optimistic else None),
            "estimand": "per SCAN; resolved TRADE = net, WAIT = 0, unresolved TRADE = -100a - fees_in (conservative)",
            "refusal_note": ("a refusal changes a comparator's action set; its economic effect is MEASURED and may be "
                             "positive or negative — WAIT can legitimately improve economics by avoiding losing trades")}


def forecast_quality(rows: list, comparators: list, *, seed: int = 11, draws: int = 2000) -> dict:
    """rows: [{session, contract, realized:{bid, executable}, samples:{comparator: array|None}}].
    A contract leaves the scored population for ALL comparators when ANY comparator produced no distribution."""
    exclusions, scored, censored = {}, [], 0
    for r in rows:
        if r["realized"].get("bid") is None:
            censored += 1
            exclusions.setdefault("REALIZED_ENDPOINT_MISSING", 0)
            exclusions["REALIZED_ENDPOINT_MISSING"] += 1
            continue
        missing = [c for c in comparators if r["samples"].get(c) is None]
        if missing:
            for c in missing:
                k = "NO_DISTRIBUTION:%s" % c
                exclusions[k] = exclusions.get(k, 0) + 1
            continue
        scored.append(r)
    n_eligible = len(rows)
    coverage = len(scored) / n_eligible if n_eligible else 0.0
    rng = np.random.default_rng(seed)
    out = {"n_eligible": n_eligible, "n_scored": len(scored), "scored_coverage": coverage,
           "exclusion_census": exclusions, "censored_realized": censored,
           "population_label": (POPULATION_LABEL if (exclusions or censored) else "FULL_POPULATION"),
           "per_comparator": {}}
    for c in comparators:
        by_scan, ranks, unexec = {}, [], 0
        for r in scored:
            s = np.asarray(r["samples"][c], dtype=float)
            y = float(r["realized"]["bid"])
            by_scan.setdefault(r["session"], []).append(crps(s, y))
            ranks.append(rank_of(s, y, rng=rng))
            if not r["realized"].get("executable", True):
                unexec += 1
        boot = session_block_bootstrap(by_scan, draws=draws, seed=seed)
        worst = max((v for vals in by_scan.values() for v in vals), default=None)
        out["per_comparator"][c] = {
            "crps": boot, "rank_uniformity": (rank_uniformity(ranks, n_ensemble=len(scored[0]["samples"][c])) if scored else None),
            "unexecutable_scored_at_observed_bid": unexec,
            "exclusion_sensitivity_observed_worst": ({"value": worst, "label": SENSITIVITY_LABEL} if exclusions else None)}
    if scored and any(r["realized"].get("executable") is not None for r in scored):
        for c in comparators:
            p = [float(np.mean(np.asarray(r["samples"][c]) > 0)) for r in scored]
            o = [1.0 if r["realized"].get("executable", True) else 0.0 for r in scored]
            out["per_comparator"][c]["executability_brier"] = brier(p, o)
    return out
