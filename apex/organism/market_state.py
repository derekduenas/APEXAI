"""UNIVERSAL MARKET STATE — one provenance-carrying snapshot.

A thin COMPOSER over organs that already exist: Regime Atlas (causal,
trailing-only), Catalyst context (as-of fenced), the paper book, the
BTC fabric ledgers, and the observed toll surface. It invents no
measurements: every field arrives with provenance and known_from, or
it is UNKNOWN / NOT_IMPLEMENTED. UNKNOWN != 0 and no consumer may
coerce it.

Sections mirror the operator's state taxonomy; sections whose sensing
does not exist yet say so instead of pretending.

decision_power: NONE_COMPOSER.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REGIME_ATLAS = Path("exports/regime_atlas_v1.jsonl")
BTC_FABRIC = Path("results/btc/paper_ledger.jsonl")
TOLL = Path("/apex-data/history-b/pit_singlename/"
            "movement_toll_obs.jsonl")

NOT_IMPLEMENTED = {"status": "NOT_IMPLEMENTED"}


def _field(value, *, known_from, provenance, quality="OBSERVED"):
    return {"value": value, "known_from": str(known_from),
            "provenance": provenance, "quality": quality}


def _regime(as_of_date: str, atlas: Path) -> dict:
    """Last atlas row at or before the date. Trailing-only by the
    atlas's own construction, so <= is causal."""
    if not atlas.exists():
        return {"status": "UNKNOWN", "why": "regime atlas absent"}
    best = None
    for line in atlas.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("session", "9999") <= as_of_date and (
                best is None or r["session"] > best["session"]):
            best = r
    if best is None:
        return {"status": "UNKNOWN", "why": "no atlas row <= as_of"}
    keep = {k: best[k] for k in
            ("session", "trend", "vol", "dispersion", "correlation",
             "breadth", "event_density") if k in best}
    return _field(keep, known_from=best["session"],
                  provenance="exports/regime_atlas_v1.jsonl "
                             "(descriptive-first; context before "
                             "authority)")


def _catalyst(symbol: str | None, as_of: str) -> dict:
    if symbol is None:
        return {"status": "UNKNOWN", "why": "no subject given"}
    try:
        from apex.catalyst import context as cc
        ctx = cc.context(symbol=symbol, as_of=as_of)
        return _field({k: ctx.get(k) for k in
                       ("environment", "directional_support",
                        "events_known", "reaction_disagreements")},
                      known_from=as_of,
                      provenance="apex.catalyst.context (as-of "
                                 "fenced)")
    except Exception as e:                              # noqa: BLE001
        return {"status": "UNKNOWN",
                "why": f"catalyst unavailable: {type(e).__name__}"}


def _book() -> dict:
    try:
        from apex.organism import book
        st = book.state()
        return _field({k: st[k] for k in
                       ("capital", "available_capital", "open_risk",
                        "open_positions", "session_realized_pnl")},
                      known_from=st["as_of"],
                      provenance="results/organism/paper_book.jsonl")
    except Exception as e:                              # noqa: BLE001
        return {"status": "UNKNOWN",
                "why": f"book unavailable: {type(e).__name__}"}


def _btc(as_of: str, fabric: Path) -> dict:
    if not fabric.exists():
        return {"status": "UNKNOWN",
                "why": "BTC paper ledger not on this host"}
    last = None
    for line in fabric.read_text().splitlines()[-500:]:
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = str(r.get("T") or r.get("window_end") or "")
        if t and t <= as_of:
            last = r
    if last is None:
        return {"status": "UNKNOWN", "why": "no BTC row <= as_of"}
    return _field({"cohort": last.get("cohort"),
                   "kind": last.get("kind"),
                   "T": last.get("T")},
                  known_from=str(last.get("T")),
                  provenance="results/btc/paper_ledger.jsonl")


def _cost(symbol: str | None, as_of: str, toll: Path) -> dict:
    """Observed round-trip cost prior: expanding median of observed
    tolls for the symbol strictly before as_of. Same law as Lane B."""
    if symbol is None or not toll.exists():
        return {"status": "UNKNOWN", "why": "no symbol or toll file"}
    import statistics
    vals = []
    for line in toll.open():
        try:
            r = json.loads(line)
        except Exception:                               # noqa: BLE001
            continue
        if r.get("symbol") == symbol and r.get("cohort") == "SINGLE" \
                and r.get("toll") is not None \
                and str(r.get("day", "9999")) < as_of[:10]:
            vals.append(r["toll"])
    if len(vals) < 20:
        return {"status": "NOT_ESTIMABLE",
                "why": f"only {len(vals)} prior toll obs (<20)"}
    rt = 2 * statistics.median(vals) * 1.34 * 1e4 + 0.05
    return _field(round(rt, 1), known_from=as_of,
                  provenance="movement_toll_obs.jsonl expanding "
                             "median, x1.34 uplift + fees",
                  quality="ESTIMATED_FROM_OBSERVED")


