"""BTC VENUE SEMANTICS REGISTRY -- units and cadences as law.

THE 2026-08-21 CATCHES (operator + BTC-L2, resolved by published spec,
never by guessing):

  * Bitnomial Product Data prices are TICKS: price_usd = ticks x
    product_spec.price_increment (PBTCUCZ50: increment $5/BTC ->
    15,467 ticks = $77,335/BTC; the "1/5 mystery" was units).
    BITNOMIAL_PRICE_UNIT_ISSUE = RESOLVED_BY_SPEC.
  * Bitnomial Charts OHLC is ALREADY USD -- multiplying it by the
    increment would fabricate $386k BTC. Endpoint units are
    per-endpoint, never per-venue.
  * The ACTIVE PBTCUC perp is CASH SETTLED (live spec 5614 verified
    2026-08-21); the expired PBUC series was deliverable -- old specs
    may never contaminate current contract metadata.
  * OI publication cadence != poll cadence. Empirically measured over
    our own ledger (2026-08-21): Bitnomial 1 OI change / 67 polls
    (docs: published by following morning) -> OI_DAILY_PUBLISHED;
    Deribit 80 changes / 84 polls -> OI_REALTIME; Kraken Futures
    4 / 84 -> OI_DELAYED. UNKNOWN != REALTIME. The Predator's
    intraday participant-pressure inference may only consume
    OI_REALTIME sources.

Every converted value carries: raw_value, raw_unit, conversion,
canonical_value, canonical_unit, spec_version/source.
"""
from __future__ import annotations

# OI timeliness classes -- the canonical distinction. UNKNOWN is its
# own honest class and is NEVER treated as REALTIME.
OI_REALTIME = "OI_REALTIME"
OI_DELAYED = "OI_DELAYED"
OI_DAILY_PUBLISHED = "OI_DAILY_PUBLISHED"
OI_NOT_AVAILABLE = "OI_NOT_AVAILABLE"
OI_UNKNOWN_CADENCE = "OI_UNKNOWN_CADENCE"

# Machine-readable endpoint semantics. `price_conversion` names the
# rule; convert() below is the only sanctioned implementation.
BITNOMIAL_ENDPOINT_SEMANTICS_REGISTRY = {
    "/product/data/": {
        "price_fields": ("last_price", "settlement_price", "mark_price",
                         "open_price", "high_price", "low_price",
                         "close_price", "price_limit_upper",
                         "price_limit_lower"),
        "price_unit": "TICKS",
        "price_conversion": "MULTIPLY_BY_PRODUCT_SPEC_PRICE_INCREMENT",
        "volume_unit": "CONTRACTS",
        "oi_unit": "CONTRACTS",
        "oi_publication": OI_DAILY_PUBLISHED,
        "oi_publication_evidence": "docs: OI updated by following "
                                   "morning; measured 1 change/67 polls "
                                   "2026-08-21",
    },
    "/web/charts/price/": {
        "price_unit": "USD_ALREADY",
        "price_conversion": "NONE",
        "law": "multiplying Charts USD by price_increment fabricates a "
               "5x price -- forbidden, regression-tested",
    },
    "/web/charts/voi/": {
        "volume_unit": "CONTRACTS",
        "oi_unit": "CONTRACTS",
        "notional_unit": "CENTS",
        "notional_conversion": "DIVIDE_BY_100_TO_USD",
    },
    # RESOLVED 2026-08-21 (docs + live fetch): the funding-rates mount
    # is /exchange/api/v1/funding-rates/ -- NOT under the /prod/ segment
    # the other endpoints use. That mount mismatch was the whole 404
    # mystery. Fields price_index and mark_price are in TICKS (verified:
    # interval 08-16Z mark_price=15467 ticks == the /product/data
    # funding-interval mark). funding_rate is the per-8h-interval rate.
    # The endpoint publishes SETTLED HISTORICAL intervals only -- the
    # in-progress interval is absent. ACTUAL funding, never an estimate.
    "/funding-rates/": {
        "mount": "https://bitnomial.com/exchange/api/v1/funding-rates/",
        "mount_law": "NOT under /api/v1/prod/ -- resolved by docs "
                     "2026-08-21, ends the 404 hunt",
        "price_fields": ("price_index", "mark_price"),
        "price_unit": "TICKS",
        "price_conversion": "MULTIPLY_BY_PRODUCT_SPEC_PRICE_INCREMENT",
        "funding_rate_semantics": "ACTUAL_SETTLED_PER_INTERVAL",
        "interval_hours": 8,
        "publication": "after interval_end only; in-progress interval "
                       "is honestly absent",
    },
}

