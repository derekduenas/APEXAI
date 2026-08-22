"""CFTC TRADERS IN FINANCIAL FUTURES -- real institutional positioning.

The first genuine positioning data APEX has ever had. Before this the
whole positioning layer was an interface reporting UNAVAILABLE eleven
times; the forced-flow question -- "is somebody going to HAVE to buy?" --
had no input at all.

SOURCE: CFTC Socrata `gpe5-46if` (Traders in Financial Futures, futures
only). Verified live 2026-08-19: 89 fields, full Dealer / Asset Manager /
Leveraged Fund decomposition with longs, shorts, spreads, weekly changes,
%-of-OI and trader counts.

WHAT IT IS NOT, and this matters more than what it is:

  * NOT live. Positions are as of TUESDAY, published FRIDAY. Measured
    lag on 2026-08-19 was 8 days. Every fact carries its own
    `freshness_days` and the Pattern Assassin has a POSITIONING_STALE
    wound specifically for intraday claims built on it.
  * NOT "smart money". Leveraged Funds are hedge funds AND CTAs AND
    anyone else the CFTC classifies that way; Asset Managers are largely
    long-only mandates whose net long is structural, not a view. A large
    dealer short is usually the other side of customer flow, not a bet.
    Every fact therefore carries an ALTERNATIVE_MOTIVE alongside its
    interpretation.
  * NOT a signal. A crowded short can stay crowded for months.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

from apex.pattern_observatory import OBSERVATORY_POWER, WRITE_ROOT
from apex.pattern_observatory.positioning import (
    AVAILABLE_LAGGED, NOT_ACQUIRED, PositioningFact,
)
from apex.pattern_observatory.publication_lag import (
    LaggedObservation, PUBLISHED, publication_time,
)

ENDPOINT = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CACHE = Path(WRITE_ROOT) / "positioning" / "cftc_tff.jsonl"
CA_BUNDLE = "/etc/ssl/cert.pem"
PUBLICATION_DELAY = "positions as of Tuesday, released Friday (~3 days); "
CADENCE = "weekly"

# Contract names EXACTLY as the CFTC publishes them, verified live.
# Mapping by substring would silently pick up MICRO variants and
# double-count, so these are full-string matches.
CONTRACTS = {
    "ES": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    "NQ": "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
    "RTY": "MICRO E-MINI RUSSELL 2000 INDX - CHICAGO MERCANTILE EXCHANGE",
    "VIX": "VIX FUTURES - CBOE FUTURES EXCHANGE",
    "UST10Y": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
    "USTBOND": "UST BOND - CHICAGO BOARD OF TRADE",
}

# The three trader classes, and what each one's positioning actually
# tends to mean. These are STATED PRIORS, not inferences from outcomes.
TRADER_CLASSES = {
    "lev_money": {
        "label": "LEVERAGED_FUNDS",
        "interpretation": "speculative positioning; the class most likely "
                          "to be forced out by an adverse move",
        "alternative_motive": "includes CTAs running systematic trend and "
                              "relative-value desks whose futures leg is one "
                              "half of a basis trade -- a large short can be "
                              "a cash-futures arb, not a bearish view"},
    "asset_mgr": {
        "label": "ASSET_MANAGERS",
        "interpretation": "institutional/real-money exposure",
        "alternative_motive": "long-only mandates are structurally long; "
                              "the net long is a benchmark, not a forecast"},
    "dealer": {
        "label": "DEALERS_INTERMEDIARIES",
        "interpretation": "sell-side inventory",
        "alternative_motive": "dealers warehouse the other side of customer "
                              "flow; their position is usually a consequence "
                              "of somebody else's view, not their own"},
}

MIN_HISTORY_FOR_PERCENTILE = 52     # one year of weekly reports


class CFTCError(RuntimeError):
    pass


def fetch(*, since: str = "2024-01-01", limit: int = 5000,
          timeout: float = 30.0) -> list:
    """Raises on failure. A silent empty list would look identical to
    'no positioning exists', which is the confusion this module removes."""
    q = {"$where": f"report_date_as_yyyy_mm_dd > '{since}'",
         "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": str(limit)}
    url = f"{ENDPOINT}?{urllib.parse.urlencode(q)}"
    ctx = ssl.create_default_context(cafile=CA_BUNDLE)
    try:
        with urllib.request.urlopen(url, context=ctx, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:                                  # noqa: BLE001
        raise CFTCError(f"CFTC TFF fetch failed: {type(e).__name__}: {e}") from e


def _net(row: dict, cls: str) -> int | None:
    lo = row.get(f"{cls}_positions_long"
                 if cls != "dealer" else "dealer_positions_long_all")
    sh = row.get(f"{cls}_positions_short"
                 if cls != "dealer" else "dealer_positions_short_all")
    if lo is None or sh is None:
        return None
    return int(float(lo)) - int(float(sh))


def series_for(rows: list, contract_key: str, cls: str) -> list:
    """Chronological [(report_date, net)] for one contract and class."""
    name = CONTRACTS.get(contract_key)
    if name is None:
        raise CFTCError(f"unknown contract key {contract_key!r}")
    out = []
    for r in rows:
        if r.get("market_and_exchange_names") != name:
            continue
        n = _net(r, cls)
        if n is None:
            continue
        out.append((r["report_date_as_yyyy_mm_dd"][:10], n, r))
    return sorted(out, key=lambda x: x[0])


def to_fact(rows: list, contract_key: str, cls: str, *, now) -> PositioningFact:
    """Build a PositioningFact with percentiles, z-score and deltas.

    Percentile/z are NOT_ESTIMABLE below MIN_HISTORY_FOR_PERCENTILE
    reports -- an extreme measured against 6 weeks is a statement about
    those 6 weeks.
    """
    import pandas as pd
    import statistics

    meta = TRADER_CLASSES[cls]
    s = series_for(rows, contract_key, cls)
    if not s:
        return PositioningFact(
            source=f"CFTC_{contract_key}", subject=contract_key,
            metric=f"{meta['label']}_NET", value=None,
            as_of_market_date=None, known_from=str(now),
            publication_delay=PUBLICATION_DELAY, availability=NOT_ACQUIRED,
            interpretation=None, alternative_motive=meta["alternative_motive"],
            confidence="UNKNOWN")

    date, net, raw = s[-1]
    hist = [n for _d, n, _r in s]

    # PUBLICATION-LAG INTEGRITY. `date` is the TUESDAY the positions were
    # measured; the report did not become public until the FOLLOWING
    # FRIDAY 15:30 ET. Stamping the report date as known_from would hand
    # APEX three days of lookahead on every historical sequence study.
    pub = publication_time("CFTC_TFF", date)
    freshness = (pd.Timestamp(now).tz_localize(None)
                 - pd.Timestamp(date)).days if now is not None else None

    pct = z = None
    if len(hist) >= MIN_HISTORY_FOR_PERCENTILE:
        window = hist[-260:]                     # ~5 years of weeklies
        pct = sum(1 for h in window if h < net) / len(window)
        sd = statistics.pstdev(window)
        z = (net - statistics.fmean(window)) / sd if sd > 0 else None
    c1 = net - hist[-2] if len(hist) >= 2 else None
    c4 = net - hist[-5] if len(hist) >= 5 else None

    confidence = ("LOW" if freshness is not None and freshness > 10 else
                  "MODERATE" if len(hist) >= MIN_HISTORY_FOR_PERCENTILE
                  else "LOW")
    return PositioningFact(
        source=f"CFTC_{contract_key}", subject=contract_key,
        metric=f"{meta['label']}_NET", value=float(net),
        as_of_market_date=date, known_from=str(pub),
        publication_delay=PUBLICATION_DELAY, availability=AVAILABLE_LAGGED,
        freshness_days=(float(freshness) if freshness is not None else None),
        percentile_52w=pct, percentile_multiyear=pct, z_score=z,
        change_1w=(float(c1) if c1 is not None else None),
        change_4w=(float(c4) if c4 is not None else None),
        interpretation=meta["interpretation"],
        alternative_motive=meta["alternative_motive"], confidence=confidence)


def as_lagged(fact: PositioningFact) -> LaggedObservation:
    """Wrap a fact in the integrity contract. Construction RAISES if the
    publication time somehow precedes the report date."""
    return LaggedObservation(
        source="CFTC_TFF", subject=fact.subject,
        event_time=fact.as_of_market_date, known_from=fact.known_from,
        value=fact.value, source_state=PUBLISHED,
        staleness_days=fact.freshness_days,
        policy={"lag": fact.publication_delay})


def ingest(*, now, since: str = "2024-01-01") -> dict:
    """Fetch, build facts for every contract and class, cache raw rows."""
    rows = fetch(since=since)
    facts = []
    for key in CONTRACTS:
        for cls in TRADER_CLASSES:
            try:
                facts.append(to_fact(rows, key, cls, now=now))
            except Exception:                               # noqa: BLE001
                continue
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE.open("a") as fh:
            fh.write(json.dumps({
                "kind": "cftc_tff_ingest", "as_of": str(now),
                "rows_fetched": len(rows), "facts_built": len(facts),
                "contracts": list(CONTRACTS),
                "decision_power": OBSERVATORY_POWER}, default=str) + "\n")
    except Exception:                                       # noqa: BLE001
        pass
    dated = [f for f in facts if f.as_of_market_date]
    return {"kind": "cftc_positioning_ingest", "as_of": str(now),
            "rows_fetched": len(rows), "facts": facts,
            "n_facts": len(facts),
            "most_recent_report": (max(f.as_of_market_date for f in dated)
                                   if dated else None),
            "max_freshness_days": (max((f.freshness_days or 0) for f in dated)
                                   if dated else None),
            "is_live_data": False,
            "is_smart_money": False,
            "decision_power": OBSERVATORY_POWER}
