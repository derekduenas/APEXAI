"""NGBoost-style natural-gradient boosting of a Normal(mu, sigma) (M3).

Parameters theta = (mu, log sigma). Scoring rule: log score. The natural
gradient is Fisher^{-1} times the ordinary gradient; for the Normal in this
parameterization Fisher = diag(1/sigma^2, 2), so
    ng_mu    = (y - mu)                    (= sigma^2 * d(-logp)/dmu ... sign flipped to a descent step)
    ng_lsig  = ((y - mu)^2 / sigma^2 - 1) / 2
Base learners: decision stumps per parameter per round; bounded rounds; a
single learning rate. This is a compact re-implementation for the workbench,
not the reference library; its benchmark performance elsewhere is not evidence
about options profitability."""
from __future__ import annotations

import math

import numpy as np

from .contracts import ForecastObject, Model, ModelRefused
from .quantile_tree import _stump_fit, _stump_predict


class NormalNGBoost(Model):
    model_id = "NGBOOST_NORMAL_STUMPS"
    supplies = ("mean", "variance", "density", "quantiles")
    fit_budget = 1

    def __init__(self, *, rounds: int = 80, lr: float = 0.05, features=("ret_1", "ret_5", "rv_30")):
        super().__init__()
        self.rounds, self.lr, self.features = rounds, lr, tuple(features)
        self.mu0 = 0.0; self.ls0 = 0.0; self.stumps: list = []

    def _X(self, rows):
        X = np.array([[r["features"][f] for f in self.features] for r in rows], dtype=float)
        if not np.all(np.isfinite(X)):
            raise ModelRefused("NONFINITE_FEATURES")
        return X

    def _fit(self, rows):
        X = self._X(rows); y = np.array([r["y"] for r in rows], dtype=float)
        if len(y) < 50:
            raise ModelRefused("TOO_FEW_ROWS")
        self.mu0, self.ls0 = float(np.mean(y)), float(math.log(np.std(y) + 1e-12))
        mu = np.full(len(y), self.mu0); ls = np.full(len(y), self.ls0)
        for _ in range(self.rounds):
            sig2 = np.exp(2 * ls)
            ng_mu = (y - mu)
            ng_ls = ((y - mu) ** 2 / sig2 - 1.0) / 2.0
            s_mu, s_ls = _stump_fit(X, ng_mu), _stump_fit(X, ng_ls)
            self.stumps.append((s_mu, s_ls))
            mu = mu + self.lr * _stump_predict(s_mu, X)
            ls = ls + self.lr * _stump_predict(s_ls, X)
        return {"rounds": self.rounds, "train_logscore": float(np.mean(self.logpdf(y, mu, np.exp(ls))))}

    @staticmethod
    def logpdf(y, mu, sigma):
        return -0.5 * np.log(2 * np.pi * sigma ** 2) - (y - mu) ** 2 / (2 * sigma ** 2)

    def predict_params(self, X: np.ndarray):
        mu = np.full(len(X), self.mu0); ls = np.full(len(X), self.ls0)
        for s_mu, s_ls in self.stumps:
            mu = mu + self.lr * _stump_predict(s_mu, X)
            ls = ls + self.lr * _stump_predict(s_ls, X)
        return mu, np.exp(ls)

    def _forecast(self, features: dict, *, cutoff_epoch, created_epoch, horizon_bars=15) -> ForecastObject:
        X = np.array([[features[f] for f in self.features]], dtype=float)
        mu, sig = self.predict_params(X)
        from scipy.stats import norm
        q = {str(t): float(norm.ppf(t, loc=mu[0], scale=sig[0])) for t in (0.05, 0.25, 0.5, 0.75, 0.95)}
        return ForecastObject(model_id=self.model_id, artifact_digest=self.serialize()["artifact_digest"], horizon_minutes=horizon_bars,
                              input_cutoff_epoch=cutoff_epoch, created_epoch=created_epoch, supplies=self.supplies,
                              mean=float(mu[0]), variance=float(sig[0] ** 2), quantiles=q,
                              density={"family": "GAUSSIAN", "location": float(mu[0]), "scale": float(sig[0]), "variance": float(sig[0] ** 2)},
                              meta={"scoring_rule": "log score", "gradient": "natural (Fisher-scaled)"})

    def _params(self):
        return {"rounds": self.rounds, "lr": self.lr, "features": list(self.features), "mu0": self.mu0, "ls0": self.ls0,
                "stumps": [[a, b] for a, b in self.stumps]}

    @classmethod
    def _from_params(cls, p):
        m = cls(rounds=p["rounds"], lr=p["lr"], features=tuple(p["features"]))
        m.mu0, m.ls0, m.stumps = p["mu0"], p["ls0"], [tuple(x) for x in p["stumps"]]
        return m
