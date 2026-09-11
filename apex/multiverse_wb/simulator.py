"""Transparent conditional joint simulator (M4).

State at the cutoff: S0, the fitted variance model (GARCH/GJR-t or a flat variance), an optional
regime probability vector with per-state variance multipliers, an IV state (declared process), and an
execution-condition state (declared spread process). Output: N joint paths over H one-minute steps of
    S_t        underlying (log-return recursion with the model's innovations)
    h_t        conditional variance path
    IV_t       implied-volatility state under the DECLARED process (IV_FIXED | IV_STRESS_MULT | IV_DRIFT)
    spread_t   execution spread (bps) under the DECLARED process (SPREAD_FIXED | SPREAD_STRESS_MULT)
Every output names its restriction (e.g. "IV held fixed"). Seeds, cutoff, parameter hashes and the
discretization are preserved. Sampling error (Monte Carlo standard errors) is reported separately
from model uncertainty (fit / regime). Unweighted STRESS branches are returned in a separate list with
no probability. Jumps are not included: no estimator for their occurrence/size is declared."""
from __future__ import annotations

import math

import numpy as np

from apex.worldmodel_wb.contracts import digest
from apex.worldmodel_wb.vol_models import std_t_rvs

IV_PROCESSES = ("IV_FIXED", "IV_STRESS_MULT", "IV_DRIFT")
SPREAD_PROCESSES = ("SPREAD_FIXED", "SPREAD_STRESS_MULT")


class SimulatorRefused(ValueError):
    pass


