"""Robinhood MCP adapter on FIXTURES shaped exactly like the 2026-09-11 read-only smoke responses.
Establishes: parsing with recorded conventions; sizes absent on equity quotes; interpolated bars dropped and counted;
option quotes satisfy the boundary's quote contract; the gate refuses without switch/authorization; order and
position tools are refused by construction; the twin composes a snapshot from these bars and the frozen artifact
forecasts from it; a stale prior-session option quote is refused by the boundary's quote sanitation."""
import json

import pytest

from apex.multiverse_wb import pricing as PR
from apex.options_pilot.records import validate_quote
from apex.pulse_options import ingest as G, snapshot as SN, inference as I
from apex.pulse_options import robinhood_mcp as RH
from apex.pulse_options.providers import ProviderUnavailable, load_bars

EQ = {"results": [{"quote": {"symbol": "SPY", "last_trade_price": "757.870000", "venue_last_trade_time": "2026-09-10T19:59:59.99992519Z",
                             "last_non_reg_trade_price": "758.700000", "venue_last_non_reg_trade_time": "2026-09-11T02:45:51.692Z",
                             "adjusted_previous_close": "757.830000", "previous_close": "757.830000", "previous_close_date": "2026-09-10",
                             "bid_price": "758.610000", "venue_bid_time": "2026-09-11T02:46:21.086Z", "ask_price": "758.680000",
                             "venue_ask_time": "2026-09-11T02:46:21.086Z", "has_traded": True, "state": "active"},
                   "close": {"symbol": "SPY", "date": "2026-09-10", "price": "757.83", "interpolated": False, "source": "sip-list-exchange-close"}}]}
CHAINS = {"chains": [{"id": "c277b118-58d9-4060-8dc5-a3b5898955cb", "symbol": "SPY", "expiration_dates": ["2026-09-11", "2026-10-02", "2026-10-09"],
                      "trade_value_multiplier": "100.0000", "settle_on_open": False}]}
INSTR = {"instruments": [{"id": "bcd66aaa-9789-41c7-96be-4ec1ac7483a4", "chain_symbol": "SPY", "expiration_date": "2026-10-02", "strike_price": "758.0000",
                          "type": "call", "state": "active", "tradability": "tradable", "trade_value_multiplier": "100.0000", "sellout_datetime": "2026-10-02T19:45:00+00:00"},
                         {"id": "36e626e4-64ce-46ae-9397-8390cdf3603c", "chain_symbol": "SPY", "expiration_date": "2026-10-02", "strike_price": "758.0000",
                          "type": "put", "state": "active", "tradability": "tradable", "trade_value_multiplier": "100.0000"}]}
OQ = {"results": [{"quote": {"instrument_id": "bcd66aaa-9789-41c7-96be-4ec1ac7483a4", "ask_price": "11.110000", "ask_size": 9, "bid_price": "11.050000", "bid_size": 52,
                             "mark_price": "11.080000", "implied_volatility": "0.139400", "delta": "0.531342", "gamma": "0.015442", "theta": "-0.276791", "vega": "0.735383",
                             "open_interest": 29, "volume": 835, "updated_at": "2026-09-10T20:14:59.931865088Z"}, "close": {"price": "13.06"}},
                  {"quote": {"instrument_id": "36e626e4-64ce-46ae-9397-8390cdf3603c", "ask_price": "10.520000", "ask_size": 53, "bid_price": "10.430000", "bid_size": 121,
                             "mark_price": "10.475000", "implied_volatility": "0.152215", "delta": "-0.474218", "updated_at": "2026-09-10T20:14:59.92157756Z"}, "close": {"price": "8.39"}}]}
IDX = {"quotes": [{"instrument_id": "3b912aa2", "symbol": "VIX", "value": "17.84", "state": "", "venue_timestamp": "2026-09-10T16:15:01.33168-04:00", "updated_at": "2026-09-10T17:59:16.03301433-04:00"}]}


