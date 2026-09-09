"""Synthetic control worlds, fully specified. Nothing here reads market data.

Rows are generated directly in the shape the tournament consumes, with the
session structure and the 15-minute overlap dependence built in explicitly."""
from __future__ import annotations

import math
import random

SIGMA_RET1, SIGMA_RET5 = 3e-4, 6.7e-4          # feature scales, so raw-feature models see realistic magnitudes
LOG_RV_MEAN, LOG_RV_SD, LOG_RV_PHI = math.log(3e-4), 0.3, 0.9
FEATURE_PHI = 0.3                                # AR(1) on each standardised feature, reset per session
OVERLAP = 15                                     # eps_t = mean of 15 consecutive iid shocks: MA(14) unit variance
ROWS_PER_SESSION = 330
GAUSSIAN_NU_ANCHOR = 4.0                         # W3 innovations

WORLDS = {
    "W1_LINEAR":        {"signal": "z1",    "r2": 0.0010, "seed": 1001, "noise": "gaussian",
                         "role": "WEAK-signal linear sensitivity DIAGNOSTIC (revision 1 declared it "
                                 "blocking; M1-M0 sat at the HAC threshold with an inference "
                                 "disagreement; parameters and seed unchanged)"},
    "W1S_LINEAR":       {"signal": "z1",    "r2": 0.0100, "seed": 1006, "noise": "gaussian",
                         "role": "BLOCKING: basic linear-detection check (added in revision 2, seed "
                                 "and specification frozen before execution)"},
    "W2_INTERACTION":   {"signal": "z1z5",  "r2": 0.0010, "seed": 1002, "noise": "gaussian",
                         "role": "WEAK-signal sensitivity DIAGNOSTIC, not a power estimate"},
    "W2S_INTERACTION":  {"signal": "z1z5",  "r2": 0.0100, "seed": 1005, "noise": "gaussian",
                         "role": "BLOCKING: the pipeline must detect the intended nonlinear mechanism"},
    "W3_HEAVY_TAIL":    {"signal": None,    "r2": 0.0,    "seed": 1003, "noise": "student_t_nu4",
                         "role": "shape can improve with no conditional-mean discovery"},
    "W4_NULL":          {"signal": None,    "r2": 0.0,    "seed": 1004, "noise": "gaussian",
                         "role": "no predictability anywhere"},
}

# Expected outcomes, declared before any run. Keys are (a, b) differentials.
EXPECTED = {
    "W1_LINEAR":       {("C", "L"): "NO_SIGNAL"},                      # M1-M0 and L-S here are diagnostics
    "W1S_LINEAR":      {("C", "L"): "NO_SIGNAL", ("M1", "M0"): "SIGNAL_DETECTED", ("L", "S"): "SIGNAL_DETECTED"},
    "W2_INTERACTION":  {("M1", "M0"): "NO_SIGNAL"},                    # C-L here is a diagnostic, not asserted
    "W2S_INTERACTION": {("C", "L"): "SIGNAL_DETECTED", ("M1", "M0"): "NO_SIGNAL"},
    "W3_HEAVY_TAIL":   {("C", "L"): "NO_SIGNAL", ("L", "S"): "NO_SIGNAL", ("M1", "M0"): "NO_SIGNAL"},
    "W4_NULL":         {("C", "L"): "NO_SIGNAL", ("L", "S"): "NO_SIGNAL", ("M1", "M0"): "NO_SIGNAL"},
}
BLOCKING = {"W1S_LINEAR": [("M1", "M0"), ("C", "L")],
            "W2S_INTERACTION": [("C", "L")],
            "W3_HEAVY_TAIL": [("C", "L")],
            "W4_NULL": [("C", "L"), ("L", "S"), ("M1", "M0")]}
DIAGNOSTIC_ONLY = {"W1_LINEAR": [("M1", "M0"), ("L", "S"), ("C", "L")],
                   "W2_INTERACTION": [("C", "L")]}


