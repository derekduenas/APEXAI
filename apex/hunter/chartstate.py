"""ChartState — what a chart-literate observer knows about one stock AT T.

Every feature is computed strictly as-of T through ONE choke point
(`visible_bars`): a 1m bar timestamped t covers [t, t+1m) and becomes
visible only at t+1m (completion), matching the replay kernel's law. The
day's high after T, the day's final volume, and the final VWAP are
structurally unreachable — the counterexample tests inject a monster bar
after T and require every field to be unchanged.

Daily context (previous-day/weekly levels, ATR, volume baselines) comes
from a separate DailyContext computed from PRIOR sessions only, plus
today's premarket. Missing context degrades data_quality flags; it never
silently fabricates a neutral value (fail closed lives downstream in the
scanner's data-quality gate).

feature_schema_version identifies this exact field set + computation; any
change to either is a NEW schema version with a NEW birth.

SESSION-ANCHORED FEATURE VALIDITY (v1.2): every field whose semantics
require history from the TRUE exchange session open (vwap and its
derivatives, opening range and its derivatives, gap and its derivatives,
rvol_tod, cum_volume, day_return) is computed EXACTLY as before, THEN
gated on `session_coverage.session_anchor_valid` (apex/hunter/
session_coverage.py, built on the true 09:30 ET calendar boundary, never
inferred from where bars happen to start). Invalid -> the field reads
None, and `feature_validity[name]` carries a typed
{status, reason} pair — never a silently-corrupted number, never zero.
Trailing-window features (r_1m..r_60m, trend_slope, hh_hl/lh_ll,
realized_vol_ann, range_so_far_frac, range_vs_atr) need no session
anchor and are UNCHANGED by this gate; on a normal session where the
true open was observed, session_anchor_valid is True and every
session-anchored field computes byte-identically to v1 — this gate adds
a filter, it does not change a formula.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from apex.hunter.session_coverage import compute_session_coverage
from apex.intraday.sessions import Session, classify

# v1.2 (SESSION INTEGRITY HARDENING, 2026-08-17 Day-1 defect): open_t used
# to BE the session anchor (first visible bar == market open, always).
# session_coverage.compute_session_coverage() now supplies the TRUE
# exchange-calendar session_open independently of what bars happen to
# exist; session-anchored features (vwap/or/gap/rvol/cum_volume/
# day_return) are gated on session_anchor_valid and read None + a typed
# reason, never a number computed from the wrong anchor. Trailing-window
# features (r_Nm, trend_slope, realized_vol_ann, ...) are UNCHANGED — see
# feature_validity docstring below for the full contract.
FEATURE_SCHEMA_VERSION = "hunter_feature_schema_v1.2"

BAR = pd.Timedelta(minutes=1)
OPENING_RANGE_MINUTES = 30          # frozen: classic 30m opening range
STRUCTURE_LOOKBACK_MIN = 15         # VWAP reclaim/rejection memory
TREND_WINDOW_MIN = 60               # trend slope fit window


def visible_bars(bars: pd.DataFrame, t_utc) -> pd.DataFrame:
    """THE as-of choke point: bars complete (start + 1m <= T), today's
    regular session only. Every feature reads from this frame or from
    DailyContext; nothing else touches raw bars."""
    t = pd.Timestamp(t_utc)
    if t.tzinfo is None:
        raise ValueError("as-of time must be tz-aware")
    if bars.empty:
        # LAB-01: an empty frame (symbol not yet listed / vendor gap) has
        # object-dtype columns; comparing would TypeError and kill the
        # whole scan tick. No bars = no state, for one symbol only.
        return bars
    f = bars[bars["event_time_utc"] + BAR <= t]
    return f[f["event_time_utc"].map(
        lambda x: classify(x) is Session.REGULAR)].reset_index(drop=True)


@dataclass(frozen=True)
class DailyContext:
    """Everything from BEFORE today's open (plus today's premarket).
    Built by the daily-context builder from prior-session bars; each field
    may be None when the data does not exist — never defaulted."""

    symbol: str
    as_of_date: str
    prev_day_high: float | None = None
    prev_day_low: float | None = None
    prev_close: float | None = None
    weekly_high: float | None = None       # prior 5 sessions, excl. today
    weekly_low: float | None = None
    premarket_high: float | None = None    # today, PRE session only
    premarket_low: float | None = None
    atr_frac: float | None = None          # mean daily true range / close
    median_day_range_frac: float | None = None
    cum_vol_by_minute: dict = field(default_factory=dict)  # min-of-day -> median cum vol
    median_dollar_volume: float | None = None
    sector_etf: str | None = None
    sessions_observed: int = 0


@dataclass(frozen=True)
class ChartState:
    symbol: str
    t_utc: str
    price: float
    minutes_into_session: int
    # price structure (simple returns over trailing windows, as-of T)
    r_1m: float | None
    r_5m: float | None
    r_15m: float | None
    r_30m: float | None
    r_60m: float | None
    day_return: float | None               # vs today's first visible open
    # vwap
    vwap: float | None
    distance_to_vwap: float | None         # (px - vwap)/vwap
    vwap_slope: float | None               # d(vwap)/vwap over last 15m
    above_vwap: bool | None
    vwap_reclaim: bool                     # below -> above within last 15m
    vwap_rejection: bool                   # above -> below within last 15m
    # opening range
    or_complete: bool
    or_high: float | None
    or_low: float | None
    position_in_or: float | None           # 0 at OR low, 1 at OR high
    or_break_up: bool
    or_break_down: bool
    or_failure: bool                       # broke out, then back inside
    # levels (prior sessions + premarket)
    prev_day_high: float | None
    prev_day_low: float | None
    prev_close: float | None
    premarket_high: float | None
    premarket_low: float | None
    weekly_high: float | None
    weekly_low: float | None
    # volatility
    atr_frac: float | None                 # daily, from context
    realized_vol_ann: float | None         # today, 1m bars, as-of T
    range_so_far_frac: float | None
    range_vs_atr: float | None             # expansion >1, compression <1
    # volume
    cum_volume: float | None
    rvol_tod: float | None                 # vs time-of-day median baseline
    volume_accel: float | None             # last 15m vol / prior 15m vol
    dollar_volume_today: float | None
    # trend structure (5m aggregation)
    trend_slope: float | None              # frac/hour, fit over last 60m
    hh_hl: bool                            # last three 5m bars ascending
    lh_ll: bool
    # gap
    gap_frac: float | None                 # today open vs prev close
    gap_direction: str | None              # UP / DOWN / NONE
    gap_fill_frac: float | None            # fraction of gap retraced, [0,+)
    # liquidity / quality
    median_dollar_volume: float | None
    minutes_recorded: int
    minutes_missing_frac: float | None
    last_bar_age_min: float
    data_quality: tuple = ()
    session_coverage: dict = field(default_factory=dict)
    feature_validity: dict = field(default_factory=dict)
    feature_schema_version: str = FEATURE_SCHEMA_VERSION

    def as_record(self) -> dict:
        return asdict(self)


def _ret(px: pd.Series, times: pd.Series, t, minutes: int) -> float | None:
    cutoff = t - pd.Timedelta(minutes=minutes)
    base = px[times + BAR <= cutoff]
    if base.empty:
        return None
    return float(px.iloc[-1] / base.iloc[-1] - 1)


def compute_chart_state(symbol: str, bars: pd.DataFrame, t_utc,
                        ctx: DailyContext) -> ChartState | None:
    """None when no regular bars are visible yet (state does not exist)."""
    t = pd.Timestamp(t_utc)
    f = visible_bars(bars, t)
    if f.empty:
        return None
    px = f["close"].astype(float)
    hi, lo = f["high"].astype(float), f["low"].astype(float)
    vol = f["volume"].astype(float)
    times = f["event_time_utc"]
    price = float(px.iloc[-1])
    quality: list = []

    open_t = times.iloc[0]
    day_open = float(f["open"].astype(float).iloc[0])

    # SESSION INTEGRITY GATE: the TRUE exchange-calendar anchor, never
    # inferred from open_t. minutes_into_session derives from THIS,
    # unconditionally -- it needs no bars at all, only the calendar and
    # the current event time (test U: correct even when anchor invalid).
    session_cov = compute_session_coverage(bars, ctx.as_of_date, t)
    anchor_ok = session_cov.session_anchor_valid
    if session_cov.session_open is not None:
        minutes_in = int((t - pd.Timestamp(session_cov.session_open))
                         .total_seconds() // 60)
    else:                                       # non-trading day: defensive
        minutes_in = int((t - open_t).total_seconds() // 60)

    # vwap path (as-of by construction: cumulative over visible bars)
    tp = (hi + lo + px) / 3
    cum_v = vol.cumsum()
    vwap_path = (tp * vol).cumsum() / cum_v.replace(0, np.nan)
    vwap = float(vwap_path.iloc[-1]) if np.isfinite(vwap_path.iloc[-1]) else None
    above = (price > vwap) if vwap is not None else None
    look = times + BAR > t - pd.Timedelta(minutes=STRUCTURE_LOOKBACK_MIN)
    rel = (px[look] > vwap_path[look])
    reclaim = bool(len(rel) >= 2 and (~rel.iloc[0]) and rel.iloc[-1])
    rejection = bool(len(rel) >= 2 and rel.iloc[0] and (~rel.iloc[-1]))
    slope_base = vwap_path[look]
    vwap_slope = (float((slope_base.iloc[-1] - slope_base.iloc[0])
                        / slope_base.iloc[0])
                  if len(slope_base) >= 2 and vwap is not None else None)

    # opening range: window is defined by the TRUE session open, never
    # by open_t (the first VISIBLE bar) -- a fake OR can never complete
    # from a late-starting feed (test Q)
    or_anchor = (pd.Timestamp(session_cov.session_open)
                if session_cov.session_open is not None else open_t)
    or_end = or_anchor + pd.Timedelta(minutes=OPENING_RANGE_MINUTES)
    or_mask = times < or_end
    or_complete = bool(anchor_ok and t >= or_end + BAR and or_mask.any())
    or_high = float(hi[or_mask].max()) if or_complete else None
    or_low = float(lo[or_mask].min()) if or_complete else None
    pos_in_or = or_break_up = or_break_down = or_failure = None
    if or_complete and or_high is not None and or_high > or_low:
        pos_in_or = float((price - or_low) / (or_high - or_low))
        post = px[~or_mask]
        or_break_up = bool((post > or_high).any())
        or_break_down = bool((post < or_low).any())
        broke = or_break_up or or_break_down
        or_failure = bool(broke and or_low <= price <= or_high)
    or_break_up = bool(or_break_up) if or_break_up is not None else False
    or_break_down = bool(or_break_down) if or_break_down is not None else False
    or_failure = bool(or_failure) if or_failure is not None else False

    # volatility
    r = px.pct_change().dropna()
    rvol_ann = (float(r.std() * np.sqrt(390 * 252)) if len(r) >= 5 else None)
    day_hi, day_lo = float(hi.max()), float(lo.min())
    range_frac = (day_hi - day_lo) / price if price else None
    range_vs_atr = (range_frac / ctx.atr_frac
                    if range_frac is not None and ctx.atr_frac else None)
    if ctx.atr_frac is None:
        quality.append("NO_ATR_CONTEXT")

    # volume
    cum_volume = float(vol.sum())
    rvol = None
    if ctx.cum_vol_by_minute:
        base = ctx.cum_vol_by_minute.get(str(min(minutes_in, 389)))
        if base:
            rvol = float(cum_volume / base)
        else:
            quality.append("NO_RVOL_BASELINE_AT_MINUTE")
    else:
        quality.append("NO_RVOL_BASELINE")
    last15 = vol[times + BAR > t - pd.Timedelta(minutes=15)].sum()
    prior15 = vol[(times + BAR > t - pd.Timedelta(minutes=30))
                  & (times + BAR <= t - pd.Timedelta(minutes=15))].sum()
    vaccel = float(last15 / prior15) if prior15 > 0 else None
    dollar_vol = float((px * vol).sum())

    # trend structure on 5m closes over the trend window
    w = f[times + BAR > t - pd.Timedelta(minutes=TREND_WINDOW_MIN)]
    trend_slope = hh = ll = None
    if len(w) >= 10:
        w5 = (w.set_index("event_time_utc")
               .resample("5min", label="right", closed="right"))
        c5, h5, l5 = w5["close"].last().dropna(), w5["high"].max().dropna(), \
            w5["low"].min().dropna()
        if len(c5) >= 3:
            x = np.arange(len(c5), dtype=float)
            beta = np.polyfit(x, c5.to_numpy(dtype=float), 1)[0]
            trend_slope = float(beta / price * 12)          # frac per hour
            hh = bool((h5.iloc[-3:].diff().dropna() > 0).all()
                      and (l5.iloc[-3:].diff().dropna() > 0).all())
            ll = bool((h5.iloc[-3:].diff().dropna() < 0).all()
                      and (l5.iloc[-3:].diff().dropna() < 0).all())
    hh = bool(hh) if hh is not None else False
    ll = bool(ll) if ll is not None else False

    # gap vs prior close (context; None when context missing)
    gap = gap_dir = gap_fill = None
    if ctx.prev_close:
        gap = float(day_open / ctx.prev_close - 1)
        gap_dir = "UP" if gap > 0 else ("DOWN" if gap < 0 else "NONE")
        if abs(gap) > 1e-9:
            gap_fill = float(max(0.0, (day_open - price) / (day_open - ctx.prev_close)))
    else:
        quality.append("NO_PREV_CLOSE")

    age_min = float((t - (times.iloc[-1] + BAR)).total_seconds() / 60)
    if age_min > 10:
        quality.append("STALE_BARS")
    missing = 1.0 - len(f) / max(minutes_in, 1) if minutes_in > 0 else None
    if missing is not None and missing > 0.2:
        quality.append("SPARSE_BARS")

    # SESSION INTEGRITY GATE (v1.2), the ONLY place this schema version
    # changes prior behavior: every formula above is untouched (byte-
    # identical to v1 whenever anchor_ok is True, i.e. the true session
    # open was observed -- see test_chartstate_session_integrity.py's
    # full-session equivalence proof). Invalid -> the local variables
    # feeding the session-anchored fields below are overridden to
    # None/False so the return statement's existing expressions (e.g.
    # `distance_to_vwap=(price/vwap-1) if vwap else None`) cascade
    # correctly with zero further changes.
    invalid_reason = (
        f"observation began {session_cov.observed_start}, true session "
        f"open {session_cov.session_open}" if session_cov.observed_start
        else "session open never observed")
    if not anchor_ok:
        vwap = vwap_slope = None
        above = None
        reclaim = rejection = False
        or_high = or_low = pos_in_or = None
        or_break_up = or_break_down = or_failure = False
        gap = gap_dir = gap_fill = None
        rvol = None
        cum_volume = None
        day_open = None

    feature_validity = {}
    for _name in ("vwap", "distance_to_vwap", "vwap_slope", "above_vwap",
                 "vwap_reclaim", "vwap_rejection", "or_complete", "or_high",
                 "or_low", "position_in_or", "or_break_up", "or_break_down",
                 "or_failure", "gap_frac", "gap_direction", "gap_fill_frac",
                 "rvol_tod", "cum_volume", "day_return"):
        feature_validity[_name] = (
            {"status": "VALID", "reason": None} if anchor_ok else
            {"status": "INVALID_MISSING_SESSION_START",
             "reason": invalid_reason})
    feature_validity["minutes_into_session"] = {
        "status": "VALID",
        "reason": "derived from exchange calendar, independent of bars"}
    for _name, _val in (("r_1m", _ret(px, times, t, 1)),
                        ("r_5m", _ret(px, times, t, 5)),
                        ("r_15m", _ret(px, times, t, 15)),
                        ("r_30m", _ret(px, times, t, 30)),
                        ("r_60m", _ret(px, times, t, 60)),
                        ("trend_slope", trend_slope),
                        ("realized_vol_ann", rvol_ann)):
        feature_validity[_name] = (
            {"status": "VALID", "reason": None} if _val is not None else
            {"status": "NOT_YET_AVAILABLE",
             "reason": "insufficient trailing bars"})

    return ChartState(
        symbol=symbol, t_utc=str(t), price=price,
        minutes_into_session=minutes_in,
        session_coverage=session_cov.as_record(),
        feature_validity=feature_validity,
        r_1m=_ret(px, times, t, 1), r_5m=_ret(px, times, t, 5),
        r_15m=_ret(px, times, t, 15), r_30m=_ret(px, times, t, 30),
        r_60m=_ret(px, times, t, 60),
        day_return=float(price / day_open - 1) if day_open else None,
        vwap=vwap,
        distance_to_vwap=(price / vwap - 1) if vwap else None,
        vwap_slope=vwap_slope, above_vwap=above,
        vwap_reclaim=reclaim, vwap_rejection=rejection,
        or_complete=or_complete, or_high=or_high, or_low=or_low,
        position_in_or=pos_in_or, or_break_up=or_break_up,
        or_break_down=or_break_down, or_failure=or_failure,
        prev_day_high=ctx.prev_day_high, prev_day_low=ctx.prev_day_low,
        prev_close=ctx.prev_close, premarket_high=ctx.premarket_high,
        premarket_low=ctx.premarket_low, weekly_high=ctx.weekly_high,
        weekly_low=ctx.weekly_low,
        atr_frac=ctx.atr_frac, realized_vol_ann=rvol_ann,
        range_so_far_frac=range_frac, range_vs_atr=range_vs_atr,
        cum_volume=cum_volume, rvol_tod=rvol, volume_accel=vaccel,
        dollar_volume_today=dollar_vol,
        trend_slope=trend_slope, hh_hl=hh, lh_ll=ll,
        gap_frac=gap, gap_direction=gap_dir, gap_fill_frac=gap_fill,
        median_dollar_volume=ctx.median_dollar_volume,
        minutes_recorded=len(f), minutes_missing_frac=missing,
        last_bar_age_min=age_min, data_quality=tuple(quality))
