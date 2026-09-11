"""SVI slice fit with static-arbitrage diagnostics (M4).

Raw SVI (Gatheral–Jacquier) for one expiry: total implied variance
    w(k) = a + b [ rho (k - m) + sqrt((k - m)^2 + sigma^2) ],   k = ln(K/F)
Constraints: b >= 0, |rho| < 1, sigma > 0, a + b sigma sqrt(1 - rho^2) >= 0.
Butterfly (Durrleman) diagnostic: g(k) = (1 - k w'/(2w))^2 - (w'^2/4)(1/w + 1/4) + w''/2 >= 0.
Calendar diagnostic: w_T2(k) >= w_T1(k) for T2 > T1 on a common k grid.
Applies to EUROPEAN pricing only; American quotes must not be treated as European inputs. A
failed fit or a violated diagnostic is RECORDED on the surface; nothing is projected to 'clean'."""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize

from .pricing import PricingRefused


def svi_w(k, a, b, rho, m, sigma):
    k = np.asarray(k, dtype=float)
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma ** 2))


def fit_svi_slice(*, k: np.ndarray, w: np.ndarray, T: float) -> dict:
    """Least squares on total variance with the SVI constraints; returns params + diagnostics."""
    k, w = np.asarray(k, dtype=float), np.asarray(w, dtype=float)
    if len(k) < 5 or not np.all(np.isfinite(k)) or not np.all(np.isfinite(w)) or np.any(w <= 0):
        raise PricingRefused("SVI_INPUT_INVALID")

    def loss(th):
        a, b, rho, m, sig = th
        if b < 0 or abs(rho) >= 1 or sig <= 0 or a + b * sig * math.sqrt(1 - rho * rho) < 0:
            return 1e6
        return float(np.mean((svi_w(k, a, b, rho, m, sig) - w) ** 2))

    x0 = [float(np.min(w)) * 0.8, 0.1, -0.3, 0.0, 0.2]
    res = optimize.minimize(loss, x0, method="Nelder-Mead", options={"maxiter": 6000, "xatol": 1e-10, "fatol": 1e-16})
    for _ in range(3):                                   # restarts from the incumbent: Nelder-Mead stalls on 5 parameters
        r2 = optimize.minimize(loss, res.x, method="Nelder-Mead", options={"maxiter": 6000, "xatol": 1e-10, "fatol": 1e-16})
        if r2.fun < res.fun:
            res = r2
    r3 = optimize.minimize(loss, res.x, method="Powell", options={"maxiter": 20000, "xtol": 1e-10, "ftol": 1e-16})
    if r3.fun < res.fun:
        res = r3
    a, b, rho, m, sig = res.x
    ok = res.fun < 1e6 and b >= 0 and abs(rho) < 1 and sig > 0
    out = {"params": {"a": a, "b": b, "rho": rho, "m": m, "sigma": sig}, "T": T, "rmse_total_variance": math.sqrt(max(res.fun, 0.0)),
           "fit_ok": bool(ok), "n": int(len(k)), "k_range": [float(k.min()), float(k.max())]}
    out["butterfly"] = butterfly_diagnostic(out["params"], k_grid=np.linspace(k.min(), k.max(), 101))
    return out


def butterfly_diagnostic(p: dict, *, k_grid: np.ndarray) -> dict:
    a, b, rho, m, sig = p["a"], p["b"], p["rho"], p["m"], p["sigma"]
    k = np.asarray(k_grid, dtype=float)
    w = svi_w(k, a, b, rho, m, sig)
    root = np.sqrt((k - m) ** 2 + sig ** 2)
    w1 = b * (rho + (k - m) / root)
    w2 = b * sig ** 2 / root ** 3
    g = (1 - k * w1 / (2 * w)) ** 2 - (w1 ** 2 / 4) * (1 / w + 0.25) + w2 / 2
    viol = k[g < -1e-10]
    return {"min_g": float(np.min(g)), "violations": int(len(viol)), "arbitrage_free_butterfly": bool(len(viol) == 0),
            "k_at_violation": viol[:5].tolist()}


def calendar_diagnostic(slices: list, *, k_grid: np.ndarray) -> dict:
    """slices: [{"T", "params"}] sorted by T; total variance must be non-decreasing in T."""
    s = sorted(slices, key=lambda x: x["T"])
    problems = []
    for i in range(1, len(s)):
        w0 = svi_w(k_grid, **s[i - 1]["params"]); w1 = svi_w(k_grid, **s[i]["params"])
        bad = np.sum(w1 < w0 - 1e-10)
        if bad:
            problems.append({"T_low": s[i - 1]["T"], "T_high": s[i]["T"], "k_violations": int(bad)})
    return {"arbitrage_free_calendar": not problems, "problems": problems}


class Surface:
    """A set of fitted slices with their diagnostics; `iv(k, T)` refuses outside fitted expiries or when the
    slice failed; interpolation in T is linear in total variance and is LABELLED."""

    def __init__(self, slices: list, *, source: str, quote_quality: dict):
        self.slices = sorted(slices, key=lambda x: x["T"])
        self.source, self.quote_quality = source, quote_quality
        self.calendar = calendar_diagnostic(self.slices, k_grid=np.linspace(-0.3, 0.3, 61)) if len(self.slices) > 1 else {"arbitrage_free_calendar": None, "problems": []}

    def describe(self) -> dict:
        return {"source": self.source, "quote_quality": self.quote_quality, "n_slices": len(self.slices),
                "slices": [{"T": s["T"], "fit_ok": s["fit_ok"], "rmse": s["rmse_total_variance"], "butterfly": s["butterfly"]} for s in self.slices],
                "calendar": self.calendar, "european_only": True,
                "note": "diagnostics are RECORDED; a violated slice is not repaired or projected"}

    def iv(self, k: float, T: float) -> dict:
        exact = [s for s in self.slices if abs(s["T"] - T) < 1e-9]
        if exact:
            s = exact[0]
            if not s["fit_ok"]:
                raise PricingRefused("SLICE_FIT_FAILED for T=%r" % T)
            w = float(svi_w(k, **s["params"]))
            return {"iv": math.sqrt(w / T), "total_variance": w, "interpolated": False, "butterfly_ok": s["butterfly"]["arbitrage_free_butterfly"]}
        lower = [s for s in self.slices if s["T"] < T and s["fit_ok"]]; upper = [s for s in self.slices if s["T"] > T and s["fit_ok"]]
        if not lower or not upper:
            raise PricingRefused("T_OUTSIDE_FITTED_EXPIRIES")
        s0, s1 = lower[-1], upper[0]
        w0, w1 = float(svi_w(k, **s0["params"])), float(svi_w(k, **s1["params"]))
        lam = (T - s0["T"]) / (s1["T"] - s0["T"])
        w = w0 + lam * (w1 - w0)
        return {"iv": math.sqrt(w / T), "total_variance": w, "interpolated": True, "between": [s0["T"], s1["T"]],
                "method": "linear in total variance between fitted slices (labelled)"}
