"""Nasdaq Data Link / Sharadar API client and snapshot builder.

The API is an ACQUISITION channel only. The authoritative dataset for the
experiment is the frozen local snapshot this module writes -- section 31 requires
every result to trace to a data snapshot, and a live endpoint cannot provide
that because vendors restate, backfill and correct.

WHAT THIS MODULE REFUSES TO DO

  * Read a key from anywhere but the environment. There is no parameter, no
    config field and no file that can carry it, so a key cannot be committed.
  * Download before verifying entitlement. A large pull against an unentitled
    account wastes quota and produces a partial file that looks like data.
  * Treat an empty response as success. Zero rows from a table we asked for is
    a FAILURE, not an empty dataset.
  * Substitute one table for another, or fall back to a different source.
  * Write the key into a manifest, a log line, an error message or a URL that
    gets printed. Every URL is redacted before it is shown.

RATE LIMITING

Nasdaq returns HTTP 429 with `QELx06` ("your account has temporarily been
disabled") when limits are exceeded, and the lockout persists for some minutes.
Retrying hard makes it worse, so backoff here is long and the probe deliberately
asks for ONE row from ONE table: entitlement is a yes/no question and does not
require data.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://data.nasdaq.com/api/v3"
ENV_VAR = "NASDAQ_DATA_LINK_API_KEY"
VENDOR = "SHARADAR"

# macOS Python installations frequently ship without a usable CA bundle; the
# system bundle is present and correct. Overridable for other platforms.
CA_BUNDLE = os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem")

# Long by design. 429 here means "temporarily disabled", and hammering extends
# the lockout rather than clearing it.
BACKOFF_SECONDS = (0, 90, 180, 300, 600)


class ApiKeyMissing(RuntimeError):
    """The API key environment variable is not set."""


class NotEntitled(RuntimeError):
    """The account cannot access a table Experiment #001 requires."""


class RateLimited(RuntimeError):
    """The account is throttled or temporarily disabled."""


class EmptyResponse(RuntimeError):
    """The vendor returned zero rows for a table we asked for."""


def api_key() -> str:
    """The key, from the environment and nowhere else."""
    key = os.environ.get(ENV_VAR, "").strip()
    if not key:
        raise ApiKeyMissing(
            f"{ENV_VAR} is not set.\n"
            f"  Set it in your shell for the current session:\n"
            f"      export {ENV_VAR}='your-key-here'\n"
            f"  or prefix a single command:\n"
            f"      {ENV_VAR}='your-key-here' python scripts/fetch_sharadar.py ...\n"
            f"  The key is never read from a file, a config entry or an argument, "
            f"so it cannot be committed by accident."
        )
    return key


def _redact(text: str, key: str) -> str:
    return text.replace(key, "<API_KEY>") if key else text


def strip_credentials(url: str) -> str:
    """Remove any api_key from a URL before it is stored or displayed.

    Defence in depth at the SINK. Redacting at each call site works only while
    every call site remembers; stripping here means a caller that passes a URL
    with a live key still cannot write one to disk.
    """
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


@dataclass(frozen=True)
class TableStatus:
    table: str
    accessible: bool
    http_status: int | None
    error_code: str
    columns: tuple = ()
    detail: str = ""

    def line(self) -> str:
        mark = "OK  " if self.accessible else "DENIED"
        return (
            f"  [{mark}] {VENDOR}/{self.table}: HTTP {self.http_status} "
            f"{self.error_code} {self.detail}".rstrip()
        )


@dataclass
class EntitlementReport:
    checked_at: str
    statuses: list = field(default_factory=list)

    @property
    def accessible(self) -> list:
        return [s.table for s in self.statuses if s.accessible]

    @property
    def denied(self) -> list:
        return [s.table for s in self.statuses if not s.accessible]

    @property
    def rate_limited(self) -> bool:
        return any(s.http_status == 429 for s in self.statuses)

    def render(self) -> str:
        lines = [f"entitlement probe at {self.checked_at}"]
        lines += [s.line() for s in self.statuses]
        if self.rate_limited:
            lines.append(
                "  NOTE: HTTP 429 is a THROTTLE, not an entitlement verdict. The "
                "account is temporarily disabled; retry later before concluding "
                "anything about the subscription."
            )
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "accessible": self.accessible,
            "denied": self.denied,
            "rate_limited": self.rate_limited,
            "detail": [
                {
                    "table": s.table,
                    "accessible": s.accessible,
                    "http_status": s.http_status,
                    "error_code": s.error_code,
                    "columns": list(s.columns),
                }
                for s in self.statuses
            ],
        }


