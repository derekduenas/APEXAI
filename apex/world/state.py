"""State variables and the ONLINE-ONLY regime classifier.

Two disciplines, both structural:

STALENESS PROPAGATES. Every variable carries (value, as_of, vintage, source,
stale). Anything combined from a stale input is stale. A consumer cannot
quietly launder a three-week-old credit spread into a fresh-looking state.

THE CLASSIFIER IS ONLINE OR IT IS NOTHING. It sees data through T and
nothing after: trailing windows only, thresholds from TRAILING quantiles,
no full-sample fit, no forward smoothing. Labels are timestamped at
assignment and NEVER revised -- if new data would relabel a past date, the
original stands and the relabel is a separate diagnostic series. The
classifier's DETECTION LAG against a hindsight labeling is measured and
reported (diagnostic only): a classifier with a 30-day lag is a description
of the past, not an input to a decision.

WHAT THIS MODULE REFUSES: any notion of which state is "good". There is no
per-state return, no conditional Sharpe, no state-picking. "GP works only in
state X" is a NEW HYPOTHESIS for the registration machinery, not a feature
of this layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

STALE_AFTER_DAYS = 7          # a market-derived variable older than this is stale


@dataclass(frozen=True)
class StateVariable:
    name: str
    value: float
    as_of: str                # last data date the value derives from
    vintage: str              # when it became knowable (== as_of for market data)
    source: str
    stale: bool

    @staticmethod
    def combine_staleness(*vars_) -> bool:
        """Staleness is infectious, never averaged away."""
        return any(v.stale for v in vars_)


def _var(name, value, as_of, now, source="sharadar-derived") -> StateVariable:
    stale = (pd.Timestamp(now) - pd.Timestamp(as_of)).days > STALE_AFTER_DAYS
    return StateVariable(name=name, value=float(value), as_of=str(as_of),
                         vintage=str(as_of), source=source, stale=stale)


def index_state_variables(spy: pd.Series, asof, now=None) -> dict:
    """Index-level state from the benchmark series, using data <= asof ONLY.

    Trend, volatility (level and term structure), drawdown. Cheap enough to
    compute over the full lake history; the cross-sectional variables
    (breadth, dispersion, correlation, liquidity) need the wide panel and are
    computed by `cross_sectional_state_variables` on whatever window is
    loaded.
    """
    now = now or asof
    s = spy.loc[:pd.Timestamp(asof)].dropna()
    if len(s) < 260:
        raise ValueError("insufficient trailing history for index state")
    d = str(s.index[-1].date())
    r = s.pct_change().dropna()
    vol20 = float(r.tail(20).std() * np.sqrt(252))
    vol60 = float(r.tail(60).std() * np.sqrt(252))
    return {
        "trend_vs_200d": _var("trend_vs_200d",
                              s.iloc[-1] / s.tail(200).mean() - 1, d, now),
        "vol_20d": _var("vol_20d", vol20, d, now),
        "vol_term_20_over_60": _var("vol_term_20_over_60",
                                    vol20 / vol60 if vol60 > 0 else 1.0, d, now),
        "drawdown": _var("drawdown", s.iloc[-1] / s.max() - 1, d, now),
    }


def cross_sectional_state_variables(close: pd.DataFrame, dollar_volume,
                                    asof, now=None) -> dict:
    """Breadth, dispersion, mean pairwise correlation, liquidity -- data <= asof."""
    now = now or asof
    px = close.loc[:pd.Timestamp(asof)].dropna(axis=1, thresh=60)
    d = str(px.index[-1].date())
    r = px.pct_change().tail(60)
    breadth = float((px.iloc[-1] > px.tail(50).mean()).mean())
    disp = float(r.iloc[-1].std())
    # mean pairwise correlation via the dispersion identity: for N names with
    # equal vol, corr ~ var(mean)/mean(var). Cheap, online, and monotone in
    # the true mean correlation.
    mean_ret = r.mean(axis=1)
    corr = float(np.clip(mean_ret.var() / r.var(axis=1).replace(0, np.nan).mean(),
                         0, 1))
    liq = float(dollar_volume.loc[:pd.Timestamp(asof)].tail(20).sum(axis=1).mean())
    return {
        "breadth_above_50d": _var("breadth_above_50d", breadth, d, now),
        "dispersion_60d": _var("dispersion_60d", disp, d, now),
        "mean_pairwise_corr": _var("mean_pairwise_corr", corr, d, now),
        "aggregate_addv": _var("aggregate_addv", liq, d, now),
    }


# ---------------------------------------------------------------------------
# the online classifier
# ---------------------------------------------------------------------------

REGIMES = ("CALM_UP", "CALM_DOWN", "VOL_UP", "VOL_DOWN")
VOL_LOOKBACK_DAYS = 756       # trailing 3y for the online vol quantile
VOL_HIGH_QUANTILE = 0.75
UNCERTAIN_BAND = 0.10         # within 10% of a threshold => uncertain flag


def classify_online(spy: pd.Series, asof) -> dict:
    """State at `asof` from data <= asof ONLY. Deterministic, no fitting.

    trend: close vs 200d SMA. vol: trailing-20d realized vs the TRAILING-3y
    75th percentile of itself (an online quantile -- the threshold at T uses
    only data before T). stress: drawdown < -10%, reported as an overlay
    flag, not a fifth state. `uncertain` is set near either boundary
    (question 9: the state must say when it does not know)."""
    s = spy.loc[:pd.Timestamp(asof)].dropna()
    r = s.pct_change().dropna()
    vol = r.rolling(20).std() * np.sqrt(252)
    trailing = vol.tail(VOL_LOOKBACK_DAYS).iloc[:-1]
    thresh = float(trailing.quantile(VOL_HIGH_QUANTILE))
    v_now = float(vol.iloc[-1])
    sma = float(s.tail(200).mean())
    trend_up = bool(s.iloc[-1] > sma)
    vol_high = bool(v_now > thresh)
    regime = ("VOL_" if vol_high else "CALM_") + ("UP" if trend_up else "DOWN")
    uncertain = (abs(s.iloc[-1] / sma - 1) < UNCERTAIN_BAND / 10
                 or (thresh > 0 and abs(v_now / thresh - 1) < UNCERTAIN_BAND))
    return {"date": str(s.index[-1].date()), "regime": regime,
            "stress": bool(s.iloc[-1] / s.max() - 1 < -0.10),
            "uncertain": bool(uncertain),
            "vol_20d": round(v_now, 4), "vol_threshold": round(thresh, 4),
            "trend_vs_sma": round(float(s.iloc[-1] / sma - 1), 4)}


class LabelStore:
    """Append-only regime labels. A past label is NEVER revised: a would-be
    relabel is recorded in a separate diagnostic series, and an attempt to
    overwrite raises."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _rows(self) -> dict:
        if not self.path.exists():
            return {}
        return {r["date"]: r for r in
                (json.loads(l) for l in self.path.read_text().strip().splitlines())}

    def assign(self, label: dict) -> None:
        rows = self._rows()
        existing = rows.get(label["date"])
        if existing is not None:
            if existing["regime"] != label["regime"]:
                raise ValueError(
                    f"label for {label['date']} already assigned "
                    f"({existing['regime']}); labels are never revised -- "
                    f"record the disagreement as a diagnostic series instead")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(label, sort_keys=True) + "\n")

    def series(self) -> pd.Series:
        rows = self._rows()
        return pd.Series({pd.Timestamp(d): r["regime"] for d, r in rows.items()}
                         ).sort_index()


