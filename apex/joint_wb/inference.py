"""Inference (contract §2.3): CR1 session-cluster-robust covariance and WILD_CLUSTER_BOOTSTRAP_CI_BY_INVERSION_V1.

One construction only: a confidence interval is obtained BY INVERTING the restricted wild cluster bootstrap test.
Exactly ONE coefficient in ONE equation is restricted; the other equations are untouched. A finite search can
prove neither unboundedness nor the absence of acceptance islands, so a capped accepted endpoint is reported as
INVERSION_SEARCH_UNRESOLVED and every returned hull carries NUMERIC_TEST_INVERSION_APPROXIMATION.

Declared limitation: session clustering (and the session-block bootstrap) assumes independence ACROSS clusters.
Dependence BETWEEN sessions is not addressed by either."""
from __future__ import annotations

import math

import numpy as np

CLUSTER_LIMITATION = ("CLUSTER_INDEPENDENCE_ASSUMED: session clustering and the session-block bootstrap assume "
                      "independence ACROSS sessions; multi-day volatility regimes and weekly effects are NOT addressed")
APPROXIMATION_LABEL = "NUMERIC_TEST_INVERSION_APPROXIMATION: a finite grid cannot prove unboundedness or exclude unsampled acceptance islands"
B_DEFAULT = 2000
SEED_DEFAULT = 11
ALPHA = 0.05
DISCARD_CEILING = 0.01


class InferenceRefused(ValueError):
    pass


def _cluster_index(sessions) -> list:
    order, seen = [], {}
    for s in sessions:
        if s not in seen:
            seen[s] = len(order); order.append(s)
    idx = [[] for _ in order]
    for i, s in enumerate(sessions):
        idx[seen[s]].append(i)
    return [np.array(g, dtype=int) for g in idx]


def cr1(Z: np.ndarray, e: np.ndarray, clusters: list) -> np.ndarray:
    """CR1 cluster-robust covariance of one equation's coefficients."""
    n, k = Z.shape
    G = len(clusters)
    if G < 2:
        raise InferenceRefused("TOO_FEW_CLUSTERS: %d" % G)
    bread = np.linalg.inv(Z.T @ Z)
    meat = np.zeros((k, k))
    for g in clusters:
        zg = Z[g]; ug = zg.T @ e[g]
        meat += np.outer(ug, ug)
    adj = (G / (G - 1.0)) * ((n - 1.0) / (n - k))
    return bread @ (adj * meat) @ bread


def cr1_se(Z, e, clusters, j: int) -> float:
    v = cr1(Z, e, clusters)[j, j]
    if not math.isfinite(v) or v <= 0:
        raise InferenceRefused("CR1_VARIANCE_INVALID: %r" % (v,))
    return math.sqrt(v)


def _restricted(Z, y, j, a0):
    """Impose a_j = a0 in THIS equation only: regress the offset outcome on the remaining regressors, then add the
    offset back so the null mean sits at a0 (mu0 = a0 z_j + Z_-j beta0)."""
    keep = [c for c in range(Z.shape[1]) if c != j]
    Zr = Z[:, keep]
    yr = y - a0 * Z[:, j]
    beta0 = np.linalg.lstsq(Zr, yr, rcond=None)[0]
    mu0 = a0 * Z[:, j] + Zr @ beta0
    return mu0, y - mu0


