"""Bounded quantile gradient boosting on decision stumps (M3).

One boosted ensemble per quantile level, pinball-loss gradients, depth-1 trees
(stumps) on a bounded number of rounds. Quantiles are NOT automatically a
joint distribution: `enforce_order` applies the predeclared method
(rearrangement: sort the quantile vector) and the crossing rate is measured
BEFORE correction and reported. No path model is implied."""
from __future__ import annotations

import numpy as np

from .contracts import ForecastObject, Model, ModelRefused

ORDERING_METHOD = "REARRANGEMENT_SORT: sort predicted quantiles per row; crossing rate measured before sorting"


def _stump_fit(X: np.ndarray, g: np.ndarray, *, n_thresholds: int = 16) -> dict:
    """Best single split minimizing squared error to the negative gradient g."""
    best = {"feature": None, "threshold": None, "left": float(np.mean(g)), "right": float(np.mean(g)), "sse": float(np.sum((g - np.mean(g)) ** 2))}
    for j in range(X.shape[1]):
        col = X[:, j]
        for thr in np.quantile(col, np.linspace(0.05, 0.95, n_thresholds)):
            m = col <= thr
            if m.sum() < 5 or (~m).sum() < 5:
                continue
            l, r = float(np.mean(g[m])), float(np.mean(g[~m]))
            sse = float(np.sum((g[m] - l) ** 2) + np.sum((g[~m] - r) ** 2))
            if sse < best["sse"]:
                best = {"feature": int(j), "threshold": float(thr), "left": l, "right": r, "sse": sse}
    return best


def _stump_predict(stump: dict, X: np.ndarray) -> np.ndarray:
    if stump["feature"] is None:
        return np.full(len(X), stump["left"])
    return np.where(X[:, stump["feature"]] <= stump["threshold"], stump["left"], stump["right"])


class QuantileBoost(Model):
    model_id = "QUANTILE_STUMP_BOOST"
    supplies = ("quantiles",)
    fit_budget = 1

    def __init__(self, *, taus=(0.05, 0.25, 0.5, 0.75, 0.95), rounds: int = 60, lr: float = 0.1, features=("ret_1", "ret_5", "rv_30")):
        super().__init__()
        self.taus, self.rounds, self.lr, self.features = tuple(taus), rounds, lr, tuple(features)
        self.ens: dict = {}
        self.base: dict = {}

    def _X(self, rows):
        X = np.array([[r["features"][f] for f in self.features] for r in rows], dtype=float)
        if not np.all(np.isfinite(X)):
            raise ModelRefused("NONFINITE_FEATURES")
        return X

    def _fit(self, rows):
        X = self._X(rows); y = np.array([r["y"] for r in rows], dtype=float)
        if len(y) < 50:
            raise ModelRefused("TOO_FEW_ROWS")
        for tau in self.taus:
            pred = np.full(len(y), float(np.quantile(y, tau)))
            self.base[tau] = float(pred[0]); stumps = []
            for _ in range(self.rounds):
                g = np.where(y > pred, tau, tau - 1.0)             # negative pinball gradient selects the split...
                st = _stump_fit(X, g)
                resid = y - pred                                   # ...leaf values are the tau-quantile of residuals
                if st["feature"] is None:                          # (scale-aware, as in reference implementations)
                    st["left"] = st["right"] = float(np.quantile(resid, tau))
                else:
                    m = X[:, st["feature"]] <= st["threshold"]
                    st["left"], st["right"] = float(np.quantile(resid[m], tau)), float(np.quantile(resid[~m], tau))
                stumps.append(st)
                pred = pred + self.lr * _stump_predict(st, X)
            self.ens[tau] = stumps
        return {"rounds": self.rounds, "taus": list(self.taus)}

    def predict_raw(self, X: np.ndarray) -> np.ndarray:
        out = np.empty((len(X), len(self.taus)))
        for i, tau in enumerate(self.taus):
            p = np.full(len(X), self.base[tau])
            for st in self.ens[tau]:
                p = p + self.lr * _stump_predict(st, X)
            out[:, i] = p
        return out

    @staticmethod
    def crossing_rate(Q: np.ndarray) -> float:
        return float(np.mean(np.any(np.diff(Q, axis=1) < 0, axis=1))) if len(Q) else 0.0

    @staticmethod
    def enforce_order(Q: np.ndarray) -> np.ndarray:
        return np.sort(Q, axis=1)

    def _forecast(self, features: dict, *, cutoff_epoch, created_epoch, horizon_bars=15) -> ForecastObject:
        X = np.array([[features[f] for f in self.features]], dtype=float)
        raw = self.predict_raw(X)
        crossed = self.crossing_rate(raw)
        q = self.enforce_order(raw)[0]
        return ForecastObject(model_id=self.model_id, artifact_digest=self.serialize()["artifact_digest"], horizon_minutes=horizon_bars,
                              input_cutoff_epoch=cutoff_epoch, created_epoch=created_epoch, supplies=self.supplies,
                              quantiles={str(t): float(v) for t, v in zip(self.taus, q)},
                              meta={"crossing_before_correction": crossed, "ordering_method": ORDERING_METHOD,
                                    "joint_path_model": False, "note": "quantiles are marginal; not a path distribution"})

    def _params(self):
        return {"taus": list(self.taus), "rounds": self.rounds, "lr": self.lr, "features": list(self.features),
                "base": {str(k): v for k, v in self.base.items()}, "ens": {str(k): v for k, v in self.ens.items()}}

    @classmethod
    def _from_params(cls, p):
        m = cls(taus=tuple(p["taus"]), rounds=p["rounds"], lr=p["lr"], features=tuple(p["features"]))
        m.base = {float(k): v for k, v in p["base"].items()}; m.ens = {float(k): v for k, v in p["ens"].items()}
        return m