# BITNOMIAL WEBSOCKET (docs 2026-08-21): wss://bitnomial.com/exchange/ws
# subscribe within 10s; trade={ack_id,price,quantity,symbol,taker_side,
# timestamp}; book snapshot={ack_id,asks[[p,q]],bids[[p,q]]} + level
# deltas applied only when level.ack_id > book.ack_id. The venue
# provides NO contiguous sequence numbers -- gap detection is built
# from ack monotonicity + book invariants and labeled so.
BITNOMIAL_WS_SEMANTICS = {
    "url": "wss://bitnomial.com/exchange/ws",
    "price_unit": "UNKNOWN_UNTIL_RESOLVED",
    "price_unit_law": "docs do not state WS price units; resolve "
                      "empirically against REST /product/data tick "
                      "values at runtime, refuse USD conversion until "
                      "resolved, persist the resolution evidence",
    "sequence_contiguity": "NOT_PROVIDED_BY_VENUE",
    "book_delta_law": "apply level iff level.ack_id > snapshot ack_id; "
                      "quantity 0 clears the price level; book ack_id 0 "
                      "means markets closed",
}

VENUE_OI_SEMANTICS = {
    "BITNOMIAL": {"oi_class": OI_DAILY_PUBLISHED,
                  "evidence": "docs (following-morning publication) + "
                              "measured 1 change/67 polls 2026-08-21",
                  "real_time_capable": False},
    "DERIBIT": {"oi_class": OI_REALTIME,
                "evidence": "measured 80 changes/84 polls 2026-08-21",
                "real_time_capable": True},
    "KRAKEN_FUTURES": {"oi_class": OI_DELAYED,
                       "evidence": "measured 4 changes/84 polls "
                                   "2026-08-21; native cadence "
                                   "unverified against docs",
                       "real_time_capable": False},
    "OKX": {"oi_class": OI_NOT_AVAILABLE,
            "evidence": "funding endpoint only; OI not polled",
            "real_time_capable": False},
}


# PRICE SEMANTIC TYPES (operator law, 2026-08-21 lineage audit). The
# word MARK may not be used unless the upstream source defines the
# field as a mark price -- and even then its CADENCE is part of the
# semantics. Measured on /product/data/5614 over 153 polls (~40min):
#   last_price        4 changes, own timestamp    -> LAST_TRADE (live)
#   mark_price        0 changes, NO own timestamp -> FUNDING_MARK
#                     (anchored to the funding interval; comparing it
#                     against real-time references manufactured a fake
#                     -1.48% "discount" -- the fresh last trade was
#                     only -0.27% from Deribit)
#   settlement_price  0 changes, daily settle ts  -> SETTLEMENT
PRICE_SEMANTIC_TYPES = ("LAST_TRADE", "BEST_BID", "BEST_ASK", "BOOK_MID",
                        "INDEX", "FUNDING_MARK", "SETTLEMENT", "UNKNOWN")

BITNOMIAL_PRODUCT_DATA_PRICE_SEMANTICS = {
    "last_price": {"semantic_type": "LAST_TRADE",
                   "timestamp_field": "last_price_time",
                   "cadence_evidence": "4 changes/153 polls 2026-08-21"},
    "mark_price": {"semantic_type": "FUNDING_MARK",
                   "timestamp_field": None,
                   "cadence_evidence": "0 changes/153 polls 2026-08-21; "
                                       "funding-interval anchored",
                   "law": "NEVER compared against real-time references"},
    "settlement_price": {"semantic_type": "SETTLEMENT",
                         "timestamp_field": "settlement_time",
                         "cadence_evidence": "0 changes/153 polls; daily"},
}

