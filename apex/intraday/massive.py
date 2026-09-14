"""Read-only Massive market-data adapter with causal normalization.

This module is deliberately a *sensor* seam.  It does not place orders, know
about execution, or choose a strategy.  It translates the vendor response into
small dictionaries that the replay layer can validate.

The adapter keeps two time concepts separate: ``event_time`` describes the
observation, while ``source_receipt_epoch`` is when this API response reached
APEX now.  The latter is never presented as the historical arrival time of a
row.  One-minute aggregate visibility is the explicit completion rule (bar
start + 60 seconds); option visibility is the provider-stated SIP timestamp.

``http_get`` is injectable so tests exercise URL construction, pagination,
validation, and causal boundaries without contacting a provider.  Credentials
are sent in an Authorization header only and never retained in a request
record, exception, URL, or normalized row.

decision_power: NONE -- historical market-data sensor only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable

from apex.intraday.contract import IntradayProvider


ENV_VAR = "MASSIVE_API_KEY"
API_BASE = "https://api.massive.com"
ADAPTER_VERSION = "massive-adapter-1.0-causal"
_TOKEN_QUERY_NAMES = {"api_key", "apikey", "api-key", "token", "access_token", "key"}


class NotWired(RuntimeError):
    """The Massive subscription/credential has not been made available."""


class MassiveDataError(RuntimeError):
    """A provider response or request violates the adapter contract."""


def _refuse(what: str) -> None:
    raise NotWired(
        f"MassiveIntradayProvider.{what}: no {ENV_VAR} in the environment. "
        "This is an OPERATOR act: subscribe and export the credential. "
        "The adapter fails closed rather than fabricating an empty market."
    )


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0.0


def _nonnegative(value: Any) -> bool:
    return _finite(value) and float(value) >= 0.0


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=str)


def _response_bytes(value: Any) -> bytes:
    """Hash the response representation without allowing it into records.

    Synthetic HTTP fakes sometimes hand the adapter a Python mapping rather
    than raw JSON.  ``allow_nan=True`` here keeps the response diagnosable so
    the row validator can name the offending field; normalized identities
    still use the strict ``_canonical`` function and can never contain NaN.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=True, default=str).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _observation_digest(value: dict) -> str:
    """Identity of vendor content, independent of when APEX fetched it."""
    return _digest({key: item for key, item in value.items()
                    if key not in {"source_receipt_epoch", "attribution_status",
                                   "observation_id"}})


def _utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def visible_rows(rows: Iterable[dict], decision_epoch: float) -> tuple[dict, ...]:
    """Return only observations whose declared visibility is not in the future.

    The comparison is deliberately inclusive: a bar completed at exactly
    09:31:00 is visible at 09:31:00, while the same bar is not visible at
    09:30:59.999999.  Rows with no declared availability are not made visible
    by guessing from a local retrieval timestamp.
    """
    if not _finite(decision_epoch):
        raise MassiveDataError("MASSIVE_DECISION_TIME_INVALID")
    out = []
    for index, row in enumerate(rows):
        available = row.get("available_epoch") if isinstance(row, dict) else None
        if not _finite(available):
            continue
        if float(available) <= float(decision_epoch):
            out.append(row)
    return tuple(out)


