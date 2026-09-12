"""JOINT-V1 estimation (contract §2.2, §2.3): one multivariate regression on a COMMON design.

    B_hat = (Z'Z)^-1 Z'Y      A_hat = B_hat'      E_hat = Y - Z B_hat      Sigma_hat = E'E / (n - k)

Rows of B_hat index predictors and columns index outcomes; A_hat = B_hat' has outcome rows for Δx = A z + ε. The
transpose matters even though both are 4×4. Only COMPLETE four-output rows enter the fit. Row construction
EXCLUDES and counts; the assembled matrices REFUSE."""
from __future__ import annotations

import math

import numpy as np

from .state import StateRefused, predictor_vector

MIN_ROWS = 200
K = 4
OUTCOMES = ("d_x_iv", "d_x_sk", "d_x_sp", "d_x_sz")
COEFFICIENT_BOUNDS = {"intercept": 5.0, "r": 20.0, "abs_r_scaled": 10.0, "log_q_ratio": 10.0}
MISSING_ENDPOINT_CEILING = 0.10
SPREAD_FLOOR_CEILING = 0.05


class ModelRefusedR4(ValueError):
    pass


def build_rows(pairs: list) -> dict:
    """pairs: [{row_id, session, start:{x_iv,x_sk,x_sp,x_sz}, end:{...}, r, q, v_hat, spread_floored, endpoint_missing,
    available_deadline}]. Returns complete rows plus the exclusion census (§1.4, §1.5, §2.2, §2.3)."""
    rows, census = [], {}
    def drop(why):
        census[why] = census.get(why, 0) + 1
    for p in pairs:
        if p.get("endpoint_missing"):
            drop("ENDPOINT_MISSING"); continue
        st, en = p.get("start") or {}, p.get("end") or {}
        if any(st.get(k) is None or en.get(k) is None for k in ("x_iv", "x_sk", "x_sp", "x_sz")):
            drop("INCOMPLETE_OUTCOMES"); continue
        if p.get("iv_source_changed"):
            drop("IV_SOURCE_CHANGED"); continue
        try:
            z = predictor_vector(r=p["r"], q=p["q"], v_hat=p["v_hat"])
        except StateRefused as e:
            drop(str(e).split(":")[0]); continue
        y = tuple(en[k] - st[k] for k in ("x_iv", "x_sk", "x_sp", "x_sz"))
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in y + z):
            drop("NONFINITE_ROW"); continue
        rows.append({"row_id": p["row_id"], "session": p["session"], "z": z, "y": y,
                     "spread_floored": bool(p.get("spread_floored")), "available_deadline": p.get("available_deadline")})
    n_offered = len(pairs)
    return {"rows": rows, "census": census, "n_offered": n_offered, "n_complete": len(rows),
            "excluded": n_offered - len(rows),
            "exclusion_rate": (n_offered - len(rows)) / n_offered if n_offered else 0.0,
            "ceiling_note": ("the 10 % ceiling is an ENGINEERING REFUSAL THRESHOLD; it does not establish that "
                             "complete-case estimates below it are unbiased — informative missingness biases them at any rate")}


