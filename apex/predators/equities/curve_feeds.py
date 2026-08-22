"""CURVE DIMENSION FEEDS -- illuminating the dark senses.

THE PHASE 1 FORENSIC: transition_quality was STRONG in 0 of 4,760
Captain reviews because Curve HIGH needs >=3 elevated dimensions across
>=2 dependency groups, and six of ten dimensions had NEVER ONCE been
supported. The Predator's decision law required evidence from senses it
did not possess. This module builds the senses that available data can
honestly support -- and refuses the ones it cannot.

THE OBJECTIVE IS NOT "MAKE HIGH FIRE". It is: every intended dimension
becomes honestly computable when its required information exists. No
constant here is tuned toward any firing rate, and nothing was inspected
against outcomes.

SEMANTIC HONESTY LAW (operator, 2026-08-22):

    BAR_ACTIVITY_PROXY  !=  LIQUIDITY
    PRICE_IMPACT_PROXY  !=  SPREAD
    VOLUME              !=  DEPTH
    volume              !=  order flow
    equity ETFs         !=  cross-asset

So this module builds:

    volatility                READY   canonical -- realized vol from bars
    correlation               READY   canonical -- subject vs market,
                                      property-tested for RS redundancy
    cross_equity_complex      PROXY   HONESTLY RENAMED. We hold SPY/QQQ/
                                      IWM + 11 sector SPDRs; that is the
                                      equity complex, NOT cross-asset.
                                      The canonical `cross_asset`
                                      dimension stays dark.
    volume_pressure_proxy     PROXY   NOT `flow`. No aggressor/trade-side
                                      data is persisted, so true order
                                      flow is unknowable from this store.
    liquidity                 DARK    NOT_ESTIMABLE -- no quotes are
                                      persisted. A bar proxy may NEVER
                                      occupy this slot.
    event_reaction            DARK    INPUT_STARVED -- the event stream
                                      is point-in-time correct but
                                      carries CIK only, no ticker map,
                                      so no event can be attached to a
                                      subject.

All series are causal: value at time T uses only bars whose event_time
<= T, and estimators are trailing-exclusive (the self-inclusive
denominator defect is not repeated here).

decision_power: NONE_CURVE_DIMENSION_SHADOW -- these do not feed live
Captain until an explicit natural-acceptance promotion.
"""
from __future__ import annotations

import math

SHADOW_POWER = "NONE_CURVE_DIMENSION_SHADOW"

# TERMINOLOGY LAW (operator, 2026-08-22). "CANONICAL" below describes
# the IMPLEMENTATION SEMANTICS -- that volatility and correlation are
# the real dimensions rather than proxies. It does NOT mean Captain may
# consume them. Anyone reading this file months from now must not infer
# authorization from the word canonical.
IMPLEMENTATION_SEMANTICS = "CANONICAL"      # real dimensions, not proxies
DECISION_AUTHORITY = "SHADOW"               # until natural acceptance
PROMOTION_STATUS = "NOT_AUTHORIZED_PENDING_MONDAY_NATURAL_ACCEPTANCE"

# canonical market and complex references present in the bar store
MARKET_PROXY = "SPY"
EQUITY_COMPLEX = ("SPY", "QQQ", "IWM")
SECTOR_ETFS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
               "XLRE", "XLU", "XLV", "XLY")

# estimation windows -- pre-registered 2026-08-22, chosen to match the
# existing Curve cadence (1m bars, MIN_POINTS_FOR_CURVATURE=10), never
# swept against any output
VOL_WINDOW = 20          # bars in a realized-vol estimate
CORR_WINDOW = 30         # bars in a rolling correlation
MIN_SERIES = 12          # below this, a series is not emitted at all

DARK_DIMENSIONS = {
    "liquidity": {
        "status": "NOT_ESTIMABLE",
        "requires": ("persisted bid", "persisted ask", "quote timestamp",
                     "bid size", "ask size", "depth where available"),
        "law": "bar activity is NOT executable liquidity; no proxy may "
               "occupy the canonical liquidity slot",
    },
    "event_reaction": {
        "status": "INPUT_STARVED",
        "requires": ("CIK->ticker map to attach filings to subjects",),
        "note": "the event stream IS point-in-time correct "
                "(event_time_utc + known_from_utc, ~14min lag) but "
                "carries company_raw/CIK only -- no subject mapping",
    },
    "cross_asset": {
        "status": "NOT_JUSTIFIED",
        "requires": ("genuinely non-equity instruments: rates, FX, "
                     "commodities, credit",),
        "law": "three equity ETFs are not cross-asset information; the "
               "honest measure is cross_equity_complex (a PROXY)",
    },
    "flow": {
        "status": "INPUT_STARVED",
        "requires": ("trade-side / aggressor semantics",),
        "law": "signed bar return x volume is not aggressor flow; the "
               "honest measure is volume_pressure_proxy (a PROXY)",
    },
}


def _returns(closes: list) -> list:
    out = []
    for i in range(1, len(closes)):
        a, b = closes[i - 1], closes[i]
        if a and b and a > 0 and b > 0:
            out.append(math.log(b / a))
    return out


def _stdev(xs: list) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _bar_series(bars: list) -> tuple:
    """(times, closes, volumes) from ascending bars.

    Times are pandas Timestamps, not strings: every consumer compares
    them against a `now` Timestamp, and emitting strings pushed that
    conversion onto each caller (and broke the first replay).
    """
    import pandas as pd
    t = [pd.Timestamp(b["event_time_utc"]) for b in bars]
    c = [b["close"] for b in bars]
    v = [b.get("volume") or 0.0 for b in bars]
    return t, c, v