def beta_for_r2(r2: float) -> float:
    """y = rv*(beta*g + eps), Var(g)=1, Var(eps)=1 -> R2 = beta^2/(beta^2+1)."""
    return math.sqrt(r2 / (1.0 - r2)) if r2 > 0 else 0.0


def make_world(name: str, *, n_fit_sessions: int, n_dev_sessions: int,
               rows_per_session: int = ROWS_PER_SESSION) -> dict:
    spec = WORLDS[name]
    rng = random.Random(spec["seed"])
    beta = beta_for_r2(spec["r2"])
    t_sd = math.sqrt(GAUSSIAN_NU_ANCHOR / (GAUSSIAN_NU_ANCHOR - 2.0))

    def shock():
        if spec["noise"] == "gaussian":
            return rng.gauss(0.0, 1.0)
        # Student-t nu=4 by the ratio construction, scaled to unit variance
        g = rng.gauss(0.0, 1.0)
        chi2 = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(int(GAUSSIAN_NU_ANCHOR)))
        return (g / math.sqrt(chi2 / GAUSSIAN_NU_ANCHOR)) / t_sd

    def session(sess_index: int, base_t: float):
        z1 = z5 = 0.0
        lrv = LOG_RV_MEAN
        inn_sd = math.sqrt(1.0 - FEATURE_PHI ** 2)
        shocks = [shock() for _ in range(rows_per_session + OVERLAP)]
        out = []
        for i in range(rows_per_session):
            z1 = FEATURE_PHI * z1 + inn_sd * rng.gauss(0.0, 1.0)
            z5 = FEATURE_PHI * z5 + inn_sd * rng.gauss(0.0, 1.0)
            lrv = LOG_RV_PHI * lrv + (1 - LOG_RV_PHI) * LOG_RV_MEAN + LOG_RV_SD * math.sqrt(1 - LOG_RV_PHI ** 2) * rng.gauss(0.0, 1.0)
            rv = math.exp(lrv)
            eps = sum(shocks[i:i + OVERLAP]) / math.sqrt(OVERLAP)
            g = {"z1": z1, "z1z5": z1 * z5, None: 0.0}[spec["signal"]]
            y = rv * (beta * g + eps)
            t = base_t + 60.0 * i
            row = {"event_time": t, "i": i, "close": 400.0, "minute": i + 30,
                   "features": {"ret_1": SIGMA_RET1 * z1, "ret_5": SIGMA_RET5 * z5, "rv_30": rv},
                   "assumed_available": t + 60.0, "bar_complete": t + 60.0,
                   "session_id": "S%05d" % sess_index, "why": None}
            out.append((row, y, t + 60.0 * (OVERLAP + 1)))
        return out

    fit, dev = [], []
    base = 1_600_000_000.0
    for k in range(n_fit_sessions):
        fit.extend(session(k, base + k * 86400.0))
    for k in range(n_dev_sessions):
        dev.extend(session(n_fit_sessions + k, base + (n_fit_sessions + k) * 86400.0))
    return {"world": name, "spec": dict(spec), "beta": beta, "fit": fit, "dev": dev,
            "generator": {"features": "AR(1) phi=%.2f per session, N(0,1) marginal" % FEATURE_PHI,
                          "rv_30": "lognormal, AR(1) phi=%.2f on log, mean log %.4f sd %.2f" % (LOG_RV_PHI, LOG_RV_MEAN, LOG_RV_SD),
                          "noise": "%s; MA(%d) of iid shocks, unit variance, mimicking %d-minute overlap" % (spec["noise"], OVERLAP - 1, OVERLAP),
                          "signal": spec["signal"], "r2": spec["r2"], "beta": beta,
                          "orthogonality": "z1*z5 is uncorrelated with z1 and z5 by construction (independent, mean zero)",
                          "sessions": {"fit": n_fit_sessions, "dev": n_dev_sessions, "rows_each": rows_per_session}}}