def fit(built: dict, *, cutoff_epoch: float, label: str | None = None) -> dict:
    rows = built["rows"]
    if built["exclusion_rate"] > MISSING_ENDPOINT_CEILING:
        raise ModelRefusedR4("ENDPOINT_MISSINGNESS_EXCESSIVE: %.3f > %.2f" % (built["exclusion_rate"], MISSING_ENDPOINT_CEILING))
    if rows:
        fl = sum(1 for r in rows if r["spread_floored"]) / len(rows)
        if fl > SPREAD_FLOOR_CEILING:
            raise ModelRefusedR4("SPREAD_FLOOR_EXCESSIVE: %.3f > %.2f" % (fl, SPREAD_FLOOR_CEILING))
    late = [r["row_id"] for r in rows if r.get("available_deadline") is not None and r["available_deadline"] > cutoff_epoch]
    if late:
        raise ModelRefusedR4("FIREWALL: %d row(s) available after cutoff %.0f, first %r" % (len(late), cutoff_epoch, late[:3]))
    if len(rows) < MIN_ROWS:
        raise ModelRefusedR4("INSUFFICIENT_HISTORY: %d < %d" % (len(rows), MIN_ROWS))
    Z = np.array([r["z"] for r in rows], dtype=float)
    Y = np.array([r["y"] for r in rows], dtype=float)
    if not (np.all(np.isfinite(Z)) and np.all(np.isfinite(Y))):
        raise ModelRefusedR4("NONFINITE_INPUT: assembled matrices (an implementation fault, not data)")
    if np.any(Y.std(axis=0) == 0):
        raise ModelRefusedR4("DEGENERATE_STATE: constant outcome column %s" % [OUTCOMES[i] for i in np.where(Y.std(axis=0) == 0)[0]])
    ZtZ = Z.T @ Z
    cond = float(np.linalg.cond(ZtZ))
    if not math.isfinite(cond) or cond > 1e10:
        raise ModelRefusedR4("DESIGN_RANK_DEFICIENT: cond(Z'Z) = %.3g" % cond)
    B = np.linalg.solve(ZtZ, Z.T @ Y)                 # (k x 4): rows predictors, columns outcomes
    A = B.T                                            # (4 x k): outcome rows, for Δx = A z + ε
    E = Y - Z @ B
    n = len(rows)
    Sigma = (E.T @ E) / (n - K)
    Sigma = 0.5 * (Sigma + Sigma.T)
    for j, name in enumerate(("intercept", "r", "abs_r_scaled", "log_q_ratio")):
        bad = np.abs(B[j, :]) > COEFFICIENT_BOUNDS[name]
        if bad.any():
            raise ModelRefusedR4("COEFFICIENT_OUT_OF_BOUNDS: %s on %s (|b| up to %.3g > %.3g)"
                                 % (name, [OUTCOMES[i] for i in np.where(bad)[0]], float(np.max(np.abs(B[j, :]))), COEFFICIENT_BOUNDS[name]))
    eig = np.linalg.eigvalsh(Sigma)
    if float(np.min(eig)) <= 0:
        raise ModelRefusedR4("COVARIANCE_NOT_PD: min eigenvalue %.3g" % float(np.min(eig)))
    return {"B": B, "A": A, "Sigma": Sigma, "E": E, "Z": Z, "Y": Y, "n": n, "k": K,
            "sessions": [r["session"] for r in rows], "row_ids": [r["row_id"] for r in rows],
            "cutoff_epoch": cutoff_epoch, "label": label, "cond_ZtZ": cond,
            "sigma_eigenvalues": eig.tolist(), "sigma_condition": float(eig.max() / eig.min()),
            "orientation": "B rows = predictors, columns = outcomes; A = B' has outcome rows for dx = A z + eps",
            "census": built["census"], "n_offered": built["n_offered"], "exclusion_rate": built["exclusion_rate"]}


def forecast_mean(fitted: dict, z) -> np.ndarray:
    """Δx mean = A z (outcome rows) — the orientation the contract fixes."""
    return np.asarray(fitted["A"]) @ np.asarray(z, dtype=float)


def diagnostics(fitted: dict) -> dict:
    """Recorded, never gates: residual association with (r, |r|, r^2) and per-equation Jarque-Bera."""
    from scipy import stats
    Z, E = fitted["Z"], fitted["E"]
    r = Z[:, 1]
    out = {"mean_independence": {}, "jarque_bera": {}}
    for i, name in enumerate(OUTCOMES):
        col = E[:, i]
        out["mean_independence"][name] = {k: float(np.corrcoef(v, col)[0, 1]) for k, v in
                                          (("r", r), ("abs_r", np.abs(r)), ("r2", r * r))}
        jb = stats.jarque_bera(col)
        out["jarque_bera"][name] = {"stat": float(jb.statistic), "p": float(jb.pvalue),
                                    "flag": bool(jb.pvalue < 0.001) and "RESIDUAL_NONGAUSSIAN_FLAG" or None}
    out["note"] = "diagnostics are RECORDED as flags; none of them refuses a fit in V1"
    return out
