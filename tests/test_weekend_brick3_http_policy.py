"""Weekend commissioning, Brick 3: bounded HTTP policy, offline. Observations are classified, never explained."""
from __future__ import annotations

import urllib.error

import pytest

from apex.pulse_options import http_policy as HP


class _Opener:
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    def __call__(self, url, headers, timeout):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _http_error(code):
    return urllib.error.HTTPError("http://x", code, "msg", hdrs=None, fp=None)


def _run(script, **pol):
    sleeps = []
    op = _Opener(script)
    health = HP.EndpointHealth()
    try:
        body, attempts = HP.guarded_get("http://x/endpoint?q=1", endpoint="x/endpoint", health=health, opener=op, policy=pol or None, sleep=sleeps.append, clock=lambda: 0.0)
        return body, attempts, sleeps, health, None
    except HP.ProviderObservation as e:
        return None, e.attempts, sleeps, health, e


def test_ok_first_try_records_one_attempt():
    body, attempts, sleeps, health, err = _run([(200, b'{"ok":1}')])
    assert body == '{"ok":1}' and len(attempts) == 1 and attempts[0]["class"] == "OK" and sleeps == [] and err is None


def test_timeout_is_retried_with_bounded_backoff_then_classified_timeout():
    body, attempts, sleeps, health, err = _run([TimeoutError("timed out"), TimeoutError("timed out"), TimeoutError("timed out")])
    assert body is None and [a["class"] for a in attempts] == ["TIMEOUT"] * 3 and sleeps == [0.5, 1.5]
    assert err is not None and "TIMEOUT" in str(err)


def test_quota_429_retries_and_recovers():
    body, attempts, sleeps, health, err = _run([_http_error(429), (200, b"fine")])
    assert body == "fine" and [a["class"] for a in attempts] == ["QUOTA", "OK"] and sleeps == [0.5]


def test_auth_errors_are_never_retried():
    for code in (401, 403):
        body, attempts, sleeps, health, err = _run([_http_error(code), (200, b"never")])
        assert body is None and len(attempts) == 1 and attempts[0]["class"] == "AUTH_ERROR" and sleeps == []


def test_partial_body_is_classified_partial_not_ok():
    body, attempts, sleeps, health, err = _run([(200, b"")])
    assert body is None and attempts[0]["class"] == "PARTIAL"


def test_server_error_exhausts_attempts_and_reports_each():
    body, attempts, sleeps, health, err = _run([_http_error(503), _http_error(502), _http_error(500)])
    assert [a["class"] for a in attempts] == ["SERVER_ERROR"] * 3 and [a["status"] for a in attempts] == [503, 502, 500]


def test_endpoint_health_is_isolated_per_endpoint_and_names_no_root_cause():
    health = HP.EndpointHealth()
    HP.guarded_get("http://a/bars", endpoint="a/bars", health=health, opener=_Opener([(200, b"ok")]), sleep=lambda s: None, clock=lambda: 0.0)
    with pytest.raises(HP.ProviderObservation):
        HP.guarded_get("http://a/nbbo", endpoint="a/nbbo", health=health, opener=_Opener([_http_error(401)]), sleep=lambda s: None, clock=lambda: 0.0)
    s = health.summary()
    assert s["a/bars"]["last"] == "OK" and s["a/nbbo"]["last"] == "AUTH_ERROR" and set(s) == {"a/bars", "a/nbbo"}
    assert all("why" not in o for v in health.by_endpoint.values() for o in v)        # classification only, no invented cause


def test_classify_vocabulary_is_closed():
    assert HP.classify(status=200, body_len=10) == "OK" and HP.classify(status=404) == "NOT_FOUND" and HP.classify(status=418) == "CLIENT_ERROR"
    assert HP.classify(exc=urllib.error.URLError("refused")) == "CONNECTION" and HP.classify(exc=ValueError("x")) == "UNKNOWN"
    for c in ("OK", "AUTH_ERROR", "QUOTA", "NOT_FOUND", "CLIENT_ERROR", "SERVER_ERROR", "TIMEOUT", "CONNECTION", "PARTIAL", "UNKNOWN"):
        assert c in HP.CLASSES
