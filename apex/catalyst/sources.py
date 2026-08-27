"""SOURCE ADAPTERS — the senses. Deterministic infrastructure, no LLM.

Retrieval is plumbing and must behave like plumbing: same inputs, same
outputs, no reasoning, no memory, no judgement. The language model runs
strictly downstream of a durable raw record, because the failure this
ordering prevents is the worst one available to us:

    LLM REMEMBERS A HEADLINE  ->  CATALYST FACT

A model asked "did anything happen?" will answer, and its answer will
vary when the world did not. A fetched document either exists on disk
with a hash and a URL, or it does not exist at all.

STDLIB ONLY. The runtime venv has no HTTP client and this mission adds
no dependency; urllib is enough to read an RSS feed, and a source layer
that cannot be installed is not a sense.

EVERY ADAPTER IS ISOLATED. One dead source degrades a cycle by one
source. A cycle reports what it reached AND what it failed to reach,
because silent partial coverage is indistinguishable from a quiet
world -- and those two states must never look alike.

known_from is RETRIEVAL time, never publication time. A release
published at 08:30 that we fetched at 08:33 was not actionable at
08:30, and recording otherwise would hand research three free minutes
of the future.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

TIMEOUT_S = 20
MAX_ITEMS_PER_SOURCE = 40

# Declared, honest, and contactable. SEC's fair-access policy expects a
# real contact; APEX_SOURCE_CONTACT supplies one without any operator
# identity being hardcoded into the repository.
_CONTACT = os.environ.get("APEX_SOURCE_CONTACT", "").strip()
USER_AGENT = ("APEX-Research/1.0 (automated market research"
              + (f"; {_CONTACT}" if _CONTACT else "") + ")")

SOURCE_TYPES = ("OFFICIAL_FEED", "OFFICIAL_API", "REGULATORY_FILING",
                "STATISTICAL_API", "NEWS_SEARCH", "COMPANY_IR")

# The classes a sweep is allowed to claim it searched. This exists so
# that "no catalyst" can never be silently confused with "no catalyst
# in the handful of places I happened to look" -- a cycle reports the
# classes it covered, and an absence is only ever an absence WITHIN
# that coverage.
COVERAGE_CLASSES = ("MACRO_OFFICIAL", "CORPORATE_OFFICIAL",
                    "COMPANY_IR", "REGULATORY", "BROAD_DISCOVERY")


class SourceUnavailable(RuntimeError):
    """This source could not be read. Not an event, not a silence."""


@dataclass(frozen=True)
class RawObservation:
    """One fetched document, before anything interprets it."""
    source_observation_id: str
    source: str
    source_type: str
    source_authority: str
    locator: str
    title: str
    published_time: str
    retrieved_time: str
    first_seen_time: str
    known_from: str
    raw_text_hash: str
    raw_excerpt: str
    entity_hints: tuple = ()
    release_sha: str = "UNKNOWN"

    def as_record(self) -> dict:
        return {"kind": "raw_source_observation", **asdict(self),
                "law": "raw evidence is immutable; interpretation never "
                       "replaces it",
                "decision_power": "SHADOW_CONTEXT_ONLY"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        raise SourceUnavailable(f"{url}: {type(e).__name__} {e}") from e


def _obs_id(source: str, locator: str, title: str) -> str:
    h = hashlib.sha256(f"{source}|{locator}|{title}".encode())
    return "SO_" + h.hexdigest()[:20]


# ------------------------------------------------------- entity hints

# DETERMINISTIC only. A ticker is hinted when its name or symbol
# literally appears. Anything cleverer than string matching is
# interpretation, and interpretation happens downstream of the ledger.
ENTITY_TERMS = {
    "AAPL": ("apple inc", "apple's", " apple "),
    "NVDA": ("nvidia",), "MSFT": ("microsoft",),
    "AMD": ("advanced micro devices", " amd "),
    "META": ("meta platforms", "facebook"), "AMZN": ("amazon",),
    "GOOGL": ("alphabet inc", "google"), "TSLA": ("tesla",),
    "AVGO": ("broadcom",), "INTC": ("intel corp", " intel "),
}
MACRO_TERMS = {
    "RATES": ("interest rate", "yield", "treasury", "fomc", "federal funds"),
    "FED": ("federal reserve", "fomc", "monetary policy", "powell"),
    "INFLATION": ("inflation", "consumer price", "cpi", "pce", "ppi"),
    "LABOR": ("employment", "payroll", "unemployment", "jobless"),
    "GROWTH": ("gross domestic product", "gdp", "retail sales"),
    "ENERGY": ("crude", "petroleum", "natural gas", "oil"),
    "USD": ("dollar", "exchange rate", "foreign exchange"),
    "VOLATILITY": ("volatility", "financial stability"),
}


_URL_RE = re.compile(r"https?://\S+|<[^>]+>")


def entity_hints(text: str) -> tuple:
    """Deterministic entity extraction from PROSE ONLY.

    URLs and markup are stripped first. Live traffic showed why: every
    Google News item embeds news.google.com links, so a story about
    Middle East oil supply was being tagged GOOGL. Feed furniture
    inflating a ticker's catalyst count is the same failure as one Fed
    sentence inflating an event count -- a plumbing artifact masquerading
    as a signal about a company.
    """
    low = f" {_URL_RE.sub(' ', text).lower()} "
    hits = [s for s, terms in ENTITY_TERMS.items()
            if any(t in low for t in terms)]
    hits += [m for m, terms in MACRO_TERMS.items()
             if any(t in low for t in terms)]
    return tuple(sorted(set(hits)))


# ------------------------------------------------------------ parsing

def _local(tag: str) -> str:
    """Tag name without its namespace."""
    return tag.split("}")[-1]


def _text(node, *names):
    """Namespace-agnostic child lookup.

    Feeds arrive as RSS 2.0, RSS 1.0/RDF and Atom, and each puts its
    items in a different namespace. Matching qualified names meant the
    Fed's H.15 rates feed parsed to zero items while reporting success
    -- a blind source wearing a green light, which is the exact failure
    class the coverage record exists to expose.
    """
    want = {n.lower() for n in names}
    for el in node:
        if _local(el.tag).lower() in want and (el.text or "").strip():
            return el.text.strip()
    return ""


def _parse_feed(body: bytes, *, source: str, source_type: str,
                authority: str, release_sha: str) -> list:
    """RSS or Atom. A feed we cannot parse is unavailable, not empty."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise SourceUnavailable(f"{source}: unparseable feed ({e})")

    items = [el for el in root.iter()
             if _local(el.tag).lower() in ("item", "entry")]

    out, now = [], _now()
    for it in items[:MAX_ITEMS_PER_SOURCE]:
        title = _text(it, "title")
        if not title:
            continue
        link = _text(it, "link", "id", "guid")
        if not link:                       # Atom puts it in an attribute
            for el in it:
                if _local(el.tag).lower() == "link" and el.get("href"):
                    link = el.get("href")
                    break
        pub = _text(it, "pubDate", "published", "updated", "date")
        desc = _text(it, "description", "summary", "content")[:1200]
        blob = f"{title}\n{desc}"
        out.append(RawObservation(
            source_observation_id=_obs_id(source, link, title),
            source=source, source_type=source_type,
            source_authority=authority, locator=link or source,
            title=title, published_time=pub or "UNKNOWN",
            retrieved_time=now, first_seen_time=now, known_from=now,
            raw_text_hash=hashlib.sha256(blob.encode()).hexdigest(),
            raw_excerpt=desc, entity_hints=entity_hints(blob),
            release_sha=release_sha))
    return out


