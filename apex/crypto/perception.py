"""Crypto-native perception — the equity philosophy, NOT the equity
semantics. No 09:30 open, no closing auction, no sectors, no opening
range: BTC's structure is ROLLING (24h VWAP, 24h range position, 4h
breakout structure, hour-of-UTC-day volume seasonality) and its world is
the surrounding crypto ecosystem (ETH/SOL relative behavior, breadth,
correlation), not sector ETFs.

Everything is as-of: candles arrive COMPLETED from the feed layer, and
the future-poison counterexample applies here exactly as in equities.
Missing structure is a typed absence, never a fabricated neutral.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

CRYPTO_SCHEMA_VERSION = "crypto_feature_schema_v1"

PRODUCTS = ("BTC-USD", "ETH-USD", "SOL-USD")
INSTRUMENT = "BTC-USD"


@dataclass(frozen=True)
class CryptoChartState:
    product: str
    t_utc: str
    price: float
    r_15m: float | None
    r_30m: float | None
    r_60m: float | None
    r_240m: float | None
    vwap_24h: float | None
    distance_to_vwap: float | None
    above_vwap: bool | None
    pos_in_24h_range: float | None       # 0 at low, 1 at high
    breakout_4h_up: bool                 # close beyond trailing 4h extreme
    breakout_4h_down: bool               # (extreme computed EXCLUDING the
    hi_4h: float | None                  #  current bar: no self-breakout)
    lo_4h: float | None
    realized_vol_1h_ann: float | None
    vol_scale_30m: float | None          # vol-implied 30m move (frac)
    rvol_hour: float | None              # last-hour vol vs 14d same-UTC-hour
    vol_accel: float | None              # last 15m vol vs prior hour avg
    spread_bps: float | None
    book_imbalance: float | None
    minutes_recorded: int
    data_quality: tuple = ()
    schema_version: str = CRYPTO_SCHEMA_VERSION

    def as_record(self) -> dict:
        return asdict(self)


def hour_volume_baseline(candles_14d: pd.DataFrame) -> dict:
    """Median hourly volume per UTC hour over the trailing window —
    crypto's time-of-day seasonality (weekend/Asia/US-overlap effects)."""
    f = candles_14d.copy()
    f["h"] = f["event_time_utc"].dt.hour
    f["d"] = f["event_time_utc"].dt.date
    hourly = f.groupby(["d", "h"])["volume"].sum().reset_index()
    return {str(h): float(v) for h, v in
            hourly.groupby("h")["volume"].median().items()}


def compute_state(product: str, candles: pd.DataFrame, t_utc,
                  baseline: dict | None,
                  book: dict | None) -> CryptoChartState | None:
    t = pd.Timestamp(t_utc)
    f = candles[candles["event_time_utc"] + pd.Timedelta(minutes=1) <= t]
    if len(f) < 90:
        return None
    px = f["close"].astype(float)
    vol = f["volume"].astype(float)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    times = f["event_time_utc"]
    price = float(px.iloc[-1])
    quality: list = []

    def ret(minutes):
        cut = t - pd.Timedelta(minutes=minutes)
        base = px[times + pd.Timedelta(minutes=1) <= cut]
        return float(price / base.iloc[-1] - 1) if len(base) else None

    w24 = times + pd.Timedelta(minutes=1) > t - pd.Timedelta(hours=24)
    tp = (hi + lo + px) / 3
    v24 = vol[w24]
    vwap = (float((tp[w24] * v24).sum() / v24.sum())
            if v24.sum() > 0 else None)
    h24, l24 = float(hi[w24].max()), float(lo[w24].min())
    pos = ((price - l24) / (h24 - l24)
           if h24 > l24 else None)

    w4 = (times + pd.Timedelta(minutes=1) > t - pd.Timedelta(hours=4))
    prior4 = f[w4].iloc[:-1]                     # exclude current bar
    hi4 = float(prior4["high"].max()) if len(prior4) > 30 else None
    lo4 = float(prior4["low"].min()) if len(prior4) > 30 else None

    r1h = px[times + pd.Timedelta(minutes=1)
             > t - pd.Timedelta(hours=1)].pct_change().dropna()
    rv = (float(r1h.std() * np.sqrt(60 * 24 * 365))
          if len(r1h) >= 30 else None)
    vscale = (float(r1h.std() * np.sqrt(30)) if len(r1h) >= 30 else None)

    rvol = None
    if baseline:
        last_hr_vol = float(vol[times + pd.Timedelta(minutes=1)
                                > t - pd.Timedelta(hours=1)].sum())
        base = baseline.get(str(t.hour))
        if base and base > 0:
            rvol = float(last_hr_vol / base)
        else:
            quality.append("NO_HOUR_BASELINE")
    else:
        quality.append("NO_VOLUME_BASELINE")
    v15 = float(vol[times + pd.Timedelta(minutes=1)
                    > t - pd.Timedelta(minutes=15)].sum())
    v60 = float(vol[times + pd.Timedelta(minutes=1)
                    > t - pd.Timedelta(hours=1)].sum())
    accel = (v15 / (v60 / 4)) if v60 > 0 else None

    gap_min = (t - (times.iloc[-1] + pd.Timedelta(minutes=1))
               ).total_seconds() / 60
    if gap_min > 5:
        quality.append("STALE_CANDLES")

    return CryptoChartState(
        product=product, t_utc=str(t), price=price,
        r_15m=ret(15), r_30m=ret(30), r_60m=ret(60), r_240m=ret(240),
        vwap_24h=vwap,
        distance_to_vwap=(price / vwap - 1) if vwap else None,
        above_vwap=(price > vwap) if vwap else None,
        pos_in_24h_range=round(pos, 4) if pos is not None else None,
        breakout_4h_up=bool(hi4 and price > hi4),
        breakout_4h_down=bool(lo4 and price < lo4),
        hi_4h=hi4, lo_4h=lo4,
        realized_vol_1h_ann=round(rv, 4) if rv else None,
        vol_scale_30m=round(vscale, 6) if vscale else None,
        rvol_hour=round(rvol, 3) if rvol else None,
        vol_accel=round(accel, 3) if accel else None,
        spread_bps=(book or {}).get("spread_bps"),
        book_imbalance=(book or {}).get("imbalance_top10"),
        minutes_recorded=len(f), data_quality=tuple(quality))


def crypto_world(states: dict, t_utc) -> dict:
    """The surrounding ecosystem: BTC never watched in isolation."""
    rets = {p: s.r_60m for p, s in states.items()
            if s is not None and s.r_60m is not None}
    btc, eth = states.get("BTC-USD"), states.get("ETH-USD")
    out = {"kind": "crypto_world", "t_utc": str(t_utc),
           "returns_60m": {p: round(r, 5) for p, r in rets.items()},
           "breadth_positive_frac": round(float(np.mean(
               [r > 0 for r in rets.values()])), 2) if rets else None,
           "btc_eth_rs_60m": (round(btc.r_60m - eth.r_60m, 5)
                              if btc and eth and btc.r_60m is not None
                              and eth.r_60m is not None else None),
           "btc_vol_state": btc.realized_vol_1h_ann if btc else None,
           "uncertain": bool(
               btc is None or btc.r_60m is None
               or abs(btc.r_60m) >= 0.02 or btc.data_quality)}
    return out
