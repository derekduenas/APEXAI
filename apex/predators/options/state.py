"""OPTIONS DOMAIN STATE -- what the derivatives market is saying at T.

Computed from a FrozenState (the temporal firewall guarantees nothing
after T is even present). Everything here is OBSERVATION, never a
label: this module may say "ATM IV is 0.28 and 20d realized is 0.19",
it may NOT say "vol is cheap" -- that is a research claim requiring
governance, not a formula.

APEX PRICES ITS OWN BOOK. IV and Greeks come from the commissioned
pricing stack (bsm / american_binomial / dividends), never from a
vendor field. A vendor's analytics are a cross-check; ours are canon.

decision_power: NONE -- a sensor.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

NOT_ESTIMABLE = "NOT_ESTIMABLE"

# pre-registered 2026-08-23, before any outcome was inspected
RV_WINDOWS_MIN = (30, 60, 390)      # intraday short, hour, full session
ATM_BAND = 0.02                     # |K/S - 1| <= 2% counts as ATM
MIN_QUOTES_FOR_SURFACE = 8
MAX_SPREAD_PCT_FOR_IV = 0.60        # wider than this: IV is noise


@dataclass(frozen=True)
class OptionsState:
    symbol: str
    T: str
    spot: float | None
    realized_vol: dict = field(default_factory=dict)
    atm_iv: float | None = None
    atm_dte: float | None = None
    iv_minus_rv: float | str = NOT_ESTIMABLE
    iv_over_rv: float | str = NOT_ESTIMABLE
    put_skew: float | str = NOT_ESTIMABLE
    call_skew: float | str = NOT_ESTIMABLE
    term_structure: tuple = ()
    surface_points: int = 0
    quote_quality: str = "UNKNOWN"
    median_spread_pct: float | None = None
    data_quality: str = "UNKNOWN"
    pricing_source: str = "APEX_COMMISSIONED_STACK"
    law: str = ("observation only -- no CHEAP/RICH/BUY_VOL/SELL_VOL "
                "label may be attached without governed research")
    decision_power: str = "NONE"

    def as_record(self) -> dict:
        return {"kind": "options_state", **asdict(self)}


def realized_vol(bars: list, window_min: int) -> float | None:
    """Trailing realized volatility, annualized. Causal by
    construction: `bars` is already the frozen <=T slice."""
    if len(bars) < window_min + 1:
        return None
    closes = [b["c"] for b in bars[-(window_min + 1):]]
    rets = [math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i] > 0 and closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(390 * 252)


def _rows_at(quotes: list, T: str) -> list:
    """Latest quote per contract at or before T (the frozen slice is
    already causal; this collapses it to one row per contract)."""
    latest = {}
    for r in quotes:
        key = (r["expiration"], r["strike"], r["right"])
        prev = latest.get(key)
        if prev is None or r["timestamp"] >= prev["timestamp"]:
            latest[key] = r
    return list(latest.values())


def build(frozen, *, rate: float = 0.04, dividend_schedule=None
          ) -> OptionsState:
    """Construct the options domain state from a FrozenState."""
    import pandas as pd

    from apex.option_analytics.bsm import implied_volatility
    spot = frozen.spot_ref
    bars = [b for b in frozen.underlying_bars]
    rv = {f"rv_{w}m": realized_vol(bars, w) for w in RV_WINDOWS_MIN}
    if spot is None:
        return OptionsState(symbol=frozen.symbol, T=frozen.T, spot=None,
                            realized_vol=rv, data_quality="INSUFFICIENT")

    rows = _rows_at(list(frozen.option_quotes), frozen.T)
    T_ts = pd.Timestamp(frozen.T)
    spreads, ivs = [], []      # ivs: (dte, moneyness, right, iv)
    for r in rows:
        try:
            b, a, k = float(r["bid"]), float(r["ask"]), float(r["strike"])
        except (TypeError, ValueError):
            continue
        if b <= 0 or a <= 0 or a < b:
            continue
        mid = (a + b) / 2.0
        sp = (a - b) / mid
        spreads.append(sp)
        if sp > MAX_SPREAD_PCT_FOR_IV:
            continue                      # too wide: IV would be noise
        exp = pd.Timestamp(r["expiration"])
        dte = (exp - T_ts.normalize().tz_localize(None)
               if T_ts.tzinfo is None else
               exp.tz_localize("UTC") - T_ts).total_seconds() / 86400.0
        if dte <= 0:
            continue
        right = "call" if r["right"].upper().startswith("C") else "put"
        try:
            iv = implied_volatility(
                option_type=right, market_price=mid, spot=spot,
                strike=k, time_to_expiry_years=dte / 365.0, rate=rate)
        except Exception:                                # noqa: BLE001
            continue
        if iv and 0.0 < iv < 5.0:
            ivs.append((dte, k / spot, right, iv))

    if len(ivs) < MIN_QUOTES_FOR_SURFACE:
        return OptionsState(
            symbol=frozen.symbol, T=frozen.T, spot=spot,
            realized_vol=rv, surface_points=len(ivs),
            median_spread_pct=(sorted(spreads)[len(spreads) // 2]
                               if spreads else None),
            data_quality="INSUFFICIENT_SURFACE")

    # --- ATM IV: nearest-expiry, nearest-money, both rights averaged
    near_dte = min(d for d, _m, _r, _v in ivs)
    atm_c = [v for d, m, _r, v in ivs
             if d == near_dte and abs(m - 1.0) <= ATM_BAND]
    if not atm_c:                          # widen honestly if needed
        closest = min(ivs, key=lambda x: (x[0], abs(x[1] - 1.0)))
        atm_c = [closest[3]]
    atm_iv = sum(atm_c) / len(atm_c)

    # --- skew: 25-delta-ish proxy by moneyness (no delta needed)
    def _near(mny, right):
        c = [v for d, m, r_, v in ivs
             if d == near_dte and r_ == right and abs(m - mny) < 0.03]
        return sum(c) / len(c) if c else None
    otm_put = _near(0.95, "put")
    otm_call = _near(1.05, "call")
    put_skew = (otm_put - atm_iv) if otm_put is not None else NOT_ESTIMABLE
    call_skew = (otm_call - atm_iv) if otm_call is not None \
        else NOT_ESTIMABLE

    # --- term structure: ATM IV by expiry
    by_dte = {}
    for d, m, _r, v in ivs:
        if abs(m - 1.0) <= ATM_BAND * 2:
            by_dte.setdefault(round(d), []).append(v)
    term = tuple(sorted((d, round(sum(v) / len(v), 4))
                        for d, v in by_dte.items()))

    rv_ref = rv.get("rv_390m") or rv.get("rv_60m") or rv.get("rv_30m")
    med_sp = sorted(spreads)[len(spreads) // 2] if spreads else None
    return OptionsState(
        symbol=frozen.symbol, T=frozen.T, spot=spot, realized_vol=rv,
        atm_iv=round(atm_iv, 5), atm_dte=round(near_dte, 2),
        iv_minus_rv=(round(atm_iv - rv_ref, 5) if rv_ref
                     else NOT_ESTIMABLE),
        iv_over_rv=(round(atm_iv / rv_ref, 4) if rv_ref
                    else NOT_ESTIMABLE),
        put_skew=(round(put_skew, 5) if put_skew != NOT_ESTIMABLE
                  else NOT_ESTIMABLE),
        call_skew=(round(call_skew, 5) if call_skew != NOT_ESTIMABLE
                   else NOT_ESTIMABLE),
        term_structure=term, surface_points=len(ivs),
        median_spread_pct=(round(med_sp, 4) if med_sp else None),
        quote_quality=("GOOD" if med_sp and med_sp < 0.10 else
                       "ACCEPTABLE" if med_sp and med_sp < 0.25 else
                       "WIDE"),
        data_quality="FULL")
