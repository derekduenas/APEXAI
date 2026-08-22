"""ALPACA FABRIC — offline unit tests against DOCUMENTED message shapes.

No live connection is attempted (APCA_API_SECRET_KEY is not present in
this environment): these tests feed _on_message() directly with JSON
and then _pump() the ingest queue, exercising the real reader ->
queue -> handler path introduced by the 2026-08-19 P0-1 repair
fab._pump()
matching Alpaca's published protocol, proving parsing/state-update
logic in isolation. The quote and bar message shapes below are COPIED
VERBATIM from Alpaca's docs as pasted by the operator; the trade shape
follows Alpaca's documented, publicly-stable schema. This is NOT a
substitute for live certification -- see DATA-2 LIVE CERTIFICATION,
which cannot run without the secret key.
"""
from __future__ import annotations

import json
import time

import pytest

from apex.intraday.alpaca_fabric import AlpacaRealtimeFabric


class _FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(json.loads(msg))


def _fab(symbols=("AAPL", "MSFT")):
    return AlpacaRealtimeFabric(symbols=list(symbols))


# --------------------------------------------------------- auth handshake
def test_auth_handshake_sends_subscribe_for_all_symbols(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "test_secret")
    fab = _fab(("AAPL", "MSFT", "TSLA"))
    ws = _FakeWS()
    fab._on_open(ws)
    assert ws.sent[0] == {"action": "auth", "key": "test_key",
                          "secret": "test_secret"}
    # never plaintext-logs the secret anywhere else
    assert "test_secret" not in json.dumps(fab.health())

    fab._on_message(ws, json.dumps(
        [{"T": "success", "msg": "authenticated"}]))
    fab._pump()
    assert fab.authorized is True
    assert ws.sent[1] == {"action": "subscribe",
                          "trades": ["AAPL", "MSFT", "TSLA"],
                          "quotes": ["AAPL", "MSFT", "TSLA"]}


def test_missing_secret_refuses_to_start(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "test_key")
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    from apex.intraday.alpaca_fabric import AlpacaFabricViolation
    fab = _fab()
    with pytest.raises(AlpacaFabricViolation, match="APCA_API_SECRET_KEY"):
        fab._on_open(_FakeWS())


# ----------------------------------------------- documented message shapes
def test_confirmed_quote_message_shape_parses():
    """VERBATIM from the operator-pasted docs:
    {"T":"q","S":"FAKEPACA","bx":"O","bp":133.85,"bs":4,"ax":"R",
     "ap":135.77,"as":5,"c":["R"],"z":"A","t":"...ISO8601..."}"""
    fab = _fab(("FAKEPACA",))
    raw = json.dumps([{"T": "q", "S": "FAKEPACA", "bx": "O", "bp": 133.85,
                       "bs": 4, "ax": "R", "ap": 135.77, "as": 5,
                       "c": ["R"], "z": "A",
                       "t": "2024-07-24T07:56:53.639713735Z"}])
    fab._on_message(_FakeWS(), raw)
    fab._pump()
    q = fab.latest_quote("FAKEPACA")
    assert q["bid"] == 133.85 and q["ask"] == 135.77
    assert q["bid_size"] == 4 and q["ask_size"] == 5


def test_trade_message_documented_schema_parses():
    """Alpaca's documented trade shape: S,p,s,t(ISO8601),x,c,i,z."""
    fab = _fab(("AAPL",))
    raw = json.dumps([{"T": "t", "S": "AAPL", "i": 12345, "x": "D",
                       "p": 126.55, "s": 100, "c": ["@", "I"],
                       "t": "2026-08-17T15:51:44.208Z", "z": "C"}])
    fab._on_message(_FakeWS(), raw)
    fab._pump()
    assert fab.counters["trades"] == 1
    bars = fab.bars_1m("AAPL")
    # a single trade with no completed minute yet -> empty is legal
    assert fab.counters["unknown_symbol"] == 0


