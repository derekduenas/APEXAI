"""EXP-002 N0 diagnostic: does the null control's NO_SIGNAL assertion for the
matched pair L-S follow from the transformation it performs?

PURELY SYNTHETIC. No market data, no admitted files, no fitting of any kind.
Every parameter is FIXED from the sealed run's record or declared here; nothing
is estimated. This tests the null's LOGICAL claim. It is not a candidate
replacement control and selects nothing.

Run:  python3 scripts/exp002_n0_diagnostic.py <out.json>
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

from apex.world_model import inference
from apex.world_model.exp002 import studentt as T
from apex.world_model.exp002.registration import N0
from apex.world_model.exp002.run import _block_permute            # the EXACT permutation used

# ---- fixed constants, taken from the sealed run; NOTHING is fitted here
NU = 6.384478029123821          # _RESULT.json fit.t.nu
S_STAR = 3.287952250006828      # _RESULT.json fit.t.s
BASE_K = 2.932453397662227      # _RESULT.json fit.base_k
BLOCK = N0["block"]
SEED = 20260909
N_ROWS = 100_000
RV0 = 1.0e-3                    # a fixed nominal rv_30 level; only its spread matters
TAUS = (0.0, 0.3, 0.6, 0.9)     # lognormal spread of rv_30 across rows
MEAN_INTERCEPT_FRAC = 0.02      # m_i = (c + b x_i); c, b as fractions of the mean scale
MEAN_SLOPE_FRAC = 0.05


def _psi(z: np.ndarray) -> np.ndarray:
    return (NU + 1.0) * z / (NU + z * z)


def _psi_prime(z: np.ndarray) -> np.ndarray:
    return (NU + 1.0) * (NU - z * z) / (NU + z * z) ** 2


def _t_logpdf(y: np.ndarray, mu: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Vectorised form of apex.world_model.exp002.studentt.logpdf (verified
    against it element-wise in this script)."""
    z = (y - mu) / scale
    return (math.lgamma((NU + 1.0) / 2.0) - math.lgamma(NU / 2.0) - 0.5 * math.log(NU * math.pi)
            - np.log(scale) - (NU + 1.0) / 2.0 * np.log1p(z * z / NU))


def _gauss_logpdf(y: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    z = (y - mu) / sigma
    return -0.5 * z * z - np.log(sigma) - 0.5 * math.log(2.0 * math.pi)


def _world(tau: float, rng: np.random.Generator) -> dict:
    rv = RV0 * np.exp(tau * rng.standard_normal(N_ROWS) - tau * tau / 2.0)
    scale = S_STAR * rv                     # the registered scale law, arm S/L/C
    sigma_g = BASE_K * rv                   # the registered Gaussian law, arms M0/M1
    sbar = float(scale.mean())
    x = rng.standard_normal(N_ROWS)
    m = MEAN_INTERCEPT_FRAC * sbar + MEAN_SLOPE_FRAC * sbar * x     # the "L" mean; "S" is 0
    # outcomes generated CORRECTLY coupled to their own row's scale
    tdraw = rng.standard_normal(N_ROWS) / np.sqrt(rng.chisquare(NU, N_ROWS) / NU)
    y = scale * tdraw
    return {"rv": rv, "scale": scale, "sigma_g": sigma_g, "m": m, "y": y}


def _stat(d: np.ndarray) -> dict:
    s = inference.dm_hac_statistic(d.tolist())
    s["verdict"] = "SIGNAL_DETECTED" if (s["mean"] > 0 and s["t"] > 2.0) else "NO_SIGNAL"
    return {k: s[k] for k in ("mean", "t", "verdict")}


def main(out_path: str) -> int:
    rng = np.random.default_rng(SEED)
    rows = []
    for tau in TAUS:
        w = _world(tau, rng)
        yp = np.array(_block_permute(w["y"].tolist(), SEED, BLOCK))   # the real N0 transform
        rec = {"tau": tau}
        for label, perm, ys in (("intact", False, w["y"]), ("permuted", True, yp)):
            z = ys / w["scale"]
            d_t = _t_logpdf(ys, w["m"], w["scale"]) - _t_logpdf(ys, np.zeros(N_ROWS), w["scale"])
            d_g = _gauss_logpdf(ys, w["m"], w["sigma_g"]) - _gauss_logpdf(ys, np.zeros(N_ROWS), w["sigma_g"])
            rec[label] = {
                "L_minus_S_student_t": _stat(d_t),
                "M1_minus_M0_gaussian_analogue": _stat(d_g),
                "frac_abs_z_gt_sqrt_nu": float(np.mean(np.abs(z) > math.sqrt(NU))),
                "mean_psi_prime": float(_psi_prime(z).mean()),
                "mean_psi": float(_psi(z).mean()),
            }
        rows.append(rec)
    # element-wise agreement with the shipped scalar logpdf, on a small sample
    w = _world(0.6, np.random.default_rng(7))
    idx = list(range(0, N_ROWS, N_ROWS // 50))
    max_abs = max(abs(T.logpdf(float(w["y"][i]), float(w["m"][i]), float(w["scale"][i]), NU)
                      - float(_t_logpdf(w["y"][i:i + 1], w["m"][i:i + 1], w["scale"][i:i + 1])[0]))
                  for i in idx)
    out = {"diagnostic": "EXP002_N0_LOGICAL_CLAIM", "synthetic_only": True, "market_data_used": False,
           "fitting_performed": "NONE", "nu": NU, "s_star": S_STAR, "base_k": BASE_K,
           "block": BLOCK, "seed": SEED, "n_rows": N_ROWS, "taus": list(TAUS),
           "sqrt_nu": math.sqrt(NU), "logpdf_agreement_max_abs_diff": max_abs,
           "worlds": rows}
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(json.dumps({"taus": [r["tau"] for r in rows],
                      "permuted_L_minus_S_t": [r["permuted"]["L_minus_S_student_t"]["t"] for r in rows],
                      "permuted_gaussian_t": [r["permuted"]["M1_minus_M0_gaussian_analogue"]["t"] for r in rows],
                      "frac_tail": [r["permuted"]["frac_abs_z_gt_sqrt_nu"] for r in rows],
                      "mean_psi_prime": [r["permuted"]["mean_psi_prime"] for r in rows]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
