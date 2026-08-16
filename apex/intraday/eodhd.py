"""EODHDIntradayProvider — the $30 pilot adapter. PROVIDER V1, not truth.

Purpose: determine whether Hunter can find genuine intraday signal before
buying institutional data. Nothing here contorts governance to flatter the
vendor: capabilities are recorded as documented-and-then-MEASURED, delisted
intraday is SUPPORTED_WITH_LIMITATIONS by decree, and the universe is
defined by APEX/Sharadar first with provider coverage recorded as an
observed limitation -- never by "symbols that happened to download".

SECRETS: EODHD_API_TOKEN from the environment only. SecretMissingError when
absent; the token is stripped from every URL before anything is logged,
recorded, raised, or hashed. No fallback, no config-file path.

Provider facts verified against docs on 2026-08-15 (recorded in
docs/P1A-INTRADAY-FOUNDATION.md addendum): /api/intraday/{SYMBOL}.US,
UTC unix timestamps, ~120-day max span per 1m request, quota-metered,
1m history from ~2004 for ACTIVE names, delisted intraday materially
weaker before ~2021.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pandas as pd

from apex.intraday.contract import IntradayDataError, IntradayProvider

ENV_VAR = "EODHD_API_TOKEN"
ADAPTER_VERSION = "eodhd-adapter-0.1"
BASE = "https://eodhd.com/api"
MAX_SPAN_DAYS = 120
LAKE = Path("data/intraday/eodhd")
LEDGER = LAKE / "manifests" / "eodhd_download_ledger.jsonl"

# conservative local budget, deliberately far under the vendor daily cap
# LAB-05b: quota accounting is in PROVIDER API-CALL UNITS, not HTTP
# requests. EODHD's schedule is authoritative: an Intraday request costs
# 5 units against the 100k/day plan limit (resets midnight GMT).
INTRADAY_CALL_COST = 5
DAILY_LIMIT_CALL_UNITS = 100_000
# untouchable Monday reserve: measured clock worst case (~1.8k units on
# a context-building first tick x 26 ticks + EOD resolver) + headroom
FORWARD_RESERVE_CALL_UNITS = 35_000
# per-process default, in UNITS (was 2000 requests; ~1200 requests now —
# ample for any single clock tick incl. first-of-day context builds)
DAILY_REQUEST_BUDGET = 6_000

# LAB-04b: optional cross-process NETWORK semaphore. Labs set this so CPU
# worker count and outbound provider concurrency become separate knobs;
# production never sets it (None = behavior unchanged).
NET_SEMAPHORE = None
MIN_REQUEST_INTERVAL_S = 0.15


class SecretMissingError(RuntimeError):
    """EODHD_API_TOKEN is not in the environment. No fallback exists."""


class ProviderCapabilityUnavailable(RuntimeError):
    """The subscribed product does not support this request. Not faked."""


class Support(Enum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS = "SUPPORTED_WITH_LIMITATIONS"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_SUBSCRIBED = "NOT_SUBSCRIBED"
    UNKNOWN = "UNKNOWN"


CAPABILITIES = {
    "historical_1m": {"status": Support.SUPPORTED_WITH_LIMITATIONS,
                      "earliest_known_date": "2004-01-01",
                      "known_limitations": "delisted coverage weak pre-2021; "
                                           "coverage must be MEASURED",
                      "verification_date": "2026-08-15"},
    "historical_5m": {"status": Support.SUPPORTED,
                      "verification_date": "2026-08-15"},
    "historical_hourly": {"status": Support.SUPPORTED,
                          "verification_date": "2026-08-15"},
    "premarket": {"status": Support.SUPPORTED,
                  "verification_date": "2026-08-15"},
    "after_hours": {"status": Support.SUPPORTED,
                    "verification_date": "2026-08-15"},
    "historical_active_names": {"status": Support.SUPPORTED,
                                "verification_date": "2026-08-15"},
    "historical_delisted_names": {
        "status": Support.SUPPORTED_WITH_LIMITATIONS,
        "known_limitations": "post-2021 delistings often available; earlier "
                             "materially weaker or absent. NEVER plain "
                             "SUPPORTED by decree of the pilot directive.",
        "verification_date": "2026-08-15"},
    "historical_quotes": {"status": Support.NOT_SUBSCRIBED},
    "historical_trades": {"status": Support.NOT_SUBSCRIBED},
    "realtime_trades": {"status": Support.UNKNOWN,
                        "known_limitations": "separate WebSocket product"},
    "realtime_quotes": {"status": Support.UNKNOWN},
    "level2": {"status": Support.NOT_SUPPORTED},
    "auction_data": {"status": Support.NOT_SUPPORTED},
    "options": {"status": Support.UNKNOWN,
                "known_limitations": "out of pilot scope by directive"},
    "corporate_actions": {"status": Support.SUPPORTED_WITH_LIMITATIONS,
                          "known_limitations": "splits/dividends endpoints; "
                                               "APEX interprets downstream"},
    "symbol_changes": {"status": Support.SUPPORTED_WITH_LIMITATIONS},
    "reference_data": {"status": Support.SUPPORTED_WITH_LIMITATIONS},
}


def token() -> str:
    t = os.environ.get(ENV_VAR, "").strip()
    if not t:
        raise SecretMissingError(
            f"{ENV_VAR} is not set. The token lives in the environment and "
            f"nowhere else -- no config file, no fallback, no default.")
    return t


def redact(text: str) -> str:
    """Strip the token from anything that could be logged/recorded/raised."""
    t = os.environ.get(ENV_VAR, "").strip()
    return text.replace(t, "<EODHD_TOKEN>") if t else text


def chunk_range(start: str, end: str, max_days: int = MAX_SPAN_DAYS) -> list:
    """Deterministic, non-overlapping, gapless UTC chunks <= max_days."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    if e < s:
        raise IntradayDataError("end before start")
    out, cur = [], s
    while cur <= e:
        stop = min(cur + pd.Timedelta(days=max_days - 1), e)
        out.append((str(cur.date()), str(stop.date())))
        cur = stop + pd.Timedelta(days=1)
    # invariants, self-checked every call
    for (a1, b1), (a2, _b2) in zip(out, out[1:]):
        if (pd.Timestamp(a2) - pd.Timestamp(b1)).days != 1:
            raise IntradayDataError("chunk generation produced a gap/overlap")
    for a, b in out:
        if (pd.Timestamp(b) - pd.Timestamp(a)).days + 1 > max_days:
            raise IntradayDataError(f"chunk {a}..{b} exceeds {max_days} days")
    return out