class NasdaqDataLinkClient:
    """Thin, deliberately unclever client. No caching, no magic, no fallbacks."""

    def __init__(self, key: str | None = None, ca_bundle: str = CA_BUNDLE) -> None:
        self._key = key or api_key()
        self._ctx = ssl.create_default_context(cafile=ca_bundle)
        self.calls_made = 0
        self.endpoints_used: list = []

    # -- transport -----------------------------------------------------------

    def _request(self, path: str, params: dict) -> tuple[int, object, str]:
        merged = dict(params)
        merged["api_key"] = self._key
        url = f"{BASE_URL}/{path}?" + urllib.parse.urlencode(merged)
        safe_url = _redact(url, self._key)
        self.calls_made += 1
        if safe_url not in self.endpoints_used:
            self.endpoints_used.append(safe_url.split("?")[0])
        try:
            with urllib.request.urlopen(url, timeout=60, context=self._ctx) as response:
                return response.status, json.loads(response.read().decode()), safe_url
        except urllib.error.HTTPError as exc:
            return exc.code, _redact(exc.read().decode()[:600], self._key), safe_url

    @staticmethod
    def _error_code(body: object) -> str:
        if isinstance(body, str):
            try:
                return json.loads(body)["quandl_error"]["code"]
            except Exception:  # noqa: BLE001
                return ""
        return ""

    # -- entitlement ---------------------------------------------------------

    def probe(
        self, tables, retry_on_429: bool = True, backoff=BACKOFF_SECONDS
    ) -> EntitlementReport:
        """Ask, for each table, whether this account may read it.

        One row per table. Entitlement is a yes/no question and asking it must
        not cost meaningful quota.
        """
        report = EntitlementReport(
            checked_at=dt.datetime.now(dt.timezone.utc).isoformat()
        )
        for table in tables:
            status, body, _ = self._request(
                f"datatables/{VENDOR}/{table}.json", {"qopts.per_page": 1}
            )

            if status == 429 and retry_on_429:
                for wait in backoff[1:]:
                    time.sleep(wait)
                    status, body, _ = self._request(
                        f"datatables/{VENDOR}/{table}.json", {"qopts.per_page": 1}
                    )
                    if status != 429:
                        break

            code = self._error_code(body)
            if status == 200 and isinstance(body, dict):
                columns = tuple(c["name"] for c in body["datatable"]["columns"])
                report.statuses.append(
                    TableStatus(table, True, status, "", columns, f"{len(columns)} columns")
                )
            else:
                detail = (
                    "throttled/temporarily disabled -- NOT an entitlement verdict"
                    if status == 429
                    else "subscription does not include this table"
                    if status == 403
                    else str(body)[:160]
                )
                report.statuses.append(TableStatus(table, False, status, code, (), detail))
        return report

    def require_entitled(
        self, tables, retry_on_429: bool = True, backoff=BACKOFF_SECONDS
    ) -> EntitlementReport:
        """Refuse to go further unless EVERY required table is readable."""
        report = self.probe(tables, retry_on_429=retry_on_429, backoff=backoff)
        if report.denied:
            if report.rate_limited:
                raise RateLimited(
                    "the account is throttled (HTTP 429, 'temporarily disabled'), so "
                    "entitlement cannot be determined.\n"
                    + report.render()
                    + "\n  Wait for the lockout to clear and re-probe. Do NOT treat "
                    "this as a subscription answer."
                )
            raise NotEntitled(
                "this account cannot read every table Experiment #001 requires.\n"
                + report.render()
                + f"\n  Missing: {report.denied}\n"
                "  No substitute table will be used and no partial download will "
                "be attempted."
            )
        return report

    # -- download ------------------------------------------------------------

    def fetch_table(self, table: str, params: dict | None = None, max_pages: int = 10_000):
        """Cursor-paginated read of one datatable. Returns (columns, rows, meta)."""
        query = dict(params or {})
        query.setdefault("qopts.per_page", 10_000)

        columns: list = []
        rows: list = []
        pages = 0
        cursor = None

        while pages < max_pages:
            if cursor:
                query["qopts.cursor_id"] = cursor
            status, body, safe = self._request(f"datatables/{VENDOR}/{table}.json", query)

            if status == 429:
                raise RateLimited(
                    f"{VENDOR}/{table}: throttled mid-download after {pages} pages. "
                    f"The partial result is DISCARDED -- a truncated table is not a "
                    f"dataset."
                )
            if status != 200 or not isinstance(body, dict):
                raise NotEntitled(f"{VENDOR}/{table}: HTTP {status} from {safe}: {body}")

            table_body = body["datatable"]
            if not columns:
                columns = [c["name"] for c in table_body["columns"]]
            rows.extend(table_body["data"])
            pages += 1

            cursor = (body.get("meta") or {}).get("next_cursor_id")
            if not cursor:
                break

        if not rows:
            raise EmptyResponse(
                f"{VENDOR}/{table} returned ZERO rows. That is a failure, not an "
                f"empty dataset -- refusing to write a snapshot that would look "
                f"like data and contain none."
            )
        return columns, rows, {"pages": pages, "calls": self.calls_made}


def write_snapshot_file(
    directory: Path, table: str, columns, rows, endpoint: str
) -> dict:
    """Write one raw table to CSV and describe it for the manifest."""
    import csv

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{table}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)

    payload = path.read_bytes()
    date_range = None
    if "date" in columns:
        index = columns.index("date")
        dates = sorted({str(r[index]) for r in rows if r[index]})
        if dates:
            date_range = [dates[0], dates[-1]]

    return {
        "table": table,
        "file": path.name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "rows": len(rows),
        "columns": list(columns),
        "date_range": date_range,
        "endpoint": strip_credentials(endpoint),
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "Nasdaq Data Link datatables API",
        "vendor": VENDOR,
    }
