"""Student-t density, CDF, quantile and a bounded two-parameter ML fit.

Pure math for the per-row functions so a grade never depends on a library's
numerics; numpy only inside the fitter, where n is large."""
from __future__ import annotations

import math

import numpy as np

from .registration import NU_BOUNDS


def logpdf(y: float, mu: float, scale: float, nu: float) -> float:
    z = (y - mu) / scale
    return (math.lgamma((nu + 1.0) / 2.0) - math.lgamma(nu / 2.0)
            - 0.5 * math.log(nu * math.pi) - math.log(scale)
            - (nu + 1.0) / 2.0 * math.log1p(z * z / nu))


def _betacf(a: float, b: float, x: float, max_iter: int = 2000, eps: float = 3e-15) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d; d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c; c = tiny if abs(c) < tiny else c
        d = 1.0 / d; h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d; d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c; c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            return h
    raise ArithmeticError("BETACF_NO_CONVERGENCE")


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log1p(-x) - lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def cdf(y: float, mu: float, scale: float, nu: float) -> float:
    """Two-sided tail via the regularised incomplete beta.

    The complement 1 - x = t^2/(nu + t^2) is formed DIRECTLY. Forming it as
    1 - nu/(nu+t^2) rounds to zero for small t, which made the CDF flat across
    a tiny interval around the median and let the quantile bisection land
    anywhere inside it."""
    t = (y - mu) / scale
    tt = t * t
    yc = tt / (nu + tt)                      # exact complement, no cancellation
    if yc < 0.5:
        p = 0.5 * (1.0 - betainc(0.5, nu / 2.0, yc))
    else:
        p = 0.5 * betainc(nu / 2.0, 0.5, nu / (nu + tt))
    return 1.0 - p if t > 0 else p


def ppf(q: float, mu: float, scale: float, nu: float) -> float:
    """Quantile by bisection on the CDF. Deterministic."""
    if not (0.0 < q < 1.0):
        raise ValueError("q out of (0,1)")
    lo, hi = -1e4, 1e4
    for _ in range(80):                       # 2e4 / 2^80 is far below any float resolution needed
        mid = 0.5 * (lo + hi)
        if cdf(mu + mid * scale, mu, scale, nu) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return mu + 0.5 * (lo + hi) * scale


def implied_sd(scale: float, nu: float) -> float:
    return scale * math.sqrt(nu / (nu - 2.0))


def _nll(z: np.ndarray, log_s: float, log_nu: float) -> float:
    s, nu = math.exp(log_s), math.exp(log_nu)
    if not (NU_BOUNDS[0] <= nu <= NU_BOUNDS[1]) or not math.isfinite(s) or s <= 0:
        return float("inf")
    zz = z / s
    c = (math.lgamma((nu + 1) / 2) - math.lgamma(nu / 2) - 0.5 * math.log(nu * math.pi) - math.log(s))
    return float(-(len(z) * c - (nu + 1) / 2 * np.log1p(zz * zz / nu).sum()))


def fit_scale_nu(z, *, max_iter: int = 500, tol: float = 1e-8) -> dict:
    """Two-parameter ML on standardised residuals z, Nelder-Mead over
    (log s, log nu), bounds enforced as infinite walls. Returns the fit and
    an explicit account of convergence and bound contact."""
    z = np.asarray(z, dtype=float)
    if len(z) < 100 or not np.all(np.isfinite(z)):
        raise ValueError("INSUFFICIENT_OR_NONFINITE_RESIDUALS")
    nu0 = 6.0
    s0 = float(z.std()) * math.sqrt((nu0 - 2) / nu0)
    if not (s0 > 0):
        raise ValueError("ZERO_RESIDUAL_SPREAD")
    x0 = np.array([math.log(s0), math.log(nu0)])
    simplex = [x0, x0 + np.array([0.1, 0.0]), x0 + np.array([0.0, 0.1])]
    f = [_nll(z, *p) for p in simplex]
    alpha, gamma, rho, sigma = 1.0, 2.0, 0.5, 0.5
    converged, iters = False, 0
    for iters in range(1, max_iter + 1):
        order = np.argsort(f)
        simplex = [simplex[i] for i in order]; f = [f[i] for i in order]
        diam = max(np.linalg.norm(simplex[i] - simplex[0]) for i in (1, 2))
        if max(abs(fi - f[0]) for fi in f[1:]) < tol and diam < tol:
            converged = True
            break
        centroid = (simplex[0] + simplex[1]) / 2.0
        xr = centroid + alpha * (centroid - simplex[2]); fr = _nll(z, *xr)
        if fr < f[0]:
            xe = centroid + gamma * (xr - centroid); fe = _nll(z, *xe)
            if fe < fr:
                simplex[2], f[2] = xe, fe
            else:
                simplex[2], f[2] = xr, fr
        elif fr < f[1]:
            simplex[2], f[2] = xr, fr
        else:
            xc = centroid + rho * (simplex[2] - centroid); fc = _nll(z, *xc)
            if fc < f[2]:
                simplex[2], f[2] = xc, fc
            else:
                for i in (1, 2):
                    simplex[i] = simplex[0] + sigma * (simplex[i] - simplex[0])
                    f[i] = _nll(z, *simplex[i])
    best = simplex[int(np.argmin(f))]
    s, nu = math.exp(best[0]), math.exp(best[1])
    if not converged:
        raise ValueError("OPTIMIZER_NO_CONVERGENCE after %d iterations" % iters)
    at_upper = nu >= NU_BOUNDS[1] - 1e-3
    at_lower = nu <= NU_BOUNDS[0] + 1e-3
    return {"s": s, "nu": nu, "nll": float(min(f)), "iterations": iters, "converged": True,
            "nu_at_upper_bound": bool(at_upper), "nu_at_lower_bound": bool(at_lower),
            "init": {"nu0": nu0, "s0": s0}, "n": int(len(z))}