class QuotaGovernor:
    """Conservative, resumable, never-spin. Exhaustion pauses; it does not
    error-and-start-over.

    TWO budgets, both of which must allow the spend (LAB-07):

      local  — `daily_budget`, this process's own cap. Cheap, but it resets
               to zero in every new process, so it can never protect a
               shared resource on its own.
      shared — the cross-process GMT-day counter in `quota_ledger`, which
               enforces the forward reserve. LAB spenders stop at
               limit - reserve; FORWARD spenders may use the reserve,
               because the reserve exists for them.

    `purpose` defaults to LAB. Defaulting to FORWARD would mean any caller
    that forgot to declare itself could quietly spend Monday's quota.
    """

    def __init__(self, daily_budget: int = DAILY_REQUEST_BUDGET,
                 purpose: str = "LAB", shared: bool = True):
        from apex.intraday.quota_ledger import PURPOSES
        if purpose not in PURPOSES:
            raise ValueError(f"unknown quota purpose {purpose!r}")
        self.daily_budget = daily_budget
        self.purpose = purpose
        self.shared = shared
        self.used = 0
        self.last_request = 0.0
        self.last_refusal: str | None = None

    def acquire(self, cost: int = 1) -> bool:
        """`used`/`daily_budget` are PROVIDER CALL UNITS (LAB-05b), not
        request counts — an intraday request passes cost=INTRADAY_CALL_COST."""
        if self.used + cost > self.daily_budget:
            self.last_refusal = (f"LOCAL_BUDGET: {self.used}+{cost} > "
                                 f"{self.daily_budget}")
            return False                     # PAUSE_DOWNLOAD
        if self.shared:
            from apex.intraday import quota_ledger
            claim = quota_ledger.spend(cost, self.purpose)
            if not claim["granted"]:
                self.last_refusal = claim["reason"]
                return False                 # PAUSE_DOWNLOAD, reserve intact
        wait = MIN_REQUEST_INTERVAL_S - (time.time() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.time()
        self.used += cost
        self.last_refusal = None
        return True

    def backoff(self, attempt: int, retry_after: float | None = None) -> float:
        import random
        if retry_after:
            return float(retry_after)
        return min(60.0, (2 ** attempt) + random.random())


def _ledger_append(record: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    clean = json.loads(redact(json.dumps(record, sort_keys=True, default=str)))
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(clean, sort_keys=True) + "\n")


def provider_usage() -> dict:
    """The provider's OWN accounting (EODHD User API): apiRequests (units
    consumed today, their clock), apiRequestsDate, dailyRateLimit.
    Reconciliation source of truth before any quota-blocked resume."""
    url = f"https://eodhd.com/api/user?api_token={token()}&fmt=json"
    import ssl
    _ctx = ssl.create_default_context(
        cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))
    raw = urllib.request.urlopen(url, timeout=30, context=_ctx).read()
    u = json.loads(raw)
    return {"api_requests_units": u.get("apiRequests"),
            "api_requests_date": u.get("apiRequestsDate"),
            "daily_rate_limit_units": u.get("dailyRateLimit")}