def volatility_points(bars: list, window: int = VOL_WINDOW) -> list:
    """CANONICAL VOLATILITY dimension: trailing realized volatility of
    log returns, in dimensionless per-bar units.

    Scale-invariant by construction (log returns), causal (bar i uses
    only bars <= i), and trailing-exclusive: the value stamped at time
    T is computed from returns ENDING at T, never including a future
    bar. Curve then takes its curvature of THIS series -- so the
    dimension expresses volatility *transition*, which is what a
    transition organ should consume.
    """
    t, c, _ = _bar_series(bars)
    rets = _returns(c)
    if len(rets) < window + 1:
        return []
    pts = []
    for i in range(window, len(rets) + 1):
        s = _stdev(rets[i - window:i])
        if s is not None:
            pts.append((t[i], s))          # t[i] = time of last bar used
    return pts if len(pts) >= MIN_SERIES else []


def correlation_points(subject_bars: list, market_bars: list,
                       window: int = CORR_WINDOW) -> list:
    """CANONICAL CORRELATION dimension: rolling Pearson correlation of
    subject vs market log returns.

    NOT relative strength. RS measures the DIFFERENCE in returns (does
    the subject outperform?); correlation measures whether the subject
    still MOVES WITH the market at all. A stock can outperform while
    decoupling, underperform while tightly coupled, or hold constant RS
    while its correlation collapses -- the redundancy property test
    proves these are independent.
    """
    ts, cs, _ = _bar_series(subject_bars)
    tm, cm, _ = _bar_series(market_bars)
    aligned = {}
    for t, c in zip(tm, cm):
        aligned[t] = c
    pairs = [(t, c, aligned[t]) for t, c in zip(ts, cs) if t in aligned]
    if len(pairs) < window + 2:
        return []
    times = [p[0] for p in pairs]
    rs = _returns([p[1] for p in pairs])
    rm = _returns([p[2] for p in pairs])
    pts = []
    for i in range(window, len(rs) + 1):
        a, b = rs[i - window:i], rm[i - window:i]
        sa, sb = _stdev(a), _stdev(b)
        if not sa or not sb:
            continue
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
        pts.append((times[i], cov / (sa * sb)))
    return pts if len(pts) >= MIN_SERIES else []


def cross_equity_complex_points(complex_bars: dict,
                                window: int = VOL_WINDOW) -> list:
    """PROXY -- deliberately NOT named cross_asset.

    Dispersion across the large/mega/small-cap equity complex
    (SPY/QQQ/IWM): the cross-sectional stdev of their trailing returns.
    Rising dispersion means the equity complex is disagreeing with
    itself. This is real information, and it is NOT cross-asset
    information -- no rates, FX, commodities or credit are in the store.
    """
    series = {k: _bar_series(v) for k, v in complex_bars.items()
              if v and len(v) > window + 1}
    if len(series) < 2:
        return []
    common = None
    for _k, (t, _c, _v) in series.items():
        s = set(t)
        common = s if common is None else (common & s)
    common = sorted(common or [])
    if len(common) < window + 2:
        return []
    closes = {k: {t: c for t, c in zip(v[0], v[1])}
              for k, v in series.items()}
    rets = {k: _returns([closes[k][t] for t in common]) for k in closes}
    pts = []
    for i in range(window, len(common) - 1):
        vals = [rets[k][i - 1] for k in rets if i - 1 < len(rets[k])]
        d = _stdev(vals)
        if d is not None:
            pts.append((common[i], d))
    return pts if len(pts) >= MIN_SERIES else []


def volume_pressure_proxy_points(bars: list,
                                 window: int = VOL_WINDOW) -> list:
    """PROXY -- deliberately NOT named flow.

    Signed displacement weighted by relative volume: sign(return) *
    |return| * (volume / trailing mean volume). With no aggressor data
    this cannot say who initiated; it says only that price moved on
    unusual participation. The name carries PROXY so no consumer can
    mistake it for order flow.
    """
    t, c, v = _bar_series(bars)
    if len(c) < window + 3:
        return []
    pts = []
    for i in range(window + 1, len(c)):
        base = sum(v[i - window:i]) / window
        if base <= 0 or not c[i - 1] or c[i - 1] <= 0 or c[i] <= 0:
            continue
        r = math.log(c[i] / c[i - 1])
        pts.append((t[i], r * (v[i] / base)))
    return pts if len(pts) >= MIN_SERIES else []


# what each feed is allowed to be called, and where it may go
FEED_SEMANTICS = {
    "volatility": {"kind": "CANONICAL",
                   "decision_authority": DECISION_AUTHORITY,
                   "dimension": "volatility",
                   "dependency_group": "VOLATILITY",
                   "reason_for_group": "derived from return dispersion, "
                                       "not from level or cross-section"},
    "correlation": {"kind": "CANONICAL",
                    "decision_authority": DECISION_AUTHORITY,
                    "dimension": "correlation",
                    "dependency_group": "CROSS_SECTIONAL",
                    "reason_for_group": "requires other subjects; shares "
                                        "the cross-sectional dependency "
                                        "with breadth/sector_leadership",
                    "redundancy_risk": "measured against relative_"
                                       "strength by property test"},
    "cross_equity_complex": {"kind": "PROXY", "dimension": None,
                             "dependency_group": "EXTERNAL_PROXY",
                             "law": "may NOT populate cross_asset"},
    "volume_pressure_proxy": {"kind": "PROXY", "dimension": None,
                              "dependency_group": "LIQUIDITY_FLOW_PROXY",
                              "law": "may NOT populate flow or liquidity"},
}
