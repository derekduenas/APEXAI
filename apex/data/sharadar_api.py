"""Sharadar's OWN API -- https://api.sharadar.com/v1.0/data/<table>

NOT data.nasdaq.com. `apex/data/nasdaq_api.py` targets the Nasdaq Data Link
datatables host, which is a DIFFERENT service and irrelevant to this
subscription; hours were lost diagnosing an edge/WAF 429 there that returned the
identical response for a deliberately invalid key. This module is the correct
client.

THE BEHAVIOUR THIS MODULE EXISTS TO DEFEND AGAINST

**[measured 2026-08-11]** The API TRUNCATES SILENTLY. A request for five
trading days of SEP -- about 29,500 rows -- returns exactly 10,000 rows with
HTTP 200, no error, no warning and no truncation header. Nothing in the response
distinguishes "here is your data" from "here is a third of your data".

A snapshot built without guarding this would look complete, hash cleanly, pass
every schema check, and be missing two thirds of the market. Every downstream
number would be wrong in a way no test in this repository could detect, because
the data would be internally consistent.

THE GUARD: a page whose row count EQUALS the requested limit is treated as
possibly truncated and MUST be followed by another page. Only a short page
terminates a pull. `fetch_table` raises rather than returning a suspect result.

RATE LIMITING, from the response headers themselves:
    X-RateLimit-Limit / Remaining            request count
    X-RateLimit-Weighted-Limit / Remaining   weighted budget (a big page costs more)
    X-RateLimit-Cost                         what the last call cost
    X-RateLimit-Reset                        unix seconds until the window resets
The client reads these and sleeps until reset rather than blundering into a 429.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

BASE_URL = "https://api.sharadar.com/v1.0"
ENV_VAR = "NASDAQ_DATA_LINK_API_KEY"
CA_BUNDLE = os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem")

# The observed default cap. Requests are paged at this size and any full page is
# treated as suspect until a short page proves the pull complete.
PAGE_SIZE = 10_000

# Verified to return complete results where 10,000 truncates. Cost scales with
# the limit (cost ~ limit/1000), so this is budget, not free.
MAX_LIMIT = 100_000

# Keep a reserve so a concurrent process cannot push us into a hard throttle.
WEIGHTED_RESERVE = 2_000

# The rate-limit window is 15 minutes; a sleep must be able to span it.
MAX_WINDOW_WAIT = 960.0


class SharadarError(RuntimeError):
    """The API could not supply what was asked for."""


class ApiKeyMissing(SharadarError):
    """The API key environment variable is not set."""


class SilentTruncation(SharadarError):
    """A response may have been truncated and the caller must not use it."""


def api_key() -> str:
    key = os.environ.get(ENV_VAR, "").strip()
    if not key:
        raise ApiKeyMissing(
            f"{ENV_VAR} is not set.\n"
            f"      export {ENV_VAR}='your-key-here'\n"
            f"  The key is read from the environment and nowhere else."
        )
    return key


def _redact(text: str, key: str) -> str:
    return text.replace(key, "<API_KEY>") if key else text


def strip_credentials(url: str) -> str:
    """Remove api_key from a URL before it is stored or shown. Sink-level."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in {"api_key", "apikey", "auth_token"}
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(kept), parsed.fragment)
    )


@dataclass
class RateLimit:
    remaining: int = 0
    weighted_remaining: int = 0
    weighted_limit: int = 0
    reset_epoch: int = 0
    last_cost: int = 0

    def update(self, headers) -> None:
        def as_int(name, default=0):
            try:
                return int(headers.get(name, default))
            except (TypeError, ValueError):
                return default

        self.remaining = as_int("X-RateLimit-Remaining")
        self.weighted_remaining = as_int("X-RateLimit-Weighted-Remaining")
        self.weighted_limit = as_int("X-RateLimit-Weighted-Limit")
        self.reset_epoch = as_int("X-RateLimit-Reset")
        self.last_cost = as_int("X-RateLimit-Cost")

    def wait_if_needed(self) -> float:
        """Sleep until the window ACTUALLY resets if the budget is nearly gone.

        The window is 15 minutes. An earlier version capped each sleep at 300s,
        so it woke with the window still open, slept again, and stalled a caller
        for ten minutes without making progress. Sleep the whole way or not at
        all.
        """
        if self.weighted_limit and self.weighted_remaining <= WEIGHTED_RESERVE:
            pause = max(0.0, self.reset_epoch - time.time()) + 2.0
            if pause > 0:
                time.sleep(min(pause, MAX_WINDOW_WAIT))
                return pause
        return 0.0


