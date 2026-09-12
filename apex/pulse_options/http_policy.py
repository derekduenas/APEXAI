"""BOUNDED HTTP POLICY for the read-only market-data client (Brick 3).

One declared policy for timeouts, bounded retry with backoff, quota handling, authentication errors and partial
responses. Every provider observation is CLASSIFIED, never explained: the classifier names what was observed
(status code, exception type, body length) and does not invent a root cause. Endpoint health is isolated per
endpoint key; a failure on one endpoint never substitutes data from another. stdlib only."""
from __future__ import annotations

import time
import urllib.error
import urllib.request

POLICY_ID = "HTTP_POLICY_V1"
DEFAULTS = {"timeout_s": 10.0, "max_attempts": 3, "backoff_s": (0.5, 1.5, 4.0), "retry_on": (429, 500, 502, 503, 504, "TIMEOUT", "CONNECTION"),
            "never_retry_on": (400, 401, 403, 404), "min_body_bytes": 2}
CLASSES = ("OK", "AUTH_ERROR", "QUOTA", "NOT_FOUND", "CLIENT_ERROR", "SERVER_ERROR", "TIMEOUT", "CONNECTION", "PARTIAL", "UNKNOWN")


class ProviderObservation(RuntimeError):
    """Raised when the policy gives up; carries the classified attempts."""

    def __init__(self, endpoint: str, attempts: list):
        super().__init__("%s: %s after %d attempt(s): %s" % (POLICY_ID, endpoint, len(attempts), attempts[-1]["class"] if attempts else "NONE"))
        self.endpoint, self.attempts = endpoint, attempts


def classify(*, status=None, exc=None, body_len=None, min_body=DEFAULTS["min_body_bytes"]) -> str:
    if exc is not None:
        if isinstance(exc, TimeoutError) or "timed out" in str(exc).lower():
            return "TIMEOUT"
        if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
            return "CONNECTION"
        return "UNKNOWN"
    if status in (401, 403):
        return "AUTH_ERROR"
    if status == 429:
        return "QUOTA"
    if status == 404:
        return "NOT_FOUND"
    if status is not None and 400 <= status < 500:
        return "CLIENT_ERROR"
    if status is not None and status >= 500:
        return "SERVER_ERROR"
    if body_len is not None and body_len < min_body:
        return "PARTIAL"
    return "OK"


class EndpointHealth:
    """Per-endpoint observation log; no aggregation across endpoints, no root-cause inference."""

    def __init__(self):
        self.by_endpoint: dict = {}

    def record(self, endpoint: str, obs: dict) -> None:
        self.by_endpoint.setdefault(endpoint, []).append(obs)

    def summary(self) -> dict:
        return {k: {"n": len(v), "last": v[-1]["class"], "classes": sorted({o["class"] for o in v})} for k, v in self.by_endpoint.items()}


def guarded_get(url: str, *, headers: dict | None = None, endpoint: str, health: EndpointHealth | None = None, opener=None,
                policy: dict | None = None, sleep=time.sleep, clock=time.time) -> tuple:
    """Returns (body_text, attempts). Raises ProviderObservation when the policy gives up. `opener(url, headers, timeout)`
    is injectable for offline tests and must return (status, body_bytes) or raise."""
    pol = {**DEFAULTS, **(policy or {})}
    attempts = []

    def _default_opener(u, h, t):
        req = urllib.request.Request(u, headers=h or {})
        with urllib.request.urlopen(req, timeout=t) as r:
            return r.status, r.read()

    open_ = opener or _default_opener
    for i in range(pol["max_attempts"]):
        t0 = clock()
        status = body = exc = None
        try:
            status, body = open_(url, headers or {}, pol["timeout_s"])
        except urllib.error.HTTPError as e:
            status, exc = e.code, None
            try:
                body = e.read()
            except Exception:                                              # noqa: BLE001
                body = b""
        except Exception as e:                                             # noqa: BLE001
            exc = e
        cls = classify(status=status, exc=exc, body_len=(len(body) if body is not None else None), min_body=pol["min_body_bytes"])
        obs = {"attempt": i + 1, "class": cls, "status": status, "exception": (type(exc).__name__ if exc else None),
               "body_bytes": (len(body) if body is not None else None), "elapsed_s": round(clock() - t0, 3), "endpoint": endpoint, "policy": POLICY_ID}
        attempts.append(obs)
        if health is not None:
            health.record(endpoint, obs)
        if cls == "OK":
            return body.decode(errors="replace"), attempts
        retryable = (status in pol["retry_on"]) or (cls in pol["retry_on"])
        if not retryable or i + 1 >= pol["max_attempts"]:
            break
        sleep(pol["backoff_s"][min(i, len(pol["backoff_s"]) - 1)])
    raise ProviderObservation(endpoint, attempts)