def equity_options_state(symbol: str) -> dict:
    """OPTIONS AS INFORMATION, not just expression: live OPRA
    indicative snapshot via Alpaca (the feed verified working on this
    runtime). Returns ATM IV, put skew proxy, spread width -- with
    provenance -- or NOT_ESTIMABLE. Never guesses IV. Requires
    APCA_API_KEY_ID / APCA_API_SECRET_KEY in the environment (loaded
    by the caller from the secrets files; never echoed)."""
    import os
    import urllib.request
    key = os.environ.get("APCA_API_KEY_ID")
    sec = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not sec:
        return {"status": "NOT_ESTIMABLE",
                "why": "no broker-data credentials in environment"}
    url = (f"https://data.alpaca.markets/v1beta1/options/snapshots/"
           f"{symbol}?feed=indicative&limit=300")
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            snaps = json.loads(r.read()).get("snapshots", {})
    except Exception as e:                              # noqa: BLE001
        return {"status": "NOT_ESTIMABLE",
                "why": f"snapshot fetch failed: {type(e).__name__}"}
    ivs, spreads, puts = [], [], []
    for occ, sn in snaps.items():
        q = sn.get("latestQuote") or {}
        g = sn.get("greeks") or {}
        iv = sn.get("impliedVolatility")
        bid, ask = q.get("bp"), q.get("ap")
        if iv and bid and ask and ask > 0:
            ivs.append(iv)
            spreads.append(2 * (ask - bid) / (ask + bid))
            if "P" in occ[-9:]:
                puts.append((g.get("delta"), iv))
    if not ivs:
        return {"status": "NOT_ESTIMABLE",
                "why": "no quoted contracts with IV in snapshot"}
    import statistics as _st
    atm_put = [iv for d, iv in puts
               if isinstance(d, (int, float)) and -0.55 < d < -0.45]
    otm_put = [iv for d, iv in puts
               if isinstance(d, (int, float)) and -0.30 < d < -0.20]
    skew = (round(_st.mean(otm_put) - _st.mean(atm_put), 4)
            if atm_put and otm_put else "NOT_ESTIMABLE")
    return _field(
        {"n_quoted": len(ivs),
         "iv_median": round(_st.median(ivs), 4),
         "put_skew_25d_minus_atm": skew,
         "median_relative_spread": round(_st.median(spreads), 4)},
        known_from=datetime.now(timezone.utc).isoformat(),
        provenance="ALPACA_OPRA_INDICATIVE_SNAPSHOT",
        quality="OBSERVED_QUOTES")


def compose(*, as_of: str, symbol: str | None = None,
            live_options: bool = False,
            regime_atlas: Path | None = None,
            btc_fabric: Path | None = None,
            toll: Path | None = None) -> dict:
    """One snapshot. Cheap sections always; expensive sections only
    when a subject is named."""
    return {
        "kind": "universal_market_state",
        "as_of": as_of,
        "subject": symbol or "MARKET",
        "composed_utc": datetime.now(timezone.utc).isoformat(),
        "REGIME": _regime(as_of[:10], regime_atlas or REGIME_ATLAS),
        "EVENT": _catalyst(symbol, as_of),
        "ECONOMICS": {
            "portfolio": _book(),
            "expected_rt_cost_bps": _cost(symbol, as_of,
                                          toll or TOLL)},
        "DERIVATIVES": {
            "equity_options": (
                equity_options_state(symbol) if symbol
                and live_options else {
                    "status": "NOT_QUERIED",
                    "why": "live_options flag off or no subject; "
                           "prospective NBBO also accumulates via "
                           "the option shadow timers"}),
            "btc": _btc(as_of, btc_fabric or BTC_FABRIC)},
        "PRICE": {"status": "SLEEVE_LOCAL",
                  "why": "price state lives in each sleeve's own "
                         "causal feeds (equity field, BTC fabric); "
                         "not duplicated here"},
        "RELATIVE": {"peer_map": _field(
            "exports/peer_map_v1.json (SIC-4, 272/299 mapped)",
            known_from="2026-08-30",
            provenance="EDGAR SIC codes", quality="STRUCTURAL")},
        "LIQUIDITY": NOT_IMPLEMENTED | {
            "why": "no governed depth/imbalance sensing exists"},
        "QUANT": NOT_IMPLEMENTED | {
            "why": "no quant-state representation has earned "
                   "economic existence yet (Part VI law)"},
        "TIME": _field(as_of, known_from=as_of,
                       provenance="caller clock"),
        "law": "UNKNOWN is a value; no consumer may coerce it",
        "decision_power": "NONE_COMPOSER",
    }
