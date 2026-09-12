"""EXP-004 location arms (R4): intercept + fit-split standardised basis, OLS
via SVD lstsq (rcond 1e-12), every arm re-estimates all of its coefficients.
Rank deficiency and zero-variance columns are refused, never repaired."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from .registration import ARMS

RCOND = 1e-12
# feature keys per arm; the product column is formed from the CLIPPED ingredients
COLUMNS = {
    "L":  ("ret_1", "ret_5"),
    "A":  ("ret_1", "ret_5", "Bbar_c", "P_c"),
    "AX": ("ret_1", "ret_5", "Bbar_c", "P_c", "BP_c"),
    "C":  ("ret_1", "ret_5", "Bbar_c", "P_c", "BP_c", "F_c"),
}
assert tuple(COLUMNS) == ARMS


class ArmRefused(ValueError):
    """An arm could not be fitted under the declared rules."""


def _col(f: dict, name: str) -> float:
    if name == "BP_c":
        return f["Bbar_c"] * f["P_c"]
    return f[name]


def design(rows: list, arm: str) -> np.ndarray:
    return np.array([[_col(r["features"], c) for c in COLUMNS[arm]] for r in rows], dtype=float)


def fit_arm(rows_y: list, arm: str) -> dict:
    rows = [r for r, _, _ in rows_y]
    ys = np.array([y for _, y, _ in rows_y], dtype=float)
    X = design(rows, arm)
    mean, sd = X.mean(axis=0), X.std(axis=0)
    # a constant column must be caught EXACTLY: np.std of identical values can be ~1e-17, not 0
    span = X.max(axis=0) - X.min(axis=0)
    bad = [c for c, s, sp in zip(COLUMNS[arm], sd, span) if not (s > 0) or not np.isfinite(s) or sp == 0]
    if bad:
        raise ArmRefused("ZERO_VARIANCE_FEATURE: %s in arm %s has no fit-split variance" % (bad, arm))
    Z = np.column_stack([np.ones(len(rows)), (X - mean) / sd])
    beta, _, rank, _ = np.linalg.lstsq(Z, ys, rcond=RCOND)
    if rank < Z.shape[1]:
        raise ArmRefused("RANK_DEFICIENT: arm %s design rank %d < %d at rcond=%g" % (arm, rank, Z.shape[1], RCOND))
    if not np.all(np.isfinite(beta)):
        raise ArmRefused("NONFINITE_COEFFICIENTS: arm %s" % arm)
    return {"arm": arm, "columns": list(COLUMNS[arm]), "beta": beta.tolist(), "mean": mean.tolist(),
            "sd": sd.tolist(), "rank": int(rank), "n": int(len(rows)), "solver": "numpy.linalg.lstsq(SVD)",
            "rcond": RCOND}


def mean_of(spec: dict, f: dict) -> float:
    x = np.array([_col(f, c) for c in spec["columns"]], dtype=float)
    z = (x - np.array(spec["mean"])) / np.array(spec["sd"])
    b = np.array(spec["beta"])
    return float(b[0] + z @ b[1:])


def means_of(spec: dict, rows: list) -> np.ndarray:
    X = design(rows, spec["arm"])
    Z = (X - np.array(spec["mean"])) / np.array(spec["sd"])
    b = np.array(spec["beta"])
    return b[0] + Z @ b[1:]


def fit_all(rows_y: list) -> dict:
    """Exactly four location fits on the identical row population."""
    specs = {arm: fit_arm(rows_y, arm) for arm in ARMS}
    body = json.dumps(specs, sort_keys=True, default=float).encode()
    return {"specs": specs, "fits_performed": len(ARMS), "n_train": len(rows_y),
            "params_hash": hashlib.sha256(body).hexdigest()[:16]}
