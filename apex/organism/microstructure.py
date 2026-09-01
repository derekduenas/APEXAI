"""SIP MICROSTRUCTURE ENGINE — causal state from the raw tape.

Turns tick-level SIP trades and NBBO quotes (Alpaca REST historical,
or any equivalent event stream) into the causal state the operator
mandated: intensities, spread dynamics, NBBO size imbalance,
microprice displacement, signed trade pressure, impact per unit flow,
liquidity consumption/replenishment, abnormal arrival, short-horizon
vol.

HONESTY LAWS
  * SIP gives top-of-book only. Nothing here claims depth, queue,
    or cancellation truth; proxies are labeled as proxies.
  * Trade signing uses the QUOTE RULE (trade at/above ask = buy,
    at/below bid = sell) with a midpoint TICK-RULE fallback --
    documented, causal (uses the latest quote at/before the trade),
    imperfect by construction. This is the standard Lee-Ready family
    and its error rate is a known limitation, not hidden.
  * A measure whose inputs are missing is NOT_ESTIMABLE.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import urllib.parse
import urllib.request

NOT_ESTIMABLE = "NOT_ESTIMABLE"
DATA = "https://data.alpaca.markets/v2/stocks"


def _get(url: str) -> dict:
    key = os.environ.get("APCA_API_KEY_ID")
    sec = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not sec:
        raise RuntimeError("no data credentials in environment")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_ticks(symbol: str, start: str, end: str, *,
                what: str = "trades", limit: int = 10000,
                max_pages: int = 10) -> list:
    """Historical SIP ticks, paged. `what` in (trades, quotes)."""
    out, token = [], None
    for _ in range(max_pages):
        q = {"start": start, "end": end, "limit": limit,
             "feed": "sip"}
        if token:
            q["page_token"] = token
        d = _get(f"{DATA}/{symbol}/{what}?"
                 + urllib.parse.urlencode(q))
        out.extend(d.get(what, []))
        token = d.get("next_page_token")
        if not token:
            break
    return out


def _sign_trades(trades: list, quotes: list) -> list:
    """Quote-rule signing with tick-rule fallback (documented,
    causal: latest quote at/before each trade)."""
    signed, qi, last_mid, last_px, last_sign = [], 0, None, None, 0
    for t in trades:
        while qi < len(quotes) and quotes[qi]["t"] <= t["t"]:
            q = quotes[qi]
            if q.get("bp") and q.get("ap"):
                last_mid = (q["bp"] + q["ap"]) / 2
                last_bid, last_ask = q["bp"], q["ap"]
            qi += 1
        px = t["p"]
        if last_mid is not None:  # last_bid/last_ask set with it
            if px >= last_ask:
                s = 1
            elif px <= last_bid:
                s = -1
            elif px > last_mid:
                s = 1
            elif px < last_mid:
                s = -1
            else:
                s = (1 if last_px is not None and px > last_px
                     else -1 if last_px is not None and px < last_px
                     else last_sign)
        else:
            s = (1 if last_px is not None and px > last_px
                 else -1 if last_px is not None and px < last_px
                 else 0)
        signed.append({**t, "sign": s, "mid": last_mid})
        last_px, last_sign = px, s or last_sign
    return signed


def micro_state(trades: list, quotes: list, *,
                window_label: str = "") -> dict:
    """Causal microstructure state over one window of ticks.
    Everything computed from what is actually present."""
    out = {"kind": "micro_state", "window": window_label,
           "n_trades": len(trades), "n_quotes": len(quotes),
           "decision_power": "NONE_STATE"}
    if len(trades) < 20 or len(quotes) < 20:
        out["status"] = NOT_ESTIMABLE
        out["why"] = "fewer than 20 trades or quotes in window"
        return out

    # time span in seconds
    def _ts(x):
        s = x["t"].replace("Z", "")
        # nanosecond ISO -> seconds float
        base, _, frac = s.partition(".")
        from datetime import datetime
        dt = datetime.fromisoformat(base)
        return dt.timestamp() + (float("0." + frac[:6])
                                 if frac else 0.0)
    span = max(_ts(trades[-1]) - _ts(trades[0]), 1e-9)

    good_q = [q for q in quotes if q.get("bp") and q.get("ap")
              and q["ap"] > q["bp"] > 0]
    if len(good_q) < 20:
        out["status"] = NOT_ESTIMABLE
        out["why"] = "fewer than 20 valid two-sided NBBO quotes"
        return out

    spreads = [(q["ap"] - q["bp"]) / ((q["ap"] + q["bp"]) / 2) * 1e4
               for q in good_q]
    mids = [(q["ap"] + q["bp"]) / 2 for q in good_q]

    # PULSE-001 (2026-09-01). These two features are SIZE-DEPENDENT and
    # previously read `q.get("bs", 0)`, which turns "size unknown" into
    # "size is zero": the imbalance then reports a PERFECTLY BALANCED
    # book and the microprice collapses to 0.0, yielding a fabricated
    # -10000 bps displacement with no status flag. Missing is not zero.
    # Spread, returns, flow and intensity do not depend on size and are
    # computed regardless.
    sized_q = [q for q in good_q
               if isinstance(q.get("bs"), (int, float))
               and isinstance(q.get("as"), (int, float))
               and (q["bs"] + q["as"]) > 0]
    if len(sized_q) < 20:
        imbal, micro_disp, sized_mids = [], [], []
    else:
        sized_mids = [(q["ap"] + q["bp"]) / 2 for q in sized_q]
        imbal = [(q["bs"] - q["as"]) / (q["bs"] + q["as"])
                 for q in sized_q]
        # microprice = size-weighted touch price
        micro = [(q["ap"] * q["bs"] + q["bp"] * q["as"])
                 / (q["bs"] + q["as"]) for q in sized_q]
        micro_disp = [(m - md) / md * 1e4
                      for m, md in zip(micro, sized_mids)]

    signed = _sign_trades(trades, quotes)
    buy_v = sum(t["s"] for t in signed if t["sign"] > 0)
    sell_v = sum(t["s"] for t in signed if t["sign"] < 0)
    net_flow = buy_v - sell_v

    # impact per unit flow: mid change over window / |signed volume|
    mid0, mid1 = mids[0], mids[-1]
    ret_bps = (mid1 / mid0 - 1) * 1e4
    impact = (ret_bps / net_flow * 1000
              if net_flow else NOT_ESTIMABLE)

    # short-horizon realized vol from mid changes (per-minute bps)
    rets = [math.log(b / a) * 1e4 for a, b in zip(mids, mids[1:])
            if a > 0]
    rv = (statistics.pstdev(rets) * math.sqrt(
        max(len(rets) / (span / 60), 1e-9))
        if len(rets) >= 10 else NOT_ESTIMABLE)

    half = len(good_q) // 2
    touch_sz = [q["bs"] + q["as"] for q in sized_q]
    out.update({
        "trade_intensity_per_s": round(len(trades) / span, 3),
        "quote_intensity_per_s": round(len(quotes) / span, 3),
        "spread_bps_median": round(statistics.median(spreads), 3),
        "spread_bps_change": round(
            statistics.median(spreads[half:])
            - statistics.median(spreads[:half]), 3),
        "nbbo_imbalance_mean": (round(statistics.mean(imbal), 4)
                                if imbal else NOT_ESTIMABLE),
        "microprice_disp_bps_mean": (
            round(statistics.mean(micro_disp), 4)
            if micro_disp else NOT_ESTIMABLE),
        "signed_buy_volume": buy_v,
        "signed_sell_volume": sell_v,
        "net_signed_volume": net_flow,
        "signing_method": "QUOTE_RULE_WITH_TICK_FALLBACK "
                          "(Lee-Ready family; known error rate)",
        "mid_return_bps": round(ret_bps, 2),
        "impact_bps_per_1k_signed": (round(impact, 4)
                                     if isinstance(impact, float)
                                     else impact),
        "touch_size_change_frac": (
            round((statistics.median(touch_sz[len(touch_sz) // 2:]) + 1)
                  / (statistics.median(touch_sz[:len(touch_sz) // 2])
                     + 1) - 1, 4)
            if len(touch_sz) >= 4 else NOT_ESTIMABLE),
        "touch_size_note": "PROXY: top-of-book quoted size only; "
                           "not depth, not queue, not cancels",
        "sized_quote_count": len(sized_q),
        "size_data_quality": ("VALID" if len(sized_q) >= 20
                              else "NOT_ESTIMABLE: fewer than 20 "
                                   "size-bearing NBBO quotes; "
                                   "size-dependent features withheld "
                                   "rather than zero-filled"),
        "short_horizon_vol_bps_per_min": (round(rv, 2)
                                          if isinstance(rv, float)
                                          else rv),
        "abnormal_trade_size": round(
            max(t["s"] for t in trades)
            / max(statistics.median(t["s"] for t in trades), 1), 1),
    })
    return out
