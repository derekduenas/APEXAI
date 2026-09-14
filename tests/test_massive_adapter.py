"""Synthetic contract tests for the Massive sensor seam.

These tests never contact Massive.  They still exercise the exact URLs,
headers, pagination, normalizers and causal visibility rules used by a live
injection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from apex.intraday.massive import (
    MassiveDataError,
    MassiveIntradayProvider,
    NotWired,
    visible_rows,
)


BAR_T0 = int(datetime(2026, 9, 10, 13, 30, tzinfo=timezone.utc).timestamp() * 1000)
QUOTE_T0 = int(datetime(2026, 9, 10, 13, 30, tzinfo=timezone.utc).timestamp() * 1_000_000_000)


def bar(t=BAR_T0, close=101.0, **extra):
    row = {"t": t, "o": 100.0, "h": max(101.0, close), "l": 99.0,
           "c": close, "v": 10_000, "vw": 100.25, "n": 42}
    row.update(extra)
    return row


def quote(ts=QUOTE_T0, sequence=1, bid=1.20, ask=1.30, **extra):
    row = {"sip_timestamp": ts, "sequence_number": sequence,
           "bid_price": bid, "ask_price": ask, "bid_size": 10,
           "ask_size": 12, "bid_exchange": "X", "ask_exchange": "Y"}
    row.update(extra)
    return row


def contract(ticker="O:SPY260918C00650000", **extra):
    row = {"ticker": ticker, "underlying_ticker": "SPY",
           "expiration_date": "2026-09-18", "strike_price": 650.0,
           "contract_type": "call", "exercise_style": "american",
           "shares_per_contract": 100, "primary_exchange": "X"}
    row.update(extra)
    return row


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        if not self.responses:
            raise AssertionError("unexpected provider request")
        response = self.responses.pop(0)
        return response


class Clock:
    def __init__(self, *values):
        self.values = list(values)
        self.last = values[-1] if values else 0.0

    def __call__(self):
        if self.values:
            self.last = self.values.pop(0)
        return self.last


def provider(fake, clock=None, **kwargs):
    return MassiveIntradayProvider(
        api_key="unit-secret-never-in-records", http_get=fake,
        clock=clock or Clock(100.0, 101.0),
        base_url="https://massive.test", **kwargs)


def test_zero_argument_provider_still_fails_closed_without_contact():
    p = MassiveIntradayProvider()
    assert p.availability()["status"] == "BLOCKED_EXTERNAL"
    with pytest.raises(NotWired, match="OPERATOR act"):
        p.get_bars(["SPY"], "2026-09-10", "2026-09-10", "1m", None)


def test_stock_url_normalization_and_secret_boundary():
    fake = FakeHTTP([{"status": "OK", "results": [bar()]}])
    result = provider(fake).fetch_stock_bars(
        "SPY", start_date="2026-09-10", end_date="2026-09-10")
    url, headers = fake.calls[0]
    assert urlsplit(url).path == "/v2/aggs/ticker/SPY/range/1/minute/2026-09-10/2026-09-10"
    assert parse_qs(urlsplit(url).query) == {"adjusted": ["false"], "sort": ["asc"], "limit": ["50000"]}
    assert headers["Authorization"] == "Bearer unit-secret-never-in-records"
    assert "unit-secret-never-in-records" not in repr(result.as_dict())
    assert result.rows[0]["provider"] == "MASSIVE_STOCKS_V2"
    assert result.rows[0]["attribution_status"] == "UNVERIFIED_ARCHIVE_RECEIPT"
    assert result.rows[0]["source_receipt_epoch"] == 101.0


def test_completed_bar_visibility_is_inclusive_and_not_retrieval_time():
    fake = FakeHTTP([{"results": [bar()]}])
    result = provider(fake).fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10")
    row = result.rows[0]
    assert visible_rows(result.rows, row["bar_start_epoch"] + 59.999999) == ()
    assert visible_rows(result.rows, row["bar_complete_epoch"]) == (row,)
    assert row["source_receipt_epoch"] == 101.0
    assert row["available_epoch"] == row["bar_complete_epoch"]
    assert row["available_epoch"] != row["source_receipt_epoch"]


def test_malformed_bars_are_named_and_valid_rows_survive():
    rows = [bar(), bar(t=BAR_T0 + 60_000, close=102.0, h=100.0),
            bar(t=BAR_T0 + 120_000, v=float("nan")),
            {"t": BAR_T0 + 180_000}, "bad"]
    result = provider(FakeHTTP([{"results": rows}])).fetch_stock_bars(
        "SPY", start_date="2026-09-10", end_date="2026-09-10")
    assert len(result.rows) == 1
    assert len(result.rejections) == 4
    assert any("OHLC_INCONSISTENT" in reason for reason in result.rejections)
    assert any("NUMERIC_INVALID" in reason for reason in result.rejections)
    assert any("FIELDS_MISSING" in reason for reason in result.rejections)
    assert any("NOT_OBJECT" in reason for reason in result.rejections)
    assert result.quality == "PARTIAL"


def test_conflicting_duplicate_bar_is_not_silently_selected():
    result = provider(FakeHTTP([{"results": [bar(), bar(close=103.0)]}])).fetch_stock_bars(
        "SPY", start_date="2026-09-10", end_date="2026-09-10")
    assert len(result.rows) == 1
    assert any(reason.startswith("DUPLICATE_BAR_") for reason in result.rejections)


def test_pagination_is_bounded_deterministic_and_strips_token_query():
    next_url = "https://massive.test/v2/aggs/ticker/SPY/range/1/minute/2026-09-10/2026-09-10?cursor=abc&apiKey=server-provided-token"
    fake = FakeHTTP([{"results": [bar(t=BAR_T0 + 60_000)], "next_url": next_url},
                     {"results": [bar(t=BAR_T0)]}])
    result = provider(fake, clock=Clock(100.0, 101.0, 102.0, 103.0)).fetch_stock_bars(
        "SPY", start_date="2026-09-10", end_date="2026-09-10")
    assert [row["bar_start_epoch"] for row in result.rows] == [BAR_T0 / 1000, (BAR_T0 + 60_000) / 1000]
    assert len(result.requests) == 2
    assert "server-provided-token" not in fake.calls[1][0]
    assert parse_qs(urlsplit(fake.calls[1][0]).query) == {"cursor": ["abc"]}
    assert all("unit-secret" not in request.url for request in result.requests)


def test_pagination_rejects_foreign_next_host():
    fake = FakeHTTP([{"results": [bar()], "next_url": "https://evil.test/steal"}])
    with pytest.raises(MassiveDataError, match="HOST_MISMATCH"):
        provider(fake).fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10")


def test_pagination_rejects_a_credential_in_an_unlabelled_next_url():
    fake = FakeHTTP([{"results": [bar()],
                      "next_url": "https://massive.test/next?cursor=unit-secret-never-in-records"}])
    with pytest.raises(MassiveDataError, match="CONTAINS_CREDENTIAL"):
        provider(fake).fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10")


def test_pagination_limit_is_fail_closed():
    fake = FakeHTTP([{"results": [bar()], "next_url": "/next"}])
    with pytest.raises(MassiveDataError, match="PAGE_LIMIT"):
        provider(fake, max_pages=1).fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10")


def test_option_quote_url_and_sip_visibility_are_preserved():
    fake = FakeHTTP([{"status": "OK", "results": [quote()]}])
    result = provider(fake).fetch_option_quotes(
        "O:SPY260918C00650000", start="2026-09-10T13:30:00Z",
        end="2026-09-10T20:00:00Z")
    url, _ = fake.calls[0]
    assert urlsplit(url).path == "/v3/quotes/O:SPY260918C00650000"
    query = parse_qs(urlsplit(url).query)
    assert query["timestamp.gte"] == ["2026-09-10T13:30:00Z"]
    assert query["timestamp.lt"] == ["2026-09-10T20:00:00Z"]
    assert query["order"] == ["asc"]
    assert query["sort"] == ["timestamp"]
    row = result.rows[0]
    assert row["available_epoch"] == QUOTE_T0 / 1_000_000_000
    assert row["availability_basis"] == "SIP_TIMESTAMP_PROVIDER_STATED"
    assert row["sequence_number"] == 1


def test_option_time_range_is_strictly_ordered():
    with pytest.raises(MassiveDataError, match="TIME_RANGE_REVERSED"):
        provider(FakeHTTP([])).fetch_option_quotes(
            "O:SPY260918C00650000", start="2026-09-10T20:00:00Z",
            end="2026-09-10T13:30:00Z")


def test_option_quote_order_and_sort_contract_is_strict():
    with pytest.raises(MassiveDataError, match="ORDER_MUST_BE_ASC"):
        provider(FakeHTTP([])).fetch_option_quotes(
            "O:SPY260918C00650000", start="2026-09-10T13:30:00Z",
            end="2026-09-10T20:00:00Z", order="desc")
    with pytest.raises(MassiveDataError, match="SORT_MUST_BE_TIMESTAMP"):
        provider(FakeHTTP([])).fetch_option_quotes(
            "O:SPY260918C00650000", start="2026-09-10T13:30:00Z",
            end="2026-09-10T20:00:00Z", sort="timestamp.asc")


def test_observation_identity_does_not_change_when_fetched_later():
    first = provider(FakeHTTP([{"results": [bar()]}]), clock=Clock(100.0, 101.0))
    second = provider(FakeHTTP([{"results": [bar()]}]), clock=Clock(200.0, 201.0))
    a = first.fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10").rows[0]
    b = second.fetch_stock_bars("SPY", start_date="2026-09-10", end_date="2026-09-10").rows[0]
    assert a["observation_id"] == b["observation_id"]
    assert a["source_receipt_epoch"] != b["source_receipt_epoch"]


def test_option_quote_validation_names_crossed_bad_size_and_timestamp():
    rows = [quote(), quote(ts=QUOTE_T0 + 1, sequence=2, bid=2.0, ask=1.0),
            quote(ts=QUOTE_T0 + 2, sequence=3, bid_size=-1),
            quote(ts="not-ns", sequence=4)]
    result = provider(FakeHTTP([{"results": rows}])).fetch_option_quotes(
        "O:SPY260918C00650000", start="2026-09-10T13:30:00Z", end="2026-09-10T20:00:00Z")
    assert len(result.rows) == 1
    assert any("CROSSED" in reason for reason in result.rejections)
    assert any("BID_SIZE_INVALID" in reason for reason in result.rejections)
    assert any("SIP_TIMESTAMP_INVALID" in reason for reason in result.rejections)


def test_conflicting_quote_sequence_is_refused_and_identical_duplicate_collapses():
    same = quote()
    conflict = quote(bid=1.25)
    result = provider(FakeHTTP([{"results": [same, same, conflict]}])).fetch_option_quotes(
        "O:SPY260918C00650000", start="2026-09-10T13:30:00Z", end="2026-09-10T20:00:00Z")
    assert len(result.rows) == 1
    assert any(reason.startswith("DUPLICATE_QUOTE_SEQUENCE_") for reason in result.rejections)


def test_contract_reference_requires_point_in_time_and_normalizes_filters():
    fake = FakeHTTP([{"results": [contract()]}])
    result = provider(fake).fetch_option_contracts(
        as_of="2026-09-10T13:30:00Z", underlying_ticker="SPY",
        expiration_gte="2026-09-11", expiration_lte="2026-12-31",
        strike_gte=600, strike_lte=700, contract_type="CALL", expired=False)
    url, _ = fake.calls[0]
    query = parse_qs(urlsplit(url).query)
    assert query["as_of"] == ["2026-09-10T13:30:00Z"]
    assert query["underlying_ticker"] == ["SPY"]
    assert query["contract_type"] == ["call"]
    assert query["expired"] == ["false"]
    assert result.rows[0]["universe_as_of"] == "2026-09-10T13:30:00Z"


def test_contract_reference_rejects_blank_as_of_and_bad_contract_type():
    with pytest.raises(MassiveDataError, match="AS_OF_INVALID"):
        provider(FakeHTTP([])).fetch_option_contracts(as_of="")
    with pytest.raises(MassiveDataError, match="CONTRACT_TYPE_INVALID"):
        provider(FakeHTTP([])).fetch_option_contracts(as_of="2026-09-10", contract_type="straddle")


def test_empty_result_is_explicit_not_a_fabricated_complete_dataset():
    result = provider(FakeHTTP([{"results": []}])).fetch_stock_bars(
        "SPY", start_date="2026-09-10", end_date="2026-09-10")
    assert result.empty_result is True
    assert result.quality == "EMPTY"
    assert result.rows == ()


def test_unsupported_resolution_and_unverified_endpoints_fail_closed():
    p = provider(FakeHTTP([]))
    with pytest.raises(MassiveDataError, match="RESOLUTION_UNSUPPORTED"):
        p.get_bars(["SPY"], "2026-09-10", "2026-09-10", "5m", None)
    with pytest.raises(MassiveDataError, match="CORPORATE_ACTIONS_ENDPOINT_NOT_VERIFIED"):
        p.get_corporate_actions("2026-09-10", "2026-09-11")
    with pytest.raises(MassiveDataError, match="TRADE_ENDPOINT_NOT_VERIFIED"):
        p.get_trades(["SPY"], "2026-09-10", "2026-09-11")


def test_clock_rewind_during_response_refuses():
    fake = FakeHTTP([{"results": [bar()]}])
    with pytest.raises(MassiveDataError, match="CLOCK_REWIND"):
        provider(fake, clock=Clock(101.0, 100.0)).fetch_stock_bars(
            "SPY", start_date="2026-09-10", end_date="2026-09-10")


def test_response_errors_and_missing_results_are_not_empty_successes():
    with pytest.raises(MassiveDataError, match="STATUS_ERROR"):
        provider(FakeHTTP([{"status": "ERROR", "results": []}])).fetch_stock_bars(
            "SPY", start_date="2026-09-10", end_date="2026-09-10")
    with pytest.raises(MassiveDataError, match="RESULTS_MISSING"):
        provider(FakeHTTP([{"status": "OK"}])).fetch_stock_bars(
            "SPY", start_date="2026-09-10", end_date="2026-09-10")
