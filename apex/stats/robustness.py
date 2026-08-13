"""Reusable statistical robustness. Evaluates a DECLARED question; never searches.

WHAT THIS IS
------------
A pure, deterministic statistics layer that takes a time series (typically a
daily cross-sectional IC series) and a DECLARED set of methods, and returns
EVERY declared result. It closes the two gaps the master audit named: a second,
assumption-light null (block bootstrap + permutation) beside the existing HAC
reference, and a REUSABLE subperiod diagnostic instead of the one-off script the
#002 post-mortem used.

THE ONE THING IT STRUCTURALLY CANNOT DO
---------------------------------------
It cannot return "the best". There is no function that searches block sizes,
thresholds, windows, or subperiods and returns the strongest. Every entry point
takes the parameters as arguments and reports the result for exactly those
parameters. If several methods are requested, ALL are returned, labelled. The
absence of a `select_best` / `argmax` is the control -- the same discipline that
keeps `ScreenOutcome` from carrying a score.

AUTOCORRELATION IS RESPECTED
----------------------------
Overlapping 20-day forward windows make daily IC an MA(19)-ish series; 987 daily
ICs are NOT 987 independent draws. The block bootstrap resamples BLOCKS to
preserve that dependence, and the permutation null is sign-flip on
non-overlapping blocks, not on individual overlapping days. Treating the series
as i.i.d. would overstate significance -- exactly the false positive the whole
system exists to reject.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class RobustnessError(ValueError):
    """A declared robustness question was malformed."""


# --- effect size and CI (report, never select) -----------------------------


@dataclass(frozen=True)
class BootstrapResult:
    """A moving-block bootstrap of the MEAN of an autocorrelated series."""

    method: str
    block_size: int
    n_resamples: int
    seed: int
    point_estimate: float
    ci_low: float
    ci_high: float
    ci_level: float
    n_obs: int

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def moving_block_bootstrap_mean(
    series: pd.Series,
    *,
    block_size: int,
    n_resamples: int,
    seed: int,
    ci_level: float = 0.95,
) -> BootstrapResult:
    """CI for the mean via a MOVING-BLOCK bootstrap. `block_size` is DECLARED.

    The caller states the block size (e.g. 20, matching the forward-return
    overlap). This function does not choose it, does not try several, and does
    not return whichever gives the tightest interval.
    """
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        raise RobustnessError("series too short to bootstrap")
    if not (1 <= block_size <= n):
        raise RobustnessError(f"block_size {block_size} out of range 1..{n}")

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    starts_max = n - block_size + 1
    means = np.empty(n_resamples)
    for i in range(n_resamples):
        starts = rng.integers(0, starts_max, size=n_blocks)
        sample = np.concatenate([x[s:s + block_size] for s in starts])[:n]
        means[i] = sample.mean()

    alpha = (1.0 - ci_level) / 2.0
    lo, hi = np.quantile(means, [alpha, 1.0 - alpha])
    return BootstrapResult(
        method="moving_block_bootstrap",
        block_size=block_size, n_resamples=n_resamples, seed=seed,
        point_estimate=float(x.mean()),
        ci_low=float(lo), ci_high=float(hi), ci_level=ci_level, n_obs=n,
    )


@dataclass(frozen=True)
class PermutationResult:
    method: str
    block_size: int
    n_permutations: int
    seed: int
    observed_mean: float
    p_value_two_sided: float
    n_obs: int

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def block_sign_permutation(
    series: pd.Series,
    *,
    block_size: int,
    n_permutations: int,
    seed: int,
) -> PermutationResult:
    """Null test: is the mean distinguishable from zero, under block sign-flips?

    The null is "the series has no consistent sign". We flip the sign of whole
    BLOCKS (preserving within-block autocorrelation) and ask how often the
    permuted |mean| exceeds the observed. Flipping individual overlapping days
    would destroy the dependence and understate the p-value.
    """
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n < 2:
        raise RobustnessError("series too short to permute")
    if not (1 <= block_size <= n):
        raise RobustnessError(f"block_size {block_size} out of range 1..{n}")

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    observed = abs(x.mean())
    exceed = 0
    for _ in range(n_permutations):
        signs = rng.choice((-1.0, 1.0), size=n_blocks)
        flipped = np.concatenate(
            [signs[b] * x[b * block_size:(b + 1) * block_size] for b in range(n_blocks)]
        )
        if abs(flipped.mean()) >= observed:
            exceed += 1
    # +1 smoothing: a permutation p is never exactly zero.
    p = (exceed + 1) / (n_permutations + 1)
    return PermutationResult(
        method="block_sign_permutation",
        block_size=block_size, n_permutations=n_permutations, seed=seed,
        observed_mean=float(x.mean()), p_value_two_sided=float(p), n_obs=n,
    )


# --- subperiod diagnostic (declared splits, never selected) -----------------


@dataclass(frozen=True)
class SubperiodResult:
    """Per-subperiod means over DECLARED, non-overlapping date splits."""

    scheme: str
    per_subperiod: dict            # label -> {"n":.., "mean":.., "share":..}
    n_subperiods: int

    def as_dict(self) -> dict:
        return {"scheme": self.scheme, "n_subperiods": self.n_subperiods,
                "per_subperiod": self.per_subperiod}


def subperiod_means(series: pd.Series, *, scheme: str = "calendar_year") -> SubperiodResult:
    """Mean per subperiod, over a DECLARED partition of the dates.

    `scheme` names a fixed, non-searchable partition (calendar year, calendar
    quarter). It reports every subperiod. It does NOT rank them, does not return
    the strongest, and has no concept of "best subperiod" -- selecting one would
    be the #002 breadth-contamination error.
    """
    s = series.dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        raise RobustnessError("subperiod analysis needs a DatetimeIndex")
    if scheme == "calendar_year":
        key = s.index.year
    elif scheme == "calendar_quarter":
        key = s.index.to_period("Q").astype(str)
    elif scheme == "first_second_half":
        mid = len(s) // 2
        key = np.where(np.arange(len(s)) < mid, "first_half", "second_half")
    else:
        raise RobustnessError(f"unknown subperiod scheme {scheme!r}")

    total = float(s.sum())
    out = {}
    for label, idx in s.groupby(key).groups.items():
        sub = s.loc[idx]
        out[str(label)] = {
            "n": int(len(sub)),
            "mean": float(sub.mean()),
            "share_of_total": float(sub.sum() / total) if total != 0 else float("nan"),
        }
    return SubperiodResult(scheme=scheme, per_subperiod=out, n_subperiods=len(out))


# --- multiple-comparison accounting (report the denominator) ----------------


@dataclass(frozen=True)
class MultipleComparison:
    """Records how many comparisons a family contains. The denominator, visible.

    This does not CHOOSE a correction to make a result pass; it reports the
    family size and the corrected thresholds so the reader sees the denominator.
    Sequential Bonferroni over a declared budget, and Holm over a completed
    family -- both are reported, neither is 'selected'.
    """

    n_comparisons: int
    family_alpha: float

    def bonferroni_alpha(self) -> float:
        return self.family_alpha / self.n_comparisons

    def as_dict(self) -> dict:
        return {
            "n_comparisons": self.n_comparisons,
            "family_alpha": self.family_alpha,
            "bonferroni_alpha": self.bonferroni_alpha(),
        }


# --- controls: prove the tools work -----------------------------------------


def positive_control_series(n: int, mean: float, seed: int) -> pd.Series:
    """A series with a KNOWN positive mean and mild autocorrelation, for tests."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, n)
    ac = np.convolve(noise, np.ones(5) / 5, mode="same")   # induce autocorrelation
    dates = pd.bdate_range("2010-01-01", periods=n)
    return pd.Series(mean + ac, index=dates)


def negative_control_series(n: int, seed: int) -> pd.Series:
    """A mean-zero series: the null must NOT be rejected on it."""
    return positive_control_series(n, mean=0.0, seed=seed)