# The rulebook identifies PBTCUC's underlying index as the CF Bitcoin
# Mid-Price Spot Rate. The live real-time index is still not exposed;
# the funding-rates endpoint (mount resolved 2026-08-21, see registry)
# provides price_index + mark_price PER SETTLED 8H INTERVAL. So
# PERP_MARK_MINUS_INDEX exists as an interval-anchored fact, never as
# a live spread.


# ---------------------------------------------------------------------
# LIVE PRICE HIERARCHY (operator law, BTC-L2 final commissioning).
# These are NOT interchangeable "prices" -- each has a distinct role
# and may only be compared with explicit semantics + ages persisted.
BITNOMIAL_PRICE_HIERARCHY = (
    ("BOOK_MID", "contemporaneous market reference (once WS book "
                 "integrity passes)"),
    ("BEST_BID_ASK", "executable market envelope"),
    ("LAST_TRADE", "tape evidence, potentially stale on a thin venue"),
    ("FUNDING_MARK", "funding-interval semantic only"),
    ("SETTLEMENT", "settlement semantic only"),
)

# STALE-LAST-TRADE LAW (predeclared 2026-08-21, BEFORE weekend soak;
# never tuned from favorable results). Rationale on record: BTC realized
# vol ~50%/yr -> ~7bp expected drift per minute; measured cross-venue
# spreads are ~18bp; beyond ~60s of trade staleness the comparison is
# dominated by drift, not by venue pricing. BOOK_MID supersedes
# LAST_TRADE for contemporaneous venue pricing once the book passes.
LAST_TRADE_MAX_AGE_S = 60.0


def last_trade_realtime_eligibility(age_s) -> dict:
    """Gate a LAST_TRADE value's participation in real-time comparison.
    UNKNOWN age is INELIGIBLE -- unknown is not fresh."""
    if age_s is None:
        return {"eligible": False,
                "reason": "LAST_TRADE_AGE_UNKNOWN",
                "policy_max_age_s": LAST_TRADE_MAX_AGE_S}
    if age_s > LAST_TRADE_MAX_AGE_S:
        return {"eligible": False,
                "reason": "LAST_TRADE_REALTIME_COMPARISON_INELIGIBLE",
                "age_s": round(float(age_s), 3),
                "policy_max_age_s": LAST_TRADE_MAX_AGE_S}
    return {"eligible": True, "age_s": round(float(age_s), 3),
            "policy_max_age_s": LAST_TRADE_MAX_AGE_S}


# ---------------------------------------------------------------------
# FUNDING NORMALIZATION LAW: native funding is preserved verbatim
# FIRST; comparable forms are derived separately and carry their
# derivation. Raw numbers across venues are NEVER directly compared.
VENUE_FUNDING_SEMANTICS = {
    "BITNOMIAL": {"native_form": "PER_INTERVAL_ACTUAL_SETTLED",
                  "interval_hours": 8.0,
                  "source": "/funding-rates/ (historical intervals)"},
    "DERIBIT": {"native_form": "CONTINUOUS_8H_EQUIVALENT",
                "interval_hours": 8.0,
                "source": "ticker current_funding (live estimate)"},
    "OKX": {"native_form": "PER_INTERVAL_CURRENT_ESTIMATE",
            "interval_hours": 8.0,
            "source": "funding-rate endpoint (next-settlement estimate)"},
    "KRAKEN_FUTURES": {"native_form": "PER_ITS_OWN_DOCS_UNVERIFIED",
                       "interval_hours": None,
                       "source": "tickers fundingRate; native interval "
                                 "semantics unverified against docs"},
}


