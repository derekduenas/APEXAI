"""Live risk-free rate source (market-data acquisition layer) — the official US Treasury daily par
yield curve, with real provenance.

WHY THIS EXISTS (measured 2026-08-18): the first live Options Analytics
run capped EVERY analytics state at LOW quality, correctly, because its
rate input was a static approximate constant deliberately stamped as
already-stale. That was the honest thing to do at the time, but it
meant rate-source staleness dominated the quality signal and masked
whatever the real short-DTE numerical behavior was.

LOCATION NOTE: this lives in apex/intraday/ (the market-data
acquisition layer), NOT in apex/option_analytics/. That package is
deliberately pure computation over caller-supplied inputs and its own
firewall test forbids any network fetch inside it -- a rule this
module would have violated. The caller fetches; option_analytics
computes.

This fetches the real curve. It does NOT hardcode a yield: the values
come from Treasury's own published XML at request time, carrying the
record date they were published for.

Requirements enforced structurally, not by convention:
  - provenance          -> source URL + publisher recorded on every curve
  - timestamp           -> Treasury's own record_date, not our fetch time
  - tenor               -> full published tenor set, not one scalar
  - interpolation       -> named method, recorded on the curve
  - freshness           -> age in days computed from the record date
  - no source="ASSUMED" -> RiskFreeCurve already refuses that literal

decision_power: NONE_MARKET_DATA.
"""
from __future__ import annotations

import os
import re
import ssl
import urllib.request
from dataclasses import dataclass

from apex.option_analytics.rate_curve import RiskFreeCurve

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                "interest-rates/pages/xml?data=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}")

SOURCE_NAME = "US_TREASURY_DAILY_PAR_YIELD_CURVE"
INTERPOLATION_METHOD = "LINEAR_IN_TENOR_YEARS"

# ---- short end (Phase 1.1) -------------------------------------------
# The par yield curve's front point is 1 MONTH, so a 1-2 DTE option's
# tenor sits below it and rate_for_tenor() correctly refuses to
# extrapolate. Two authoritative sources cover the gap, both verified
# reachable and same-day on 2026-08-18:
#   - NY Fed SOFR       (overnight, the official secured reference rate)
#   - Treasury bill rates (4wk/6wk/8wk/13wk/17wk coupon-equivalent yields)
# Composed together these give real coverage from overnight outward. No
# value is hardcoded; both are fetched at request time.
NY_FED_SOFR_URL = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/1.json"
TREASURY_BILL_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                     "interest-rates/pages/xml?data=daily_treasury_bill_rates"
                     "&field_tdr_date_value={year}")
COMPOSITE_SOURCE_NAME = "SOFR_PLUS_TREASURY_BILLS_PLUS_PAR_CURVE"
OVERNIGHT_TENOR_YEARS = 1.0 / 365.0

# Treasury bill coupon-equivalent yield fields -> tenor in years.
BILL_FIELDS = (
    ("ROUND_B1_YIELD_4WK_2", 28 / 365.0), ("ROUND_B1_YIELD_6WK_2", 42 / 365.0),
    ("ROUND_B1_YIELD_8WK_2", 56 / 365.0), ("ROUND_B1_YIELD_13WK_2", 91 / 365.0),
    ("ROUND_B1_YIELD_17WK_2", 119 / 365.0),
)

# Treasury's published tenor points, in years.
TENOR_FIELDS = (
    ("BC_1MONTH", 1 / 12), ("BC_1_5MONTH", 1.5 / 12), ("BC_2MONTH", 2 / 12),
    ("BC_3MONTH", 0.25), ("BC_4MONTH", 4 / 12), ("BC_6MONTH", 0.5),
    ("BC_1YEAR", 1.0), ("BC_2YEAR", 2.0), ("BC_3YEAR", 3.0),
    ("BC_5YEAR", 5.0), ("BC_7YEAR", 7.0), ("BC_10YEAR", 10.0),
    ("BC_20YEAR", 20.0), ("BC_30YEAR", 30.0),
)

# Beyond this the curve is stale enough that callers should let
# live_quality degrade the analytics state rather than trust it.
FRESH_MAX_AGE_DAYS = 4.0


class TreasuryRateSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RateSourceProvenance:
    source_name: str
    source_url: str
    record_date: str
    fetched_at: str
    age_days: float
    interpolation_method: str
    tenor_count: int
    is_fresh: bool
    decision_power: str = "NONE_MARKET_DATA"

    def as_record(self) -> dict:
        from dataclasses import asdict
        return {"kind": "rate_source_provenance", **asdict(self)}


def _ssl_ctx() -> ssl.SSLContext:
    return ssl.create_default_context(
        cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))