# ----------------------------------------------------------- adapters

FEED_SOURCES = (
    ("FEDERAL_RESERVE_PRESS", "PRIMARY_OFFICIAL", "OFFICIAL_FEED",
     "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("FEDERAL_RESERVE_MONETARY", "PRIMARY_OFFICIAL", "OFFICIAL_FEED",
     "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("FEDERAL_RESERVE_SPEECHES", "PRIMARY_OFFICIAL", "OFFICIAL_FEED",
     "https://www.federalreserve.gov/feeds/speeches.xml"),
    ("FEDERAL_RESERVE_H15_RATES", "PRIMARY_OFFICIAL", "OFFICIAL_FEED",
     "https://www.federalreserve.gov/feeds/h15.xml"),
    ("BUREAU_ECONOMIC_ANALYSIS", "PRIMARY_OFFICIAL", "OFFICIAL_FEED",
     "https://apps.bea.gov/rss/rss.xml"),
)

# ---- PRIMARY MACRO: statistical releases, not headlines about them.
# A number from the agency that computed it beats a story about it.
BLS_SERIES = {"CUUR0000SA0": "CPI (all urban consumers)",
              "LNS14000000": "Unemployment rate",
              "CES0000000001": "Total nonfarm payrolls"}

TREASURY_YIELD_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center"
    "/interest-rates/pages/xml?data=daily_treasury_yield_curve"
    "&field_tdr_date_value=2026")

