"""HUNTER_MODEL_HISTORY_V1 — the variance model's input set, separated from the setup detector's.

WHY THIS IS A SEPARATE INPUT. ChartState and setup detection reason about TODAY: today's extension, today's
premarket levels, today's VWAP. The conditional variance model reasons about a SAMPLE, and its contract requires
MIN_OBS = 200 adjacent one-minute returns. Feeding it only today's bars means it cannot speak until roughly 200
minutes into the regular session. Measured on real SPY Alpaca bars for 2026-09-14:

    09:35 ET    4 returns  REFUSED        12:50 ET  194 returns  REFUSED
    10:30 ET   59 returns  REFUSED        14:00 ET  264 returns  SIMULATED_UNCALIBRATED

The open -- the part of the session the desk most needs a distribution for -- had none.

SO THE TWO INPUTS ARE SEPARATED. Today's frame still drives ChartState and the setup. The model gets its own
history: prior COMPLETED regular sessions read from the configured adapter's cache, plus today's live bars.

WHAT IS NOT RELAXED. MIN_OBS stays 200. The variance firewall stays. Nothing current-day and unfinished enters:
prior sessions are complete by construction, today's bars pass the same completed/visible test they always did,
and the adjacency rule still refuses to call a session junction a one-minute return -- which matters more here
than anywhere else, because widening the window is exactly what removes the market-date filter's protection.
"""
from __future__ import annotations

SCHEMA = "HUNTER_MODEL_HISTORY_V1"
DEFAULT_SESSIONS = 2          # prior completed sessions; 1 full session ~390 regular-hours returns


def prior_session_dates(as_of_epoch: float, sessions: int = DEFAULT_SESSIONS) -> list:
    """The `sessions` most recent COMPLETED trading dates strictly before the decision's market date."""
    import sys

    import pandas as pd
    sys.path.insert(0, "scripts")
    from nightly_pull import is_trading_day
    d = pd.Timestamp(as_of_epoch, unit="s", tz="UTC").tz_convert("America/New_York").normalize()
    out = []
    probe = d - pd.Timedelta(days=1)
    for _ in range(12):
        if len(out) >= sessions:
            break
        if is_trading_day(str(probe.date())):
            out.append(str(probe.date()))
        probe -= pd.Timedelta(days=1)
    return sorted(out)


def build(symbol: str, today_bars, *, as_of_epoch: float, gov,
          sessions: int = DEFAULT_SESSIONS, fetch=None):
    """Prior completed sessions (from the configured adapter/cache) + today's bars, in one frame.

    Returns (frame, provenance). A failure to read history is NEVER fatal: the caller falls back to today's bars
    and the provenance says why, because a silently narrowed sample is exactly the defect this module exists for.
    """
    import pandas as pd

    prov = {"schema": SCHEMA, "symbol": symbol, "sessions_requested": sessions}
    dates = prior_session_dates(as_of_epoch, sessions)
    prov["prior_sessions"] = dates
    frames, sources = [], []
    if dates:
        try:
            from apex.intraday.eodhd import fetch_intraday_chunk, normalize_rows
            f = fetch or fetch_intraday_chunk
            rows, src = f(symbol if symbol.endswith(".US") else symbol + ".US",
                          dates[0], dates[-1], gov)
            prior = normalize_rows(rows or [], symbol)
            if len(prior):
                # Keep ONLY the completed prior sessions. Anything stamped on or after the decision's market date
                # is today's business and must arrive through today's frame, which applies the visibility test.
                et = prior["event_time_utc"].dt.tz_convert("America/New_York")
                keep = et.dt.date.astype(str).isin(dates)
                prior = prior[keep]
                if len(prior):
                    frames.append(prior)
                    sources.append("adapter_cache:%s" % src)
            prov["prior_bars"] = int(sum(len(x) for x in frames))
        except Exception as e:                                       # noqa: BLE001
            prov["prior_history_unavailable"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    if today_bars is not None and len(today_bars):
        frames.append(today_bars)
        sources.append("today_live")
    prov["sources"] = sources
    if not frames:
        return None, prov
    out = pd.concat(frames, ignore_index=True).sort_values("event_time_utc", kind="stable")
    out = out.drop_duplicates(subset=["event_time_utc"], keep="last").reset_index(drop=True)
    prov["total_bars"] = int(len(out))
    prov["availability_basis"] = ("BAR_COMPLETION_ASSUMED_NOT_MEASURED_RECEIPT"
                                 if "available_epoch" not in out else
                                 "BAR_COMPLETION_AND_SUPPLIED_AVAILABILITY")
    return out, prov
