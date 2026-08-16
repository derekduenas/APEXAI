"""RobinhoodAdapter — read + review ONLY.

THE SEAL IS STRUCTURAL, NOT A FLAG. This class does not define
`place_equity_order`, `place_option_order`, or any submit/execute
method. There is no `live_enabled=False` to flip, because there is
nothing to enable: the capability is absent from the type. A subclass
cannot add one usefully either — the gateway routes exclusively through
the read/review surface enumerated in ALLOWED_TOOLS, and
`sealing.assert_no_placement_surface()` scans the live object.

If the Robinhood MCP itself exposes placement tools, APEX still cannot
reach them: this adapter is the ONLY door, and the door has no handle
for placement.

TRANSPORT: the MCP server is registered but requires interactive OAuth
(`Needs authentication`). Until an operator authenticates, every method
returns a typed BLOCKED_BROKER_AUTH result. Fabricating broker
connectivity is forbidden — an unauthenticated broker must LOOK
unauthenticated at every layer.
"""

from __future__ import annotations

from apex.execution.contracts import (BrokerAccountState, BrokerCapabilities,
                                      BrokerOrderPreview, BrokerQuote,
                                      BrokerReview, BrokerReviewResult,
                                      BrokerTradability)

ADAPTER_VERSION = "robinhood_adapter_v1_read_review_only"
BROKER = "robinhood"

# the ONLY tools this adapter will ever route to. Placement tools are
# not listed, not imported, and not reachable.
ALLOWED_TOOLS = (
    "get_account_info", "get_buying_power", "get_positions",
    "get_open_orders", "get_stock_quote", "get_stock_info",
    "get_options_chains", "get_options_instruments",
    "get_options_market_data", "get_options_positions",
    "review_equity_order", "review_option_order",
)
FORBIDDEN_TOOL_MARKERS = ("place", "submit", "execute", "cancel_all", "sell_",
                          "buy_")


class BrokerAuthRequired(RuntimeError):
    """The broker is registered but not authenticated (operator act)."""