# ---- COMPANY IR: the issuer speaking directly, ahead of any filing.
IR_FEEDS = (
    ("APPLE_NEWSROOM", "AAPL",
     "https://www.apple.com/newsroom/rss-feed.rss"),
    ("NVIDIA_NEWSROOM", "NVDA",
     "https://nvidianews.nvidia.com/releases.xml"),
    ("MICROSOFT_NEWS", "MSFT", "https://news.microsoft.com/feed/"),
)

# ---- BROAD DISCOVERY: how APEX first learns something happened at
# all. Deliberately tiered AGGREGATOR -- below WIRE, therefore NOT
# fact-bearing. These may raise a question; only a primary source may
# answer it. Kept small on purpose: this is minimum world awareness,
# not a news firehose.
DISCOVERY_FEEDS = (
    ("GOOGLE_NEWS_MARKETS", "https://news.google.com/rss/search?"
     "q=stock+market+OR+federal+reserve+OR+earnings+when:1d"
     "&hl=en-US&gl=US&ceid=US:en"),
    ("GOOGLE_NEWS_GEOPOLITICS", "https://news.google.com/rss/search?"
     "q=(geopolitical+OR+tariff+OR+sanctions+OR+oil+supply)+when:1d"
     "&hl=en-US&gl=US&ceid=US:en"),
    ("YAHOO_FINANCE", "https://finance.yahoo.com/news/rssindex"),
)

FEDERAL_REGISTER_URL = (
    "https://www.federalregister.gov/api/v1/documents.rss"
    "?per_page=20&order=newest")

# combat universe only -- SEC is polled per-issuer, so the request
# count is bounded by the roster rather than by the market
SEC_CIKS = {"AAPL": "0000320193", "NVDA": "0001045810",
            "MSFT": "0000789019"}
MATERIAL_FORMS = ("8-K", "10-Q", "10-K", "425", "SC 13D", "DEFM14A")


def fetch_feed(name, authority, stype, url, *, release_sha="UNKNOWN"):
    return _parse_feed(_get(url), source=name, source_type=stype,
                       authority=authority, release_sha=release_sha)