def lab_spare_units(now_utc=None) -> dict:
    """PRODUCTION_FORWARD > REPLAY is sovereign: the laboratory may spend
    only limit - consumed - FORWARD_RESERVE, even when the provider would
    happily accept more.

    STALE-COUNTER RULE (documented EODHD behavior): after midnight GMT
    the displayed counter can keep showing the PRIOR day's usage until a
    new request lands — apiRequestsDate exists to disambiguate. If the
    reported date != current GMT date, the counter belongs to the old
    bucket and current consumption is treated as zero-with-flag, never
    inferred from the stale value (which would falsely read 'exhausted'
    right after reset)."""
    import pandas as _pd
    u = provider_usage()
    limit = u["daily_rate_limit_units"] or DAILY_LIMIT_CALL_UNITS
    today_gmt = str((_pd.Timestamp(now_utc) if now_utc
                     else _pd.Timestamp.now(tz="UTC")).date())
    stale = u["api_requests_date"] != today_gmt
    consumed = 0 if stale else (u["api_requests_units"] or 0)
    # LAB-07: this used to END here -- a computed number with no caller and
    # therefore no authority. It now RECONCILES the shared spend ledger that
    # actually gates every acquire(), taking the max of the two (the local
    # counter sees in-flight claims the provider has not billed yet; the
    # provider sees spend that never passed through a governor).
    from apex.intraday import quota_ledger
    if not stale:
        quota_ledger.reconcile_with_provider(consumed, u["api_requests_date"],
                                             now_utc)
    enforced_consumed = max(consumed, quota_ledger.read(now_utc)["units"])
    spare = max(0, limit - enforced_consumed - FORWARD_RESERVE_CALL_UNITS)
    return {**u, "current_gmt_date": today_gmt,
            "counter_stale_prior_bucket": stale,
            "consumed_current_bucket_units": consumed,
            "enforced_consumed_units": enforced_consumed,
            "forward_reserve_units": FORWARD_RESERVE_CALL_UNITS,
            "available_lab_units": spare,
            "lab_headroom_enforced": quota_ledger.headroom(quota_ledger.LAB,
                                                           now_utc)}


def cache_path(symbol: str, lo: str, hi: str) -> Path:
    return LAKE / "raw" / symbol / f"{symbol}_{lo}_{hi}.json.gz"