def _bars_fixture(n=90, start="2026-09-10T18:30:00Z", gap_at=40):
    base = RH._epoch(start); px = 757.67
    bars = []
    for i in range(n):
        o = px; c = px + (0.1 if i % 3 else -0.15); h = max(o, c) + 0.05; l = min(o, c) - 0.05
        b = {"begins_at": RH.datetime.utcfromtimestamp(base + 60 * i).strftime("%Y-%m-%dT%H:%M:%SZ"), "open_price": "%.6f" % o, "close_price": "%.6f" % c,
             "high_price": "%.6f" % h, "low_price": "%.6f" % l, "volume": 20000 + i, "session": "reg"}
        if gap_at is not None and i == gap_at:
            b["interpolated"] = True
        bars.append(b); px = c
    return {"results": [{"symbol": "SPY", "interval": "minute", "bounds": "regular", "bars": bars}]}


T_RCPT = RH._epoch("2026-09-11T02:46:56Z")


def test_gate_refuses_without_switch_or_authorization_and_forbids_trading_tools():
    calls = []
    def mcp(tool, args):
        calls.append(tool); return {"data": {}}
    a = RH.RobinhoodMCPAdapter(gate=RH.RobinhoodGate(env={}), mcp_call=mcp)
    with pytest.raises(ProviderUnavailable, match="LIVE_DATA_DISABLED"):
        a.equity_quote("SPY")
    assert calls == []
    for tool in ("place_option_order", "get_option_positions", "get_accounts", "not_a_tool"):
        with pytest.raises(ProviderUnavailable, match="TOOL_REFUSED_BY_ADAPTER"):
            RH.RobinhoodMCPAdapter(gate=RH.RobinhoodGate(env={"APEX_PILOT_LIVE_DATA": "ENABLED"}), mcp_call=mcp).call(tool, {})
    g = RH.RobinhoodGate(env={}, operator_authorization="ROBINHOOD_READ_ONLY_SMOKE_AUTHORIZED 2026-09-11")
    assert g.status()["mode"] == "SMOKE_READ_ONLY" and g.status()["enabled"]
    assert RH.RobinhoodGate(env={}, operator_authorization="ROBINHOOD_READ_ONLY_SMOKE_AUTHORIZED").status()["enabled"] is False


def test_parsers_record_conventions_and_the_twin_forecasts_from_real_shaped_bars():
    q = RH.RobinhoodMCPAdapter.parse_equity_quote(EQ, receipt_time=T_RCPT)
    assert q["bid"] == 758.61 and q["ask"] == 758.68 and q["bid_size"] is None and q["size_note"].startswith("NOT_AVAILABLE")
    assert q["as_of"] == RH._epoch("2026-09-11T02:46:21.086Z") and q["prior_close"]["close"] == 757.83
    b = RH.RobinhoodMCPAdapter.parse_bars(_bars_fixture(), symbol="SPY", receipt_time=T_RCPT)
    assert len(b["bars"]) == 89 and b["interpolated_dropped"] == 1 and b["bars"][0]["timestamp_convention"].startswith("begins_at = bar START")
    st = G.BarStore("SPY", source="ROBINHOOD_MCP")
    load_bars(st, [{**x, "receipt_time": x["event_time"] + 61} for x in b["bars"]])   # receipt after completion for the ingest contract
    as_of = RH._epoch("2026-09-10T20:00:30Z")
    snap = SN.compose(symbol="SPY", as_of=as_of, bars=st.bars_available_by(as_of), source="ROBINHOOD_MCP",
                      book={**q, "available": as_of - 1, "as_of": as_of - 2})
    assert snap["fields"]["ret_60"]["quality"] == "NOT_ESTIMABLE"                    # the dropped interpolated minute (19:10) is a gap: refused, not filled
    assert snap["fields"]["ret_30"]["quality"] == "VALID" and snap["fields"]["underlying_bid_size"]["quality"] == "NOT_AVAILABLE"
    # with a gap-free window the frozen artifact forecasts from these bars
    b2 = RH.RobinhoodMCPAdapter.parse_bars(_bars_fixture(n=60, start="2026-09-10T19:00:00Z", gap_at=None), symbol="SPY", receipt_time=T_RCPT)
    st2 = G.BarStore("SPY", source="ROBINHOOD_MCP"); load_bars(st2, [{**x, "receipt_time": x["event_time"] + 61} for x in b2["bars"]])
    snap2 = SN.compose(symbol="SPY", as_of=as_of, bars=st2.bars_available_by(as_of), source="ROBINHOOD_MCP")
    fc = I.default_artifact().forecast(snap2, created_epoch=as_of)
    assert fc["params_hash"] == "ca04fc6e713e1a5c" and fc["scale"] > 0 and fc["reference_time_utc"].startswith("2026-09-10T19:59:00")


