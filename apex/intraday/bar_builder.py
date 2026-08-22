"""THE CANONICAL BAR BUILDER — one implementation of what a completed
1-minute equity bar means, shared by every realtime provider (Phase 0.4,
§13: "Do not let every provider invent its own meaning of a minute
bar"). Extracted from apex/intraday/equity_fabric.py's proven,
already-tested bars_1m() — behavior is unchanged there; this just gives
a second realtime provider the identical semantics without a second,
possibly-drifting implementation.

Contract: every provider's raw trade format is parsed into this ONE
common trade-record shape --

    {"event_s": float, "price": float, "size": float}

-- and build_1m_bars() does the rest, identically regardless of source:
completed-bar semantics (current wall-clock minute never emitted),
missing minutes stay missing, outage-aware coverage_status
(COMPLETE_HEALTHY / COMPLETE_WITH_GAP / INCOMPLETE), gap_duration_ms.
"""
from __future__ import annotations

MIN_TRADES_HEALTHY = 3
MAX_EDGE_GAP_S = 30.0
# Layer 3 commissioning (2026-08-21): 14 bars holding <95% of the
# official minute's volume self-labeled COMPLETE_HEALTHY -- a mid-minute
# transport loss leaves trades at both edges (edge_gap small) and no
# recorded outage window. A liquid symbol printing hundreds of times a
# minute does not legitimately go silent for 20s mid-bar; when it does,
# the bar must say COMPLETE_WITH_GAP.
MAX_INTRA_GAP_S = 20.0

# SALE-CONDITION HIGH/LOW ELIGIBILITY (2026-08-21, found by the
# independent outcome audit): SPY's 14:02 bar carried low=736.49 against
# open/high/close ~766 -- a single -3.9% print, absent from QQQ/IWM/XLK,
# that poisoned 16 of 24 MAE values in APEX's first outcome corpus. The
# builder was aggregating EVERY print into high/low; the SIP itself does
# not: CTA/UTP sale conditions mark trades (odd lots, derivative-priced,
# cash, seller, contingent, average-price, prior-reference, sold out of
# sequence, extended hours, market-center administrative prints) as NOT
# eligible to update high/low. This is the standard published exclusion
# set, not a fitted filter; trades keep counting toward volume/trades,
# and close/last semantics are deliberately unchanged tonight (the
# observed defect is high/low; widening the change to last-eligibility
# is future work, declared).
HIGH_LOW_INELIGIBLE_CONDITIONS = frozenset(
    "C G H I M N P Q R T U V W Z 4 7 9".split())


def _hl_eligible(conditions) -> bool:
    if not conditions:
        return True                        # regular-way trade
    if isinstance(conditions, str):
        conditions = [conditions]
    return not any(str(c).strip() in HIGH_LOW_INELIGIBLE_CONDITIONS
                   for c in conditions)


def build_1m_bars(trades: list, outages: list, *, now, symbol: str,
                  transport: str, minutes: int = 400):
    """`trades`: [{"event_s","price","size"}, ...], any order, may
    contain duplicates (caller's ingest layer is responsible for
    dedup/out-of-order counters; this function only needs correct
    values, it re-sorts defensively). `outages`: [(start_epoch,
    end_epoch), ...] intervals with no data, e.g. a disconnect."""
    import pandas as pd
    if not trades:
        return pd.DataFrame()
    f = pd.DataFrame(trades)
    f["ts"] = pd.to_datetime(f["event_s"], unit="s", utc=True)
    f = f.set_index("ts").sort_index()
    now_min = pd.Timestamp(now).floor("1min")
    g = f.resample("1min")

    # high/low from ELIGIBLE prints only; open/close/volume/trades from
    # all prints (unchanged semantics). A minute whose every print is
    # ineligible falls back to the unfiltered high/low rather than
    # emitting an empty price -- rare, and honest about what printed.
    if "conditions" in f.columns:
        f["_hl_ok"] = f["conditions"].map(_hl_eligible)
    else:
        f["_hl_ok"] = True
    el = f[f["_hl_ok"]].resample("1min")
    hi = el["price"].max().combine_first(g["price"].max())
    lo = el["price"].min().combine_first(g["price"].min())

    bars = pd.DataFrame({
        "open": g["price"].first(), "high": hi,
        "low": lo, "close": g["price"].last(),
        "volume": g["size"].sum(), "trades": g["price"].count(),
    }).dropna(subset=["close"])
    bars = bars[bars.index < now_min]              # completed only
    if not len(bars):
        return pd.DataFrame()
    first_t = g["price"].apply(lambda x: x.index.min() if len(x) else None)
    last_t = g["price"].apply(lambda x: x.index.max() if len(x) else None)
    # largest silence between consecutive prints WITHIN the minute
    max_intra = g["price"].apply(
        lambda x: (x.index.to_series().diff().dt.total_seconds().max()
                   if len(x) > 1 else 0.0))
    bars = bars.reset_index().rename(columns={"ts": "event_time_utc"})
    cov, gap_ms = [], []
    for _, row in bars.iterrows():
        b0 = row["event_time_utc"]
        b1 = b0 + pd.Timedelta(minutes=1)
        overlap = 0.0
        for o0, o1 in outages:
            s0, s1 = max(b0.timestamp(), o0), min(b1.timestamp(), o1)
            if s1 > s0:
                overlap += (s1 - s0)
        ft, lt = first_t.get(b0), last_t.get(b0)
        edge_gap = 0.0
        if ft is not None and lt is not None and pd.notna(ft):
            edge_gap = ((ft - b0).total_seconds()
                        + (b1 - lt).total_seconds())
        gap_ms.append(round((overlap + max(0.0, edge_gap - 10)) * 1000))
        intra = max_intra.get(b0, 0.0) or 0.0
        if overlap > 0:
            cov.append("COMPLETE_WITH_GAP")
        elif row["trades"] < MIN_TRADES_HEALTHY or edge_gap > MAX_EDGE_GAP_S:
            cov.append("INCOMPLETE")
        elif intra > MAX_INTRA_GAP_S:
            cov.append("COMPLETE_WITH_GAP")
            gap_ms[-1] = max(gap_ms[-1], round(intra * 1000))
        else:
            cov.append("COMPLETE_HEALTHY")
    bars["coverage_status"] = cov
    bars["gap_duration_ms"] = gap_ms
    bars["symbol"] = symbol
    bars["transport"] = transport
    return bars.tail(minutes)
