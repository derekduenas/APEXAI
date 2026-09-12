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

from scipy import integrate, stats

from apex.worldmodel_wb.contracts import digest

IV_PROCESSES = ("IV_FIXED", "IV_STRESS_MULT", "IV_DRIFT")
SPREAD_PROCESSES = ("SPREAD_FIXED", "SPREAD_STRESS_MULT")
INNOVATIONS = ("GAUSSIAN", "TRUNCATED_T")
DEFAULT_TAIL_CAP_SD = 8.0
_TRUNC_CACHE: dict = {}


def truncated_t_scale(nu: float, cap_sd: float) -> dict:
    """Standardized Student-t (unit variance) truncated at +/- cap_sd, then renormalized to unit variance.
    Returns the renormalization factor and the truncated tail mass. Cached per (nu, cap)."""
    key = (round(float(nu), 9), round(float(cap_sd), 9))
    if key in _TRUNC_CACHE:
        return _TRUNC_CACHE[key]
    s = math.sqrt(nu / (nu - 2.0))                                    # raw t has variance nu/(nu-2); standardized z = t / s
    c_raw = cap_sd * s                                                # cap in raw-t units
    mass_inside = stats.t.cdf(c_raw, nu) - stats.t.cdf(-c_raw, nu)
    second, _ = integrate.quad(lambda x: x * x * stats.t.pdf(x, nu), -c_raw, c_raw, limit=200)
    var_std_trunc = (second / mass_inside) / (s * s)                  # variance of the standardized, truncated variable
    out = {"renormalization": 1.0 / math.sqrt(var_std_trunc), "truncated_mass": 1.0 - mass_inside, "cap_raw": c_raw, "variance_before_renorm": var_std_trunc}
    _TRUNC_CACHE[key] = out
    return out


def draw_innovations(rng: np.random.Generator, *, nu, n: int, innovations: str, tail_cap_sd: float) -> np.ndarray:
    """Unit-variance innovations with FINITE exponential moments: GAUSSIAN, or TRUNCATED_T (standardized t with |z| <= cap,
    renormalized). An untruncated Student-t has polynomial tails, so E[exp(sigma Z)] diverges for every sigma > 0 and
    option payoffs priced on exp(returns) have no finite expectation: the truncation is an explicit model choice."""
    if innovations == "GAUSSIAN" or nu is None:
        return rng.standard_normal(n)
    tr = truncated_t_scale(nu, tail_cap_sd)
    s = math.sqrt(nu / (nu - 2.0))
    z = rng.standard_t(nu, size=n) / s
    bad = np.abs(z) > tail_cap_sd
    guard = 0
    while bad.any():
        z[bad] = rng.standard_t(nu, size=int(bad.sum())) / s
        bad = np.abs(z) > tail_cap_sd
        guard += 1
        if guard > 1000:
            raise SimulatorRefused("TRUNCATION_REJECTION_LOOP")
    return z * tr["renormalization"]


class SimulatorRefused(ValueError):
    pass