def _date_text(value: Any, *, field: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID: expected ISO date")
    text = value.strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID: {text!r}") from exc
    return text


def _timestamp_text(value: Any, *, field: str) -> str:
    """Validate, but do not reinterpret, a caller's ISO timestamp/date."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MassiveDataError(f"MASSIVE_{field.upper()}_NAIVE: timezone required")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID: expected ISO timestamp")
    text = value.strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            date.fromisoformat(text)
        except ValueError as exc:
            raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID: {text!r}") from exc
    return text


def _timestamp_epoch(value: Any, *, field: str) -> float:
    text = _timestamp_text(value, field=field)
    if len(text) == 10:
        parsed = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    else:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise MassiveDataError(f"MASSIVE_{field.upper()}_NAIVE: timezone required")
    return parsed.astimezone(timezone.utc).timestamp()


def _safe_symbol(value: Any, *, field: str = "symbol") -> str:
    if not isinstance(value, str) or not value.strip():
        raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID")
    symbol = value.strip()
    if any(ord(ch) < 0x20 for ch in symbol):
        raise MassiveDataError(f"MASSIVE_{field.upper()}_INVALID_CONTROL_CHAR")
    return symbol


def _payload(response: Any) -> dict:
    if isinstance(response, bytes):
        try:
            response = response.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MassiveDataError("MASSIVE_RESPONSE_NOT_UTF8") from exc
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError as exc:
            raise MassiveDataError("MASSIVE_RESPONSE_MALFORMED_JSON") from exc
    if not isinstance(response, dict):
        raise MassiveDataError("MASSIVE_RESPONSE_NOT_OBJECT")
    status = response.get("status")
    if status is not None and str(status).upper() not in {"OK", "SUCCESS"}:
        raise MassiveDataError(f"MASSIVE_RESPONSE_STATUS_{str(status).upper()}")
    rows = response.get("results")
    if rows is None:
        raise MassiveDataError("MASSIVE_RESPONSE_RESULTS_MISSING")
    if not isinstance(rows, list):
        raise MassiveDataError("MASSIVE_RESPONSE_RESULTS_NOT_LIST")
    return response


def _redact_url(url: str, secret: str | None = None) -> str:
    """Return a URL safe for evidence, logs, and request records."""
    try:
        parsed = urllib.parse.urlsplit(url)
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        clean = [(key, "<REDACTED>") if key.lower() in _TOKEN_QUERY_NAMES
                 else (key, value) for key, value in pairs]
        query = urllib.parse.urlencode(clean)
        out = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc,
                                       parsed.path, query, ""))
    except ValueError as exc:
        raise MassiveDataError("MASSIVE_URL_INVALID") from exc
    if secret:
        out = out.replace(secret, "<REDACTED>")
    return out


@dataclass(frozen=True)
class MassiveRequest:
    url: str
    requested_epoch: float
    received_epoch: float
    response_sha256: str
    row_count: int


@dataclass(frozen=True)
class MassiveFetch:
    """A normalized response and its non-secret provenance."""

    rows: tuple[dict, ...]
    rejections: tuple[str, ...]
    requests: tuple[MassiveRequest, ...]
    provider: str
    endpoint: str
    empty_result: bool
    quality: str

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "rows": list(self.rows),
            "rejections": list(self.rejections),
            "requests": [r.__dict__ for r in self.requests],
            "empty_result": self.empty_result,
            "quality": self.quality,
        }


class MassiveIntradayProvider(IntradayProvider):
    """Bounded Massive REST adapter.

    The zero-argument constructor preserves the original fail-closed API. A
    test or explicitly wired service may provide ``api_key`` and an injectable
    ``http_get``. No method downloads option history without an explicit
    contract ticker and bounded page/row limits.
    """

    provider = "MASSIVE"

    def __init__(self, *, api_key: str | None = None,
                 api_key_fn: Callable[[], str] | None = None,
                 http_get: Callable[[str, dict], Any] | None = None,
                 clock: Callable[[], float] = time.time,
                 base_url: str = API_BASE, timeout_s: float = 20.0,
                 max_pages: int = 10, max_rows: int = 100_000):
        if api_key is not None and api_key_fn is not None:
            raise ValueError("provide api_key or api_key_fn, not both")
        if not isinstance(max_pages, int) or max_pages < 1:
            raise ValueError("max_pages must be positive")
        if not isinstance(max_rows, int) or max_rows < 1:
            raise ValueError("max_rows must be positive")
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("base_url must be an HTTPS origin")
        self._api_key = api_key
        self._api_key_fn = api_key_fn
        self._http_get = http_get or self._default_http_get
        self._clock = clock
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)
        self.max_pages = max_pages
        self.max_rows = max_rows

    @property
    def wired(self) -> bool:
        if self._api_key_fn is not None:
            try:
                return bool(self._api_key_fn())
            except Exception:  # noqa: BLE001 - credential absence is fail-closed
                return False
        if self._api_key is not None:
            return bool(self._api_key.strip())
        return bool(os.environ.get(ENV_VAR, "").strip())

    def _credential(self) -> str:
        if self._api_key_fn is not None:
            try:
                value = self._api_key_fn()
            except Exception as exc:  # noqa: BLE001
                raise NotWired(f"{ENV_VAR} could not be read; provider not contacted") from exc
        else:
            value = self._api_key if self._api_key is not None else os.environ.get(ENV_VAR, "")
        if not isinstance(value, str) or not value.strip():
            _refuse("request")
        return value.strip()

    def availability(self) -> dict:
        return {
            "provider": "massive",
            "adapter_version": ADAPTER_VERSION,
            "wired": self.wired,
            "status": "READY_PARTIAL" if self.wired else "BLOCKED_EXTERNAL",
            "tier1": "whole-market 1m aggregates (replay substrate)",
            "tier2": "bounded, on-demand historical option NBBO slices",
            "contracts": "point-in-time reference endpoint required",
            "secret_in_records": False,
        }

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._credential()}",
                "Accept": "application/json"}

    def _default_http_get(self, url: str, headers: dict) -> str:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MassiveDataError("MASSIVE_HTTP_FAILURE") from exc

    def _url(self, path: str, params: Iterable[tuple[str, Any]] = ()) -> str:
        if not path.startswith("/"):
            raise MassiveDataError("MASSIVE_PATH_INVALID")
        query = urllib.parse.urlencode([(key, value) for key, value in params
                                        if value is not None])
        return f"{self.base_url}{path}" + (f"?{query}" if query else "")

    def _next_url(self, raw: Any, *, secret: str) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise MassiveDataError("MASSIVE_NEXT_URL_INVALID")
        if secret and secret in raw:
            raise MassiveDataError("MASSIVE_NEXT_URL_CONTAINS_CREDENTIAL")
        parsed = urllib.parse.urlsplit(raw.strip())
        base = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme and parsed.scheme != "https":
            raise MassiveDataError("MASSIVE_NEXT_URL_SCHEME_MISMATCH")
        netloc = parsed.netloc or base.netloc
        if netloc != base.netloc:
            raise MassiveDataError("MASSIVE_NEXT_URL_HOST_MISMATCH")
        path = parsed.path
        if not path.startswith("/"):
            raise MassiveDataError("MASSIVE_NEXT_URL_PATH_INVALID")
        pairs = [(key, value) for key, value in
                 urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                 if key.lower() not in _TOKEN_QUERY_NAMES]
        return self._url(path, pairs)

    def _pages(self, first_url: str) -> tuple[list[tuple[dict, float]], list[MassiveRequest]]:
        secret = self._credential()
        url = _redact_url(first_url, secret) if secret in first_url else first_url
        raw_rows: list[tuple[dict, float]] = []
        requests: list[MassiveRequest] = []
        seen_urls: set[str] = set()
        for page in range(1, self.max_pages + 1):
            if url in seen_urls:
                raise MassiveDataError("MASSIVE_PAGINATION_CYCLE")
            seen_urls.add(url)
            requested = float(self._clock())
            response = self._http_get(url, self._headers())
            received = float(self._clock())
            if received < requested:
                raise MassiveDataError("MASSIVE_CLOCK_REWIND_DURING_REQUEST")
            response_bytes = _response_bytes(response)
            doc = _payload(response)
            rows = doc["results"]
            raw_rows.extend((row, received) for row in rows)
            requests.append(MassiveRequest(
                url=_redact_url(url, secret), requested_epoch=requested,
                received_epoch=received,
                response_sha256=hashlib.sha256(response_bytes).hexdigest(),
                row_count=len(rows)))
            if len(raw_rows) > self.max_rows:
                raise MassiveDataError("MASSIVE_ROW_LIMIT_EXCEEDED")
            nxt = doc.get("next_url")
            if not nxt:
                return raw_rows, requests
            if page == self.max_pages:
                raise MassiveDataError("MASSIVE_PAGE_LIMIT_EXCEEDED")
            url = self._next_url(nxt, secret=secret)
        raise MassiveDataError("MASSIVE_PAGE_LIMIT_EXCEEDED")

    def _fetch(self, url: str, *, endpoint: str,
               normalizer: Callable[[dict, int, float], tuple[dict | None, str | None]],
               sort_key: Callable[[dict], Any]) -> MassiveFetch:
        raw_rows, requests = self._pages(url)
        normalized: list[dict] = []
        rejections: list[str] = []
        for index, (row, row_receipt) in enumerate(raw_rows):
            if not isinstance(row, dict):
                rejections.append(f"ROW_{index}_NOT_OBJECT")
                continue
            item, problem = normalizer(row, index, row_receipt)
            if problem:
                rejections.append(problem)
            elif item is not None:
                normalized.append(item)
        normalized.sort(key=sort_key)
        return MassiveFetch(
            rows=tuple(normalized), rejections=tuple(rejections),
            requests=tuple(requests), provider=self.provider, endpoint=endpoint,
            empty_result=not raw_rows, quality=("EMPTY" if not raw_rows else
                                                "PARTIAL" if rejections else "COMPLETE"))

    @staticmethod
    def _apply_duplicate_policy(fetch: MassiveFetch, *, key: Callable[[dict], Any],
                                 label: str) -> MassiveFetch:
        """Collapse byte-identical observations; refuse conflicting identities."""
        seen: dict[Any, dict] = {}
        rows: list[dict] = []
        problems = list(fetch.rejections)
        for row in fetch.rows:
            identity = key(row)
            prior = seen.get(identity)
            if prior is None:
                seen[identity] = row
                rows.append(row)
            elif _canonical({k: v for k, v in prior.items()
                             if k not in {"source_receipt_epoch", "observation_id"}}) != _canonical({
                                 k: v for k, v in row.items()
                                 if k not in {"source_receipt_epoch", "observation_id"}}):
                problems.append(f"DUPLICATE_{label}_{identity!s}_CONFLICT")
            # Identical duplicate: the first observation wins.  Its request
            # receipt is already preserved; the duplicate adds no information.
        return MassiveFetch(
            rows=tuple(rows), rejections=tuple(problems),
            requests=fetch.requests, provider=fetch.provider,
            endpoint=fetch.endpoint, empty_result=fetch.empty_result,
            quality=("EMPTY" if fetch.empty_result else
                     "PARTIAL" if problems else "COMPLETE"))

    @staticmethod
    def _bar_row(row: dict, index: int, receipt: float, symbol: str):
        t = row.get("t")
        if not _finite(t) or float(t) < 0 or float(t) != int(float(t)):
            return None, f"ROW_{index}_BAR_TIMESTAMP_INVALID"
        missing = [key for key in ("o", "h", "l", "c", "v") if key not in row]
        if missing:
            return None, f"ROW_{index}_BAR_FIELDS_MISSING_{','.join(missing)}"
        values = {name: row.get(key) for name, key in
                  (("open", "o"), ("high", "h"), ("low", "l"),
                   ("close", "c"), ("volume", "v"))}
        if not all(_finite(value) for value in values.values()):
            return None, f"ROW_{index}_BAR_NUMERIC_INVALID"
        if not all(_positive(values[name]) for name in ("open", "high", "low", "close")):
            return None, f"ROW_{index}_BAR_PRICE_NONPOSITIVE"
        if not _nonnegative(values["volume"]):
            return None, f"ROW_{index}_BAR_VOLUME_INVALID"
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
            return None, f"ROW_{index}_BAR_OHLC_INCONSISTENT"
        n = row.get("n")
        if n is not None and (not _integer(n) or n < 0):
            return None, f"ROW_{index}_BAR_TRADE_COUNT_INVALID"
        vw = row.get("vw")
        if vw is not None and not _positive(vw):
            return None, f"ROW_{index}_BAR_VWAP_INVALID"
        start = float(t) / 1000.0
        body = {"provider": "MASSIVE_STOCKS_V2", "symbol": symbol,
                "provider_symbol": symbol,
                "event_time_epoch": start, "bar_start_epoch": start,
                "event_time_utc": _utc_iso(start),
                "bar_complete_epoch": start + 60.0,
                "available_epoch": start + 60.0,
                "availability_basis": "BAR_COMPLETION_DERIVED_V1",
                "source_receipt_epoch": receipt,
                "attribution_status": "UNVERIFIED_ARCHIVE_RECEIPT",
                "open": float(values["open"]), "high": float(values["high"]),
                "low": float(values["low"]), "close": float(values["close"]),
                "volume": float(values["volume"]), "trade_count": n,
                "transactions": n,
                "vwap": float(vw) if vw is not None else None,
                "timestamp_unit": "unix_milliseconds_bar_start"}
        body["observation_id"] = _observation_digest(body)
        return body, None

    @staticmethod
    def _quote_row(row: dict, index: int, receipt: float, ticker: str):
        timestamp = row.get("sip_timestamp")
        if not _integer(timestamp) or timestamp < 0:
            return None, f"ROW_{index}_QUOTE_SIP_TIMESTAMP_INVALID"
        bid, ask = row.get("bid_price"), row.get("ask_price")
        if not _positive(bid) or not _positive(ask):
            return None, f"ROW_{index}_QUOTE_PRICE_INVALID"
        if float(ask) < float(bid):
            return None, f"ROW_{index}_QUOTE_CROSSED"
        sequence = row.get("sequence_number")
        if not _integer(sequence) or sequence < 0:
            return None, f"ROW_{index}_QUOTE_SEQUENCE_INVALID"
        out = {"provider": "MASSIVE_OPTIONS_V3", "contract_ticker": ticker,
               "event_time_epoch": timestamp / 1_000_000_000.0,
               "timestamp_epoch": timestamp / 1_000_000_000.0,
               "timestamp_raw": timestamp,
               "sip_timestamp_ns": timestamp,
               "available_epoch": timestamp / 1_000_000_000.0,
               "availability_basis": "SIP_TIMESTAMP_PROVIDER_STATED",
               "source_receipt_epoch": receipt,
               "attribution_status": "UNVERIFIED_ARCHIVE_RECEIPT",
               "bid": float(bid), "ask": float(ask),
               "bid_size": row.get("bid_size"), "ask_size": row.get("ask_size"),
               "bid_exchange": row.get("bid_exchange"),
               "ask_exchange": row.get("ask_exchange"),
               "sequence_number": sequence}
        for name in ("bid_size", "ask_size"):
            if out[name] is not None and (not _integer(out[name]) or out[name] < 0):
                return None, f"ROW_{index}_QUOTE_{name.upper()}_INVALID"
        out["observation_id"] = _observation_digest(out)
        return out, None

    @staticmethod
    def _contract_row(row: dict, index: int, receipt: float, as_of: str):
        ticker = row.get("ticker")
        underlying = row.get("underlying_ticker")
        expiration = row.get("expiration_date")
        strike = row.get("strike_price")
        kind = row.get("contract_type")
        if not all(isinstance(value, str) and value.strip() for value in
                   (ticker, underlying, expiration, kind)):
            return None, f"ROW_{index}_CONTRACT_REQUIRED_FIELD_MISSING"
        if not _positive(strike):
            return None, f"ROW_{index}_CONTRACT_STRIKE_INVALID"
        out = {"provider": "MASSIVE_OPTIONS_REFERENCE_V3", "ticker": ticker,
               "underlying_ticker": underlying, "expiration_date": expiration,
               "strike_price": float(strike), "contract_type": kind,
               "exercise_style": row.get("exercise_style"),
               "shares_per_contract": row.get("shares_per_contract"),
               "primary_exchange": row.get("primary_exchange"),
               "universe_as_of": as_of, "source_receipt_epoch": receipt,
               "attribution_status": "UNVERIFIED_ARCHIVE_RECEIPT"}
        shares = out["shares_per_contract"]
        if shares is not None and not _positive(shares):
            return None, f"ROW_{index}_CONTRACT_SHARES_INVALID"
        out["observation_id"] = _observation_digest(out)
        return out, None

    def fetch_stock_bars(self, symbol: str, *, start_date: Any, end_date: Any,
                         adjusted: bool = False, sort: str = "asc",
                         limit: int = 50_000) -> MassiveFetch:
        self._credential()
        symbol = _safe_symbol(symbol)
        start = _date_text(start_date, field="start_date")
        end = _date_text(end_date, field="end_date")
        if end < start:
            raise MassiveDataError("MASSIVE_DATE_RANGE_REVERSED")
        if sort != "asc":
            raise MassiveDataError("MASSIVE_BAR_SORT_MUST_BE_ASC")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50_000:
            raise MassiveDataError("MASSIVE_BAR_LIMIT_INVALID")
        path = f"/v2/aggs/ticker/{urllib.parse.quote(symbol, safe='')}/range/1/minute/{start}/{end}"
        url = self._url(path, (("adjusted", str(bool(adjusted)).lower()),
                               ("sort", sort), ("limit", limit)))
        fetch = self._fetch(url, endpoint="STOCK_BARS_1M",
                            normalizer=lambda row, i, r: self._bar_row(row, i, r, symbol),
                            sort_key=lambda row: (row["event_time_epoch"], row["observation_id"]))
        return self._apply_duplicate_policy(fetch, key=lambda row: row["event_time_epoch"], label="BAR")

    def fetch_option_quotes(self, contract_ticker: str, *, start: Any, end: Any,
                            limit: int = 50_000, order: str = "asc",
                            sort: str = "timestamp") -> MassiveFetch:
        self._credential()
        ticker = _safe_symbol(contract_ticker, field="contract_ticker")
        start_text, end_text = _timestamp_text(start, field="timestamp_gte"), _timestamp_text(end, field="timestamp_lt")
        if _timestamp_epoch(start, field="timestamp_gte") >= _timestamp_epoch(end, field="timestamp_lt"):
            raise MassiveDataError("MASSIVE_QUOTE_TIME_RANGE_REVERSED")
        if order != "asc":
            raise MassiveDataError("MASSIVE_QUOTE_ORDER_MUST_BE_ASC")
        if sort != "timestamp":
            raise MassiveDataError("MASSIVE_QUOTE_SORT_MUST_BE_TIMESTAMP")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50_000:
            raise MassiveDataError("MASSIVE_QUOTE_LIMIT_INVALID")
        # Keep the OCC ``O:`` prefix readable in evidence; it is legal in a
        # path segment and matches the documented contract-ticker spelling.
        path = f"/v3/quotes/{urllib.parse.quote(ticker, safe=':')}"
        url = self._url(path, (("timestamp.gte", start_text),
                               ("timestamp.lt", end_text), ("order", order),
                               ("sort", sort),
                               ("limit", limit)))
        fetch = self._fetch(url, endpoint="OPTION_NBBO_QUOTES",
                            normalizer=lambda row, i, r: self._quote_row(row, i, r, ticker),
                            sort_key=lambda row: (row["event_time_epoch"], row["sequence_number"], row["observation_id"]))
        return self._apply_duplicate_policy(fetch, key=lambda row: row["sequence_number"], label="QUOTE_SEQUENCE")

    def fetch_option_contracts(self, *, as_of: Any,
                               underlying_ticker: str | None = None,
                               expiration_gte: Any | None = None,
                               expiration_lte: Any | None = None,
                               strike_gte: float | None = None,
                               strike_lte: float | None = None,
                               contract_type: str | None = None,
                               expired: bool | None = None) -> MassiveFetch:
        self._credential()
        as_of_text = _timestamp_text(as_of, field="as_of")
        params: list[tuple[str, Any]] = [("as_of", as_of_text)]
        if underlying_ticker is not None:
            params.append(("underlying_ticker", _safe_symbol(underlying_ticker, field="underlying_ticker")))
        if expiration_gte is not None:
            params.append(("expiration_date.gte", _date_text(expiration_gte, field="expiration_gte")))
        if expiration_lte is not None:
            params.append(("expiration_date.lte", _date_text(expiration_lte, field="expiration_lte")))
        for name, value in (("strike_price.gte", strike_gte), ("strike_price.lte", strike_lte)):
            if value is not None:
                if not _positive(value):
                    raise MassiveDataError("MASSIVE_STRIKE_FILTER_INVALID")
                params.append((name, value))
        if contract_type is not None:
            if str(contract_type).lower() not in {"call", "put"}:
                raise MassiveDataError("MASSIVE_CONTRACT_TYPE_INVALID")
            params.append(("contract_type", str(contract_type).lower()))
        if expired is not None:
            if not isinstance(expired, bool):
                raise MassiveDataError("MASSIVE_EXPIRED_FILTER_INVALID")
            params.append(("expired", str(expired).lower()))
        url = self._url("/v3/reference/options/contracts", params)
        fetch = self._fetch(url, endpoint="OPTION_CONTRACT_REFERENCE",
                            normalizer=lambda row, i, r: self._contract_row(row, i, r, as_of_text),
                            sort_key=lambda row: (row["underlying_ticker"], row["expiration_date"], row["strike_price"], row["contract_type"], row["ticker"]))
        return self._apply_duplicate_policy(fetch, key=lambda row: row["ticker"], label="CONTRACT")

    # Provider-neutral interface. These methods expose normalized rows while
    # the fetch_* methods preserve request/rejection evidence.
    def get_bars(self, security_ids, start, end, resolution, session_filter):
        if not self.wired:
            _refuse("get_bars")
        if resolution not in {"1m", "1min", "1minute", "minute"}:
            raise MassiveDataError("MASSIVE_RESOLUTION_UNSUPPORTED")
        rows = []
        for symbol in security_ids:
            rows.extend(self.fetch_stock_bars(symbol, start_date=start, end_date=end).rows)
        return rows

    def get_reference_state(self, as_of):
        if not self.wired:
            _refuse("get_reference_state")
        return list(self.fetch_option_contracts(as_of=as_of).rows)

    def get_corporate_actions(self, start, end):
        if not self.wired:
            _refuse("get_corporate_actions")
        raise MassiveDataError("MASSIVE_CORPORATE_ACTIONS_ENDPOINT_NOT_VERIFIED")

    def get_quotes(self, security_ids, start, end):
        if not self.wired:
            _refuse("get_quotes")
        rows = []
        for ticker in security_ids:
            rows.extend(self.fetch_option_quotes(ticker, start=start, end=end).rows)
        return rows

    def get_trades(self, security_ids, start, end):
        if not self.wired:
            _refuse("get_trades")
        raise MassiveDataError("MASSIVE_TRADE_ENDPOINT_NOT_VERIFIED")