@dataclass
class FetchLog:
    requests: int = 0
    pages: int = 0
    waits: int = 0
    started_at: str = ""
    endpoints: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": "Sharadar API v1.0 (api.sharadar.com)",
            "requests": self.requests,
            "pages": self.pages,
            "rate_limit_waits": self.waits,
            "started_at": self.started_at,
            "endpoints": self.endpoints,
        }


class SharadarClient:
    def __init__(self, key: str | None = None) -> None:
        self._key = key or api_key()
        self._ctx = ssl.create_default_context(cafile=CA_BUNDLE)
        self.rate = RateLimit()
        self.log = FetchLog(started_at=dt.datetime.now(dt.timezone.utc).isoformat())

    def _request(self, table: str, params: dict) -> tuple[str, dict, str]:
        merged = dict(params)
        merged["api_key"] = self._key
        url = f"{BASE_URL}/data/{table}?" + urllib.parse.urlencode(merged)
        safe = strip_credentials(url)

        waited = self.rate.wait_if_needed()
        if waited:
            self.log.waits += 1

        request = urllib.request.Request(
            url, headers={"User-Agent": "apex-equities-research/0.1"}
        )
        self.log.requests += 1
        endpoint = f"{BASE_URL}/data/{table}"
        if endpoint not in self.log.endpoints:
            self.log.endpoints.append(endpoint)

        try:
            with urllib.request.urlopen(request, timeout=180, context=self._ctx) as response:
                body = response.read().decode("utf-8")
                self.rate.update(response.headers)
                return body, dict(response.headers), safe
        except urllib.error.HTTPError as exc:
            detail = _redact(exc.read().decode()[:300], self._key)
            raise SharadarError(f"{table}: HTTP {exc.code} from {safe} :: {detail}") from None

    def fetch_chunk(self, table: str, params: dict, limit: int):
        """One request. Returns (columns, rows, truncated).

        `truncated` is True when the row count EQUALS the limit, which is the
        only signal this API gives that data was withheld -- there is no error,
        no header and no flag.
        """
        query = dict(params)
        query["limit"] = limit
        body, _, safe = self._request(table, query)

        reader = csv.reader(io.StringIO(body))
        try:
            columns = next(reader)
        except StopIteration:
            raise SharadarError(f"{table}: empty response from {safe}") from None
        rows = list(reader)
        return columns, rows, len(rows) >= limit

    def fetch_table(self, table: str, params: dict | None = None, limit: int = MAX_LIMIT):
        """Fetch a table slice, PROVING it was not silently truncated.

        Paging is deliberately NOT used. **[measured 2026-08-11]** `page` is
        IGNORED when `limit` is set: pages 1, 2 and 3 of the same query return
        byte-identical rows. A paging loop therefore never terminates, and --
        worse -- a naive implementation would happily concatenate the same page
        many times and call the duplicate-laden result a dataset.

        Instead the limit is raised until the response is strictly SHORTER than
        it, which is the only available proof of completeness. If even the
        maximum limit comes back full, the caller must narrow the date range;
        this raises rather than returning a suspect result.
        """
        query = dict(params or {})
        columns, rows, truncated = self.fetch_chunk(table, query, limit)

        if truncated:
            raise SilentTruncation(
                f"{table}: returned exactly {len(rows):,} rows at limit={limit:,}, "
                f"so the response is TRUNCATED and is discarded.\n"
                f"  params: {query}\n"
                f"  This API truncates with HTTP 200 and no warning. Narrow the "
                f"date range or raise the limit -- do NOT use this result."
            )

        if not rows:
            raise SharadarError(
                f"{table}: ZERO rows for {query}. A failure, not an empty dataset."
            )
        return columns, rows

    def probe(self, tables) -> dict:
        """One cheap row per table. Confirms entitlement without burning budget."""
        out = {}
        for table in tables:
            try:
                body, _, _ = self._request(table, {"ticker": "AAPL", "limit": 1})
                header = body.splitlines()[0].split(",") if body else []
                out[table] = {"accessible": True, "columns": header}
            except SharadarError as exc:
                out[table] = {"accessible": False, "error": str(exc)[:200]}
        return out