def fetch_sec_filings(symbol: str, cik: str, *,
                      release_sha: str = "UNKNOWN") -> list:
    """Company-direct regulatory filings. An 8-K is the company saying
    it itself -- the highest authority available for a corporate fact."""
    body = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    try:
        recent = json.loads(body)["filings"]["recent"]
    except (json.JSONDecodeError, KeyError) as e:
        raise SourceUnavailable(f"SEC {symbol}: unexpected shape ({e})")

    now, out = _now(), []
    forms = recent.get("form", [])
    for i, form in enumerate(forms[:MAX_ITEMS_PER_SOURCE]):
        if form not in MATERIAL_FORMS:
            continue
        acc = recent.get("accessionNumber", [""] * len(forms))[i]
        date = recent.get("filingDate", [""] * len(forms))[i]
        doc = recent.get("primaryDocument", [""] * len(forms))[i]
        title = f"{symbol} files {form}"
        link = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{acc.replace('-', '')}/{doc}")
        blob = f"{title}|{acc}"
        out.append(RawObservation(
            source_observation_id=_obs_id("SEC_EDGAR", acc, title),
            source="SEC_EDGAR", source_type="REGULATORY_FILING",
            source_authority="COMPANY_DIRECT", locator=link,
            title=title, published_time=date or "UNKNOWN",
            retrieved_time=now, first_seen_time=now, known_from=now,
            raw_text_hash=hashlib.sha256(blob.encode()).hexdigest(),
            raw_excerpt=f"form={form} accession={acc}",
            entity_hints=(symbol,), release_sha=release_sha))
    return out


