"""EXP-004 dispersion (R5, R6). Objectives as registered:

    J0(log s0, log nu) = sum_i [ log s0 - log t_nu(z_i / s0) ]
    a_i = log s1 + lambda * P~_i
    J1(log s1, lambda) = sum_i [ a_i - log t_nu0(z_i * exp(-a_i)) ]

The fitter reports; THIS module enforces the refusal policy. No residual is
ever filtered. Accepted parameters must give finite, positive scales everywhere."""
from __future__ import annotations

import math

import numpy as np

from apex.world_model.exp002 import studentt as T
from apex.world_model.exp002.registration import NU_BOUNDS

LAMBDA_BOUNDS = (-2.0, 2.0)
BOUND_TOL = 1e-3
MIN_RESIDUALS = 100
IDENTITY_REL_TOL = 1e-9


class DispersionRefused(ValueError):
    """A named refusal at the dispersion stage (declared model-domain policy)."""


def _validate_residuals(z: np.ndarray, label: str) -> None:
    # NO filtering: presence of any non-finite value refuses the whole fit
    if not np.all(np.isfinite(z)):
        raise DispersionRefused("NONFINITE_RESIDUALS: %s" % label)
    if len(z) < MIN_RESIDUALS:
        raise DispersionRefused("INSUFFICIENT_RESIDUALS: %d < %d (%s)" % (len(z), MIN_RESIDUALS, label))


def _log_t_unit(w: np.ndarray, nu: float) -> np.ndarray:
    return (math.lgamma((nu + 1.0) / 2.0) - math.lgamma(nu / 2.0) - 0.5 * math.log(nu * math.pi)
            - (nu + 1.0) / 2.0 * np.log1p(w * w / nu))


def J0(z: np.ndarray, log_s: float, log_nu: float) -> float:
    s, nu = math.exp(log_s), math.exp(log_nu)
    return float(np.sum(log_s - _log_t_unit(z / s, nu)))


def J1(z: np.ndarray, p: np.ndarray, log_s1: float, lam: float, nu0: float) -> float:
    a = log_s1 + lam * p
    return float(np.sum(a - _log_t_unit(z * np.exp(-a), nu0)))


def identity_check(z: np.ndarray, p: np.ndarray, log_s0: float, nu0: float) -> dict:
    """Required before any fit is accepted: J1(log s0, 0) == J0(log s0, log nu0)."""
    j1, j0 = J1(z, p, log_s0, 0.0, nu0), J0(z, log_s0, math.log(nu0))
    rel = abs(j1 - j0) / max(abs(j0), 1e-300)
    return {"J1_at_lambda0": j1, "J0": j0, "rel_diff": rel, "tol": IDENTITY_REL_TOL, "ok": rel <= IDENTITY_REL_TOL}


def _nelder_mead(f, x0: np.ndarray, *, step: float = 0.1, max_iter: int = 500, tol: float = 1e-8) -> tuple:
    """The same algorithm and coefficients as studentt.fit_scale_nu, for 2-D."""
    simplex = [x0, x0 + np.array([step, 0.0]), x0 + np.array([0.0, step])]
    fv = [f(*p) for p in simplex]
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    converged, iters = False, 0
    for iters in range(1, max_iter + 1):
        order = np.argsort(fv)
        simplex = [simplex[i] for i in order]; fv = [fv[i] for i in order]
        diam = max(np.linalg.norm(simplex[i] - simplex[0]) for i in (1, 2))
        if max(abs(fi - fv[0]) for fi in fv[1:]) < tol and diam < tol:
            converged = True
            break
        centroid = (simplex[0] + simplex[1]) / 2.0
        xr = centroid + alpha * (centroid - simplex[2]); fr = f(*xr)
        if fr < fv[0]:
            xe = centroid + gamma * (xr - centroid); fe = f(*xe)
            simplex[2], fv[2] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fv[1]:
            simplex[2], fv[2] = xr, fr
        else:
            xc = centroid + rho * (simplex[2] - centroid); fc = f(*xc)
            if fc < fv[2]:
                simplex[2], fv[2] = xc, fc
            else:
                for i in (1, 2):
                    simplex[i] = simplex[0] + sigma * (simplex[i] - simplex[0])
                    fv[i] = f(*simplex[i])
    best = simplex[int(np.argmin(fv))]
    return best, float(min(fv)), converged, iters


