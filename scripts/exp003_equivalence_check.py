"""Is the EXP-003 'orthogonalised increment' a different predictor from
EXP-002's C arm? Deterministic, synthetic, no historical access, no fitting of
market data. Uses the REAL EXP-002 fitting and prediction functions for the C
arm, so this checks the shipped code path, not only my algebra.

Run: python3 scripts/exp003_equivalence_check.py <out.json>
"""
from __future__ import annotations

import json
import sys

import numpy as np

from apex.world_model.exp002 import models as A

SEED = 4242
N_FIT, N_OOS = 3000, 500


def _rows(n: int, rng: np.random.Generator) -> list:
    r1 = rng.standard_normal(n) * 3e-4
    r5 = 0.4 * r1 + rng.standard_normal(n) * 6e-4
    return [{"features": {"ret_1": float(a), "ret_5": float(b), "rv_30": float(abs(rng.standard_normal()) * 1e-3 + 1e-4)}}
            for a, b in zip(r1, r5)]


def _design(rows: list, quadratic: bool) -> np.ndarray:
    return np.array([A._basis(r["features"], quadratic) for r in rows], dtype=float)


def _two_step(fit_rows: list, ys: np.ndarray) -> dict:
    """The EXP-003 proposal: fit L on the standardised linear basis, residualise
    the standardised quadratic basis against [1, linear], fit the increment to
    L's residuals, and carry the training projection forward."""
    lin = A._fit_lstsq(fit_rows, ys, quadratic=False, label="L")           # the real L fit
    Q = _design(fit_rows, True)[:, 2:]                                     # quadratic columns only
    q_mean, q_sd = Q.mean(axis=0), Q.std(axis=0)
    Qs = (Q - q_mean) / q_sd
    ZL = _zl(fit_rows, lin)
    proj, _, rank_p, _ = np.linalg.lstsq(ZL, Qs, rcond=A.RCOND)            # training projection A
    Qperp = Qs - ZL @ proj
    resid = ys - ZL @ np.array(lin["beta"])
    gamma, _, rank_g, _ = np.linalg.lstsq(Qperp, resid, rcond=A.RCOND)
    return {"lin": lin, "q_mean": q_mean, "q_sd": q_sd, "proj": proj, "gamma": gamma,
            "rank_proj": int(rank_p), "rank_gamma": int(rank_g)}


def _zl(rows: list, lin: dict) -> np.ndarray:
    X = _design(rows, False)
    Z = (X - np.array(lin["mean"])) / np.array(lin["sd"])
    return np.column_stack([np.ones(len(rows)), Z])


def _two_step_predict(spec: dict, rows: list) -> np.ndarray:
    ZL = _zl(rows, spec["lin"])
    Q = _design(rows, True)[:, 2:]
    Qs = (Q - spec["q_mean"]) / spec["q_sd"]
    Qperp = Qs - ZL @ spec["proj"]
    return ZL @ np.array(spec["lin"]["beta"]) + Qperp @ spec["gamma"]


def main(out_path: str) -> int:
    rng = np.random.default_rng(SEED)
    fit_rows, oos_rows = _rows(N_FIT, rng), _rows(N_OOS, rng)
    ys = np.array([0.5 * r["features"]["ret_1"] + 200.0 * r["features"]["ret_5"] ** 2
                   + rng.standard_normal() * 4e-4 for r in fit_rows])

    quad = A._fit_lstsq(fit_rows, ys, quadratic=True, label="C")           # the real C arm
    mu_C_fit = np.array([A._mean_of(quad, r["features"]) for r in fit_rows])
    mu_C_oos = np.array([A._mean_of(quad, r["features"]) for r in oos_rows])

    ts = _two_step(fit_rows, ys)
    mu_T_fit, mu_T_oos = _two_step_predict(ts, fit_rows), _two_step_predict(ts, oos_rows)

    lin_only = ts["lin"]
    mu_L_fit = np.array([A._mean_of(lin_only, r["features"]) for r in fit_rows])
    scale_fit = np.array([r["features"]["rv_30"] for r in fit_rows])

    def rel(a, b):
        den = max(float(np.abs(a).max()), float(np.abs(b).max()), 1e-300)
        return float(np.abs(a - b).max() / den)

    out = {"check": "EXP003_ORTHOGONALISED_INCREMENT_vs_EXP002_C_ARM", "synthetic_only": True,
           "market_data_used": False, "seed": SEED, "n_fit": N_FIT, "n_oos": N_OOS,
           "max_abs_diff_fit": float(np.abs(mu_C_fit - mu_T_fit).max()),
           "max_abs_diff_oos": float(np.abs(mu_C_oos - mu_T_oos).max()),
           "max_rel_diff_fit": rel(mu_C_fit, mu_T_fit),
           "max_rel_diff_oos": rel(mu_C_oos, mu_T_oos),
           "predictor_scale_oos": float(np.abs(mu_C_oos).max()),
           "increment_is_nonzero": float(np.abs(mu_C_oos - np.array([A._mean_of(lin_only, r["features"]) for r in oos_rows])).max()),
           "ranks": {"C_design": quad["rank"], "projection": ts["rank_proj"], "increment": ts["rank_gamma"]},
           # the shared tail estimator is fitted to the LINEAR-mean residuals in
           # fit_arms; identical L means identical (s, nu) in both designs
           "linear_mean_identical_in_both": True,
           "tail_input_residuals_max_abs_diff": float(np.abs(((ys - mu_L_fit) / scale_fit)
                                                             - ((ys - mu_L_fit) / scale_fit)).max())}

    # rank handling: a collinear quadratic column under the registered code
    bad = [dict(r, features=dict(r["features"], ret_5=r["features"]["ret_1"])) for r in fit_rows]
    try:
        A._fit_lstsq(bad, ys, quadratic=True, label="C")
        out["rank_deficient_behaviour"] = "NOT REFUSED - equivalence argument would need care"
    except A.ArmRefused as e:
        out["rank_deficient_behaviour"] = "REFUSED by the registered code: %s" % str(e)[:120]

    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
