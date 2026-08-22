"""DIGITAL WORLD (Twin 2.0) — the blueprint's richer terrain, computed
from data APEX already has, with typed absence for everything it doesn't.

Sections (PROFIT-MACHINE-BLUEPRINT): MARKET STRUCTURE (trend, breadth,
dispersion, CORRELATION, volatility, liquidity), LEADERSHIP (sector
ranking, concentration, RS concentration), RISK ENVIRONMENT (risk-on/off
via cyclical-vs-defensive spread, volatility transition, tail state),
INTRADAY STRUCTURE (gap environment, VWAP behavior, participation,
opening behavior), EVENT WORLD (DORMANT until a timestamped feed),
TRANSITION STATE (the DAILY ONLINE REGIME CLASSIFIER, wired at last:
SFP daily history bridged with daily closes derived from the cached
trailing 1m data — labels never revised, as-of prior session; PMF is
reported as label + uncertainty + boundary distances, never an invented
probability vector), SYSTEM STATE (PER-FACET freshness — the audit's
WEAK item — plus feed quality, model/calibration/execution health).

Twin 2.0 is OBSERVATIONAL: it records a richer world; it changes no
Epoch 1 decision. The capital caution proxy stays exactly the frozen
rule until a versioned ruling wires richer state into decisions
(Epoch 2). Every facet is either computed from real inputs or a typed
absence — never a fabricated neutral.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from apex.hunter.session_coverage import compute_session_coverage
from apex.intraday.sessions import Session, classify
from apex.world.state import classify_online

TWIN2_VERSION = "hunter_twin_v2"
SFP_SPY = Path("data/snapshots/sharadar/current/raw/SFP/SFP_SPY.csv")

CYCLICAL = ("XLK.US", "XLY.US", "XLF.US")
DEFENSIVE = ("XLP.US", "XLU.US", "XLV.US")


def _reg(f: pd.DataFrame) -> pd.DataFrame:
    return f[f["event_time_utc"].map(lambda t: classify(t) is
                                     Session.REGULAR)]


def load_spy_daily(today: str, trailing_1m: pd.DataFrame | None) -> pd.Series | None:
    """SFP daily closes bridged with session closes derived from the
    cached trailing 1m frame (PRIOR sessions only — as-of law)."""
    if not SFP_SPY.exists():
        return None
    sfp = pd.read_csv(SFP_SPY, usecols=["date", "close"])
    s = pd.Series(sfp["close"].to_numpy(),
                  index=pd.to_datetime(sfp["date"])).sort_index()
    if trailing_1m is not None and not trailing_1m.empty:
        reg = _reg(trailing_1m).copy()
        reg["d"] = (reg["event_time_utc"].dt.tz_convert("America/New_York")
                    .dt.date.astype(str))
        reg = reg[reg["d"] < today]                 # prior sessions only
        bridge = reg.groupby("d")["close"].last()
        bridge.index = pd.to_datetime(bridge.index)
        s = pd.concat([s[~s.index.isin(bridge.index)], bridge]).sort_index()
    return s


def transition_state(spy_daily: pd.Series | None, today: str,
                     lookback_sessions: int = 60) -> dict:
    """Online regime label as-of the PRIOR session, plus time-since-
    transition from re-running the (never-revised) classifier over the
    trailing window. No invented PMF: label + uncertainty + boundary
    distances, honestly."""
    if spy_daily is None or len(spy_daily) < 800:
        return {"status": "DAILY_SERIES_UNAVAILABLE"}
    asof = spy_daily.index[spy_daily.index < pd.Timestamp(today)].max()
    now_state = classify_online(spy_daily, asof)
    labels = []
    dates = spy_daily.index[spy_daily.index <= asof][-lookback_sessions:]
    for d in dates:
        labels.append(classify_online(spy_daily, d)["regime"])
    since = 0
    for lab in reversed(labels):
        if lab != labels[-1]:
            break
        since += 1
    return {"status": "ONLINE",
            "regime": now_state["regime"],
            "stress_overlay": now_state["stress"],
            "uncertain": now_state["uncertain"],
            "boundary_distances": {
                "trend_vs_sma": now_state["trend_vs_sma"],
                "vol_vs_threshold": round(
                    now_state["vol_20d"] / now_state["vol_threshold"] - 1, 4)
                if now_state["vol_threshold"] else None},
            "time_since_transition_sessions": since,
            "transitions_in_window": int(sum(
                1 for i in range(1, len(labels))
                if labels[i] != labels[i - 1])),
            "label_asof": now_state["date"],
            "pmf": {"status": "UNCALIBRATED_NOT_COMPUTED",
                    "note": "a probability vector would be invented; the "
                            "label + uncertainty flag is what is known"}}


def _sector_states(etf_frames: dict, now, today: str | None = None) -> dict:
    """SESSION INTEGRITY GATE (v1.2): day_return/above_vwap are the SAME
    class of session-anchored feature gated in apex/hunter/chartstate.py
    — computed here independently (Twin 2.0 does not route ETF frames
    through ChartState), so they need the SAME session_coverage check.
    Gated on session_anchor_valid; everything else (dollar_volume,
    last_bar_age_min, returns_1m -- a trailing series, no anchor needed)
    is unchanged."""
    out = {}
    for sym, f in etf_frames.items():
        reg = _reg(f)
        if reg.empty:
            continue
        px = reg["close"].astype(float)
        vol = reg["volume"].astype(float)
        vwap = float((px * vol).sum() / max(vol.sum(), 1))
        anchor_ok = True
        cov = None
        if today is not None:
            cov = compute_session_coverage(f, today, now)
            anchor_ok = cov.session_anchor_valid
        out[sym] = {
            "day_return": (float(px.iloc[-1] / px.iloc[0] - 1)
                          if anchor_ok else None),
            "above_vwap": bool(px.iloc[-1] > vwap) if anchor_ok else None,
            "session_anchor_valid": anchor_ok,
            "session_coverage": cov.as_record() if cov is not None else None,
            "dollar_volume": float((px * vol).sum()),
            "last_bar_age_min": float(
                (now - (reg["event_time_utc"].iloc[-1]
                        + pd.Timedelta(minutes=1))).total_seconds() / 60),
            "returns_1m": px.pct_change().dropna()}
    return out


def build_world(etf_frames: dict, now, today: str, *,
                universe_facets: dict | None = None,
                spy_daily: pd.Series | None = None,
                spy_atr_frac: float | None = None) -> dict:
    """One world_state record. `universe_facets` comes from the scan
    record (computed by the Scout over the whole universe)."""
    now = pd.Timestamp(now)
    st = _sector_states(etf_frames, now, today)
    spy = st.get("SPY.US", {})
    sectors = {k: v for k, v in st.items()
               if k not in ("SPY.US", "QQQ.US", "IWM.US")}
    # SESSION INTEGRITY GATE (v1.2): day_return is None for any symbol
    # whose session anchor is invalid (see _sector_states) -- every
    # aggregate below must exclude None rather than crash on it
    # (sorted()/np.mean()/abs() all raise on a None mixed with floats).
    # This is not cosmetic: an invalid-anchor morning is EXACTLY when
    # every sector's day_return goes None simultaneously.
    rets = {k: v["day_return"] for k, v in sectors.items()
           if v["day_return"] is not None}
    n_anchor_valid = sum(1 for v in st.values()
                        if v.get("session_anchor_valid"))
    observation_integrity = {
        "n_symbols": len(st), "n_session_anchor_valid": n_anchor_valid,
        "session_anchor_valid_frac": (round(n_anchor_valid / len(st), 2)
                                      if st else None),
        "healthy_session_state": bool(st) and n_anchor_valid == len(st)}
    absent = {"status": "INSUFFICIENT_INPUTS"}

    # correlation: mean pairwise corr of sector 1m returns, trailing 60m
    corr = absent
    mats = [v["returns_1m"].tail(60).reset_index(drop=True)
            for v in sectors.values() if len(v["returns_1m"]) >= 30]
    if len(mats) >= 4:
        m = pd.concat(mats, axis=1).dropna()
        if len(m) >= 20:
            c = m.corr().to_numpy()
            corr = {"mean_pairwise_60m": round(float(
                c[np.triu_indices_from(c, 1)].mean()), 3),
                "baseline": "NONE_YET (shock detection uncalibrated)"}

    ranked = sorted(rets.items(), key=lambda kv: -kv[1])
    spy_ret = spy.get("day_return")
    cyc = [rets[s] for s in CYCLICAL if s in rets]
    dfn = [rets[s] for s in DEFENSIVE if s in rets]
    vol_now = None
    if "returns_1m" in spy:
        r = spy["returns_1m"]
        if len(r) >= 5:
            vol_now = float(r.std() * np.sqrt(390 * 252))

    world = {
        "kind": "world_state", "twin_version": TWIN2_VERSION,
        "timestamp_utc": str(now), "session_date": today,
        "decision_power": "NONE_OBSERVATIONAL_EPOCH1",
        "market_structure": {
            "trend": {"spy_day_return": spy_ret,
                      "spy_above_vwap": spy.get("above_vwap")},
            "volatility": {"spy_realized_ann": round(vol_now, 4)
                           if vol_now else None,
                           "vs_atr_context": (round(vol_now / (spy_atr_frac
                                              * np.sqrt(252)), 2)
                                              if vol_now and spy_atr_frac
                                              else None)},
            "breadth": {"sectors_positive_frac": round(float(np.mean(
                [r > 0 for r in rets.values()])), 2) if rets else None},
            "dispersion": {"sector_return_std": round(float(np.std(
                list(rets.values()))), 5) if rets else None},
            "correlation": corr,
            "liquidity": {"etf_dollar_volume_total": round(float(sum(
                v["dollar_volume"] for v in st.values())), 0) or None},
        },
        "leadership": {
            "sector_ranking_top": ranked[:3],
            "sector_ranking_bottom": ranked[-3:],
            "leadership_concentration": (round(ranked[0][1] - float(
                np.median(list(rets.values()))), 5) if ranked else None),
            "industry_factor_leadership": {"status":
                                           "DORMANT_NO_CONSTITUENT_MAP"},
        },
        "risk_environment": {
            "risk_on_off_spread": (round(float(np.mean(cyc)
                                                - np.mean(dfn)), 5)
                                   if cyc and dfn else None),
            "volatility_transition": (
                "EXPANDING" if vol_now and spy_atr_frac
                and vol_now > 1.5 * spy_atr_frac * np.sqrt(252)
                else ("COMPRESSED" if vol_now and spy_atr_frac
                      and vol_now < 0.5 * spy_atr_frac * np.sqrt(252)
                      else ("NORMAL" if vol_now and spy_atr_frac
                            else None))),
            "tail_state": {"max_abs_sector_return": round(max(
                (abs(r) for r in rets.values()), default=0.0), 4)
                if rets else None},
            "correlation_shock": {"status": "UNCALIBRATED_NO_BASELINE"},
        },
        "intraday_structure": (universe_facets or
                               {"status": "SCOUT_FACETS_UNAVAILABLE"}),
        "observation_integrity": observation_integrity,
        "event_world": {"status": "DORMANT_NO_TIMESTAMPED_FEED"},
        "transition_state": transition_state(spy_daily, today),
        "system_state": {
            "per_facet_freshness_min": {k: round(v["last_bar_age_min"], 1)
                                        for k, v in st.items()},
            "feeds_present": f"{len(st)}/{len(etf_frames)}",
            "model_health": "see birth registry (append-only)",
            "calibration_health": "INSUFFICIENT_FORWARD_EVIDENCE",
            "execution_health": "SEALED_BY_DESIGN",
        },
    }
    return world
