"""The acquisition channel must not be able to leak a key or fake a dataset.

Network calls are not exercised here. What IS exercised is every invariant that
protects the experiment from the acquisition layer:

  * the key comes from the environment and nowhere else
  * the key never appears in a manifest, an error, or a printed URL
  * zero rows is a FAILURE, never an empty dataset
  * a missing entitlement is loud and names the table
  * throttling (429) is never reported as an entitlement verdict
"""

from __future__ import annotations

import json

import pytest

from apex.data.nasdaq_api import (
    ApiKeyMissing,
    EmptyResponse,
    EntitlementReport,
    NasdaqDataLinkClient,
    NotEntitled,
    RateLimited,
    TableStatus,
    _redact,
    api_key,
    write_snapshot_file,
)

REQUIRED = ("TICKERS", "SEP", "DAILY", "ACTIONS")
FAKE_KEY = "abcdef0123456789abcdef0123456789"


# ---------------------------------------------------------------------------
# THE KEY
# ---------------------------------------------------------------------------


def test_a_missing_key_names_the_variable_and_shows_how_to_set_it(monkeypatch):
    monkeypatch.delenv("NASDAQ_DATA_LINK_API_KEY", raising=False)

    with pytest.raises(ApiKeyMissing) as excinfo:
        api_key()

    message = str(excinfo.value)
    assert "NASDAQ_DATA_LINK_API_KEY" in message
    assert "export" in message


def test_a_blank_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("NASDAQ_DATA_LINK_API_KEY", "   ")

    with pytest.raises(ApiKeyMissing):
        api_key()


def test_the_key_cannot_be_supplied_through_config_or_a_file():
    """There is no parameter or config path that can carry a key into the repo."""
    import inspect

    from apex.data import nasdaq_api

    source = inspect.getsource(nasdaq_api)
    assert "config.get" not in source, "a config-sourced key could be committed"
    assert 'os.environ.get(ENV_VAR' in source


def test_urls_are_redacted_before_being_shown():
    url = f"https://data.nasdaq.com/api/v3/x.json?api_key={FAKE_KEY}&rows=1"

    assert FAKE_KEY not in _redact(url, FAKE_KEY)
    assert "<API_KEY>" in _redact(url, FAKE_KEY)


# ---------------------------------------------------------------------------
# ENTITLEMENT
# ---------------------------------------------------------------------------


class FakeClient(NasdaqDataLinkClient):
    """A client whose transport is scripted, so no network is touched."""

    def __init__(self, responses):
        self._key = FAKE_KEY
        self._responses = responses
        self.calls_made = 0
        self.endpoints_used = []

    def _request(self, path, params):
        self.calls_made += 1
        table = path.split("/")[-1].replace(".json", "")
        status, body = self._responses[table]
        return status, body, f"{path}?api_key=<API_KEY>"


def _ok(columns):
    return 200, {"datatable": {"columns": [{"name": c} for c in columns], "data": [[1] * len(columns)]}}


def _denied(code=403):
    return code, json.dumps({"quandl_error": {"code": "QEPx05", "message": "not subscribed"}})


def _throttled():
    return 429, json.dumps(
        {"quandl_error": {"code": "QELx06", "message": "temporarily been disabled"}}
    )


def test_full_entitlement_is_reported_with_columns():
    client = FakeClient({t: _ok(["ticker", "date"]) for t in REQUIRED})

    report = client.probe(REQUIRED, retry_on_429=False)

    assert report.accessible == list(REQUIRED)
    assert not report.denied
    assert report.statuses[0].columns == ("ticker", "date")


def test_a_denied_table_is_named_and_blocks_everything():
    client = FakeClient({"TICKERS": _ok(["ticker"]), "SEP": _denied(),
                         "DAILY": _denied(), "ACTIONS": _ok(["ticker"])})

    with pytest.raises(NotEntitled) as excinfo:
        client.require_entitled(REQUIRED, retry_on_429=False)

    message = str(excinfo.value)
    assert "SEP" in message and "DAILY" in message
    assert "No substitute table will be used" in message


def test_throttling_is_never_reported_as_an_entitlement_verdict():
    """429 means 'come back later', not 'you are not subscribed'.

    Conflating the two would produce a permanent-sounding gap report from a
    transient condition, and could send the user off to buy a subscription they
    may already have.
    """
    client = FakeClient({t: _throttled() for t in REQUIRED})

    with pytest.raises(RateLimited) as excinfo:
        client.require_entitled(REQUIRED, retry_on_429=False)

    message = str(excinfo.value)
    assert "NOT" in message and "subscription answer" in message
    assert "throttled" in message.lower()