class RobinhoodAdapter:
    """Read/review surface only. No placement methods exist."""

    def __init__(self, mcp_caller=None, authenticated: bool | None = None):
        # mcp_caller: injected callable(tool_name, **kwargs) -> dict.
        # None => unauthenticated/unavailable; every call returns typed
        # BLOCKED, never a fabricated success.
        self._call_raw = mcp_caller
        self._authenticated = (bool(mcp_caller) if authenticated is None
                               else authenticated)

    # ------------------------------------------------------------ transport
    def _call(self, tool: str, **kwargs) -> dict:
        if tool not in ALLOWED_TOOLS:
            raise PermissionError(
                f"SEALED: {tool!r} is not in the adapter's allowed "
                f"read/review surface; placement is structurally absent")
        if any(m in tool for m in FORBIDDEN_TOOL_MARKERS):
            raise PermissionError(f"SEALED: {tool!r} looks like a mutating "
                                  f"tool and is refused by name")
        if not self._authenticated or self._call_raw is None:
            raise BrokerAuthRequired(
                "robinhood MCP registered but NOT authenticated "
                "(interactive OAuth is an operator act)")
        return self._call_raw(tool, **kwargs)

    @property
    def authenticated(self) -> bool:
        return bool(self._authenticated and self._call_raw)

    def connection_health(self) -> dict:
        return {"broker": BROKER, "adapter": ADAPTER_VERSION,
                "authenticated": self.authenticated,
                "status": "READY" if self.authenticated
                else "BLOCKED_BROKER_AUTH",
                "allowed_tools": list(ALLOWED_TOOLS),
                "placement_surface": "ABSENT_BY_CONSTRUCTION",
                "operator_step": (None if self.authenticated else
                                  "run `claude mcp list`, then authenticate "
                                  "robinhood-trading interactively")}

    # ------------------------------------------------------------ read side
    def capabilities(self) -> BrokerCapabilities:
        """UNVERIFIED until probed against a live authenticated session:
        UNKNOWN capabilities are None, never optimistic True."""
        if not self.authenticated:
            return BrokerCapabilities(broker=BROKER, source="UNVERIFIED")
        try:
            info = self._call("get_account_info")
        except Exception:                                   # noqa: BLE001
            return BrokerCapabilities(broker=BROKER, source="UNVERIFIED")
        lvl = (info or {}).get("options_level")
        return BrokerCapabilities(
            broker=BROKER, source="PROBED",
            equity_market=True, equity_limit=True, equity_stop=True,
            equity_stop_limit=True, equity_trailing_stop=True,
            equity_native_bracket=None,       # not exposed => UNKNOWN
            equity_moo=None, equity_moc=None,
            options_long_call=bool(lvl and lvl >= 2),
            options_long_put=bool(lvl and lvl >= 2),
            options_debit_spread=bool(lvl and lvl >= 3),
            options_multi_leg=bool(lvl and lvl >= 3),
            fractional=None, extended_hours=None,
            verified_at=str((info or {}).get("as_of", "")) or None)

    def account_state(self) -> BrokerAccountState:
        if not self.authenticated:
            return BrokerAccountState(status="BLOCKED_AUTH",
                                      detail="robinhood not authenticated")
        try:
            acct = self._call("get_account_info") or {}
            bp = self._call("get_buying_power") or {}
            pos = self._call("get_positions") or {}
            orders = self._call("get_open_orders") or {}
            return BrokerAccountState(
                status="OK",
                buying_power=_f(bp.get("buying_power")),
                cash=_f(acct.get("cash")),
                positions=tuple((pos or {}).get("positions", ()))[:200],
                open_orders=tuple((orders or {}).get("orders", ()))[:200],
                options_level=acct.get("options_level"),
                as_of=str(acct.get("as_of", "")) or None)
        except Exception as e:                              # noqa: BLE001
            return BrokerAccountState(status="UNAVAILABLE",
                                      detail=type(e).__name__)

    def quote(self, symbol: str) -> BrokerQuote:
        if not self.authenticated:
            return BrokerQuote(status="UNAVAILABLE", symbol=symbol)
        try:
            q = self._call("get_stock_quote", symbol=symbol) or {}
            return BrokerQuote(status="OK", symbol=symbol,
                               bid=_f(q.get("bid")), ask=_f(q.get("ask")),
                               last=_f(q.get("last") or q.get("price")),
                               as_of=str(q.get("as_of", "")) or None,
                               age_seconds=_f(q.get("age_seconds")))
        except Exception:                                   # noqa: BLE001
            return BrokerQuote(status="UNAVAILABLE", symbol=symbol)

    def tradability(self, symbol: str) -> BrokerTradability:
        if not self.authenticated:
            return BrokerTradability(status="UNKNOWN", symbol=symbol,
                                     reason="broker not authenticated")
        try:
            info = self._call("get_stock_info", symbol=symbol) or {}
            tradable = info.get("tradable")
            return BrokerTradability(
                status=("TRADABLE" if tradable is True
                        else "HALTED" if tradable is False else "UNKNOWN"),
                symbol=symbol, reason=str(info.get("state", "")))
        except Exception:                                   # noqa: BLE001
            return BrokerTradability(status="UNKNOWN", symbol=symbol,
                                     reason="lookup failed")

    def option_chain(self, symbol: str, expiration: str | None = None) -> dict:
        if not self.authenticated:
            return {"status": "BLOCKED_BROKER_AUTH", "symbol": symbol}
        try:
            ch = self._call("get_options_chains", symbol=symbol) or {}
            inst = self._call("get_options_instruments", symbol=symbol,
                              expiration=expiration) or {}
            md = self._call("get_options_market_data", symbol=symbol,
                            expiration=expiration) or {}
            return {"status": "OK", "symbol": symbol, "chain": ch,
                    "instruments": inst, "market_data": md}
        except Exception as e:                              # noqa: BLE001
            return {"status": "UNAVAILABLE", "symbol": symbol,
                    "detail": type(e).__name__}

    # ----------------------------------------------------------- review side
    def review_order(self, intent) -> BrokerReviewResult:
        """Ask the venue to REVIEW (not place). Unauthenticated or
        unavailable review is typed, never assumed to pass."""
        if not self.authenticated:
            return BrokerReviewResult(
                review=BrokerReview.UNAVAILABLE.value,
                reasons=("broker not authenticated: review impossible",))
        tool = ("review_option_order" if intent.asset_class == "OPTION"
                else "review_equity_order")
        try:
            r = self._call(tool, symbol=intent.symbol, side=intent.side,
                           quantity=intent.quantity,
                           order_type=intent.order_type,
                           limit_price=intent.limit_price) or {}
            warnings = tuple(r.get("warnings", ()))[:10]
            preview = BrokerOrderPreview(
                status="OK", estimated_cost=_f(r.get("estimated_cost")),
                estimated_fees=_f(r.get("estimated_fees")),
                buying_power_effect=_f(r.get("buying_power_effect")),
                warnings=warnings, raw_detail=str(r.get("detail", ""))[:300])
            if r.get("rejected"):
                return BrokerReviewResult(
                    review=BrokerReview.REFUSED.value, preview=preview,
                    reasons=tuple(r.get("reasons", ("venue refused",))))
            return BrokerReviewResult(
                review=(BrokerReview.WARNING.value if warnings
                        else BrokerReview.PASS.value),
                preview=preview, reasons=warnings)
        except Exception as e:                              # noqa: BLE001
            return BrokerReviewResult(
                review=BrokerReview.UNAVAILABLE.value,
                reasons=(f"review failed: {type(e).__name__}",))


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