def fetch_intraday_chunk(symbol: str, lo: str, hi: str,
                         governor: QuotaGovernor,
                         opener=None) -> tuple[list, str]:
    """Cache-first fetch of one <=120d 1-minute chunk. Returns (rows, source).
    Corrupt cache -> quarantine + refetch. Every request lands in the
    download ledger, token-free."""
    cp = cache_path(symbol, lo, hi)
    if cp.exists():
        try:
            rows = json.loads(gzip.decompress(cp.read_bytes()))
            return rows, "cache"
        except Exception:                                   # noqa: BLE001
            q = LAKE / "quarantine" / cp.name
            q.parent.mkdir(parents=True, exist_ok=True)
            cp.rename(q)
            _ledger_append({"event": "cache_quarantined", "file": cp.name})

    if not governor.acquire(INTRADAY_CALL_COST):
        raise IntradayDataError("PAUSE_DOWNLOAD: local call-unit budget "
                                "exhausted; resume next run (progress is "
                                "cached)")
    frm = int(pd.Timestamp(lo, tz="UTC").timestamp())
    to = int((pd.Timestamp(hi, tz="UTC") + pd.Timedelta(days=1)).timestamp())
    url = (f"{BASE}/intraday/{urllib.parse.quote(symbol)}"
           f"?interval=1m&from={frm}&to={to}&fmt=json&api_token={token()}")
    if opener is None:
        import ssl
        _ctx = ssl.create_default_context(
            cafile=os.environ.get("APEX_CA_BUNDLE", "/etc/ssl/cert.pem"))
        opener = lambda u: urllib.request.urlopen(u, timeout=60,
                                                  context=_ctx).read()
    open_fn = opener
    for attempt in range(4):
        try:
            if NET_SEMAPHORE is not None:
                with NET_SEMAPHORE:
                    raw = open_fn(url)
            else:
                raw = open_fn(url)
            rows = json.loads(raw)
            if not isinstance(rows, list):
                raise IntradayDataError(redact(f"malformed response for "
                                               f"{symbol} {lo}..{hi}"))
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(gzip.compress(json.dumps(rows).encode()))
            _ledger_append({"event": "fetch", "symbol": symbol, "lo": lo,
                            "hi": hi, "rows": len(rows),
                            "sha": hashlib.sha256(raw if isinstance(raw, bytes)
                                                  else raw.encode()).hexdigest()[:16],
                            "attempt": attempt, "quota_used": governor.used})
            return rows, "network"
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:  # type: ignore[attr-defined]
            code = getattr(e, "code", None)
            if code == 402:
                # LAB-05: the PROVIDER's daily quota is exhausted. Never
                # retried (deterministic until reset), named truthfully so
                # no downstream layer can mistake it for anything else.
                raise IntradayDataError(
                    f"PROVIDER_QUOTA_EXHAUSTED (HTTP 402) for {symbol}: "
                    f"the vendor daily allowance is spent; resume after "
                    f"reset") from None
            if code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(governor.backoff(attempt,
                                            getattr(e, "headers", {}) and
                                            e.headers.get("Retry-After")))
                continue
            raise IntradayDataError(redact(f"fetch failed for {symbol} "
                                           f"{lo}..{hi}: {e}")) from None
    raise IntradayDataError("bounded retries exhausted")


def normalize_rows(rows: list, symbol: str) -> pd.DataFrame:
    """Vendor JSON -> canonical frame; UTC epoch -> tz-aware; duplicates and
    out-of-order refused upstream by the replay layer, deduped-with-record
    here only if byte-identical."""
    if not rows:
        return pd.DataFrame(columns=["provider_symbol", "event_time_utc",
                                     "open", "high", "low", "close", "volume"])
    f = pd.DataFrame(rows)
    f["event_time_utc"] = pd.to_datetime(f["timestamp"], unit="s", utc=True)
    f["provider_symbol"] = symbol
    return f[["provider_symbol", "event_time_utc", "open", "high", "low",
              "close", "volume"]].sort_values("event_time_utc")


class EODHDIntradayProvider(IntradayProvider):
    def __init__(self):
        self.governor = QuotaGovernor()

    def availability(self) -> dict:
        wired = bool(os.environ.get(ENV_VAR, "").strip())
        return {"provider": "eodhd", "adapter_version": ADAPTER_VERSION,
                "wired": wired,
                "status": "READY" if wired else "BLOCKED_EXTERNAL_CREDENTIAL",
                "capabilities": {k: {kk: (vv.value if isinstance(vv, Support)
                                          else vv) for kk, vv in v.items()}
                                 for k, v in CAPABILITIES.items()}}

    def get_bars(self, security_ids, start, end, resolution, session_filter):
        if resolution != "1m":
            raise ProviderCapabilityUnavailable(
                f"pilot ingests 1m source bars only; derive {resolution} "
                f"downstream (APEX supplies intelligence, the vendor data)")
        out = {}
        for sid in security_ids:
            frames = []
            for lo, hi in chunk_range(start, end):
                rows, _src = fetch_intraday_chunk(sid, lo, hi, self.governor)
                frames.append(normalize_rows(rows, sid))
            out[sid] = (pd.concat(frames, ignore_index=True)
                        if frames else normalize_rows([], sid))
        return out

    def get_reference_state(self, as_of):
        raise ProviderCapabilityUnavailable(
            "reference identity comes from the APEX/Sharadar bridge, not the "
            "pilot vendor")

    def get_corporate_actions(self, start, end):
        raise ProviderCapabilityUnavailable(
            "pilot phase: corporate actions interpreted from the existing "
            "APEX lake; EODHD CA endpoints land with the census if needed")

    def get_quotes(self, security_ids, start, end):
        raise ProviderCapabilityUnavailable("historical quotes: NOT_SUBSCRIBED")

    def get_trades(self, security_ids, start, end):
        raise ProviderCapabilityUnavailable("historical trades: NOT_SUBSCRIBED")
