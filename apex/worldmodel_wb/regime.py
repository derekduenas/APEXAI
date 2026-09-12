"""Two-state Gaussian Markov-switching estimator with CAUSAL filtering (M3).

    y_t | R_t = k  ~  N(mu_k, sigma_k^2),   P(R_t = j | R_{t-1} = i) = A[i, j]
Parameters are estimated by EM on the TRAINING rows only (before the cutoff).
For decisions the adapter exposes P(R_t = k | F_t) (FILTERED, Hamilton
recursion over the causal prefix), never smoothed probabilities. `smoothed()`
exists for diagnostics and is labelled as such. Every output carries the
probability vector, its entropy, the parameter version (digest), the update
cutoff, support counts per state (from the training filter), the time since
the last declared transition, and an ABSTAIN flag when the state estimate is
unsupported (a state with fewer than `min_support` training observations, or
entropy above `max_entropy`)."""
from __future__ import annotations

import math

import numpy as np

from .contracts import Model, ModelRefused, digest


def _npdf(y, mu, sig):
    return np.exp(-0.5 * ((y - mu) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))


class MarkovSwitching2(Model):
    model_id = "MARKOV_SWITCHING_2_GAUSSIAN"
    supplies = ()
    fit_budget = 1

    def __init__(self, *, key: str = "ret_1", iters: int = 60, min_support: int = 30, max_entropy: float = 0.95):
        super().__init__()
        self.key, self.iters, self.min_support, self.max_entropy = key, iters, min_support, max_entropy
        self.p: dict = {}

    # ------------------------------------------------------------ filtering / smoothing
    def _filter_arrays(self, y: np.ndarray, mu, sig, A, pi0):
        n = len(y); f = np.empty((n, 2)); pred = np.empty((n, 2)); ll = 0.0
        prior = np.array(pi0, dtype=float)
        for t in range(n):
            pred[t] = prior
            lik = prior * np.array([_npdf(y[t], mu[k], sig[k]) for k in range(2)])
            s = lik.sum()
            if not (s > 0):
                raise ModelRefused("FILTER_UNDERFLOW at t=%d" % t)
            f[t] = lik / s; ll += math.log(s)
            prior = f[t] @ A
        return f, pred, ll

    def _fit(self, rows):
        y = np.array([r[self.key] for r in rows], dtype=float)
        if len(y) < 100 or not np.all(np.isfinite(y)):
            raise ModelRefused("BAD_INPUT")
        mu = [float(np.mean(y)) - float(np.std(y)) * 0.5, float(np.mean(y)) + float(np.std(y)) * 0.5]
        sig = [float(np.std(y)) * 0.7, float(np.std(y)) * 1.3]
        A = np.array([[0.95, 0.05], [0.05, 0.95]]); pi0 = np.array([0.5, 0.5])
        ll_prev = -math.inf
        for it in range(self.iters):
            f, pred, ll = self._filter_arrays(y, mu, sig, A, pi0)
            # backward (smoothing) for EM only — never exposed as a decision probability
            n = len(y); sm = np.empty((n, 2)); sm[-1] = f[-1]
            xi = np.zeros((2, 2))
            for t in range(n - 2, -1, -1):
                ratio = np.where(pred[t + 1] > 0, sm[t + 1] / pred[t + 1], 0.0)
                sm[t] = f[t] * (A @ ratio)
                xi += np.outer(f[t], ratio) * A
            w = sm
            for k in range(2):
                mu[k] = float(np.sum(w[:, k] * y) / np.sum(w[:, k]))
                sig[k] = float(math.sqrt(np.sum(w[:, k] * (y - mu[k]) ** 2) / np.sum(w[:, k])) + 1e-9)
            A = xi / xi.sum(axis=1, keepdims=True)
            pi0 = sm[0]
            if abs(ll - ll_prev) < 1e-8:
                break
            ll_prev = ll
        order = np.argsort(sig)                                     # state 0 = calm, 1 = stressed (by variance)
        mu = [mu[i] for i in order]; sig = [sig[i] for i in order]; A = A[np.ix_(order, order)]; pi0 = pi0[order]
        f, _, ll = self._filter_arrays(y, mu, sig, A, pi0)
        support = [int(np.sum(np.argmax(f, axis=1) == k)) for k in range(2)]
        self.p = {"mu": mu, "sigma": sig, "A": A.tolist(), "pi0": pi0.tolist(), "loglik": ll, "n": int(len(y)),
                  "support_train": support, "iterations": it + 1, "labels": ["CALM(low variance)", "STRESSED(high variance)"],
                  "label_note": "labels are interpretations to test, not observed truths"}
        return dict(self.p)

    def filtered(self, y_prefix: list, *, cutoff_epoch: float) -> dict:
        """P(R_t = k | y_1..y_t): uses ONLY the prefix handed in. Appending later observations to a
        longer prefix cannot change this value for the same t (tested)."""
        if not self.fitted:
            raise ModelRefused("NOT_FITTED")
        y = np.array(y_prefix, dtype=float)
        f, _, _ = self._filter_arrays(y, self.p["mu"], self.p["sigma"], np.array(self.p["A"]), np.array(self.p["pi0"]))
        prob = f[-1]
        ent = float(-np.sum(prob * np.log(np.clip(prob, 1e-300, 1.0))) / math.log(2))
        states = np.argmax(f, axis=1)
        last_change = 0
        for t in range(len(states) - 1, 0, -1):
            if states[t] != states[t - 1]:
                last_change = len(states) - t
                break
        unsupported = [k for k in range(2) if self.p["support_train"][k] < self.min_support]
        abstain = bool(unsupported) or ent > self.max_entropy
        return {"probabilities": prob.tolist(), "entropy_bits": ent, "argmax_state": int(np.argmax(prob)),
                "labels": self.p["labels"], "parameter_version": digest(self.p), "update_cutoff_epoch": cutoff_epoch,
                "n_observations_used": int(len(y)), "support_train": self.p["support_train"],
                "bars_since_last_transition": last_change, "weighting": "FILTERED (causal)",
                "abstain": abstain, "abstain_why": ("UNSUPPORTED_STATE: %s" % unsupported if unsupported else
                                                    "HIGH_ENTROPY: %.3f > %.2f" % (ent, self.max_entropy) if ent > self.max_entropy else None)}

    def smoothed(self, y: list) -> np.ndarray:
        """DIAGNOSTIC ONLY: uses the whole sample; never for decisions."""
        yy = np.array(y, dtype=float)
        f, pred, _ = self._filter_arrays(yy, self.p["mu"], self.p["sigma"], np.array(self.p["A"]), np.array(self.p["pi0"]))
        n = len(yy); sm = np.empty((n, 2)); sm[-1] = f[-1]; A = np.array(self.p["A"])
        for t in range(n - 2, -1, -1):
            ratio = np.where(pred[t + 1] > 0, sm[t + 1] / pred[t + 1], 0.0)
            sm[t] = f[t] * (A @ ratio)
        return sm

    def _forecast(self, *a, **k):
        raise ModelRefused("REGIME_MODEL_SUPPLIES_NO_FORECAST: use filtered() for state probabilities")

    def _params(self): return dict(self.p)

    @classmethod
    def _from_params(cls, p):
        m = cls(); m.p = dict(p); return m
