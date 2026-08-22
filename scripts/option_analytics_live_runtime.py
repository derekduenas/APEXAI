#!/usr/bin/env python
"""APEX OPTION ANALYTICS LIVE RUNTIME V1 -- the first live process
consuming apex.option_analytics against REAL Alpaca OPRA snapshots.

    python scripts/option_analytics_live_runtime.py [--minutes 8] [--cadence 60]

PIPELINE PER CONTRACT (operator's spec, F "APEX OPTION ANALYTICS LIVE
RUNTIME V1"):

    LIVE OPRA SNAPSHOT
          v
    quote sanity / no-arbitrage
          v
    underlying + strike + expiry, rates + dividends
          v
    IV_BID / IV_MID / IV_ASK
          v
    BSM Greeks + American Greeks + FD cross-check
          v
    model disagreement (now 3-WAY: vendor Greeks vs BSM vs American --
    see the market_state.py correction: Alpaca DOES carry `greeks`/
    `impliedVolatility` for actively-quoted contracts)
          v
    OptionAnalyticsState
          v
    OptionSurfaceState

INPUT-QUALITY LAW (operator directive): model correctness is necessary,
but market-input correctness dominates. Every live state carries
quote_age_s, underlying_age_s, rate_source_age_days, bid_size/ask_size,
and dividend_confidence via apex.option_analytics.live_quality --
weak inputs degrade state_quality, never handed to the expression
engine as a precise-looking number over garbage.

TWO HONEST, EXPLICITLY-LABELED DATA GATES in this first live run
(neither fabricated, both structurally flagged via live_quality so
they show up as degraded quality rather than false confidence):

  1. RATE CURVE: RESOLVED (Phase 1.1). A real composite curve is now
     fetched live -- NY Fed SOFR (overnight) + Treasury bills (4wk-17wk)
     + the Treasury par yield curve (1m-30y). If every live leg fails the
     runtime REFUSES (RATE_SOURCE_UNAVAILABLE) rather than substituting a
     static constant: a 2025-vintage 4% must never masquerade as today's
     rate inside a live analytics state.
  2. DIVIDENDS: no live corporate-actions calendar is wired. A small,
     explicitly-provenanced table of REAL dividend facts (captured via
     Robinhood's get_equity_fundamentals tool at the timestamp noted
     below, not invented) is used to derive either a directly-observed
     upcoming ex-dividend date (SPY) or a conservative "no ex-dividend
     before expiry" inference from the last known ex-date + quarterly
     cadence + a wide buffer (AAPL, QQQ). A contract whose expiry falls
     outside what this table can support is honestly refused
     (NO_DIVIDEND_SCHEDULE_SUPPLIED), never guessed.

decision_power = NONE_OPTION_ANALYTICS everywhere. This process places
no order, holds no Capital/broker authority, and writes exclusively
under results/option_analytics/live/.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent))

import pandas as pd  # noqa: E402

from apex.governance.service_progress import (  # noqa: E402
    ServiceProgressState, is_pid_alive, start as sp_start, write as sp_write,
)
from apex.option_analytics.canonical_state import build_canonical_state  # noqa: E402
from apex.option_analytics.dividends import DividendSchedule  # noqa: E402
from apex.option_analytics.model_disagreement import build_range  # noqa: E402
from apex.option_analytics.rate_curve import RiskFreeCurve  # noqa: E402
from apex.options_research.market_state import from_alpaca_snapshot  # noqa: E402
from apex.options_research.surface_state import build_surface  # noqa: E402

SERVICE_NAME = "option_analytics_live_runtime"
RUNTIME_STATE_PATH = Path("results/option_analytics/live/runtime/service_progress.json")
STATES_LEDGER = Path("results/option_analytics/live/states.jsonl")
SURFACES_LEDGER = Path("results/option_analytics/live/surfaces.jsonl")
ERRORS_LEDGER = Path("results/option_analytics/live/errors/error_ledger.jsonl")
CYCLE_SUMMARY_LEDGER = Path("results/option_analytics/live/cycle_summaries.jsonl")

DATA_BASE = "https://data.alpaca.markets"
WATCHLIST = ("AAPL", "SPY", "QQQ")
MAX_DTE_CONSIDERED = 120
MAX_STRIKES_PER_EXPIRY = 6
N_AMERICAN_STEPS = 300

# DTE BUCKET SAMPLING (Phase 1.1). The 2026-08-18 run took the two
# nearest expiries per symbol and both landed at 1-2 DTE, so short-DTE
# numerical behaviour and rate-source staleness were confounded and
# nothing was learned about longer maturities. Sampling now spans the
# named buckets deliberately.
#
# A bucket with no liquid contract is REPORTED EMPTY, never filled by
# stretching a neighbouring expiry into it -- the whole point is
# numerical characterisation, and a mislabelled contract would corrupt
# exactly the comparison we are trying to make.
DTE_BUCKETS = (("1-2", 1, 2), ("3-7", 3, 7), ("8-30", 8, 30),
               (">30", 31, MAX_DTE_CONSIDERED))
MAX_EXPIRIES_PER_BUCKET = 1

# ---- DATA GATE 1: rate curve ------------------------------------------
# A static rate may NEVER masquerade as current rate truth in a LIVE
# analytics state. These constants are retained for TEST / SYNTHETIC /
# EXPLICIT_DIAGNOSTIC use only; the live path refuses instead (see
# rate_curve_now). Guarded by test_static_rate_never_reaches_live_state.
STATIC_RATE_VALUE = 0.04
STATIC_RATE_SOURCE = "STATIC_APPROXIMATE_V1_NOT_A_LIVE_FEED"
STATIC_RATE_SET_AT = pd.Timestamp("2025-01-01T00:00:00Z")
STATIC_RATE_ALLOWED_USES = ("TEST", "SYNTHETIC", "EXPLICIT_DIAGNOSTIC")
RATE_SOURCE_UNAVAILABLE = "RATE_SOURCE_UNAVAILABLE"

# ---- DATA GATE 2: dividends -------------------------------------------------
# Captured live via mcp__robinhood-trading__get_equity_fundamentals at
# 2026-08-18T17:15Z. Real observed facts, not invented. `next_ex_div`
# is either a directly-observed future date (SPY) or a conservative
# lower bound derived from last_ex_div + one quarter (AAPL, QQQ) -- a
# contract expiring before `safe_no_dividend_until` is confirmed
# dividend-free for the purposes of this run; one expiring on/after it
# is refused (NO_DIVIDEND_SCHEDULE_SUPPLIED), never guessed.
DIVIDEND_FACTS = {
    "AAPL": {"last_ex_div": "2026-08-10", "amount": 0.27,
            "safe_no_dividend_until": "2026-11-01",
            "source": "ROBINHOOD_FUNDAMENTALS_SNAPSHOT_2026-08-18T17:15Z"},
    "SPY": {"next_ex_div": "2026-09-18", "amount": 1.903520,
           "source": "ROBINHOOD_FUNDAMENTALS_SNAPSHOT_2026-08-18T17:15Z"},
    "QQQ": {"last_ex_div": "2026-06-22", "amount": 0.813490,
           "safe_no_dividend_until": "2026-09-01",
           "source": "ROBINHOOD_FUNDAMENTALS_SNAPSHOT_2026-08-18T17:15Z"},
}


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(
        cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))


def _alpaca_headers() -> dict:
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError(
            "APCA_API_KEY_ID/APCA_API_SECRET_KEY not set -- this runtime "
            "refuses to start rather than run blind")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _get_json(url: str, headers: dict, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode())


def fetch_options_snapshot(symbol: str, headers: dict,
                           date_gte: str | None = None,
                           date_lte: str | None = None) -> dict:
    """One page of OPRA snapshots, optionally restricted to an expiry
    window.

    THE PAGINATION TRAP (Phase 1.1): an unfiltered `?limit=100` returns
    a SINGLE page that in practice contains exactly one expiry -- on
    2026-08-19 every one of the 100 rows was the already-expired
    2026-08-18. Sampling "the nearest two expiries" from that page could
    therefore never reach a longer maturity, which is why the first live
    run saw only 1-2 DTE. Each DTE bucket now queries its OWN expiry
    window instead of hoping one page spans them."""
    url = f"{DATA_BASE}/v1beta1/options/snapshots/{symbol}?limit=100"
    if date_gte:
        url += f"&expiration_date_gte={date_gte}"
    if date_lte:
        url += f"&expiration_date_lte={date_lte}"
    return _get_json(url, headers).get("snapshots", {})


def fetch_bucketed_snapshots(symbol: str, headers: dict, *, now) -> dict:
    """Fetch one page per DTE bucket, each restricted to that bucket's
    real date window. Returns {option_symbol: (snapshot, bucket_label)}.
    A bucket whose window returns nothing stays genuinely empty."""
    session_day = pd.Timestamp(now).normalize()
    out: dict = {}
    for label, lo, hi in DTE_BUCKETS:
        gte = (session_day + pd.Timedelta(days=lo)).strftime("%Y-%m-%d")
        lte = (session_day + pd.Timedelta(days=hi)).strftime("%Y-%m-%d")
        try:
            snaps = fetch_options_snapshot(symbol, headers, date_gte=gte,
                                           date_lte=lte)
        except Exception as e:  # noqa: BLE001
            print(f"{symbol} bucket {label} fetch failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            continue
        for osym, snap in snaps.items():
            out.setdefault(osym, (snap, label))
    return out


def fetch_underlying_quote(symbol: str, headers: dict) -> dict:
    return _get_json(f"{DATA_BASE}/v2/stocks/{symbol}/quotes/latest", headers).get("quote", {})


def rate_curve_now(*, now):
    """REAL composite curve (Phase 1.1): NY Fed SOFR overnight +
    Treasury bills (4wk-17wk) + the par yield curve (1m-30y). Falls back
    to the explicitly-stale static constant ONLY if every live leg is
    unreachable -- and says so, so live_quality still degrades honestly
    rather than the run silently pretending it had a fresh rate."""
    try:
        from apex.intraday.treasury_rate_source import fetch_composite_curve
        curve, prov = fetch_composite_curve(now=now)
        return curve, prov.age_days, prov.source_name
    except Exception as e:  # noqa: BLE001
        # NO SILENT 4%. A curve of None makes rate_for_tenor() return
        # None for every tenor, which build_canonical_state already turns
        # into a REFUSED state -- the honest outcome. Substituting a
        # static constant here would let a 2025-vintage 4% masquerade as
        # today's rate inside a live analytics state.
        print(f"live rate source unavailable ({type(e).__name__}: {e}) -- "
              f"REFUSING; no static rate may stand in for current truth",
              flush=True)
        return (None, None, RATE_SOURCE_UNAVAILABLE)


def rate_source_age_days(now) -> float:
    return (pd.Timestamp(now) - STATIC_RATE_SET_AT).total_seconds() / 86400.0


def dividend_schedule_for(symbol: str, expiry_date: str, *, known_from
                          ) -> tuple:
    """Returns (DividendSchedule|None, dividend_confidence). None means
    an honest refusal -- this table cannot support the requested
    expiry, and the caller must not guess."""
    facts = DIVIDEND_FACTS.get(symbol)
    if facts is None:
        return None, "UNKNOWN"
    expiry = pd.Timestamp(expiry_date)

    if "next_ex_div" in facts:
        next_ex = pd.Timestamp(facts["next_ex_div"])
        if expiry < next_ex:
            sched = DividendSchedule(events=(), confirmed_no_dividends=True,
                                     source=facts["source"], as_of=str(known_from))
            return sched, "CONFIRMED_NONE"
        sched = DividendSchedule(events=((facts["next_ex_div"], facts["amount"]),),
                                 confirmed_no_dividends=False,
                                 source=facts["source"], as_of=str(known_from))
        return sched, "REAL_SCHEDULE"

    safe_until = pd.Timestamp(facts["safe_no_dividend_until"])
    if expiry < safe_until:
        sched = DividendSchedule(events=(), confirmed_no_dividends=True,
                                 source=facts["source"] + " (inferred from last "
                                 f"ex-div {facts['last_ex_div']} + quarterly cadence)",
                                 as_of=str(known_from))
        return sched, "CONFIRMED_NONE"
    return None, "UNKNOWN"


def _select_contracts(snapshots: dict, spot: float, now: pd.Timestamp) -> list:
    """Filters to near-ATM, currently-quoted contracts spread across the
    named DTE buckets. Bounds compute cost (American binomial runs per
    contract) to something a real-time cadence can sustain.

    Returns (option_symbol, snapshot, dte_bucket_label) triples."""
    by_bucket: dict = {}
    for opt_symbol, (snap, bucket_label) in snapshots.items():
        q = snap.get("latestQuote") or {}
        if q.get("bp") is None or q.get("ap") is None:
            continue
        try:
            import re
            m = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", opt_symbol)
            if not m:
                continue
            _, yymmdd, _, strike8 = m.groups()
            expiry = f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
            strike = int(strike8) / 1000.0
        except Exception:  # noqa: BLE001
            continue
        dte = (pd.Timestamp(expiry).tz_localize(now.tzinfo) - now.normalize()).days
        if dte < 0 or dte > MAX_DTE_CONSIDERED:
            continue
        by_bucket.setdefault(bucket_label, {}).setdefault(
            expiry, []).append((abs(strike - spot), opt_symbol, snap))

    # nearest-ATM contracts from the nearest expiry inside each bucket.
    selected = []
    for label, _lo, _hi in DTE_BUCKETS:
        expiries = by_bucket.get(label) or {}
        for expiry in sorted(expiries)[:MAX_EXPIRIES_PER_BUCKET]:
            contracts = sorted(expiries[expiry],
                               key=lambda t: t[0])[:MAX_STRIKES_PER_EXPIRY]
            selected.extend((opt_symbol, snap, label)
                            for _, opt_symbol, snap in contracts)
    return selected


def _record_error(cycle: int, stage: str, exc: Exception, *, input_refs: tuple,
                  known_from) -> None:
    import traceback
    ERRORS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with ERRORS_LEDGER.open("a") as fh:
        fh.write(json.dumps({
            "cycle": cycle, "stage": stage, "exception_type": type(exc).__name__,
            "exception_message": str(exc), "input_refs": input_refs,
            "known_from": str(known_from), "traceback": traceback.format_exc()[-2000:],
        }, default=str) + "\n")


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")


def process_symbol(symbol: str, headers: dict, cycle: int, now: pd.Timestamp) -> dict:
    fetched_at = pd.Timestamp.now(tz="UTC")
    underlying_q = fetch_underlying_quote(symbol, headers)
    ubid, uask = underlying_q.get("bp"), underlying_q.get("ap")
    if ubid is None or uask is None:
        raise RuntimeError(f"{symbol}: no current underlying quote")
    spot = (ubid + uask) / 2.0
    underlying_quote_time = underlying_q.get("t")
    underlying_age_s = ((pd.Timestamp.now(tz="UTC") - pd.Timestamp(underlying_quote_time))
                        .total_seconds()) if underlying_quote_time else None

    snapshots = fetch_bucketed_snapshots(symbol, headers, now=now)
    # THE 2026-08-19 NEGATIVE-QUOTE-AGE ROOT CAUSE.
    # 18,794 of 21,018 states (89.4%) carried a NEGATIVE quote_age_s,
    # median -6.08s and remarkably stable at -5.6 to -7.5s in every hour
    # of the session. That is not provider timestamp weirdness and not
    # local clock skew: `now` is captured ONCE at the top of the cycle
    # loop, the bucketed REST fetch above then takes several seconds
    # (measured cycle duration 13.5s), and any quote the exchange stamps
    # DURING that fetch is legitimately newer than our cycle-start clock.
    # We were measuring freshness against a baseline we had already left
    # behind.
    #
    # The proof is in this very function: underlying_age_s above is
    # computed against a FRESH pd.Timestamp.now() and reads a clean
    # median of -0.077s, while the option ages measured against `now`
    # read -6.08s. Same file, same session, one line apart.
    #
    # So staleness is measured against the moment the snapshot actually
    # ARRIVED. `known_from` deliberately stays `now`: when APEX learned
    # a thing is a different question from how old the quote was, and
    # conflating them is what produced this bug.
    quotes_observed_at = pd.Timestamp.now(tz="UTC")
    selected = _select_contracts(snapshots, spot, now)

    curve, rate_age, rate_source_name = rate_curve_now(now=now)
    states, vendor_comparisons, surface_inputs = [], [], {}

    bucket_stats: dict = {label: {"contracts_sampled": 0, "iv_solved": 0,
                                 "vendor_greeks": 0, "refused": 0,
                                 "quote_quality": {}, "bsm_vs_american": {}}
                         for label, _lo, _hi in DTE_BUCKETS}

    for opt_symbol, snap, dte_bucket in selected:
        mkt = from_alpaca_snapshot(opt_symbol, snap, underlying_price=spot,
                                   now=quotes_observed_at, known_from=now)
        option_type = "call" if mkt.call_put == "CALL" else "put"
        div_sched, div_confidence = dividend_schedule_for(
            symbol, mkt.expiration, known_from=now)

        state = build_canonical_state(
            symbol=opt_symbol, option_type=option_type, spot=spot, strike=mkt.strike,
            expiry_date=mkt.expiration, bid=mkt.bid, ask=mkt.ask, last_trade=mkt.last_trade,
            quote_is_current=True, curve=curve, dividend_schedule=div_sched,
            known_from=now, now=now, n_american_steps=N_AMERICAN_STEPS,
            quote_age_s=mkt.staleness_s, underlying_age_s=underlying_age_s,
            rate_source_age_days=(rate_age if rate_age is not None else 1e6), bid_size=mkt.bid_size, ask_size=mkt.ask_size,
            dividend_confidence=div_confidence)
        bs = bucket_stats[dte_bucket]
        bs["contracts_sampled"] += 1
        if state.state_quality == "REFUSED":
            bs["refused"] += 1
        if state.iv and state.iv.get("iv_mid") is not None:
            bs["iv_solved"] += 1
        if mkt.delta is not None:
            bs["vendor_greeks"] += 1
        if state.iv:
            q = state.iv.get("quality")
            bs["quote_quality"][q] = bs["quote_quality"].get(q, 0) + 1
        if state.delta:
            lvl = state.delta.get("disagreement_level")
            bs["bsm_vs_american"][lvl] = bs["bsm_vs_american"].get(lvl, 0) + 1

        _append(STATES_LEDGER, {"cycle": cycle, "dte_bucket": dte_bucket,
                                "rate_source": rate_source_name,
                                "vendor_iv": mkt.implied_volatility,
                                "vendor_delta": mkt.delta, "vendor_gamma": mkt.gamma,
                                "vendor_theta": mkt.theta, "vendor_vega": mkt.vega,
                                "vendor_rho": mkt.rho, "market_bid": mkt.bid,
                                "market_ask": mkt.ask, "market_mid": mkt.mid,
                                **state.as_record()})
        states.append(state)

        if mkt.delta is not None and state.delta is not None:
            vendor_vs_bsm = build_range("delta", bsm_value=mkt.delta,
                                        american_value=state.delta["bsm_value"])
            vendor_vs_american = build_range("delta", bsm_value=mkt.delta,
                                             american_value=state.delta["american_value"])
            vendor_comparisons.append({
                "option_symbol": opt_symbol, "vendor_iv": mkt.implied_volatility,
                "apex_iv_mid": state.iv["iv_mid"] if state.iv else None,
                "vendor_vs_bsm_delta_disagreement": vendor_vs_bsm.disagreement_level,
                "vendor_vs_american_delta_disagreement": vendor_vs_american.disagreement_level,
            })

        expiry_key = mkt.expiration
        surface_inputs.setdefault(expiry_key, []).append((mkt.strike, state))

    for expiry_date, entries in surface_inputs.items():
        for strike, state in entries:
            values = {}
            if state.iv:
                values["atm_iv"] = state.iv.get("iv_mid")
                values["spread_pct"] = state.iv.get("spread_pct_of_mid")
            surf = build_surface(f"{symbol}_{expiry_date}_{strike}", expiry_date,
                                 known_from=now, now=now,
                                 standardized_moneyness=(strike - spot) / spot,
                                 values=values)
            _append(SURFACES_LEDGER, {"cycle": cycle, "symbol": symbol, **surf.as_record()})

    return {"symbol": symbol, "spot": spot, "dte_buckets": bucket_stats,
           "rate_source": rate_source_name, "rate_age_days": rate_age,
           "contracts_processed": len(states),
           "refused_count": sum(1 for s in states if s.state_quality == "REFUSED"),
           "high_quality_count": sum(1 for s in states if s.state_quality == "HIGH"),
           "vendor_comparisons": vendor_comparisons,
           "fetch_latency_s": (pd.Timestamp.now(tz="UTC") - fetched_at).total_seconds()}


def run_cycle(cycle: int, now: pd.Timestamp) -> dict:
    headers = _alpaca_headers()
    out = {"cycle": cycle, "known_from": str(now), "symbols": {}, "errors": 0}
    for symbol in WATCHLIST:
        try:
            out["symbols"][symbol] = process_symbol(symbol, headers, cycle, now)
        except Exception as e:  # noqa: BLE001
            _record_error(cycle, f"process_symbol:{symbol}", e, input_refs=(symbol,),
                         known_from=now)
            out["errors"] += 1
    _append(CYCLE_SUMMARY_LEDGER, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=8.0)
    ap.add_argument("--cadence", type=float, default=60.0)
    a = ap.parse_args()

    sp = sp_start(SERVICE_NAME, expected_cadence_s=a.cadence)
    print(f"OPTION_ANALYTICS_LIVE_RUNTIME starting pid={sp.pid}", flush=True)

    t_end = time.time() + a.minutes * 60
    cycle = 0
    while time.time() < t_end:
        cycle += 1
        now = pd.Timestamp.now(tz="UTC")
        sp.cycle_number = cycle
        sp.last_cycle_start = str(now)
        sp.heartbeat_time = str(now)
        try:
            result = run_cycle(cycle, now)
            sp.last_cycle_complete = str(pd.Timestamp.now(tz="UTC"))
            sp.last_successful_cycle = sp.last_cycle_complete
            sp.cycle_duration_s = (pd.Timestamp(sp.last_cycle_complete) - now).total_seconds()
            sp.consecutive_failures = 0
            sp.last_state_write = sp.last_cycle_complete
            sp.backlog_count = result["errors"]
            n_contracts = sum(s.get("contracts_processed", 0) for s in result["symbols"].values())
            print(f"{now:%H:%M:%S} cycle={cycle} contracts={n_contracts} "
                 f"errors={result['errors']}", flush=True)
        except Exception as e:  # noqa: BLE001
            sp.consecutive_failures += 1
            sp.total_failures += 1
            sp.error_reference = f"cycle_{cycle}_{type(e).__name__}"
            _record_error(cycle, "run_cycle", e, input_refs=(), known_from=now)
            print(f"{now:%H:%M:%S} cycle={cycle} FAILED: {type(e).__name__}: {e}", flush=True)
        sp_write(sp, RUNTIME_STATE_PATH)
        remaining = t_end - time.time()
        if remaining <= 0:
            break
        time.sleep(max(1.0, min(a.cadence, remaining)))

    sp_write(sp, RUNTIME_STATE_PATH)
    print("OPTION_ANALYTICS_LIVE_RUNTIME stopped (budget reached)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
