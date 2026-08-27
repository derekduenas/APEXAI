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
                "STATISTICAL_API", "NEWS_SEARCH")


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


def entity_hints(text: str) -> tuple:
    low = f" {text.lower()} "
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


def fetch_all(*, release_sha: str = "UNKNOWN",
              include_sec: bool = True) -> dict:
    """Run every adapter. Never raises: a cycle reports coverage.

    Returns observations plus an explicit per-source outcome, because
    'we found nothing' and 'we could not look' are different worlds and
    a research record that cannot tell them apart is worthless.
    """
    obs, ok, failed, empty = [], [], {}, []

    for name, authority, stype, url in FEED_SOURCES:
        try:
            got = fetch_feed(name, authority, stype, url,
                             release_sha=release_sha)
            obs.extend(got)
            ok.append({"source": name, "observations": len(got)})
            if not got:
                empty.append(name)
        except SourceUnavailable as e:
            failed[name] = str(e)[:200]

    if include_sec:
        for sym, cik in SEC_CIKS.items():
            nm = f"SEC_EDGAR:{sym}"
            try:
                got = fetch_sec_filings(sym, cik, release_sha=release_sha)
                obs.extend(got)
                ok.append({"source": nm, "observations": len(got)})
                if not got:
                    empty.append(nm)
            except SourceUnavailable as e:
                failed[nm] = str(e)[:200]

    total = len(ok) + len(failed)
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
            "coverage": (f"{len(ok)}/{total}" if total else "0/0"),
            "law": "a source that could not be read is UNAVAILABLE, "
                   "never a quiet world",
            "decision_power": "SHADOW_CONTEXT_ONLY"}
