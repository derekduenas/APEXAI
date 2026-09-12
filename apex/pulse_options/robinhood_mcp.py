"""ROBINHOOD MCP PROVIDER ADAPTER (read-only market data), shaped from the observed responses of the
2026-09-11 read-only smoke (docs/evidence/robinhood_smoke_2026-09-11.json).

The MCP tools are invoked by the agent session, not by this process, so the adapter takes an
injectable `mcp_call(tool_name, args) -> dict` and never imports a client. Everything is gated:
`RobinhoodGate` refuses unless APEX_PILOT_LIVE_DATA == "ENABLED" or an explicit, dated operator
authorization string is passed for a read-only smoke. Only READ tools are known to the adapter; any
order/position/account tool name is refused by construction.

Observed conventions (recorded on every parsed record):
    equity quote     bid/ask decimal strings with venue_bid_time / venue_ask_time; NO sizes -> sizes NOT_AVAILABLE
    minute bars      begins_at = bar START, UTC; prices decimal strings; `interpolated` absent when false
    option quotes    bid/ask decimal strings WITH exact-int sizes; ONE updated_at per quote (provider snapshot)
    index quotes     value decimal string; venue_timestamp and updated_at with a -04:00 offset (tz-aware)
Vendor IV/Greeks/chance_of_profit are recorded as vendor context only, never as APEX forecasts."""
from __future__ import annotations

import os
import time
from datetime import datetime

from .providers import LIVE_SWITCH, ProviderUnavailable

READ_TOOLS = ("get_equity_quotes", "get_option_chains", "get_option_instruments", "get_option_quotes", "get_equity_historicals",
              "get_option_historicals", "get_indexes", "get_index_quotes", "get_equity_price_book")
FORBIDDEN_TOOLS = ("place_option_order", "place_equity_order", "place_crypto_order", "cancel_option_order", "cancel_equity_order",
                   "exercise_option", "review_option_order", "review_equity_order", "get_option_positions", "get_equity_positions",
                   "get_portfolio", "get_accounts")
AUTH_PREFIX = "ROBINHOOD_READ_ONLY_SMOKE_AUTHORIZED "


class RobinhoodGate:
    def __init__(self, env: dict | None = None, operator_authorization: str | None = None):
        self.env = os.environ if env is None else env
        self.authorization = operator_authorization

    def status(self) -> dict:
        switch = self.env.get(LIVE_SWITCH)
        auth_ok = isinstance(self.authorization, str) and self.authorization.startswith(AUTH_PREFIX) and len(self.authorization) > len(AUTH_PREFIX) + 8
        return {"switch": switch, "switch_ok": switch == "ENABLED", "operator_authorization_ok": auth_ok,
                "enabled": switch == "ENABLED" or auth_ok, "mode": "SMOKE_READ_ONLY" if (auth_ok and switch != "ENABLED") else ("LIVE" if switch == "ENABLED" else "DISABLED")}

    def require(self, what: str) -> None:
        st = self.status()
        if not st["enabled"]:
            raise ProviderUnavailable("LIVE_DATA_DISABLED: %s not enabled (%s=%r, operator authorization absent); %s not contacted"
                                      % (what, LIVE_SWITCH, st["switch"], what))


def _f(x, what):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise ProviderUnavailable("FIELD_NOT_NUMERIC: %s=%r" % (what, x))
    if v != v:
        raise ProviderUnavailable("FIELD_NAN: %s" % what)
    return v


def _epoch(s: str) -> float:
    if not isinstance(s, str) or not s:
        raise ProviderUnavailable("TIMESTAMP_MISSING")
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    # fromisoformat accepts at most 6 fractional digits; the provider sends up to 9
    if "." in txt:
        head, rest = txt.split(".", 1)
        n = 0
        while n < len(rest) and rest[n].isdigit():
            n += 1
        frac, tail = rest[:n], rest[n:]
        txt = "%s.%s%s" % (head, frac[:6].ljust(6, "0"), tail)
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        raise ProviderUnavailable("TIMESTAMP_NAIVE: %r" % s)
    return dt.timestamp()


