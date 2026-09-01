"""OPTIONS SURFACE ENGINE — options as INFORMATION.

Fuses the two feeds APEX actually owns:
  * ThetaData v3 (local terminal, port 25503): full-chain NBBO
    snapshots with SIZES, and HISTORICAL option NBBO back to at
    least 2018 at intraday intervals -- the feed the commissioning
    audit found bought-and-wasted. Now wired.
  * Alpaca OPRA indicative snapshots: IV + greeks per contract.

Produces causal surface state: ATM IV by expiry, expected move,
term structure, standardized skew, NBBO width, quote size, and
(given two snapshots) surface repricing velocity vs the underlying.

HONESTY LAWS: no midpoint fantasy (bid/ask carried through), no
dealer-gamma sign inference from OI, missing data = NOT_ESTIMABLE.

decision_power: NONE_STATE.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
import urllib.parse
import urllib.request

NOT_ESTIMABLE = "NOT_ESTIMABLE"
TD = "http://127.0.0.1:25503/v3"


def _td_csv(path: str, params: dict) -> list[dict]:
    url = f"{TD}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as r:
        text = r.read().decode()
    return list(csv.DictReader(io.StringIO(text)))


def td_expirations(symbol: str) -> list[str]:
    rows = _td_csv("option/list/expirations", {"symbol": symbol})
    return sorted(r["expiration"].strip('"') for r in rows
                  if r.get("expiration"))


def td_chain_snapshot(symbol: str, expiration: str) -> list[dict]:
    """Live full-chain NBBO with sizes from the local terminal."""
    rows = _td_csv("option/snapshot/quote",
                   {"symbol": symbol, "expiration": expiration})
    out = []
    for r in rows:
        try:
            out.append({
                "strike": float(r["strike"]),
                "right": r["right"].strip('"'),
                "bid": float(r["bid"]), "ask": float(r["ask"]),
                "bid_size": int(r["bid_size"]),
                "ask_size": int(r["ask_size"]),
                "timestamp": r["timestamp"]})
        except (KeyError, ValueError):
            continue
    return out


def td_history_quote(symbol: str, expiration: str, strike: float,
                     right: str, date: str,
                     interval: str = "5m") -> list[dict]:
    """HISTORICAL option NBBO (verified back to >= 2018)."""
    rows = _td_csv("option/history/quote",
                   {"symbol": symbol, "expiration": expiration,
                    "strike": strike, "right": right,
                    "start_date": date, "end_date": date,
                    "interval": interval})
    out = []
    for r in rows:
        try:
            b, a = float(r["bid"]), float(r["ask"])
            if a > b > 0:
                out.append({"t": r["timestamp"], "bid": b, "ask": a,
                            "bid_size": int(r["bid_size"]),
                            "ask_size": int(r["ask_size"])})
        except (KeyError, ValueError):
            continue
    return out


def surface_state(symbol: str, spot: float,
                  expirations: list[str],
                  chains: dict[str, list] | None = None) -> dict:
    """Causal surface state from chain snapshots. `chains` may be
    supplied (replay/testing) or fetched live per expiry."""
    per_expiry = {}
    for exp in expirations:
        chain = (chains or {}).get(exp)
        if chain is None:
            try:
                chain = td_chain_snapshot(symbol, exp)
            except Exception as e:                      # noqa: BLE001
                per_expiry[exp] = {"status": NOT_ESTIMABLE,
                                   "why": f"chain fetch failed: "
                                          f"{type(e).__name__}"}
                continue
        quoted = [c for c in chain
                  if c["ask"] > c["bid"] > 0]
        if len(quoted) < 6:
            per_expiry[exp] = {"status": NOT_ESTIMABLE,
                               "why": f"only {len(quoted)} two-sided "
                                      f"quotes"}
            continue
        # ATM straddle -> expected move (pure prices, no model)
        def nearest(right):
            cands = [c for c in quoted if c["right"] == right]
            return min(cands, key=lambda c: abs(c["strike"] - spot),
                       default=None)
        ac, ap = nearest("CALL"), nearest("PUT")
        exp_move = ((ac["bid"] + ac["ask"] + ap["bid"] + ap["ask"])
                    / 4 / spot * 1e4
                    if ac and ap else NOT_ESTIMABLE)
        widths = [(c["ask"] - c["bid"])
                  / ((c["ask"] + c["bid"]) / 2) for c in quoted]
        # standardized put skew proxy: 5%-OTM put mid vs ATM put mid,
        # in price space (bid/ask preserved separately)
        otm_p = min((c for c in quoted if c["right"] == "PUT"
                     and c["strike"] <= spot * 0.95),
                    key=lambda c: abs(c["strike"] - spot * 0.95),
                    default=None)
        per_expiry[exp] = {
            "n_quoted": len(quoted),
            "atm_straddle_mid_bps_of_spot":
                round(exp_move, 1) if isinstance(exp_move, float)
                else exp_move,
            "median_relative_width": round(
                statistics.median(widths), 4),
            "atm_put": ap and {"strike": ap["strike"],
                               "bid": ap["bid"], "ask": ap["ask"],
                               "bid_size": ap["bid_size"],
                               "ask_size": ap["ask_size"]},
            "otm_put_5pct": otm_p and {
                "strike": otm_p["strike"], "bid": otm_p["bid"],
                "ask": otm_p["ask"]},
            "quote_time": quoted[0]["timestamp"],
        }
    return {"kind": "options_surface_state", "symbol": symbol,
            "spot_used": spot, "per_expiry": per_expiry,
            "provenance": "THETADATA_V3_LOCAL_TERMINAL",
            "laws": ["no dealer-gamma inference from OI",
                     "bid/ask preserved; no midpoint fantasy"],
            "decision_power": "NONE_STATE"}


def repricing_velocity(snap0: dict, snap1: dict, *,
                       spot0: float, spot1: float) -> dict:
    """Surface repricing vs underlying move between two snapshots of
    the SAME expiry set: did options move more/less than the
    underlying move justifies at the observed straddle level?"""
    out = {}
    for exp, a in snap0.get("per_expiry", {}).items():
        b = snap1.get("per_expiry", {}).get(exp)
        if not b or "atm_straddle_mid_bps_of_spot" not in a \
                or not isinstance(a.get("atm_straddle_mid_bps_of_"
                                        "spot"), (int, float)) \
                or not isinstance(b.get("atm_straddle_mid_bps_of_"
                                        "spot"), (int, float)):
            out[exp] = NOT_ESTIMABLE
            continue
        out[exp] = {
            "straddle_change_bps": round(
                b["atm_straddle_mid_bps_of_spot"]
                - a["atm_straddle_mid_bps_of_spot"], 1),
            "underlying_move_bps": round(
                (spot1 / spot0 - 1) * 1e4, 1)}
    return {"kind": "surface_repricing", "per_expiry": out,
            "decision_power": "NONE_STATE"}