def test_option_quotes_satisfy_the_quote_contract_but_a_prior_session_quote_is_stale_at_night():
    contracts = RH.RobinhoodMCPAdapter.parse_instruments(INSTR)
    qs = RH.RobinhoodMCPAdapter.parse_option_quotes(OQ, contracts_by_id=contracts, receipt_time=T_RCPT)
    call = [x for x in qs if x["right"] == "CALL"][0]
    assert call["ask"] == 11.11 and call["ask_size"] == 9 and call["bid_size"] == 52 and call["strike"] == 758.0
    v = validate_quote(call, contract={"symbol": "SPY", "expiration": "2026-10-02", "strike": 758.0, "right": "CALL"})
    assert v["timestamp_meaning"].startswith("PROVIDER_SNAPSHOT") and v["ask"] == 11.11
    with pytest.raises(PR.PricingRefused, match="STALE"):
        PR.sanitize_quote(call, now=T_RCPT)                                          # ~6.5 h old at receipt: refused
    assert PR.sanitize_quote(call, now=call["timestamp_epoch"] + 5)["usable_for_iv"] is True
    assert call["vendor_context"]["implied_volatility"] == "0.139400" and call["vendor_context_note"].startswith("vendor computations")
    idx = RH.RobinhoodMCPAdapter.parse_index_quotes(IDX, receipt_time=T_RCPT)
    assert idx["VIX"]["value"] == 17.84 and idx["VIX"]["as_of"] == RH._epoch("2026-09-10T20:15:01.33168Z")


def test_gated_fetch_path_records_calls_and_parses_end_to_end():
    def mcp(tool, args):
        return {"data": {"get_equity_quotes": EQ, "get_option_chains": CHAINS, "get_option_instruments": INSTR, "get_option_quotes": OQ,
                         "get_equity_historicals": _bars_fixture(), "get_index_quotes": IDX}[tool]}
    a = RH.RobinhoodMCPAdapter(gate=RH.RobinhoodGate(env={}, operator_authorization="ROBINHOOD_READ_ONLY_SMOKE_AUTHORIZED 2026-09-11"), mcp_call=mcp, clock=lambda: T_RCPT)
    ch = a.chain_expirations("SPY")
    assert ch["chain_id"].startswith("c277b118") and "2026-10-02" in ch["expirations"]
    cs = a.contracts(ch["chain_id"], expiration="2026-10-02", strike=758.0)
    assert len(cs) == 2 and a.calls[-1] == ("get_option_instruments", {"chain_id": ch["chain_id"], "expiration_dates": "2026-10-02", "strike_price": "758.0000"})
    qs = a.option_quotes(cs)
    assert {x["right"] for x in qs} == {"CALL", "PUT"}
    assert len(a.bars("SPY", start_epoch=RH._epoch("2026-09-10T18:30:00Z"), end_epoch=RH._epoch("2026-09-10T20:00:00Z"))) == 89
    assert a.equity_quote("SPY")["ask"] == 758.68 and a.index_quotes(["3b912aa2"])["VIX"]["value"] == 17.84
    with pytest.raises(ProviderUnavailable, match="MCP_RESPONSE_SHAPE"):
        RH.RobinhoodMCPAdapter(gate=a.gate, mcp_call=lambda t, x: "nope").equity_quote("SPY")