class RobinhoodMCPAdapter:
    provider = "ROBINHOOD_MCP"

    def __init__(self, *, gate: RobinhoodGate, mcp_call, clock=time.time):
        self.gate, self._call, self.clock = gate, mcp_call, clock
        self.calls: list = []

    def call(self, tool: str, args: dict) -> dict:
        if tool in FORBIDDEN_TOOLS or tool not in READ_TOOLS:
            raise ProviderUnavailable("TOOL_REFUSED_BY_ADAPTER: %r is not a read-only market-data tool" % tool)
        self.gate.require("Robinhood MCP %s" % tool)
        self.calls.append((tool, dict(args)))
        out = self._call(tool, args)
        if not isinstance(out, dict) or "data" not in out:
            raise ProviderUnavailable("MCP_RESPONSE_SHAPE: %s returned %r" % (tool, type(out).__name__))
        return out["data"]

    # ------------------------------------------------------------ parsers (pure; fixture-tested)
    @staticmethod
    def parse_equity_quote(data: dict, *, receipt_time: float) -> dict:
        r = data["results"][0]; q = r["quote"]
        if q.get("state") != "active":
            raise ProviderUnavailable("QUOTE_STATE_NOT_ACTIVE: %r" % q.get("state"))
        bid, ask = _f(q["bid_price"], "bid_price"), _f(q["ask_price"], "ask_price")
        ts = max(_epoch(q["venue_bid_time"]), _epoch(q["venue_ask_time"]))
        return {"symbol": q["symbol"], "bid": bid, "ask": ask, "bid_size": None, "ask_size": None,
                "as_of": ts, "available": receipt_time, "source": "ROBINHOOD_MCP:equity_quote",
                "last_regular_trade": {"price": _f(q["last_trade_price"], "last_trade_price"), "time": _epoch(q["venue_last_trade_time"])},
                "prior_close": {"close": _f(r["close"]["price"], "close"), "date": r["close"]["date"], "source": r["close"].get("source")},
                "size_note": "NOT_AVAILABLE: the equity quote carries no bid/ask sizes on this channel"}

    @staticmethod
    def parse_bars(data: dict, *, symbol: str, receipt_time: float) -> dict:
        res = [x for x in data["results"] if x.get("symbol") == symbol]
        if not res:
            raise ProviderUnavailable("NO_BARS_FOR_SYMBOL")
        out, interpolated = [], 0
        for b in res[0]["bars"]:
            if b.get("interpolated"):
                interpolated += 1
                continue                                        # gap-fill carries no information: a missing minute is data
            out.append({"event_time": _epoch(b["begins_at"]), "open": _f(b["open_price"], "open"), "high": _f(b["high_price"], "high"),
                        "low": _f(b["low_price"], "low"), "close": _f(b["close_price"], "close"), "volume": float(b["volume"]),
                        "trades": None, "vwap": None, "receipt_time": receipt_time, "publication_time": None, "provider": "ROBINHOOD_MCP",
                        "symbol": symbol, "session": b.get("session"), "timestamp_convention": "begins_at = bar START, UTC, left-edge labelled"})
        return {"bars": out, "interpolated_dropped": interpolated, "interval": res[0].get("interval"), "bounds": res[0].get("bounds")}

    @staticmethod
    def parse_option_quotes(data: dict, *, contracts_by_id: dict, receipt_time: float) -> list:
        out = []
        for r in data["results"]:
            q = r["quote"]; iid = q["instrument_id"]
            c = contracts_by_id.get(iid)
            if c is None:
                raise ProviderUnavailable("UNKNOWN_INSTRUMENT_ID: %s" % iid)
            out.append({"symbol": c["symbol"], "expiration": c["expiration"], "strike": float(c["strike"]), "right": c["right"],
                        "bid": _f(q["bid_price"], "bid_price"), "ask": _f(q["ask_price"], "ask_price"),
                        "bid_size": int(q["bid_size"]), "ask_size": int(q["ask_size"]), "timestamp_epoch": _epoch(q["updated_at"]),
                        "timestamp_raw": q["updated_at"], "timestamp_convention": "provider updated_at, UTC, one snapshot per contract",
                        "receipt_time": receipt_time, "provider": "ROBINHOOD_MCP", "instrument_id": iid,
                        "vendor_context": {k: q.get(k) for k in ("mark_price", "implied_volatility", "delta", "gamma", "theta", "vega", "open_interest", "volume")},
                        "vendor_context_note": "vendor computations; not APEX forecasts"})
        return out

    @staticmethod
    def parse_instruments(data: dict) -> dict:
        out = {}
        for i in data["instruments"]:
            out[i["id"]] = {"symbol": i["chain_symbol"], "expiration": i["expiration_date"], "strike": float(i["strike_price"]),
                            "right": "CALL" if i["type"] == "call" else "PUT", "state": i["state"], "tradability": i["tradability"],
                            "multiplier": float(i["trade_value_multiplier"]), "sellout": i.get("sellout_datetime")}
        return out

    @staticmethod
    def parse_index_quotes(data: dict, *, receipt_time: float) -> dict:
        out = {}
        for q in data["quotes"]:
            out[q["symbol"]] = {"value": _f(q["value"], "value"), "as_of": _epoch(q["venue_timestamp"]), "available": receipt_time,
                                "provider_updated": _epoch(q["updated_at"]), "source": "ROBINHOOD_MCP:index"}
        return out

    # ------------------------------------------------------------ gated fetches
    def equity_quote(self, symbol: str) -> dict:
        d = self.call("get_equity_quotes", {"symbols": [symbol]})
        return self.parse_equity_quote(d, receipt_time=self.clock())

    def bars(self, symbol: str, *, start_epoch: float, end_epoch: float) -> list:
        fmt = lambda e: datetime.utcfromtimestamp(e).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = self.call("get_equity_historicals", {"symbols": [symbol], "start_time": fmt(start_epoch), "end_time": fmt(end_epoch), "interval": "minute", "bounds": "regular"})
        return self.parse_bars(d, symbol=symbol, receipt_time=self.clock())["bars"]

    def chain_expirations(self, symbol: str) -> dict:
        d = self.call("get_option_chains", {"underlying_symbol": symbol})
        ch = [c for c in d["chains"] if c.get("symbol") == symbol and not c.get("settle_on_open")]
        if not ch:
            raise ProviderUnavailable("NO_PM_SETTLED_CHAIN")
        c = ch[0]
        if float(c["trade_value_multiplier"]) != 100.0:
            raise ProviderUnavailable("MULTIPLIER_NOT_100")
        return {"chain_id": c["id"], "expirations": list(c["expiration_dates"]), "multiplier": 100.0}

    def contracts(self, chain_id: str, *, expiration: str, strike: float) -> dict:
        d = self.call("get_option_instruments", {"chain_id": chain_id, "expiration_dates": expiration, "strike_price": "%.4f" % strike})
        return self.parse_instruments(d)

    def option_quotes(self, contracts_by_id: dict) -> list:
        d = self.call("get_option_quotes", {"instrument_ids": list(contracts_by_id)})
        return self.parse_option_quotes(d, contracts_by_id=contracts_by_id, receipt_time=self.clock())

    def index_quotes(self, ids: list) -> dict:
        d = self.call("get_index_quotes", {"instrument_ids": ids})
        return self.parse_index_quotes(d, receipt_time=self.clock())