def test_the_report_flags_the_throttled_state_explicitly():
    client = FakeClient({t: _throttled() for t in REQUIRED})

    report = client.probe(REQUIRED, retry_on_429=False)

    assert report.rate_limited
    assert "not an entitlement verdict" in report.render().lower()


def test_probe_costs_one_call_per_table():
    """Entitlement is a yes/no question; asking must not burn quota."""
    client = FakeClient({t: _ok(["ticker"]) for t in REQUIRED})

    client.probe(REQUIRED, retry_on_429=False)

    assert client.calls_made == len(REQUIRED)


# ---------------------------------------------------------------------------
# NEVER FAKE A DATASET
# ---------------------------------------------------------------------------


def test_zero_rows_is_a_failure_not_an_empty_dataset():
    client = FakeClient(
        {"SEP": (200, {"datatable": {"columns": [{"name": "ticker"}], "data": []}})}
    )

    with pytest.raises(EmptyResponse) as excinfo:
        client.fetch_table("SEP")

    assert "ZERO rows" in str(excinfo.value)


def test_a_mid_download_throttle_discards_the_partial_result():
    """A truncated table would silently become a smaller universe."""
    client = FakeClient({"SEP": _throttled()})

    with pytest.raises(RateLimited) as excinfo:
        client.fetch_table("SEP")

    assert "DISCARDED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# THE MANIFEST
# ---------------------------------------------------------------------------


def test_the_manifest_records_everything_lineage_needs(tmp_path):
    entry = write_snapshot_file(
        tmp_path,
        "SEP",
        ["ticker", "date", "close"],
        [["AAPL", "2020-01-02", 75.0], ["AAPL", "2020-01-03", 74.5]],
        endpoint="https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json",
    )

    for key in (
        "table", "file", "sha256", "rows", "columns",
        "date_range", "endpoint", "retrieved_at", "source", "vendor",
    ):
        assert key in entry, f"manifest entry is missing '{key}'"
    assert entry["rows"] == 2
    assert entry["date_range"] == ["2020-01-02", "2020-01-03"]
    assert len(entry["sha256"]) == 64


def test_the_manifest_never_contains_the_key(tmp_path):
    entry = write_snapshot_file(
        tmp_path, "SEP", ["ticker", "date"], [["AAPL", "2020-01-02"]],
        endpoint=f"https://data.nasdaq.com/x?api_key={FAKE_KEY}",
    )

    assert FAKE_KEY not in json.dumps(entry), (
        "the API key reached the manifest, which is written to disk and committed"
    )


def test_the_written_file_hashes_to_the_manifest_value(tmp_path):
    import hashlib

    entry = write_snapshot_file(
        tmp_path, "TICKERS", ["permaticker", "ticker"], [[199001, "AAA"]], endpoint="x"
    )

    actual = hashlib.sha256((tmp_path / "TICKERS.csv").read_bytes()).hexdigest()
    assert actual == entry["sha256"]


def test_the_snapshot_file_is_readable_by_the_existing_adapter(tmp_path):
    """The acquisition layer must produce exactly what the frozen adapter reads."""
    import pandas as pd

    write_snapshot_file(
        tmp_path, "TICKERS", ["permaticker", "ticker", "exchange"],
        [[199001, "AAA", "NYSE"]], endpoint="x",
    )
    frame = pd.read_csv(tmp_path / "TICKERS.csv")

    assert list(frame.columns) == ["permaticker", "ticker", "exchange"]
    assert frame.iloc[0]["ticker"] == "AAA"


def test_entitlement_report_serialises_without_the_key():
    report = EntitlementReport(checked_at="2026-08-09T00:00:00Z")
    report.statuses.append(TableStatus("SEP", True, 200, "", ("ticker",), "1 columns"))

    assert FAKE_KEY not in json.dumps(report.as_dict())
    assert report.as_dict()["accessible"] == ["SEP"]


def test_credentials_are_stripped_at_the_sink_not_just_by_callers():
    """Defence in depth: a caller that forgets to redact still cannot leak.

    Found by test_the_manifest_never_contains_the_key, which caught the endpoint
    being stored verbatim.
    """
    from apex.data.nasdaq_api import strip_credentials

    dirty = f"https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json?api_key={FAKE_KEY}&date.gte=2004-01-01"
    clean = strip_credentials(dirty)

    assert FAKE_KEY not in clean
    assert "date.gte=2004-01-01" in clean, "non-secret query parameters are lineage, keep them"
    assert clean.startswith("https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json")


def test_stripping_handles_a_url_with_no_query():
    from apex.data.nasdaq_api import strip_credentials

    url = "https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json"
    assert strip_credentials(url) == url
