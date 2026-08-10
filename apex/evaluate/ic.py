"""Information coefficient and its Newey-West corrected significance.

protocol section 7 and B2:

  * PRIMARY -- cross-sectional Spearman rank IC computed DAILY, with
    Newey-West HAC standard errors at lag 25 to correct for the autocorrelation
    induced by overlapping 20-day forward windows.

  * ROBUSTNESS -- the same IC restricted to the non-overlapping 20-trading-day
    grid, with a simple t-test.

Both are reported. Section 7: if they disagree in sign or materially in
significance, the experiment is INCONCLUSIVE, not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from apex.config import Config


@dataclass(frozen=True)
class ICResult:
    series: pd.Series
    mean: float
    std: float
    information_ratio: float
    t_stat: float
    p_value: float
    n_periods: int
    n_names_mean: float
    method: str

    def as_dict(self) -> dict:
        return {
            "mean_ic": self.mean,
            "std_ic": self.std,
            "ic_information_ratio": self.information_ratio,
            "t_stat": self.t_stat,
            "p_value": self.p_value,
            "n_periods": self.n_periods,
            "mean_names_per_period": self.n_names_mean,
            "method": self.method,
        }


def cross_sectional_ic(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    eligible: pd.DataFrame,
    min_names: int,
) -> tuple[pd.Series, pd.Series]:
    """Row-wise Spearman correlation between score and forward return.

    Spearman is Pearson on ranks, so ranking each row and taking a row-wise
    Pearson correlation is exact, and vectorises across thousands of dates
    without a Python loop.

    A date is scored only where BOTH the score and the forward return exist and
    the security is eligible. A date with fewer than `min_names` such securities
    yields NaN rather than a correlation computed on a handful of names.
    """
    mask = eligible & scores.notna() & returns.notna()

    ranked_scores = scores.where(mask).rank(axis=1)
    ranked_returns = returns.where(mask).rank(axis=1)

    count = mask.sum(axis=1)
    valid = count >= min_names

    score_dev = ranked_scores.sub(ranked_scores.mean(axis=1), axis=0)
    return_dev = ranked_returns.sub(ranked_returns.mean(axis=1), axis=0)

    covariance = (score_dev * return_dev).sum(axis=1)
    denominator = np.sqrt((score_dev**2).sum(axis=1) * (return_dev**2).sum(axis=1))

    ic = covariance / denominator.where(denominator > 0)
    return ic.where(valid), count.where(valid)


def newey_west_tstat(series: pd.Series, lag: int) -> tuple[float, float]:
    """t-statistic of the mean under HAC standard errors.

    Regressing the IC series on a constant makes the HAC covariance of the
    intercept exactly the HAC variance of the mean, which is the quantity
    section 7 asks for.
    """
    values = series.dropna()
    if len(values) < 2:
        return float("nan"), float("nan")
    model = sm.OLS(values.to_numpy(), np.ones(len(values)))
    fitted = model.fit(cov_type="HAC", cov_kwds={"maxlags": lag, "use_correction": True})
    return float(fitted.tvalues[0]), float(fitted.pvalues[0])


def simple_tstat(series: pd.Series) -> tuple[float, float]:
    values = series.dropna()
    if len(values) < 2:
        return float("nan"), float("nan")
    model = sm.OLS(values.to_numpy(), np.ones(len(values))).fit()
    return float(model.tvalues[0]), float(model.pvalues[0])


def evaluate_ic(
    scores: pd.DataFrame,
    returns: pd.DataFrame,
    eligible: pd.DataFrame,
    config: Config,
    dates: pd.DatetimeIndex,
    method: str,
) -> ICResult:
    """`method` is 'daily_newey_west' (primary) or 'non_overlapping' (robustness)."""
    min_names = int(config.get("evaluation.min_names_for_ic"))
    lag = int(config.get("evaluation.newey_west_lag"))

    ic, count = cross_sectional_ic(
        scores.loc[dates], returns.loc[dates], eligible.loc[dates], min_names
    )

    if method == "daily_newey_west":
        t_stat, p_value = newey_west_tstat(ic, lag)
    elif method == "non_overlapping":
        t_stat, p_value = simple_tstat(ic)
    else:
        raise ValueError(f"unknown IC method '{method}'")

    clean = ic.dropna()
    std = float(clean.std(ddof=1)) if len(clean) > 1 else float("nan")
    mean = float(clean.mean()) if len(clean) else float("nan")

    return ICResult(
        series=ic,
        mean=mean,
        std=std,
        information_ratio=mean / std if std and np.isfinite(std) and std > 0 else float("nan"),
        t_stat=t_stat,
        p_value=p_value,
        n_periods=int(len(clean)),
        n_names_mean=float(count.dropna().mean()) if count.notna().any() else float("nan"),
        method=method,
    )
