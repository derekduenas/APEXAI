"""MODEL ADAPTERS -- one informative baseline, one null comparator.

M0_SYNTHETIC_BASELINE_V0
    y = X beta + e,   e ~ N(0, sigma^2)
    beta  = argmin ||y - X beta||^2 + lambda ||beta||^2   (ridge)
    sigma = std of TRAINING residuals
    lambda = 1.0, PREDECLARED. Not searched. Not adjusted after S0.

The Gaussian residual assumption is a TEST-STAND assumption about a
synthetic world whose noise was in fact generated Gaussian. It is not a
claim about real markets and must never be promoted into one.

N_BASELINE_NULL_V0
    y ~ N(mean_train, std_train^2), regardless of x.
    "Knowing nothing" expressed in the same forecast contract, so the
    comparison is like-for-like.

BOTH emit a valid WORLD_MODEL_FORECAST_V0 with quantiles, intervals and
a directional probability derived from the Gaussian -- a distribution,
not a point and not a direction.

WHAT THE INTERFACE CANNOT RECEIVE
fit() takes X (list of float rows) and y (list of floats). It has no
parameter for a world, a truth object or a path. There is nothing to
pass the answer key THROUGH.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field as _field

import numpy as np

from apex.world_model.canonical import NumericContractViolation, strict_float
from apex.world_model.forecast import PredictiveDistribution

MODEL_INTERFACE_VERSION = "WM0D_MODEL_ADAPTER_V0"
QUANTILE_LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
INTERVAL_LEVEL = 0.90


class ModelContractViolation(ValueError):
    pass


def _check_matrix(X, y, *, where):
    if not X or not y or len(X) != len(y):
        raise ModelContractViolation(
            "%s: X has %d rows, y has %d" % (where, len(X), len(y)))
    for r in X:
        for v in r:
            strict_float(v, field="%s feature" % where)
    for v in y:
        strict_float(v, field="%s target" % where)


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    # Acklam's rational approximation; adequate for the test stand
    if not (0.0 < p < 1.0):
        raise NumericContractViolation("ppf of %r" % p)
    a = (-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def gaussian_distribution(mu: float, sigma: float) -> PredictiveDistribution:
    """A full WORLD_MODEL_FORECAST_V0 distribution from (mu, sigma)."""
    mu = strict_float(mu, field="mu")
    sigma = strict_float(sigma, field="sigma")
    if sigma <= 0:
        raise ModelContractViolation("sigma must be > 0, got %r" % sigma)
    z90 = _norm_ppf(0.5 + INTERVAL_LEVEL / 2)
    return PredictiveDistribution(
        expected_return=mu, median_return=mu,
        quantiles={str(q): mu + sigma * _norm_ppf(q) for q in QUANTILE_LEVELS},
        prob_return_gt_zero=1.0 - _norm_cdf(-mu / sigma),
        prob_return_lt_zero=_norm_cdf(-mu / sigma),
        predictive_intervals={str(INTERVAL_LEVEL): [mu - z90 * sigma,
                                                    mu + z90 * sigma]},
        total_uncertainty=sigma,
        epistemic_uncertainty=None,     # M0 cannot separate them: say so
        aleatoric_uncertainty=None)


@dataclass
class M0SyntheticBaseline:
    """Ridge regression with Gaussian residual. ONE configuration."""
    model_id: str = "M0_SYNTHETIC_BASELINE_V0"
    model_family: str = "RIDGE_GAUSSIAN"
    model_version: str = "0.1.0"
    ridge_lambda: float = 1.0           # PREDECLARED, never searched
    _beta: tuple = _field(default=None, repr=False)
    _sigma: float = _field(default=None, repr=False)
    _n_fit: int = 0

    def capabilities(self) -> dict:
        return {"distribution": "gaussian", "quantiles": True,
                "intervals": True, "epistemic_aleatoric_split": False,
                "requires_scaled_features": True}

    def fit(self, X: list, y: list) -> "M0SyntheticBaseline":
        _check_matrix(X, y, where="fit")
        Xa = np.asarray(X, dtype=float)
        ya = np.asarray(y, dtype=float)
        n, k = Xa.shape
        if n <= k + 1:
            raise ModelContractViolation(
                "fit: %d rows for %d features is degenerate" % (n, k))
        Xb = np.hstack([np.ones((n, 1)), Xa])
        pen = self.ridge_lambda * np.eye(k + 1)
        pen[0, 0] = 0.0                                  # no penalty on bias
        beta = np.linalg.solve(Xb.T @ Xb + pen, Xb.T @ ya)
        resid = ya - Xb @ beta
        dof = max(1, n - (k + 1))
        sigma = float(math.sqrt(float(resid @ resid) / dof))
        if not math.isfinite(sigma) or sigma <= 0:
            raise ModelContractViolation(
                "fit produced sigma=%r -- residuals are degenerate" % sigma)
        self._beta = tuple(float(b) for b in beta)
        self._sigma = sigma
        self._n_fit = n
        return self

    def predict_distribution(self, x: list) -> PredictiveDistribution:
        if self._beta is None:
            raise ModelContractViolation("predict before fit")
        for v in x:
            strict_float(v, field="predict feature")
        mu = self._beta[0] + sum(b * v for b, v in zip(self._beta[1:], x))
        return gaussian_distribution(mu, self._sigma)

    def model_identity(self) -> dict:
        return {"model_id": self.model_id, "model_family": self.model_family,
                "model_version": self.model_version,
                "interface": MODEL_INTERFACE_VERSION,
                "configuration": {"ridge_lambda": self.ridge_lambda,
                                  "residual": "gaussian",
                                  "bias_penalised": False},
                "fitted": {"beta": list(self._beta) if self._beta else None,
                           "sigma": self._sigma, "n_fit": self._n_fit}}


@dataclass
class NullBaseline:
    """Knowing nothing, honestly."""
    model_id: str = "N_BASELINE_NULL_V0"
    model_family: str = "UNCONDITIONAL_GAUSSIAN"
    model_version: str = "0.1.0"
    _mu: float = _field(default=None, repr=False)
    _sigma: float = _field(default=None, repr=False)
    _n_fit: int = 0

    def capabilities(self) -> dict:
        return {"distribution": "gaussian", "quantiles": True,
                "intervals": True, "epistemic_aleatoric_split": False,
                "uses_features": False}

    def fit(self, X: list, y: list) -> "NullBaseline":
        _check_matrix(X, y, where="fit")
        if len(y) < 3:
            raise ModelContractViolation("null needs >= 3 training targets")
        m = sum(y) / len(y)
        var = sum((v - m) ** 2 for v in y) / (len(y) - 1)
        s = math.sqrt(var)
        if s <= 0:
            raise ModelContractViolation(
                "null fit: training target has zero variance")
        self._mu, self._sigma, self._n_fit = m, s, len(y)
        return self

    def predict_distribution(self, x: list) -> PredictiveDistribution:
        if self._mu is None:
            raise ModelContractViolation("predict before fit")
        return gaussian_distribution(self._mu, self._sigma)   # x ignored

    def model_identity(self) -> dict:
        return {"model_id": self.model_id, "model_family": self.model_family,
                "model_version": self.model_version,
                "interface": MODEL_INTERFACE_VERSION,
                "configuration": {"uses_features": False},
                "fitted": {"mu": self._mu, "sigma": self._sigma,
                           "n_fit": self._n_fit}}