def fit_d0(z) -> dict:
    """D0: (s0, nu0) via the shipped two-parameter fitter; lower-bound nu refused HERE."""
    z = np.asarray(z, dtype=float)
    _validate_residuals(z, "D0")
    try:
        t = T.fit_scale_nu(z)
    except DispersionRefused:
        raise
    except (ValueError, ArithmeticError) as e:
        raise DispersionRefused("D0_FITTER: %s: %s" % (type(e).__name__, e)) from e
    if t["nu_at_lower_bound"]:
        raise DispersionRefused("NU_AT_LOWER_BOUND: nu=%.4f at %.1f; refused by declared model-domain policy"
                                % (t["nu"], NU_BOUNDS[0]))
    if not (math.isfinite(t["s"]) and t["s"] > 0 and math.isfinite(t["nll"])):
        raise DispersionRefused("NONFINITE_D0_FIT")
    return {"spec": "D0", "s0": t["s"], "nu0": t["nu"], "nll": t["nll"], "iterations": t["iterations"],
            "converged": t["converged"], "nu_at_upper_bound": t["nu_at_upper_bound"], "n": int(len(z)),
            "bound_tol": BOUND_TOL}


def fit_d1(z, p, *, nu0: float, s0: float, max_iter: int = 500, tol: float = 1e-8) -> dict:
    """D1: (s1, lambda) with nu FROZEN at nu0; init s1 = s0, lambda = 0."""
    z, p = np.asarray(z, dtype=float), np.asarray(p, dtype=float)
    _validate_residuals(z, "D1")
    if len(p) != len(z) or not np.all(np.isfinite(p)):
        raise DispersionRefused("NONFINITE_OR_MISALIGNED_P")
    ident = identity_check(z, p, math.log(s0), nu0)
    if not ident["ok"]:
        raise DispersionRefused("IDENTITY_CHECK_FAILED: rel_diff=%.3e" % ident["rel_diff"])
    lo, hi = LAMBDA_BOUNDS

    def obj(log_s1, lam):
        if not (lo <= lam <= hi) or not math.isfinite(log_s1):
            return float("inf")
        v = J1(z, p, log_s1, lam, nu0)
        return v if math.isfinite(v) else float("inf")

    try:
        best, nll, converged, iters = _nelder_mead(obj, np.array([math.log(s0), 0.0]), max_iter=max_iter, tol=tol)
    except ArithmeticError as e:                       # overflow/underflow/zero-division inside the search
        raise DispersionRefused("D1_ARITHMETIC: %s: %s" % (type(e).__name__, e)) from e
    if not converged:
        raise DispersionRefused("OPTIMIZER_NO_CONVERGENCE after %d iterations (D1)" % iters)
    s1, lam = math.exp(best[0]), float(best[1])
    if abs(lam - lo) <= BOUND_TOL or abs(lam - hi) <= BOUND_TOL:
        raise DispersionRefused("LAMBDA_AT_BOUND: lambda=%.4f within %g of %s; a constrained estimate, refused by "
                                "declared model-domain policy" % (lam, BOUND_TOL, LAMBDA_BOUNDS))
    if not (math.isfinite(s1) and s1 > 0 and math.isfinite(nll)):
        raise DispersionRefused("NONFINITE_D1_FIT")
    return {"spec": "D1", "s1": s1, "lambda": lam, "nu0": nu0, "nll": nll, "iterations": iters,
            "converged": True, "n": int(len(z)), "identity_check": ident, "bound_tol": BOUND_TOL,
            "lambda_bounds": list(LAMBDA_BOUNDS)}


def scales(spec: dict, rv30: np.ndarray, p_c: np.ndarray) -> np.ndarray:
    """Full scoring scale (R5): D0 rv*s0; D1 rv*s1*exp(lambda*P~)."""
    rv30 = np.asarray(rv30, dtype=float)
    if spec["spec"] == "D0":
        return rv30 * spec["s0"]
    with np.errstate(over="ignore", invalid="ignore"):          # overflow becomes inf and is REFUSED by check_scales
        return rv30 * spec["s1"] * np.exp(spec["lambda"] * np.asarray(p_c, dtype=float))


def check_scales(spec: dict, rv30, p_c, label: str) -> None:
    sc = scales(spec, rv30, p_c)
    if not (np.all(np.isfinite(sc)) and np.all(sc > 0)):
        raise DispersionRefused("NONFINITE_SCALE: %s under %s" % (label, spec["spec"]))


def require_finite(arr, label: str) -> np.ndarray:
    """Numerical invalidity is an INTEGRITY refusal, never a statistical negative (R6/R9)."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0 or not np.all(np.isfinite(a)):
        bad = int(a.size - np.isfinite(a).sum()) if a.size else 0
        raise DispersionRefused("NONFINITE_VALUES: %s (%d non-finite of %d)" % (label, bad, a.size))
    return a


def logpdf(y: np.ndarray, mu: np.ndarray, scale: np.ndarray, nu: float, *, label: str = "log_density") -> np.ndarray:
    """Vectorised Student-t log-density with the complete scale (includes -log scale).
    Refuses non-finite output rather than returning it."""
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        w = (np.asarray(y, dtype=float) - np.asarray(mu, dtype=float)) / scale
        out = _log_t_unit(w, nu) - np.log(scale)
    return require_finite(out, label)