def boot_pvalue(Z, y, clusters, j, a0, W) -> dict:
    """Two-sided restricted wild cluster bootstrap p-value, p = (1 + k) / (1 + B_valid), reusing the weight array."""
    b_hat = np.linalg.lstsq(Z, y, rcond=None)[0]
    try:
        se_obs = cr1_se(Z, y - Z @ b_hat, clusters, j)
    except InferenceRefused:
        return {"p": None, "why": "CR1_VARIANCE_INVALID_OBSERVED"}
    t_obs = abs((b_hat[j] - a0) / se_obs)
    mu0, e0 = _restricted(Z, y, j, a0)
    n_valid, n_extreme, discarded = 0, 0, 0
    for b in range(W.shape[0]):
        w = np.ones(len(y))
        for gi, g in enumerate(clusters):
            w[g] = W[b, gi]
        ystar = mu0 + w * e0
        bstar = np.linalg.lstsq(Z, ystar, rcond=None)[0]
        try:
            se = cr1_se(Z, ystar - Z @ bstar, clusters, j)
        except InferenceRefused:
            discarded += 1; continue
        n_valid += 1
        if abs((bstar[j] - a0) / se) >= t_obs:
            n_extreme += 1
    if n_valid == 0:
        return {"p": None, "why": "ALL_REPLICATES_DISCARDED", "discarded": discarded}
    return {"p": (1.0 + n_extreme) / (1.0 + n_valid), "t_obs": t_obs, "b_hat": float(b_hat[j]), "se_obs": se_obs,
            "n_valid": n_valid, "discarded": discarded}