def fetch_bls(*, release_sha: str = "UNKNOWN") -> list:
    """Latest datapoint per tracked series.

    The observation id is keyed on series+year+period, so re-fetching
    an unchanged release is not new evidence -- only an actual new
    print creates an observation.
    """
    out, now = [], _now()
    for sid, label in BLS_SERIES.items():
        body = _get(f"https://api.bls.gov/publicAPI/v2/timeseries/"
                    f"data/{sid}")
        try:
            series = json.loads(body)["Results"]["series"][0]["data"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise SourceUnavailable(f"BLS {sid}: unexpected shape ({e})")
        if not series:
            continue
        d = series[0]
        period = f"{d.get('year')}-{d.get('periodName')}"
        title = f"{label}: {d.get('value')} ({period})"
        blob = f"{sid}|{period}|{d.get('value')}"
        out.append(RawObservation(
            source_observation_id=_obs_id("BLS", sid, period),
            source="BLS", source_type="STATISTICAL_API",
            source_authority="PRIMARY_OFFICIAL",
            locator=f"https://data.bls.gov/timeseries/{sid}",
            title=title, published_time=period,
            retrieved_time=now, first_seen_time=now, known_from=now,
            raw_text_hash=hashlib.sha256(blob.encode()).hexdigest(),
            raw_excerpt=f"series={sid} value={d.get('value')}",
            entity_hints=entity_hints(label), release_sha=release_sha))
    return out


def fetch_treasury_curve(*, release_sha: str = "UNKNOWN") -> list:
    """The most recent daily yield curve. Rates are a macro catalyst in
    their own right, and this is the issuer's own publication."""
    root = ET.fromstring(_get(TREASURY_YIELD_URL))
    entries = [e for e in root.iter() if _local(e.tag) == "entry"]
    if not entries:
        raise SourceUnavailable("Treasury: no curve entries")
    last = entries[-1]
    vals = {_local(c.tag): (c.text or "").strip() for c in last.iter()
            if (c.text or "").strip()}
    date = vals.get("NEW_DATE", "UNKNOWN")[:10]
    keys = [k for k in ("BC_2YEAR", "BC_10YEAR", "BC_30YEAR")
            if k in vals]
    title = ("US Treasury yield curve " + date + ": "
             + ", ".join(f"{k.replace('BC_', '')} {vals[k]}"
                         for k in keys))
    blob = f"{date}|" + "|".join(f"{k}={vals[k]}" for k in sorted(vals))
    return [RawObservation(
        source_observation_id=_obs_id("US_TREASURY", "yield_curve", date),
        source="US_TREASURY", source_type="OFFICIAL_API",
        source_authority="PRIMARY_OFFICIAL",
        locator=TREASURY_YIELD_URL, title=title, published_time=date,
        retrieved_time=_now(), first_seen_time=_now(), known_from=_now(),
        raw_text_hash=hashlib.sha256(blob.encode()).hexdigest(),
        raw_excerpt=", ".join(f"{k}={vals[k]}" for k in keys),
        entity_hints=("RATES", "FED"), release_sha=release_sha)]


def fetch_all(*, release_sha: str = "UNKNOWN",
              include_sec: bool = True,
              include_discovery: bool = True) -> dict:
    """Run every adapter across all coverage classes. Never raises.

    Returns observations plus an explicit per-source outcome AND the
    coverage classes actually reached. The second part matters as much
    as the first: without it, "no catalyst" is indistinguishable from
    "no catalyst among the handful of places I looked", and those are
    very different claims to hand a research engine.
    """
    obs, ok, failed, empty = [], [], {}, []
    classes_ok, classes_attempted = set(), set()

    def attempt(name, cls, fn):
        classes_attempted.add(cls)
        try:
            got = fn()
            obs.extend(got)
            ok.append({"source": name, "class": cls,
                       "observations": len(got)})
            classes_ok.add(cls)
            if not got:
                empty.append(name)
        except SourceUnavailable as e:
            failed[name] = str(e)[:200]
        except Exception as e:                          # noqa: BLE001
            # an adapter bug must cost one source, never the sweep
            failed[name] = f"{type(e).__name__}: {str(e)[:160]}"

    # ---- PRIMARY MACRO
    for name, authority, stype, url in FEED_SOURCES:
        attempt(name, "MACRO_OFFICIAL",
                lambda n=name, a=authority, t=stype, u=url:
                fetch_feed(n, a, t, u, release_sha=release_sha))
    attempt("BLS", "MACRO_OFFICIAL",
            lambda: fetch_bls(release_sha=release_sha))
    attempt("US_TREASURY", "MACRO_OFFICIAL",
            lambda: fetch_treasury_curve(release_sha=release_sha))

    # ---- CORPORATE OFFICIAL (the issuer's own filings)
    if include_sec:
        for sym, cik in SEC_CIKS.items():
            attempt(f"SEC_EDGAR:{sym}", "CORPORATE_OFFICIAL",
                    lambda sy=sym, c=cik:
                    fetch_sec_filings(sy, c, release_sha=release_sha))

    # ---- COMPANY IR (the issuer speaking, often before the filing)
    for name, sym, url in IR_FEEDS:
        attempt(name, "COMPANY_IR",
                lambda n=name, u=url: fetch_feed(
                    n, "COMPANY_DIRECT", "COMPANY_IR", u,
                    release_sha=release_sha))

    # ---- REGULATORY
    attempt("FEDERAL_REGISTER", "REGULATORY",
            lambda: fetch_feed("FEDERAL_REGISTER", "PRIMARY_OFFICIAL",
                               "OFFICIAL_FEED", FEDERAL_REGISTER_URL,
                               release_sha=release_sha))

    # ---- BROAD DISCOVERY (leads only: AGGREGATOR is not fact-bearing)
    if include_discovery:
        for name, url in DISCOVERY_FEEDS:
            attempt(name, "BROAD_DISCOVERY",
                    lambda n=name, u=url: fetch_feed(
                        n, "AGGREGATOR", "NEWS_SEARCH", u,
                        release_sha=release_sha))

    total = len(ok) + len(failed)
    missing = sorted(classes_attempted - classes_ok)
    return {"kind": "source_sweep",
            "retrieved_utc": _now(),
            "observations": obs,
            "sources_checked": total,
            "sources_succeeded": len(ok),
            "sources_failed": len(failed),
            "succeeded": ok, "failures": failed,
            # a source that parses to nothing every time is blind, not
            # quiet; naming it keeps a green light from hiding a gap
            "sources_yielding_nothing": empty,
            "coverage_classes_reached": sorted(classes_ok),
            "coverage_classes_missing": missing,
            "coverage": (f"{len(ok)}/{total}" if total else "0/0"),
            "absence_is_qualified_by": sorted(classes_ok),
            "law": "a source that could not be read is UNAVAILABLE, "
                   "never a quiet world; and an absence of catalysts "
                   "is only ever an absence within the classes reached",
            "decision_power": "SHADOW_CONTEXT_ONLY"}
