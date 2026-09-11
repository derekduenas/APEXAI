"""Tournament infrastructure (M3): walk-forward folds with purge + embargo, the as-of data
firewall, scoring rules, calibration reports, common-row comparison and a trial registry with a
REGISTERED search budget.

Purge: a training label whose OUTCOME WINDOW [t, t + horizon] intrudes into the validation
interval is removed. Embargo: an additional declared gap after the validation interval's start
and before its end is excluded from training. Dependence inference is NOT transplanted from
EXP-004; the fold generator declares its parameters and the registry records them."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

from .contracts import ModelRefused, digest


class FirewallViolation(RuntimeError):
    pass


class DataFirewall:
    """Hands a model only rows available by the cutoff. Any access to later rows is a violation."""

    def __init__(self, rows: list):
        self.rows = sorted(rows, key=lambda r: r.get("available", r["event_time"]))
        self.accesses: list = []

    def train_view(self, cutoff_epoch: float) -> list:
        self.accesses.append(("train", cutoff_epoch))
        return [r for r in self.rows if r.get("available", r["event_time"]) <= cutoff_epoch]

    def assert_not_used(self, model_rows: list, cutoff_epoch: float) -> None:
        late = [r for r in model_rows if r.get("available", r["event_time"]) > cutoff_epoch]
        if late:
            raise FirewallViolation("%d rows after cutoff %.0f reached a model" % (len(late), cutoff_epoch))


def walk_forward_folds(rows: list, *, n_folds: int, horizon_s: float, embargo_s: float, min_train: int) -> list:
    """Chronological folds. Each fold: train rows with available <= val_start - embargo AND whose
    outcome window ends before val_start (purge); validation rows in [val_start, val_end)."""
    rs = sorted(rows, key=lambda r: r["event_time"])
    n = len(rs)
    if n < min_train + n_folds:
        raise ModelRefused("TOO_FEW_ROWS_FOR_FOLDS")
    edges = np.linspace(min_train, n, n_folds + 1).astype(int)
    folds = []
    for i in range(n_folds):
        val = rs[edges[i]:edges[i + 1]]
        if not val:
            continue
        val_start, val_end = val[0]["event_time"], val[-1]["event_time"]
        train = [r for r in rs if r.get("available", r["event_time"]) <= val_start - embargo_s
                 and r["event_time"] + horizon_s < val_start]
        purged = sum(1 for r in rs if r["event_time"] < val_start and not (r["event_time"] + horizon_s < val_start))
        folds.append({"fold": i, "train": train, "val": val, "val_start": val_start, "val_end": val_end,
                      "cutoff_epoch": val_start - embargo_s, "purged": purged, "embargo_s": embargo_s, "horizon_s": horizon_s})
    return folds


# ---------------------------------------------------------------- scoring

def log_score_normal(y, mu, var) -> float:
    return float(-0.5 * math.log(2 * math.pi * var) - (y - mu) ** 2 / (2 * var))


def log_score_t(y, loc, scale, nu) -> float:
    return float(stats.t.logpdf(y, nu, loc=loc, scale=scale))


def crps_normal(y, mu, sigma) -> float:
    z = (y - mu) / sigma
    return float(sigma * (z * (2 * stats.norm.cdf(z) - 1) + 2 * stats.norm.pdf(z) - 1 / math.sqrt(math.pi)))


def pinball(y, q, tau) -> float:
    d = y - q
    return float(max(tau * d, (tau - 1) * d))


def pit_normal(y, mu, sigma) -> float:
    return float(stats.norm.cdf(y, loc=mu, scale=sigma))


def pit_t(y, loc, scale, nu) -> float:
    return float(stats.t.cdf(y, nu, loc=loc, scale=scale))


def calibration_report(pits: list, *, bins: int = 10) -> dict:
    p = np.array(pits, dtype=float)
    if len(p) == 0:
        return {"n": 0}
    hist, _ = np.histogram(p, bins=bins, range=(0, 1))
    ks = stats.kstest(p, "uniform")
    return {"n": int(len(p)), "histogram": hist.tolist(), "expected_per_bin": len(p) / bins, "ks_stat": float(ks.statistic),
            "ks_pvalue": float(ks.pvalue), "mean_pit": float(np.mean(p)),
            "note": "PIT uniformity is necessary, not sufficient, for calibration; independence is not assumed here"}


def common_rows(a: dict, b: dict) -> list:
    """Row ids scored by BOTH systems; coverage difference is reported, never hidden."""
    return sorted(set(a) & set(b))


def paired_comparison(scores_a: dict, scores_b: dict) -> dict:
    ids = common_rows(scores_a, scores_b)
    d = np.array([scores_a[i] - scores_b[i] for i in ids], dtype=float)
    out = {"n_common": len(ids), "coverage_a": len(scores_a), "coverage_b": len(scores_b),
           "coverage_difference": len(scores_a) - len(scores_b), "mean_diff": float(np.mean(d)) if len(d) else None,
           "sd_diff": float(np.std(d, ddof=1)) if len(d) > 1 else None,
           "dependence_note": "differences may be serially dependent; the inference method must be chosen for the new estimand and declared"}
    return out


# ---------------------------------------------------------------- trial registry

class TrialRegistry:
    """Every planned comparison, including failures, is recorded. A finite search budget is registered
    BEFORE trials run; exceeding it refuses."""

    def __init__(self, *, budget: int, study_id: str):
        if type(budget) is not int or budget <= 0:
            raise ModelRefused("BUDGET_INVALID")
        self.budget, self.study_id = budget, study_id
        self.trials: list = []

    def register(self, *, family: str, features, transform: str, window: str, hyperparameters: dict, seed: int,
                 policy_thresholds: dict | None = None, ensemble_weights: dict | None = None) -> dict:
        if len(self.trials) >= self.budget:
            raise ModelRefused("SEARCH_BUDGET_EXHAUSTED: %d trials registered" % self.budget)
        t = {"trial": len(self.trials) + 1, "study_id": self.study_id, "family": family, "features": list(features), "transform": transform,
             "window": window, "hyperparameters": hyperparameters, "seed": seed, "policy_thresholds": policy_thresholds or {},
             "ensemble_weights": ensemble_weights or {}, "status": "REGISTERED", "result": None}
        t["trial_digest"] = digest({k: t[k] for k in ("family", "features", "transform", "window", "hyperparameters", "seed")})
        self.trials.append(t)
        return t

    def record(self, trial: int, *, status: str, result: dict | None) -> None:
        t = self.trials[trial - 1]
        if t["status"] != "REGISTERED":
            raise ModelRefused("TRIAL_ALREADY_RECORDED: %d" % trial)
        t["status"], t["result"] = status, result

    def summary(self) -> dict:
        return {"study_id": self.study_id, "budget": self.budget, "registered": len(self.trials),
                "by_status": {s: sum(1 for t in self.trials if t["status"] == s) for s in {t["status"] for t in self.trials}},
                "trials": self.trials, "note": "the full trial history (including failures) is retained; selection among trials is disclosed"}