def fetch_latest_curve(*, now, year: int | None = None) -> tuple:
    """Returns (RiskFreeCurve, RateSourceProvenance) from the REAL
    published curve. Raises rather than substituting a default -- a
    missing rate source must surface, never be papered over."""
    import pandas as pd
    now = pd.Timestamp(now)
    url = TREASURY_URL.format(year=year or now.year)
    req = urllib.request.Request(url, headers={"User-Agent": "apex-research"})
    try:
        with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx()) as resp:
            body = resp.read().decode()
    except Exception as e:  # noqa: BLE001
        raise TreasuryRateSourceError(
            f"could not reach the Treasury curve ({type(e).__name__}: {e}) -- "
            f"refusing to substitute an assumed rate") from e

    blocks = body.split("<m:properties>")
    if len(blocks) < 2:
        raise TreasuryRateSourceError("no curve rows in the Treasury response")
    latest = blocks[-1]

    m = re.search(r"<d:NEW_DATE[^>]*>([^<]+)</d:NEW_DATE>", latest)
    if not m:
        raise TreasuryRateSourceError("Treasury row carries no NEW_DATE")
    record_date = pd.Timestamp(m.group(1))
    if record_date.tzinfo is None:
        record_date = record_date.tz_localize("UTC")

    points = []
    for field, tenor_years in TENOR_FIELDS:
        fm = re.search(rf"<d:{field}[^>]*>([^<]+)</d:{field}>", latest)
        if not fm:
            continue
        try:
            pct = float(fm.group(1))
        except ValueError:
            continue
        points.append((tenor_years, pct / 100.0))

    if len(points) < 2:
        raise TreasuryRateSourceError(
            f"only {len(points)} usable tenor points -- refusing to build a "
            f"curve that cannot interpolate")

    points.sort(key=lambda p: p[0])
    age_days = (now - record_date).total_seconds() / 86400.0
    curve = RiskFreeCurve(points=tuple(points), source=SOURCE_NAME,
                          as_of=str(record_date))
    prov = RateSourceProvenance(
        source_name=SOURCE_NAME, source_url=url, record_date=str(record_date),
        fetched_at=str(now), age_days=round(age_days, 4),
        interpolation_method=INTERPOLATION_METHOD, tenor_count=len(points),
        is_fresh=(age_days <= FRESH_MAX_AGE_DAYS))
    return curve, prov


def _fetch_sofr(*, now) -> tuple:
    """NY Fed SOFR — the official overnight secured reference rate.
    Returns (tenor_years, rate, record_date) or raises."""
    import json as _json

    import pandas as pd
    req = urllib.request.Request(NY_FED_SOFR_URL,
                                 headers={"User-Agent": "apex-research"})
    with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
        body = _json.loads(resp.read().decode())
    rows = body.get("refRates") or []
    if not rows:
        raise TreasuryRateSourceError("NY Fed returned no SOFR row")
    row = rows[0]
    pct = row.get("percentRate")
    if pct is None:
        raise TreasuryRateSourceError("SOFR row carries no percentRate")
    rd = pd.Timestamp(row["effectiveDate"])
    if rd.tzinfo is None:
        rd = rd.tz_localize("UTC")
    return OVERNIGHT_TENOR_YEARS, float(pct) / 100.0, rd


def _fetch_bills(*, now, year: int | None = None) -> list:
    """Treasury bill coupon-equivalent yields (4wk..17wk)."""
    import pandas as pd
    url = TREASURY_BILL_URL.format(year=year or pd.Timestamp(now).year)
    req = urllib.request.Request(url, headers={"User-Agent": "apex-research"})
    with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx()) as resp:
        body = resp.read().decode()
    blocks = body.split("<m:properties>")
    if len(blocks) < 2:
        raise TreasuryRateSourceError("no bill rows in the Treasury response")
    latest = blocks[-1]
    pts = []
    for field, tenor in BILL_FIELDS:
        m = re.search(rf"<d:{field}[^>]*>([^<]+)</d:{field}>", latest)
        if not m:
            continue
        try:
            pts.append((tenor, float(m.group(1)) / 100.0))
        except ValueError:
            continue
    return pts


def fetch_composite_curve(*, now, year: int | None = None) -> tuple:
    """Full front-to-back curve: SOFR (overnight) + Treasury bills
    (4wk-17wk) + the par yield curve (1m-30y).

    Each leg is fetched independently and a leg that fails is OMITTED
    rather than substituted -- a curve missing its short end will simply
    return None for short tenors, which is the honest answer, exactly as
    before. Only the par curve is mandatory."""
    import pandas as pd
    now = pd.Timestamp(now)
    par_curve, par_prov = fetch_latest_curve(now=now, year=year)
    points = list(par_curve.points)
    legs = ["PAR_CURVE"]

    try:
        t, r, _rd = _fetch_sofr(now=now)
        points.append((t, r))
        legs.append("SOFR_OVERNIGHT")
    except Exception as e:                                  # noqa: BLE001
        print(f"SOFR leg unavailable ({type(e).__name__}) -- short end will "
              f"return UNKNOWN below the bill/par front point")

    try:
        bill_pts = _fetch_bills(now=now, year=year)
        if bill_pts:
            points.extend(bill_pts)
            legs.append("TREASURY_BILLS")
    except Exception as e:                                  # noqa: BLE001
        print(f"bill leg unavailable ({type(e).__name__})")

    # De-duplicate by tenor, keeping the first (shortest-dated
    # authoritative) source's value when two legs quote the same tenor.
    # The rounded value is used ONLY as a dedup key -- the ORIGINAL
    # tenor is what gets stored. Rounding the stored value nudged the
    # front point upward (1/365 -> 0.00273973) so an exactly-1-DTE query
    # fell microscopically below it and returned None; caught in the
    # Phase 1.1 verification run.
    merged: dict = {}
    for tenor, rate in points:
        merged.setdefault(round(tenor, 8), (tenor, rate))
    final = sorted(merged.values(), key=lambda p: p[0])

    curve = RiskFreeCurve(points=tuple(final), source=COMPOSITE_SOURCE_NAME,
                          as_of=par_prov.record_date)
    prov = RateSourceProvenance(
        source_name=COMPOSITE_SOURCE_NAME + "[" + "+".join(legs) + "]",
        source_url=NY_FED_SOFR_URL + " | " + par_prov.source_url,
        record_date=par_prov.record_date, fetched_at=str(now),
        age_days=par_prov.age_days, interpolation_method=INTERPOLATION_METHOD,
        tenor_count=len(final),
        is_fresh=par_prov.is_fresh and len(legs) >= 2)
    return curve, prov