def test_unknown_symbol_is_counted_never_crashes():
    fab = _fab(("AAPL",))
    raw = json.dumps([{"T": "t", "S": "ZZZZ_NOT_SUBSCRIBED", "p": 1.0,
                       "s": 1, "t": "2026-08-17T15:00:00Z"}])
    fab._on_message(_FakeWS(), raw)
    fab._pump()
    assert fab.counters["unknown_symbol"] == 1


def test_malformed_message_never_crashes():
    fab = _fab(("AAPL",))
    fab._on_message(_FakeWS(), "not json at all")
    fab._on_message(_FakeWS(), json.dumps([{"T": "t", "S": "AAPL"}]))  # missing p/s/t
    fab._pump()
    assert fab.counters["trades"] == 0   # neither malformed frame counted


def test_provider_error_frame_is_counted_never_silently_absorbed():
    fab = _fab(("AAPL",))
    fab._on_message(_FakeWS(), json.dumps(
        [{"T": "error", "code": 405, "msg": "symbol limit exceeded"}]))
    fab._pump()
    assert fab.counters["provider_errors"] == 1


def test_duplicate_trade_is_deduped():
    fab = _fab(("AAPL",))
    ws = _FakeWS()
    msg = json.dumps([{"T": "t", "S": "AAPL", "i": 1, "p": 100.0, "s": 10,
                       "t": "2026-08-17T15:00:00Z"}])
    fab._on_message(ws, msg)
    fab._on_message(ws, msg)
    fab._pump()
    assert fab.counters["trades"] == 2       # both counted as attempts
    assert fab.counters["duplicates"] == 1   # second one flagged


def test_future_timestamped_trade_is_rejected():
    fab = _fab(("AAPL",))
    import pandas as pd
    future = str((pd.Timestamp.now(tz="UTC")
                 + pd.Timedelta(hours=1)).isoformat())
    fab._on_message(_FakeWS(), json.dumps(
        [{"T": "t", "S": "AAPL", "i": 1, "p": 100.0, "s": 10, "t": future}]))
    fab._pump()
    assert fab.counters["future_rejected"] == 1


# ------------------------------------------------------------- health
def test_health_before_any_message_is_connecting():
    fab = _fab()
    h = fab.health()
    assert h["status"] == "CONNECTING"
    assert h["authorized"] is False


# ------------------------------------------------- THE HEALTH LAW (§4)
def test_authenticated_but_not_subscribed_is_its_own_state(monkeypatch):
    """CONNECTED != HEALTHY, AUTHENTICATED != HEALTHY: prove the state
    machine distinguishes every stage, never collapsing straight to
    HEALTHY on a control-message handshake."""
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    fab = _fab(("AAPL",))
    fab._on_open(_FakeWS())
    assert fab.health()["status"] == "CONNECTING"    # sent auth, no reply yet


def test_subscribed_no_data_is_distinct_from_healthy():
    fab = _fab(("AAPL", "MSFT"))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps([{"T": "success", "msg": "authenticated"}]))
    fab._pump()
    assert fab.health()["status"] == "AUTHENTICATED"
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["AAPL", "MSFT"],
         "quotes": ["AAPL", "MSFT"]}]))
    fab._pump()
    h = fab.health()
    assert h["status"] == "SUBSCRIBED_NO_DATA"
    assert h["subscribed"] is True
    assert h["trade_symbols_accepted"] == 2


def _recent_iso() -> str:
    import pandas as pd
    return str((pd.Timestamp.now(tz="UTC")
               - pd.Timedelta(seconds=2)).isoformat())


def test_real_trade_data_is_required_for_healthy():
    fab = _fab(("AAPL", "MSFT"))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps([{"T": "success", "msg": "authenticated"}]))
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["AAPL", "MSFT"],
         "quotes": ["AAPL", "MSFT"]}]))
    fab._pump()
    ts = _recent_iso()
    fab._on_message(ws, json.dumps(
        [{"T": "t", "S": "AAPL", "i": 1, "p": 100.0, "s": 10, "t": ts}]))
    fab._on_message(ws, json.dumps(
        [{"T": "t", "S": "MSFT", "i": 2, "p": 400.0, "s": 5, "t": ts}]))
    fab._pump()
    h = fab.health()
    assert h["status"] == "HEALTHY"           # both symbols reachable
    assert h["reachable_fraction"] == 1.0


