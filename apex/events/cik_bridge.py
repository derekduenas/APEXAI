"""Symbol -> CIK identity bridge, from the SEC's own mapping.

Completes the Event Eyes (T1 item 6): without this, catalyst_state
honestly answered EVENT_UNCERTAIN for every symbol. The source is
https://www.sec.gov/files/company_tickers.json — the SEC's authoritative
ticker->CIK file — fetched once, cached on disk with a fetched_at stamp,
and refreshed only when older than REFRESH_DAYS.

Absence law: an unmapped symbol returns None, and catalyst_state turns
None into EVENT_UNCERTAIN. The bridge never guesses; recycled tickers
are the identity trap this repo has been burned by before.
"""
from __future__ import annotations

import json
from pathlib import Path

CACHE = Path("data/reference/sec_company_tickers.json")
URL = "https://www.sec.gov/files/company_tickers.json"
UA = "APEX research derek@apex.local"          # SEC requires a real UA
REFRESH_DAYS = 7


def refresh(force: bool = False) -> dict:
    """Fetch/refresh the cache. Returns {"status": ..., "n": int}."""
    import pandas as pd
    if CACHE.exists() and not force:
        try:
            meta = json.loads(CACHE.read_text())
            age = (pd.Timestamp.now(tz="UTC")
                   - pd.Timestamp(meta["fetched_at"]))
            if age < pd.Timedelta(days=REFRESH_DAYS):
                return {"status": "CACHED", "n": len(meta["map"])}
        except (json.JSONDecodeError, KeyError):
            pass
    import ssl
    import urllib.request
    import os
    ctx = ssl.create_default_context(
        cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    raw = json.loads(urllib.request.urlopen(req, timeout=45,
                                            context=ctx).read())
    # SEC shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": ...}}
    mapping = {v["ticker"].upper(): str(v["cik_str"])
               for v in raw.values() if v.get("ticker")}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(
        {"fetched_at": str(pd.Timestamp.now(tz="UTC")),
         "source": URL, "map": mapping}))
    return {"status": "FETCHED", "n": len(mapping)}


def cik_of(symbol: str) -> str | None:
    """None = unmapped or no cache — the caller's catalyst state becomes
    EVENT_UNCERTAIN, never a guess."""
    if not CACHE.exists():
        return None
    try:
        mapping = json.loads(CACHE.read_text())["map"]
    except (json.JSONDecodeError, KeyError):
        return None
    return mapping.get(symbol.upper().replace(".US", ""))