def detection_lag_days(online_labels: pd.Series, spy: pd.Series) -> dict:
    """DIAGNOSTIC ONLY: how late is the online classifier vs hindsight?

    The hindsight reference labels each date with the full sample (a centered
    100d trend and the full-sample vol quantile) -- deliberately contaminated,
    which is why it exists only inside this diagnostic and returns only LAG
    STATISTICS, never labels a downstream consumer could touch."""
    vol = (spy.pct_change().rolling(20).std() * np.sqrt(252)).reindex(spy.index)
    hind_vol_thresh = float(vol.quantile(VOL_HIGH_QUANTILE))       # full sample
    sma = spy.rolling(100, center=True).mean()                     # peeks forward
    hind = (("VOL_" if v > hind_vol_thresh else "CALM_")
            + ("UP" if s > m else "DOWN")
            for s, m, v in zip(spy, sma, vol))
    hind = pd.Series(list(hind), index=spy.index)

    # Only DURABLE transitions count: the reference must stay in its new
    # state >= `durable_days` trading days. Without this filter the raw
    # reference churns every few days and "days to next matching label"
    # measures churn, not detection -- the first version of this diagnostic
    # reported a meaningless 365-day mean for exactly that reason.
    durable_days = 20
    max_window_days = 120
    runs = hind[hind != hind.shift(1)]
    lags, missed = [], 0
    trans = []
    for i, t in enumerate(runs.index[1:], start=1):
        end = runs.index[i + 1] if i + 1 < len(runs) else hind.index[-1]
        if len(hind.loc[t:end]) >= durable_days:
            trans.append(t)
    for t in trans:
        target = hind.loc[t]
        after = online_labels.loc[(online_labels.index >= t)
                                  & (online_labels.index
                                     <= t + pd.Timedelta(days=max_window_days))]
        hit = after[after == target]
        if len(hit):
            lags.append((hit.index[0] - t).days)
        else:
            missed += 1
    return {"durable_transitions_in_reference": int(len(trans)),
            "detected_within_120d": int(len(lags)),
            "missed_within_120d": int(missed),
            "mean_lag_days": round(float(np.mean(lags)), 1) if lags else None,
            "median_lag_days": round(float(np.median(lags)), 1) if lags else None,
            "note": "hindsight reference is deliberately contaminated and "
                    "exists only inside this diagnostic; durable transitions "
                    "(>=20d in new state) only"}