def test_partial_coverage_reads_partial_not_healthy():
    fab = _fab(("A", "B", "C", "D"))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps([{"T": "success", "msg": "authenticated"}]))
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["A", "B", "C", "D"],
         "quotes": ["A", "B", "C", "D"]}]))
    fab._on_message(ws, json.dumps(
        [{"T": "t", "S": "A", "i": 1, "p": 1.0, "s": 1,
         "t": _recent_iso()}]))              # only 1/4 reachable
    fab._pump()
    assert fab.health()["status"] == "DEGRADED"


def test_quote_only_activity_counts_as_reachable_not_no_data():
    """A quiet-but-live symbol (quotes flowing, no trade printed) must
    count toward coverage, never toward DEGRADED as if unreachable."""
    fab = _fab(("A",))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps([{"T": "success", "msg": "authenticated"}]))
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["A"], "quotes": ["A"]}]))
    fab._on_message(ws, json.dumps(
        [{"T": "q", "S": "A", "bp": 99.0, "bs": 1, "ap": 99.1, "as": 1,
         "t": _recent_iso()}]))
    fab._pump()
    h = fab.health()
    assert h["status"] == "HEALTHY"
    assert fab.symbol_activity("A") == "NO_TRADES_OCCURRED"


def test_never_reached_symbol_is_no_provider_data():
    fab = _fab(("A", "B"))
    assert fab.symbol_activity("B") == "NO_PROVIDER_DATA"


def test_resubscription_is_counted():
    fab = _fab(("A",))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["A"], "quotes": ["A"]}]))
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["A"], "quotes": ["A"]}]))
    fab._pump()
    assert fab.counters["resubscriptions"] == 1


def test_disconnect_resets_authorized_and_subscribed():
    fab = _fab(("A",))
    ws = _FakeWS()
    fab._on_message(ws, json.dumps([{"T": "success", "msg": "authenticated"}]))
    fab._on_message(ws, json.dumps(
        [{"T": "subscription", "trades": ["A"], "quotes": ["A"]}]))
    fab._pump()
    assert fab.authorized and fab.subscribed
    fab._on_close()
    assert not fab.authorized and not fab.subscribed
    assert fab.health()["status"] == "CONNECTING"


def test_health_reflects_symbol_count_and_transport():
    fab = _fab(("A", "B", "C"))
    h = fab.health()
    assert h["symbol_count"] == 3
    assert h["transport"] == "ALPACA_WEBSOCKET_SIP_V1"
    assert h["decision_power"] == "NONE_OBSERVATIONAL_EPOCH1"


# ---------------------------------------------------- provider abstraction
def test_alpaca_provider_conforms_to_broad_provider_protocol():
    from apex.intraday.provider_interface import (
        AlpacaBroadProvider, BroadMarketDataProvider,
    )
    fab = _fab(("AAPL", "MSFT"))
    provider = AlpacaBroadProvider(fab)
    assert isinstance(provider, BroadMarketDataProvider)
    ent = provider.get_entitlement()
    assert ent.measured is False     # honestly not yet live-verified
    assert "NOT independently measured" in ent.note


def test_alpaca_provider_coverage_uses_canonical_universe_coverage_state():
    from apex.intraday.provider_interface import AlpacaBroadProvider
    fab = _fab(("AAPL", "MSFT"))
    provider = AlpacaBroadProvider(fab)
    cov = provider.get_coverage()
    assert cov.intended_universe == ("AAPL", "MSFT")
    assert cov.coverage_count == 2      # both symbols ARE subscribed/streamed
    assert cov.never_observed == ("AAPL", "MSFT")  # but zero data observed
    assert cov.continuous_universe == ()
    assert cov.broad_discovery_valid is False
    assert cov.status == "DEGRADED"
