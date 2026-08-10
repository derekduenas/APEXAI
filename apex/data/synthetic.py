"""STAGE 1 -- synthetic price panel with known properties.

This is the test fixture the whole project stands on. It generates a world in
which the correct answer is known in advance, so that Stage 2 can ask the only
question that matters: does the pipeline report the truth about a world we
built ourselves?

Known properties, by construction:

  * NO cross-sectional predictability. Every security shares one log-drift.
    Volatility is heterogeneous (so F3 has something to rank) but the median of
    a lognormal is exp(nu) regardless of sigma, so P(R > median) = 0.5 for every
    security and no vol-based feature can rank forward returns.
  * Geometric random walks -- i.i.d. normal log returns, no autocorrelation.
  * Realistic splits (including a reverse split) and quarterly dividends, so the
    adjusted-vs-unadjusted distinction is exercised rather than assumed.
  * Securities that list late (IPOs) and delist partway through, with mixed
    reasons, so the survivorship and delisting-return paths are live.
  * Isolated missing bars, so the no-forward-fill rule is exercised.
  * Non-common security types and an excluded exchange, so the universe filters
    have something to reject.

`alpha > 0` switches on the POSITIVE CONTROL: a known momentum signal is
injected so Stage 2 can confirm the pipeline recovers a real effect. A rig that
only tests for "IC = 0" cannot distinguish a correct pipeline from a dead one.

Determinism: every random draw comes from an explicitly passed Generator. There
is no global seeding anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apex.config import Config
from apex.contracts import Panel

_SECURITY_ID_TEMPLATE = "SYN{:06d}"
_TICKER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def trading_calendar(start: str, end: str) -> pd.DatetimeIndex:
    """US business days less federal holidays.

    Derived, not hardcoded -- the real pipeline derives its calendar from the
    vendor's own dates for the same reason.
    """
    from pandas.tseries.holiday import USFederalHolidayCalendar

    days = pd.bdate_range(start=start, end=end)
    holidays = USFederalHolidayCalendar().holidays(start=days[0], end=days[-1])
    return days.difference(pd.DatetimeIndex(holidays))


def _weighted_choice(rng: np.random.Generator, weights: dict[str, float], size: int) -> np.ndarray:
    keys = list(weights)
    probabilities = np.array([weights[k] for k in keys], dtype="float64")
    probabilities = probabilities / probabilities.sum()
    return rng.choice(keys, size=size, p=probabilities)


def _log_uniform(rng: np.random.Generator, low: float, high: float, size) -> np.ndarray:
    return np.exp(rng.uniform(np.log(low), np.log(high), size=size))


@dataclass(frozen=True)
class SyntheticSource:
    """A `PriceSource` over a generated null (or known-signal) world."""

    config: Config
    seed: int
    alpha: float = 0.0
    overrides: dict | None = None

    name = "synthetic"
    requires_signed_registration = False

    @property
    def dataset_fingerprint(self) -> str:
        """A synthetic panel is fully determined by its config, seed and alpha."""
        import hashlib
        import json

        payload = json.dumps(
            {
                "source": "synthetic",
                "config_hash": self.config.hash,
                "seed": self.seed,
                "alpha": self.alpha,
                "overrides": self.overrides or {},
            },
            sort_keys=True,
            default=str,
        )
        return "synthetic-" + hashlib.sha256(payload.encode()).hexdigest()[:48]

    def _p(self, dotted: str):
        if self.overrides and dotted in self.overrides:
            return self.overrides[dotted]
        return self.config.get(dotted)

    def load(self) -> Panel:
        rng = np.random.default_rng(self.seed)

        dates = trading_calendar(self._p("panel.start"), self._p("panel.end"))
        n_days = len(dates)
        n_sec = int(self._p("panel.n_securities"))
        days_per_year = int(self._p("returns.trading_days_per_year"))

        securities = pd.Index(
            [_SECURITY_ID_TEMPLATE.format(i) for i in range(n_sec)], name="security_id"
        )

        # -- security attributes ------------------------------------------------
        annual_vol = rng.uniform(
            float(self._p("returns.annual_vol_min")),
            float(self._p("returns.annual_vol_max")),
            size=n_sec,
        )
        daily_vol = annual_vol / np.sqrt(days_per_year)
        # One drift for everyone. This single line is the null property.
        daily_drift = float(self._p("returns.annual_log_drift")) / days_per_year

        initial_price = _log_uniform(
            rng,
            float(self._p("prices.initial_price_min")),
            float(self._p("prices.initial_price_max")),
            n_sec,
        )
        initial_mcap = _log_uniform(
            rng,
            float(self._p("market_cap.initial_min_usd")),
            float(self._p("market_cap.initial_max_usd")),
            n_sec,
        )

        # -- base log returns ---------------------------------------------------
        base_log_returns = rng.normal(daily_drift, daily_vol, size=(n_days, n_sec))

        # -- listing / delisting ------------------------------------------------
        listing_index = np.zeros(n_sec, dtype=int)
        n_late = int(round(float(self._p("listing.late_listing_fraction")) * n_sec))
        late = rng.choice(n_sec, size=n_late, replace=False)
        listing_index[late] = rng.integers(1, max(2, n_days - days_per_year), size=n_late)

        delist_index = np.full(n_sec, n_days, dtype=int)
        n_delist = int(round(float(self._p("listing.delist_fraction")) * n_sec))
        delisted = rng.choice(n_sec, size=n_delist, replace=False)
        for position in delisted:
            earliest = listing_index[position] + days_per_year
            if earliest < n_days - 1:
                delist_index[position] = int(rng.integers(earliest, n_days))
        delist_reason = np.array([""] * n_sec, dtype=object)
        reasons = _weighted_choice(rng, self._p("listing.delist_reason_weights"), n_delist)
        for position, reason in zip(delisted, reasons):
            if delist_index[position] < n_days:
                delist_reason[position] = reason

        day_index = np.arange(n_days)[:, None]
        alive = (day_index >= listing_index[None, :]) & (day_index < delist_index[None, :])

        # -- positive control ---------------------------------------------------
        # Injected on the BASE returns so the injection magnitude is independent
        # of the injection itself. The DGP may look forward; the pipeline may not.
        log_returns = base_log_returns.copy()
        if self.alpha != 0.0:
            log_returns += self.alpha * self._momentum_signal(base_log_returns, alive)

        # -- total-return path --------------------------------------------------
        total_return_path = initial_price[None, :] * np.exp(np.cumsum(log_returns, axis=0))

        # -- corporate actions --------------------------------------------------
        split_ratio = self._splits(rng, n_days, n_sec, days_per_year)
        dividend_yield = self._dividends(rng, n_days, n_sec)

        # Unadjusted price: total return, less the dividend paid away, divided by
        # split ratios. This is what actually printed on the tape.
        price_multiplier = np.cumprod((1.0 - dividend_yield) / split_ratio, axis=0)
        close_unadj = total_return_path * price_multiplier

        shares_multiplier = np.cumprod(split_ratio, axis=0)
        share_drift = np.cumprod(
            1.0
            + rng.normal(
                0.0,
                float(self._p("market_cap.annual_share_drift_sd")) / np.sqrt(days_per_year),
                size=(n_days, n_sec),
            ),
            axis=0,
        )
        base_shares = initial_mcap / initial_price
        shares_out = base_shares[None, :] * shares_multiplier * share_drift

        # -- adjusted series ----------------------------------------------------
        # Vendor convention: the most recent adjusted close equals the most
        # recent actual close, with history scaled back from there. Only ratios
        # of the adjusted series matter, so the scale is cosmetic -- but getting
        # it right keeps the fixture honest about what a vendor hands you.
        close_adj = self._rescale_to_last(total_return_path, close_unadj, alive)
        high_adj, low_adj = self._intraday(rng, close_adj, daily_vol)

        # -- volume -------------------------------------------------------------
        turnover = _log_uniform(
            rng,
            float(self._p("liquidity.daily_turnover_min")),
            float(self._p("liquidity.daily_turnover_max")),
            n_sec,
        )
        noise = np.exp(
            rng.normal(0.0, float(self._p("liquidity.noise_log_sd")), size=(n_days, n_sec))
        )
        dollar_volume = close_unadj * shares_out * turnover[None, :] * noise
        volume = dollar_volume / close_unadj

        # -- apply life span and halts -----------------------------------------
        halted = rng.random((n_days, n_sec)) < float(self._p("missing_bars.daily_prob"))
        present = alive & ~halted

        def _mask(array: np.ndarray) -> pd.DataFrame:
            out = np.where(present, array, np.nan)
            return pd.DataFrame(out, index=dates, columns=securities)

        frames = {
            "close_adj": _mask(close_adj),
            "high_adj": _mask(high_adj),
            "low_adj": _mask(low_adj),
            "close_unadj": _mask(close_unadj),
            "volume": _mask(volume),
            "shares_out": _mask(shares_out),
        }

        meta = self._meta(rng, securities, dates, listing_index, delist_index, delist_reason)
        benchmark_tr = self._benchmark(frames["close_adj"], frames["close_unadj"] * frames["shares_out"])
        vol_index = self._vol_index(frames["close_adj"])

        return Panel(
            dates=dates,
            securities=securities,
            meta=meta,
            benchmark_tr=benchmark_tr,
            vol_index=vol_index,
            **frames,
        )

    # ----------------------------------------------------------------------
    # components
    # ----------------------------------------------------------------------

    def _momentum_signal(self, base_log_returns: np.ndarray, alive: np.ndarray) -> np.ndarray:
        """Cross-sectional z-score of the trailing skip-adjusted momentum window.

        Shifted forward one day before it is added to returns, so the bump on
        day t derives from information dated t-1. The generator is allowed to
        know the future; this keeps the injected effect an honest one-day-ahead
        predictability rather than a same-bar identity.
        """
        window = int(self._p("positive_control.signal_window"))
        skip = int(self._p("positive_control.signal_skip"))

        cumulative = np.cumsum(base_log_returns, axis=0)
        n_days = cumulative.shape[0]
        signal = np.full_like(cumulative, np.nan)
        for t in range(window + skip, n_days):
            signal[t] = cumulative[t - skip] - cumulative[t - window - skip]

        signal = np.where(alive, signal, np.nan)

        # Computed from explicit counts rather than nanmean/nanstd: early rows
        # have no listed securities at all, and an all-NaN slice is a legitimate
        # state here, not a numerical accident to be warned about.
        present = np.isfinite(signal)
        count = present.sum(axis=1, keepdims=True)
        safe_count = np.maximum(count, 1)
        mean = np.where(count > 0, np.nansum(signal, axis=1, keepdims=True) / safe_count, 0.0)
        deviation = np.where(present, signal - mean, 0.0)
        variance = (deviation**2).sum(axis=1, keepdims=True) / safe_count
        std = np.sqrt(variance)

        z = np.divide(deviation, std, out=np.zeros_like(deviation), where=std > 0)
        return np.vstack([np.zeros((1, z.shape[1])), z[:-1]])

    def _splits(
        self, rng: np.random.Generator, n_days: int, n_sec: int, days_per_year: int
    ) -> np.ndarray:
        daily_probability = float(self._p("corporate_actions.split_annual_prob")) / days_per_year
        ratios = np.asarray(self._p("corporate_actions.split_ratios"), dtype="float64")
        events = rng.random((n_days, n_sec)) < daily_probability
        chosen = rng.choice(ratios, size=(n_days, n_sec))
        return np.where(events, chosen, 1.0)

    def _dividends(self, rng: np.random.Generator, n_days: int, n_sec: int) -> np.ndarray:
        period = int(self._p("corporate_actions.dividend_period_days"))
        quarterly = float(self._p("corporate_actions.dividend_quarterly_yield"))
        pays = rng.random(n_sec) < float(self._p("corporate_actions.dividend_payer_fraction"))
        offset = rng.integers(0, period, size=n_sec)
        day_index = np.arange(n_days)[:, None]
        is_ex_day = ((day_index - offset[None, :]) % period == 0) & (day_index > 0)
        return np.where(is_ex_day & pays[None, :], quarterly, 0.0)

    @staticmethod
    def _rescale_to_last(
        total_return_path: np.ndarray, close_unadj: np.ndarray, alive: np.ndarray
    ) -> np.ndarray:
        scale = np.ones(total_return_path.shape[1])
        for j in range(total_return_path.shape[1]):
            live = np.flatnonzero(alive[:, j])
            if live.size:
                last = live[-1]
                scale[j] = close_unadj[last, j] / total_return_path[last, j]
        return total_return_path * scale[None, :]

    def _intraday(
        self, rng: np.random.Generator, close_adj: np.ndarray, daily_vol: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        multiple = float(self._p("prices.intraday_range_multiple"))
        scale = daily_vol[None, :] * multiple
        up = np.abs(rng.normal(0.0, scale, size=close_adj.shape))
        down = np.abs(rng.normal(0.0, scale, size=close_adj.shape))
        return close_adj * (1.0 + up), close_adj * (1.0 - down)

    def _meta(
        self,
        rng: np.random.Generator,
        securities: pd.Index,
        dates: pd.DatetimeIndex,
        listing_index: np.ndarray,
        delist_index: np.ndarray,
        delist_reason: np.ndarray,
    ) -> pd.DataFrame:
        n_sec = len(securities)
        n_days = len(dates)

        sector_ids = rng.integers(0, int(self._p("sectors.n_sectors")) - 1, size=n_sec)
        tiny = rng.choice(n_sec, size=int(self._p("sectors.tiny_sector_size")), replace=False)
        sector_ids[tiny] = int(self._p("sectors.n_sectors")) - 1

        # Tickers are deliberately RECYCLED across delisted and live securities,
        # so any code that joins on ticker instead of security_id breaks loudly
        # in the fixture rather than quietly on real data.
        tickers = []
        for i in range(n_sec):
            letters = _TICKER_ALPHABET[i % 26] + _TICKER_ALPHABET[(i // 26) % 26]
            tickers.append(f"{letters}{i % 97}")

        return pd.DataFrame(
            {
                "security_id": securities,
                "ticker": tickers,
                "exchange": _weighted_choice(rng, self._p("exchanges"), n_sec),
                "security_type": _weighted_choice(rng, self._p("security_types"), n_sec),
                "sector": [f"SECTOR_{s:02d}" for s in sector_ids],
                "first_date": dates[np.clip(listing_index, 0, n_days - 1)],
                "last_date": dates[np.clip(delist_index - 1, 0, n_days - 1)],
                "delist_date": [
                    dates[delist_index[i]] if delist_index[i] < n_days else pd.NaT
                    for i in range(n_sec)
                ],
                "delist_reason": [r if r else None for r in delist_reason],
            },
            index=securities,
        )

    def _benchmark(self, close_adj: pd.DataFrame, market_cap: pd.DataFrame) -> pd.Series:
        """Synthetic SPXTR: cap-weighted total-return index of the panel.

        Weights are LAGGED market cap. Using same-day weights would make the
        benchmark peek at the returns it is weighting -- a lookahead the fixture
        must not contain, or Stage 3's auditor would be validating a broken
        world.
        """
        returns = close_adj.pct_change(fill_method=None)
        weights = market_cap.shift(1)
        weights = weights.where(returns.notna())
        total = weights.sum(axis=1)
        weighted = (returns * weights).sum(axis=1) / total.replace(0.0, np.nan)
        index = (1.0 + weighted.fillna(0.0)).cumprod()
        index.iloc[0] = 1.0
        return index.rename("benchmark_tr")

    def _vol_index(self, close_adj: pd.DataFrame) -> pd.Series:
        """Synthetic VIX: cross-sectional median trailing realised vol, annualised."""
        window = int(self._p("benchmark.vix_window"))
        days_per_year = int(self._p("returns.trading_days_per_year"))
        log_returns = np.log(close_adj).diff()
        realised = log_returns.rolling(window, min_periods=window).std(ddof=1)
        median = realised.median(axis=1) * np.sqrt(days_per_year)
        median = median * float(self._p("benchmark.vix_scale"))
        return median.bfill().ffill().rename("vol_index")