class ConditionalSimulator:
    def __init__(self, *, S0: float, variance_model: dict, nu: float | None, iv0: float, spread_bps0: float,
                 iv_process: str = "IV_FIXED", iv_param: float = 1.0, spread_process: str = "SPREAD_FIXED", spread_param: float = 1.0,
                 regime: dict | None = None, cutoff_epoch: float = 0.0, drift_per_bar: float = 0.0,
                 innovations: str | None = None, tail_cap_sd: float = DEFAULT_TAIL_CAP_SD):
        """variance_model: {"kind": "GARCH", "omega","alpha","beta","gamma","h_next"} or {"kind": "FLAT", "h": var}.
        ONE state convention: `h_next` (or FLAT `h`) IS the conditional variance of the FIRST simulated bar -- exactly the
        variance model's `next_bar_variance` forecast; the recurrence is applied only AFTER each simulated shock.
        regime: {"probabilities": [p0, p1], "variance_multipliers": [m0, m1]} (mixture over states, sampled per path).
        innovations: GAUSSIAN (nu ignored) or TRUNCATED_T (default when nu is given); see draw_innovations."""
        if not (S0 > 0 and iv0 > 0 and spread_bps0 >= 0):
            raise SimulatorRefused("STATE_INVALID")
        if iv_process not in IV_PROCESSES or spread_process not in SPREAD_PROCESSES:
            raise SimulatorRefused("PROCESS_UNKNOWN")
        if variance_model.get("kind") not in ("GARCH", "FLAT"):
            raise SimulatorRefused("VARIANCE_MODEL_UNKNOWN")
        if variance_model["kind"] == "GARCH" and ("h_next" not in variance_model or "h_last" in variance_model or "e_last" in variance_model):
            raise SimulatorRefused("VARIANCE_STATE_CONVENTION: GARCH state must be {omega, alpha, beta, gamma, h_next} (h_next = first-bar variance)")
        h0 = variance_model["h_next"] if variance_model["kind"] == "GARCH" else variance_model.get("h")
        if not isinstance(h0, (int, float)) or isinstance(h0, bool) or not math.isfinite(h0) or h0 <= 0:
            raise SimulatorRefused("VARIANCE_STATE_INVALID: %r" % (h0,))
        if nu is not None and nu <= 2:
            raise SimulatorRefused("NU_INVALID")
        innovations = innovations or ("TRUNCATED_T" if nu is not None else "GAUSSIAN")
        if innovations not in INNOVATIONS:
            raise SimulatorRefused("INNOVATIONS_UNKNOWN")
        if innovations == "TRUNCATED_T" and nu is None:
            raise SimulatorRefused("TRUNCATED_T_NEEDS_NU")
        if not isinstance(tail_cap_sd, (int, float)) or isinstance(tail_cap_sd, bool) or not (tail_cap_sd >= 3.0):
            raise SimulatorRefused("TAIL_CAP_INVALID: cap must be >= 3 sd")
        self.innovations, self.tail_cap_sd = innovations, float(tail_cap_sd)
        self.S0, self.vm, self.nu, self.iv0, self.spread0 = S0, variance_model, nu, iv0, spread_bps0
        self.iv_process, self.iv_param, self.spread_process, self.spread_param = iv_process, iv_param, spread_process, spread_param
        self.regime = regime
        self.cutoff_epoch = cutoff_epoch
        if isinstance(drift_per_bar, bool) or not isinstance(drift_per_bar, (int, float)) or not math.isfinite(drift_per_bar):
            raise SimulatorRefused("DRIFT_INVALID")
        self.drift_per_bar = float(drift_per_bar)
        if regime:
            p = np.array(regime["probabilities"], dtype=float)
            if abs(p.sum() - 1) > 1e-9 or np.any(p < 0):
                raise SimulatorRefused("REGIME_PROBABILITIES_INVALID")

    def describe(self) -> dict:
        inn = {"family": self.innovations, "nu": self.nu if self.innovations == "TRUNCATED_T" else None,
               "tail_cap_sd": self.tail_cap_sd if self.innovations == "TRUNCATED_T" else None,
               **({"truncated_mass": truncated_t_scale(self.nu, self.tail_cap_sd)["truncated_mass"],
                   "renormalization": truncated_t_scale(self.nu, self.tail_cap_sd)["renormalization"]} if self.innovations == "TRUNCATED_T" else {}),
               "finite_exponential_moments": True}
        return {"S0": self.S0, "variance_model": self.vm, "nu": self.nu, "innovations": inn, "iv0": self.iv0, "spread_bps0": self.spread0, "drift_per_bar": self.drift_per_bar,
                "iv_process": self.iv_process, "iv_param": self.iv_param, "spread_process": self.spread_process, "spread_param": self.spread_param,
                "regime": self.regime, "cutoff_epoch": self.cutoff_epoch, "discretization": "1-minute steps, log-return recursion",
                "state_convention": "h_next / h = conditional variance of the FIRST simulated bar (= next_bar_variance forecast); recurrence applied after each shock",
                "jumps": "NOT_INCLUDED (no declared estimator)", "parameter_hash": digest({"vm": self.vm, "nu": self.nu, "inn": [self.innovations, self.tail_cap_sd],
                                                                                        "iv": [self.iv_process, self.iv_param],
                                                                                        "spread": [self.spread_process, self.spread_param], "regime": self.regime, "drift": self.drift_per_bar}),
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
        if self.innovations == "TRUNCATED_T":
            r.append("innovations: standardized Student-t TRUNCATED at +/-%.1f sd and renormalized (explicit choice: the untruncated t has no finite exponential moments)" % self.tail_cap_sd)
        else:
            r.append("innovations: Gaussian")
        if self.drift_per_bar:
            r.append("declared constant drift per bar (from the location forecast)")
        return r

    def simulate(self, *, horizon_bars: int, n_paths: int, seed: int) -> dict:
        rng = np.random.default_rng(seed)
        vm = self.vm
        h_next = float(vm["h"]) if vm["kind"] == "FLAT" else float(vm["h_next"])
        H = np.full(n_paths, h_next)                                   # the first simulated bar uses EXACTLY the forecast variance
        mult = np.ones(n_paths)
        state = None
        if self.regime:
            state = rng.choice(len(self.regime["probabilities"]), size=n_paths, p=self.regime["probabilities"])
            mult = np.array(self.regime["variance_multipliers"], dtype=float)[state]
        logS = np.zeros((n_paths, horizon_bars + 1)); hpath = np.zeros((n_paths, horizon_bars + 1)); hpath[:, 0] = H * mult
        for t in range(1, horizon_bars + 1):
            Z = draw_innovations(rng, nu=self.nu, n=n_paths, innovations=self.innovations, tail_cap_sd=self.tail_cap_sd)
            E = np.sqrt(H * mult) * Z
            logS[:, t] = logS[:, t - 1] + self.drift_per_bar + E
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
        out = {"S": S, "h": hpath, "h_next": h_next, "iv": IV, "spread_bps": spread, "state": state, "seed": seed, "n_paths": n_paths, "horizon_bars": horizon_bars,
               "innovations": self.describe()["innovations"],
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
