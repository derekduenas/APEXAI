"""BLOCK_SEQUENTIAL_V1 — the residual law (contract §2.4, as amended and accepted).

The sampler is retained from Draft 3.1; the ATTRIBUTION claim attached to it is the corrected one. Independent
standard 2-D base vectors are radially truncated and renormalized, then mapped:

    e1       = chol(S11) w1
    e2_joint = M e1 + chol(C) w2        M = S21 S11^-1,  C = S22 - M S12
    e2_diag  = chol(S22) w2

Population identities hold EXACTLY: Cov(e2_joint) = M S11 M' + C = S22, Cov(e1, e2_joint) = S12,
Cov(e2_diag) = S22, Cov(e1, e2_diag) = 0. They are population statements, not sample ones.

The execution-block MARGINAL LAW nevertheless differs between JOINT (a sum of two bounded vectors) and C_DIAG (a
single transformed bounded vector): equal covariance does not give equal tail shape. JOINT - C_DIAG is therefore a
COMPOUND_COUPLING_LAW_CONTRAST and never an isolated correlation effect."""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import chi2

TRUNCATION_Q = 0.9999
COMPOUND_LABEL = ("COMPOUND_COUPLING_LAW_CONTRAST: JOINT - C_DIAG moves the conditional mean, the conditional "
                  "residual covariance and the execution-block marginal law together; it is not an isolated "
                  "dependence estimate, and no V1 contrast isolates cross-block residual dependence")


class SamplerRefused(ValueError):
    pass


def c2(d: int, q: float = TRUNCATION_Q) -> float:
    return float(chi2.ppf(q, d))


def kappa(d: int, q: float = TRUNCATION_Q) -> float:
    """Exact variance deflation of an elliptically truncated MVN: P(chi2_{d+2} <= c2) / P(chi2_d <= c2)."""
    cc = c2(d, q)
    return float(chi2.cdf(cc, d + 2) / chi2.cdf(cc, d))


def draw_base(rng: np.random.Generator, *, n: int, d: int, q: float = TRUNCATION_Q) -> dict:
    """Standard d-dim vectors, radially rejected at c2(d) and divided by sqrt(kappa): population covariance I_d."""
    cc, kp = c2(d, q), kappa(d, q)
    out = np.empty((n, d)); filled = 0; rejected = 0; guard = 0
    while filled < n:
        m = max(16, int((n - filled) * 1.2))
        u = rng.standard_normal((m, d))
        keep = (u * u).sum(axis=1) <= cc
        rejected += int((~keep).sum())
        u = u[keep]
        take = min(len(u), n - filled)
        out[filled:filled + take] = u[:take]
        filled += take
        guard += 1
        if guard > 10000:
            raise SamplerRefused("TRUNCATION_REJECTION_LOOP")
    return {"w": out / math.sqrt(kp), "c2": cc, "kappa": kp, "rejected": rejected,
            "accepted_mass": float(chi2.cdf(cc, d)), "d": d}


def blocks_from_sigma(sigma: np.ndarray) -> dict:
    """Schur complement pieces with positive-definiteness checked before any Cholesky (§2.4)."""
    sigma = np.asarray(sigma, dtype=float)
    if sigma.shape != (4, 4) or not np.all(np.isfinite(sigma)):
        raise SamplerRefused("SIGMA_SHAPE_OR_FINITENESS")
    s11, s12, s21, s22 = sigma[:2, :2], sigma[:2, 2:], sigma[2:, :2], sigma[2:, 2:]
    for name, blk in (("S11", s11), ("S22", s22)):
        if np.min(np.linalg.eigvalsh(blk)) <= 0:
            raise SamplerRefused("COVARIANCE_NOT_PD:%s" % name)
    m = np.linalg.solve(s11, s21.T).T                      # M = S21 S11^-1
    c = s22 - m @ s12
    c = 0.5 * (c + c.T)
    if np.min(np.linalg.eigvalsh(c)) <= 0:
        raise SamplerRefused("COVARIANCE_NOT_PD:C (conditional)")
    return {"S11": s11, "S12": s12, "S21": s21, "S22": s22, "M": m, "C": c,
            "L11": np.linalg.cholesky(s11), "L22": np.linalg.cholesky(s22), "LC": np.linalg.cholesky(c)}


def pregenerate(*, sigma: np.ndarray, n_paths: int, seed: int, trunc_q: float = TRUNCATION_Q) -> dict:
    """ALL option-state randomness for one scan, drawn before any candidate is evaluated (§3.2).
    `trunc_q` is the declared truncation quantile; the adverse scenarios of §5.3 rule 3 vary it explicitly."""
    b = blocks_from_sigma(sigma)
    rng = np.random.default_rng(seed)
    base = {}
    for tag in ("horizon", "extension"):
        base[tag] = {"w1": draw_base(rng, n=n_paths, d=2, q=trunc_q), "w2": draw_base(rng, n=n_paths, d=2, q=trunc_q)}
    out = {"blocks": b, "seed": seed, "n_paths": n_paths, "truncation": {}, "e": {}}
    for tag, bb in base.items():
        w1, w2 = bb["w1"]["w"], bb["w2"]["w"]
        e1 = w1 @ b["L11"].T
        out["e"][tag] = {"e1": e1, "e2_joint": e1 @ b["M"].T + w2 @ b["LC"].T, "e2_diag": w2 @ b["L22"].T,
                         "w1": w1, "w2": w2}
        out["truncation"][tag] = {k: {kk: bb[k][kk] for kk in ("c2", "kappa", "rejected", "accepted_mass", "d")} for k in ("w1", "w2")}
    out["M"], out["C"], out["trunc_q"] = b["M"], b["C"], trunc_q
    out["compound_label"] = COMPOUND_LABEL
    return out


def innovations(pre: dict, *, comparator: str, tag: str = "horizon") -> np.ndarray:
    """(n_paths, 4) innovations for a comparator. Inactive coordinates are exactly zero.
    C_IV takes the FIRST COORDINATE of the SHARED e1 — never a separately truncated 1-D draw (§4.2)."""
    e = pre["e"][tag]
    n = pre["n_paths"]
    z = np.zeros((n, 4))
    if comparator == "MATCHED_FROZEN":
        return z
    if comparator == "C_IV":
        z[:, 0] = e["e1"][:, 0]; return z
    if comparator == "C_IVSK":
        z[:, :2] = e["e1"]; return z
    if comparator == "C_EXEC":
        z[:, 2:] = e["e2_diag"]; return z
    if comparator == "C_DIAG":
        z[:, :2] = e["e1"]; z[:, 2:] = e["e2_diag"]; return z
    if comparator == "JOINT":
        z[:, :2] = e["e1"]; z[:, 2:] = e["e2_joint"]; return z
    raise SamplerRefused("COMPARATOR_UNKNOWN: %r" % (comparator,))


def moment_identities(pre: dict) -> dict:
    """The exact POPULATION identities (not sample covariances), for the record and for T35."""
    b = pre["blocks"]
    return {"cov_e2_joint": b["M"] @ b["S11"] @ b["M"].T + b["C"], "target_S22": b["S22"],
            "cov_e1_e2_joint": b["S11"] @ b["M"].T, "target_S12": b["S12"],
            "cov_e2_diag": b["S22"], "cov_e1_e2_diag": np.zeros((2, 2)),
            "note": "population identities; sample covariance is a Monte Carlo diagnostic, not an identity"}