def ci_by_inversion(*, Z, y, sessions, j: int, B: int = B_DEFAULT, seed: int = SEED_DEFAULT, alpha: float = ALPHA,
                    grid: int = 25, max_widen: int = 3, max_bisect: int = 30) -> dict:
    """The declared algorithm, so two implementations agree. Rank is fixed under the wild bootstrap and is checked
    ONCE before resampling; one weight array is generated and REUSED at every tested value."""
    Z = np.asarray(Z, dtype=float); y = np.asarray(y, dtype=float)
    clusters = _cluster_index(sessions)
    if np.linalg.cond(Z.T @ Z) > 1e10:
        raise InferenceRefused("DESIGN_RANK_DEFICIENT_BEFORE_RESAMPLING")
    b_hat = np.linalg.lstsq(Z, y, rcond=None)[0]
    se = cr1_se(Z, y - Z @ b_hat, clusters, j)
    if not (math.isfinite(se) and se > 0):
        raise InferenceRefused("CR1_SE_INVALID")
    rng = np.random.default_rng(seed)
    W = rng.choice(np.array([-1.0, 1.0]), size=(B, len(clusters)))          # one draw per cluster, reused at every a0
    cache: dict = {}
    total_discarded = [0]

    def p_at(a0: float) -> float:
        a0 = float(a0)
        if a0 in cache:
            return cache[a0]
        r = boot_pvalue(Z, y, clusters, j, a0, W)
        if r["p"] is None:
            raise InferenceRefused(r.get("why", "BOOTSTRAP_FAILED"))
        total_discarded[0] += r.get("discarded", 0)
        cache[a0] = r["p"]
        return r["p"]

    b, lo, hi = float(b_hat[j]), float(b_hat[j] - 4 * se), float(b_hat[j] + 4 * se)
    tested = list(np.linspace(lo, hi, grid))
    for a0 in tested:
        p_at(a0)
    widen = {"low": 0, "high": 0}
    for side in ("low", "high"):
        while widen[side] < max_widen:
            edge = min(cache) if side == "low" else max(cache)
            if cache[edge] <= alpha:
                break
            span = abs(edge - b) * 2.0
            new_edge = b - span if side == "low" else b + span
            seg = np.linspace(new_edge, edge, grid) if side == "low" else np.linspace(edge, new_edge, grid)
            for a0 in seg:
                p_at(a0)
            widen[side] += 1
    pts = sorted(cache)
    acc = [a for a in pts if cache[a] > alpha]
    unresolved = []
    if not acc:
        return {"lower": None, "upper": None, "accepted_points": [], "status": "EMPTY_ACCEPTANCE_SET",
                "b_hat": b, "cr1_se": se, "G": len(clusters), "B": B, "seed": seed, "tested": len(cache),
                "discarded_replicates": total_discarded[0], "labels": [APPROXIMATION_LABEL, CLUSTER_LIMITATION]}
    # bisect every adjacent accepted/rejected pair
    bounds = []
    for i in range(len(pts) - 1):
        a, c = pts[i], pts[i + 1]
        if (cache[a] > alpha) == (cache[c] > alpha):
            continue
        it = 0
        while c - a > 1e-4 * se and it < max_bisect:
            mid = 0.5 * (a + c)
            pm = p_at(mid)
            if (pm > alpha) == (cache[a] > alpha):
                a = mid
            else:
                c = mid
            it += 1
        if c - a > 1e-4 * se:
            unresolved.append("BISECTION_CAP")
        bounds.append(0.5 * (a + c))
    if cache[min(pts)] > alpha:
        unresolved.append("ACCEPTED_LOW_ENDPOINT_AFTER_CAP")
    if cache[max(pts)] > alpha:
        unresolved.append("ACCEPTED_HIGH_ENDPOINT_AFTER_CAP")
    # sampled acceptance components (gaps between accepted points separated by a rejected one)
    comps, cur = [], [acc[0]]
    for prev, a in zip(acc, acc[1:]):
        between = [x for x in pts if prev < x < a]
        if any(cache[x] <= alpha for x in between):
            comps.append((cur[0], cur[-1])); cur = [a]
        else:
            cur.append(a)
    comps.append((cur[0], cur[-1]))
    disc_rate = total_discarded[0] / max(1, B * max(1, len(cache)))
    status = "OK"
    if unresolved:
        status = "INVERSION_SEARCH_UNRESOLVED"
    if disc_rate > DISCARD_CEILING:
        raise InferenceRefused("BOOTSTRAP_UNSTABLE: %.4f of replicates discarded" % disc_rate)
    lower = min(acc) if "ACCEPTED_LOW_ENDPOINT_AFTER_CAP" not in unresolved else None
    upper = max(acc) if "ACCEPTED_HIGH_ENDPOINT_AFTER_CAP" not in unresolved else None
    if bounds and lower is not None:
        lower = min([x for x in bounds if x <= min(acc)] + [min(acc)])
    if bounds and upper is not None:
        upper = max([x for x in bounds if x >= max(acc)] + [max(acc)])
    return {"lower": lower, "upper": upper, "hull": [lower, upper], "components": comps,
            "status": status, "unresolved": unresolved,
            "nonconvex": ("CI_NONCONVEX_ACCEPTANCE" if len(comps) > 1 else None),
            "b_hat": b, "cr1_se": se, "G": len(clusters), "reference": ("t_{G-1}" if len(clusters) < 30 else "normal"),
            "small_cluster_note": ("G < 30" if len(clusters) < 30 else None),
            "B": B, "seed": seed, "alpha": alpha, "tested": len(cache), "widenings": widen,
            "discarded_replicates": total_discarded[0], "tested_points": {str(round(k, 12)): v for k, v in sorted(cache.items())},
            "labels": [APPROXIMATION_LABEL, CLUSTER_LIMITATION],
            "reproducibility_note": "a same-seed rerun is bit-identical; that is REPRODUCIBILITY, not inferential correctness"}


def hc1_descriptive(Z, e) -> np.ndarray:
    """DESCRIPTIVE ONLY (§2.3): never supports a claim."""
    Z = np.asarray(Z, dtype=float)
    n, k = Z.shape
    bread = np.linalg.inv(Z.T @ Z)
    meat = (Z * (e ** 2)[:, None]).T @ Z
    return bread @ (n / (n - k) * meat) @ bread


def session_block_bootstrap(values_by_session: dict, *, draws: int = 2000, seed: int = 11) -> dict:
    """Percentile interval of the mean, resampling SESSIONS with replacement (§5.1)."""
    import random
    keys = sorted(values_by_session)
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pick = [rng.choice(keys) for _ in keys] if keys else []
        vals = [v for k in pick for v in values_by_session[k]]
        if vals:
            means.append(sum(vals) / len(vals))
    means.sort()
    allv = [v for k in keys for v in values_by_session[k]]
    return {"mean": (sum(allv) / len(allv) if allv else None), "n": len(allv), "n_sessions": len(keys),
            "ci95": ([means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]] if len(means) > 40 else None),
            "method": "session-block bootstrap, %d draws, seed %d, percentile" % (draws, seed),
            "limitation": CLUSTER_LIMITATION}
