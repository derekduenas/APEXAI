"""EODHD pilot adapter: the mandated pre-token fixture suite. No network."""

from __future__ import annotations

import gzip
import json

import pandas as pd
import pytest

from apex.intraday.contract import IntradayDataError
from apex.intraday.eodhd import (
    CAPABILITIES, EODHDIntradayProvider, ProviderCapabilityUnavailable,
    QuotaGovernor, SecretMissingError, Support, chunk_range, normalize_rows,
    redact, token,
)


# --- secrets -----------------------------------------------------------------

def test_missing_token_raises_with_no_fallback(monkeypatch):
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    with pytest.raises(SecretMissingError, match="no fallback"):
        token()


def test_redaction_strips_the_token_everywhere(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "sekret123.456")
    msg = redact("GET /api/intraday/AAPL.US?api_token=sekret123.456&fmt=json")
    assert "sekret123.456" not in msg and "<EODHD_TOKEN>" in msg


def test_availability_never_contains_the_token(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "sekret123.456")
    dump = json.dumps(EODHDIntradayProvider().availability())
    assert "sekret123.456" not in dump


# --- chunking ----------------------------------------------------------------

def test_chunks_are_gapless_nonoverlapping_and_bounded():
    chunks = chunk_range("2023-01-01", "2024-01-01")
    assert chunks[0][0] == "2023-01-01" and chunks[-1][1] == "2024-01-01"
    for (a, b) in chunks:
        assert (pd.Timestamp(b) - pd.Timestamp(a)).days + 1 <= 120
    for (_, b1), (a2, _) in zip(chunks, chunks[1:]):
        assert (pd.Timestamp(a2) - pd.Timestamp(b1)).days == 1


def test_counterexample_no_span_ever_exceeds_120_days():
    """Adversarial ranges: exactly 120, 121, leap-year spans, multi-year --
    every emitted chunk stays within the vendor maximum, and end<start
    refuses outright."""
    for start, end in (("2023-01-01", "2023-04-30"),     # exactly 120
                       ("2023-01-01", "2023-05-01"),     # 121 -> must split
                       ("2020-01-01", "2020-12-31"),     # leap year
                       ("2004-01-01", "2026-08-01")):    # the full pilot era
        for a, b in chunk_range(start, end):
            span = (pd.Timestamp(b) - pd.Timestamp(a)).days + 1
            assert span <= 120, f"{a}..{b} spans {span} days"
    assert len(chunk_range("2023-01-01", "2023-05-01")) == 2
    with pytest.raises(IntradayDataError, match="end before start"):
        chunk_range("2024-01-01", "2023-01-01")


def test_chunking_is_deterministic():
    assert chunk_range("2022-01-01", "2023-06-15") == \
        chunk_range("2022-01-01", "2023-06-15")


# --- quota governor ----------------------------------------------------------

def test_quota_exhaustion_pauses_rather_than_errors():
    g = QuotaGovernor(daily_budget=2)
    assert g.acquire() and g.acquire()
    assert not g.acquire(), "budget exhausted must PAUSE (False), not raise"


def test_backoff_is_bounded_and_respects_retry_after():
    g = QuotaGovernor()
    assert g.backoff(10) <= 60.0
    assert g.backoff(1, retry_after=7) == 7.0


# --- normalization -----------------------------------------------------------

def _rows():
    return [{"timestamp": 1767191460, "open": 10, "high": 11, "low": 9,
             "close": 10.5, "volume": 1000},
            {"timestamp": 1767191400, "open": 9.9, "high": 10.2, "low": 9.8,
             "close": 10.0, "volume": 800}]


def test_utc_epoch_parsing_and_ordering():
    f = normalize_rows(_rows(), "AAPL.US")
    assert str(f["event_time_utc"].dt.tz) == "UTC"
    assert f["event_time_utc"].is_monotonic_increasing, "out-of-order sorted"


def test_empty_valid_response_yields_empty_frame_not_error():
    f = normalize_rows([], "GHOST.US")
    assert len(f) == 0 and "event_time_utc" in f.columns


# --- cache + quarantine ------------------------------------------------------

def test_cache_hit_and_corruption_quarantine(tmp_path, monkeypatch):
    import apex.intraday.eodhd as E
    monkeypatch.setattr(E, "LAKE", tmp_path)
    # The ledger path is derived from LAKE at call time now, so patching LAKE redirects it. Patching a
    # module-level LEDGER constant no longer does anything -- and never redirected production writes either,
    # which is how a test run could append to the real lake.
    monkeypatch.setenv("EODHD_API_TOKEN", "sekret123.456")
    g = QuotaGovernor()
    calls = {"n": 0}

    def fake_open(url):
        calls["n"] += 1
        assert "sekret123.456" in url        # the real URL carries the token
        return json.dumps(_rows()).encode()

    rows, src = E.fetch_intraday_chunk("AAPL.US", "2026-01-05", "2026-01-06",
                                       g, opener=fake_open)
    assert src == "network" and calls["n"] == 1
    rows2, src2 = E.fetch_intraday_chunk("AAPL.US", "2026-01-05", "2026-01-06",
                                         g, opener=fake_open)
    assert src2 == "cache" and calls["n"] == 1, "validated cache must be reused"

    # corrupt the cache -> quarantine + refetch
    cp = E.cache_path("AAPL.US", "2026-01-05", "2026-01-06")
    cp.write_bytes(b"corrupt garbage")
    rows3, src3 = E.fetch_intraday_chunk("AAPL.US", "2026-01-05", "2026-01-06",
                                         g, opener=fake_open)
    assert src3 == "network" and calls["n"] == 2
    assert any((tmp_path / "quarantine").iterdir())

    # the download ledger exists, sits under the patched lake, and is token-free
    ledger = E.ledger_path()
    assert ledger.is_relative_to(tmp_path), "a test must not write into the real lake: %s" % ledger
    assert "sekret123.456" not in ledger.read_text()


def test_malformed_response_is_refused_with_redaction(tmp_path, monkeypatch):
    import apex.intraday.eodhd as E
    monkeypatch.setattr(E, "LAKE", tmp_path)
    monkeypatch.setattr(E, "LEDGER", tmp_path / "m" / "l.jsonl")
    monkeypatch.setenv("EODHD_API_TOKEN", "sekret123.456")
    with pytest.raises(IntradayDataError) as ei:
        E.fetch_intraday_chunk("AAPL.US", "2026-01-05", "2026-01-06",
                               QuotaGovernor(),
                               opener=lambda u: b'{"not": "a list"}')
    assert "sekret123.456" not in str(ei.value)


# --- capability honesty ------------------------------------------------------

def test_delisted_intraday_is_never_plain_supported():
    assert CAPABILITIES["historical_delisted_names"]["status"] is \
        Support.SUPPORTED_WITH_LIMITATIONS


def test_unsubscribed_capabilities_refuse_rather_than_fake():
    p = EODHDIntradayProvider()
    with pytest.raises(ProviderCapabilityUnavailable, match="NOT_SUBSCRIBED"):
        p.get_quotes(["AAPL.US"], "2026-01-01", "2026-01-02")
    with pytest.raises(ProviderCapabilityUnavailable):
        p.get_bars(["AAPL.US"], "2026-01-01", "2026-01-02", "5m", None)


def test_provider_limitation_is_distinct_from_kernel_failure():
    """A ProviderCapabilityUnavailable must not be an IntradayDataError:
    the first is the vendor's documented boundary, the second is OUR
    substrate failing. Conflating them would let vendor gaps masquerade as
    kernel bugs and vice versa."""
    assert not issubclass(ProviderCapabilityUnavailable, IntradayDataError)