class ConditionalSimulator:
    def __init__(self, *, S0: float, variance_model: dict, nu: float | None, iv0: float, spread_bps0: float,
                 iv_process: str = "IV_FIXED", iv_param: float = 1.0, spread_process: str = "SPREAD_FIXED", spread_param: float = 1.0,
                 regime: dict | None = None, cutoff_epoch: float = 0.0):
        """variance_model: {"kind": "GARCH", "omega","alpha","beta","gamma","h_last","e_last"} or {"kind": "FLAT", "h": var}.
        regime: {"probabilities": [p0, p1], "variance_multipliers": [m0, m1]} (mixture over states, sampled per path)."""
        if not (S0 > 0 and iv0 > 0 and spread_bps0 >= 0):
            raise SimulatorRefused("STATE_INVALID")
        if iv_process not in IV_PROCESSES or spread_process not in SPREAD_PROCESSES:
            raise SimulatorRefused("PROCESS_UNKNOWN")
        if variance_model.get("kind") not in ("GARCH", "FLAT"):
            raise SimulatorRefused("VARIANCE_MODEL_UNKNOWN")
        if nu is not None and nu <= 2:
            raise SimulatorRefused("NU_INVALID")
        self.S0, self.vm, self.nu, self.iv0, self.spread0 = S0, variance_model, nu, iv0, spread_bps0
        self.iv_process, self.iv_param, self.spread_process, self.spread_param = iv_process, iv_param, spread_process, spread_param
        self.regime = regime
        self.cutoff_epoch = cutoff_epoch
        if regime:
            p = np.array(regime["probabilities"], dtype=float)
            if abs(p.sum() - 1) > 1e-9 or np.any(p < 0):
                raise SimulatorRefused("REGIME_PROBABILITIES_INVALID")

    def describe(self) -> dict:
        return {"S0": self.S0, "variance_model": self.vm, "nu": self.nu, "iv0": self.iv0, "spread_bps0": self.spread0,
                "iv_process": self.iv_process, "iv_param": self.iv_param, "spread_process": self.spread_process, "spread_param": self.spread_param,
                "regime": self.regime, "cutoff_epoch": self.cutoff_epoch, "discretization": "1-minute steps, log-return recursion",
                "jumps": "NOT_INCLUDED (no declared estimator)", "parameter_hash": digest({"vm": self.vm, "nu": self.nu, "iv": [self.iv_process, self.iv_param],
                                                                                        "spread": [self.spread_process, self.spread_param], "regime": self.regime}),
                "restrictions": self.restrictions()}

    def restrictions(self) -> list:
        r = []
        if self.iv_process == "IV_FIXED":
            r.append("IV held fixed over the horizon: option repricing reflects underlying moves and time decay only")
        if self.spread_process == "SPREAD_FIXED":
            r.append("execution spread held fixed")
        if self.vm["kind"] == "FLAT":
            r.append("constant conditional variance")
        if not self.regime:
            r.append("no regime mixture")
        r.append("no jumps")
        return r

    def simulate(self, *, horizon_bars: int, n_paths: int, seed: int) -> dict:
        rng = np.random.default_rng(seed)
        vm = self.vm
        if vm["kind"] == "FLAT":
            H = np.full(n_paths, float(vm["h"]))
        else:
            H = np.full(n_paths, vm["omega"] + (vm["alpha"] + (vm["gamma"] if vm["e_last"] < 0 else 0.0)) * vm["e_last"] ** 2 + vm["beta"] * vm["h_last"])
        mult = np.ones(n_paths)
        state = None
        if self.regime:
            state = rng.choice(len(self.regime["probabilities"]), size=n_paths, p=self.regime["probabilities"])
            mult = np.array(self.regime["variance_multipliers"], dtype=float)[state]
        logS = np.zeros((n_paths, horizon_bars + 1)); hpath = np.zeros((n_paths, horizon_bars + 1)); hpath[:, 0] = H * mult
        for t in range(1, horizon_bars + 1):
            Z = std_t_rvs(rng, self.nu, n_paths) if self.nu else rng.standard_normal(n_paths)
            E = np.sqrt(H * mult) * Z
            logS[:, t] = logS[:, t - 1] + E
            if vm["kind"] == "GARCH":
                H = vm["omega"] + (vm["alpha"] + vm["gamma"] * (E < 0)) * E * E + vm["beta"] * H
            hpath[:, t] = H * mult
        S = self.S0 * np.exp(logS)
        tgrid = np.arange(horizon_bars + 1) / horizon_bars
        if self.iv_process == "IV_FIXED":
            IV = np.full((n_paths, horizon_bars + 1), self.iv0)
        elif self.iv_process == "IV_STRESS_MULT":
            IV = self.iv0 * (1 + (self.iv_param - 1) * tgrid)[None, :].repeat(n_paths, 0)
        else:
            IV = self.iv0 * np.exp(self.iv_param * tgrid)[None, :].repeat(n_paths, 0)
        spread = np.full((n_paths, horizon_bars + 1), self.spread0) * (self.spread_param if self.spread_process == "SPREAD_STRESS_MULT" else 1.0)
        R = logS[:, -1]
        out = {"S": S, "h": hpath, "iv": IV, "spread_bps": spread, "state": state, "seed": seed, "n_paths": n_paths, "horizon_bars": horizon_bars,
               "cutoff_epoch": self.cutoff_epoch, "parameter_hash": self.describe()["parameter_hash"], "restrictions": self.restrictions(),
               "moments": {"mean_log_return": float(R.mean()), "var_log_return": float(R.var()),
                           "kurtosis_excess": float(((R - R.mean()) ** 4).mean() / R.var() ** 2 - 3.0) if R.var() > 0 else None},
               "sampling_error": {"se_mean": float(R.std() / math.sqrt(n_paths)), "se_var": float(np.std((R - R.mean()) ** 2) / math.sqrt(n_paths)),
                                  "note": "Monte Carlo error under the FIXED model; more draws shrink this and nothing else"},
               "model_uncertainty": {"fit": "NOT_PROPAGATED (parameters held at point estimates)",
                                     "regime": ("mixture over %d states sampled per path" % len(self.regime["probabilities"])) if self.regime else "NONE"}}
        return out

    @staticmethod
    def stress_branches(base: dict, *, iv_mults=(0.8, 1.2, 1.5), spread_mults=(1.0, 2.0, 4.0)) -> list:
        """UNWEIGHTED stresses: no probability is attached or implied."""
        out = []
        for im in iv_mults:
            for sm in spread_mults:
                out.append({"label": "IV x%.2f, spread x%.1f" % (im, sm), "iv": base["iv"] * im, "spread_bps": base["spread_bps"] * sm,
                            "probability": None, "kind": "UNWEIGHTED_STRESS", "S": base["S"]})
        return out


def analytic_gaussian_check(*, h: float, horizon_bars: int) -> dict:
    """Special case: constant variance, Gaussian innovations -> the H-step log return is N(0, H h)."""
    return {"var": h * horizon_bars, "sd": math.sqrt(h * horizon_bars), "excess_kurtosis": 0.0}