def normalize_funding(venue: str, native_rate) -> dict:
    """Native first, derived second. Refuses annualization when the
    venue's interval semantics are unverified."""
    sem = VENUE_FUNDING_SEMANTICS.get(venue)
    if sem is None:
        raise SemanticsViolation(f"no funding semantics for {venue}")
    out = {"venue": venue, "native_rate": native_rate,
           "native_form": sem["native_form"],
           "interval_hours": sem["interval_hours"]}
    if native_rate is None:
        out["annualized_rate"] = None
        return out
    if sem["interval_hours"] is None:
        out["annualized_rate"] = None
        out["annualization_refused"] = ("interval semantics unverified "
                                        "-- NOT_ESTIMABLE")
        return out
    per_year = 8760.0 / sem["interval_hours"]
    out["annualized_rate"] = float(native_rate) * per_year
    out["annualization"] = f"native x {per_year:g} intervals/yr (simple)"
    return out


# ---------------------------------------------------------------------
# OI NORMALIZATION LAW: raw contracts are retained; BTC-equivalent /
# USD-notional are derived only where safely derivable, and provenance
# (venue + oi_class) survives normalization.
def normalize_open_interest(venue: str, raw_oi, *, btc_usd=None,
                            contract_btc=None) -> dict:
    sem = VENUE_OI_SEMANTICS.get(venue)
    if sem is None:
        raise SemanticsViolation(f"no OI semantics for {venue}")
    out = {"venue": venue, "oi_class": sem["oi_class"],
           "raw_oi": raw_oi}
    if raw_oi is None:
        out.update({"oi_btc_equivalent": None, "oi_usd_notional": None})
        return out
    v = float(raw_oi)
    if venue == "BITNOMIAL":
        # contracts of contract_btc BTC each (0.01 for PBTCUC, from spec)
        out["raw_unit"] = "CONTRACTS"
        if contract_btc is None:
            out["oi_btc_equivalent"] = None
            out["derivation_refused"] = "contract size not supplied"
        else:
            out["oi_btc_equivalent"] = v * float(contract_btc)
            out["oi_usd_notional"] = (out["oi_btc_equivalent"] *
                                      float(btc_usd) if btc_usd else None)
    elif venue == "DERIBIT":
        # inverse perp: OI is USD notional natively
        out["raw_unit"] = "USD_NOTIONAL"
        out["oi_usd_notional"] = v
        out["oi_btc_equivalent"] = (v / float(btc_usd) if btc_usd
                                    else None)
    elif venue == "KRAKEN_FUTURES":
        # PI_XBTUSD: 1 contract = 1 USD
        out["raw_unit"] = "CONTRACTS_1USD"
        out["oi_usd_notional"] = v
        out["oi_btc_equivalent"] = (v / float(btc_usd) if btc_usd
                                    else None)
    else:
        out["oi_btc_equivalent"] = None
        out["oi_usd_notional"] = None
        out["derivation_refused"] = "no safe derivation rule"
    return out


class SemanticsViolation(RuntimeError):
    pass


def convert_bitnomial_product_data_price(raw_ticks, *, product_spec: dict
                                         ) -> dict:
    """The ONLY sanctioned ticks->USD conversion. The increment comes
    from the SPECIFIC product's live spec -- never a hardcoded 5."""
    if raw_ticks is None:
        return {"raw_value": None, "canonical_value": None,
                "raw_unit": "TICKS", "canonical_unit": "USD_PER_BTC",
                "conversion": "MULTIPLY_BY_PRODUCT_SPEC_PRICE_INCREMENT"}
    inc = product_spec.get("price_increment")
    if inc is None:
        raise SemanticsViolation(
            "product spec carries no price_increment -- conversion "
            "refused, never guessed")
    return {"raw_value": raw_ticks, "raw_unit": "TICKS",
            "conversion": "MULTIPLY_BY_PRODUCT_SPEC_PRICE_INCREMENT",
            "price_increment": inc,
            "canonical_value": raw_ticks * inc,
            "canonical_unit": "USD_PER_BTC",
            "spec_source": f"product/spec/{product_spec.get('product_id')}"
                           f" symbol={product_spec.get('symbol')}"}


def charts_price_passthrough(usd_value) -> dict:
    """Charts OHLC is already USD. This function exists so the no-double-
    conversion law has a single named implementation to test."""
    return {"raw_value": usd_value, "raw_unit": "USD_ALREADY",
            "conversion": "NONE", "canonical_value": usd_value,
            "canonical_unit": "USD_PER_BTC"}
