"""BroadMarketDataProvider — the provider-neutral interface for full-
universe broad sensing (Phase 0.4). EODHD is implemented behind this
interface; a future primary feed (or a second, disagreement-checked
source) plugs in without touching Scout/World/Hunter, which consume
this interface only.

This module does NOT choose a provider and does NOT change which one is
active. It exists so that decision is a config change, not a rewrite.

decision_power: NONE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderEntitlement:
    provider: str
    trade_symbol_cap: int | None
    quote_symbol_cap: int | None
    max_connections: int | None
    measured: bool             # True = empirically measured, never inferred
    measured_at: str | None
    note: str = ""

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    status: str                 # HEALTHY | PARTIAL | DEGRADED | FAILED
    symbol_count: int
    last_message_age_s: float | None
    note: str = ""

    def as_record(self) -> dict:
        return asdict(self)


@runtime_checkable
class BroadMarketDataProvider(Protocol):
    """Every method a broad-sensor consumer (Scout/World) may call.
    A provider that cannot support one honestly returns
    NOT_SUPPORTED-shaped data, never silently omits or fabricates."""

    def subscribe_trades(self, symbols: list) -> None: ...

    def subscribe_quotes(self, symbols: list) -> None: ...

    def get_health(self) -> ProviderHealth: ...

    def get_coverage(self):
        """-> apex.intraday.universe_coverage.UniverseCoverageState"""
        ...

    def get_event_time(self, symbol: str) -> str | None:
        """The provider's own timestamp for the latest observation of
        `symbol` -- never the local receive time."""
        ...

    def get_known_from(self, symbol: str) -> str | None:
        """When APEX itself became aware of the latest observation
        (>= get_event_time, PIT law)."""
        ...

    def get_latency(self, symbol: str) -> float | None:
        """known_from - event_time, seconds. None when not measurable."""
        ...

    def get_entitlement(self) -> ProviderEntitlement: ...


class EODHDBroadProvider:
    """The CURRENT implementation, wrapping the existing, already-proven
    apex.intraday.equity_fabric.EquityRealtimeFabric. Nothing here
    changes fabric behavior -- this class only exposes it through the
    provider-neutral interface so a future provider is a drop-in, not a
    rewrite of every consumer.

    MEASURED ENTITLEMENT (2026-08-17, empirical, not inferred from
    documentation): trade channel proven healthy and stable at 50
    symbols; quote channel authorized but broke (zero messages, no
    error) somewhere between 20 and 30 symbols across repeated clean-
    start tests -- bisected but not pinned to an exact number, and not
    reproduced as a hard, documented limit anywhere EODHD publishes.
    This is DEEP-sensor-scale, not broad-universe scale.
    """

    PROVIDER_NAME = "EODHD_WEBSOCKET_REALTIME_V1"
    MEASURED_TRADE_CAP = 50
    MEASURED_QUOTE_CAP_UPPER_BOUND = 20   # last CONFIRMED-working count

    def __init__(self, fabric):
        self._fabric = fabric

    def subscribe_trades(self, symbols: list) -> None:
        self._fabric.resubscribe(symbols)

    def subscribe_quotes(self, symbols: list) -> None:
        # quote channel self-truncates to QUOTE_MAX_SYMBOLS internally;
        # see the MEASURED note above -- never treated as load-bearing
        self._fabric.resubscribe(symbols)

    def get_health(self) -> ProviderHealth:
        h = self._fabric.health()
        return ProviderHealth(
            provider=self.PROVIDER_NAME, status=h["status"],
            symbol_count=h["symbol_count"],
            last_message_age_s=h["trade_channel"].get("last_message_age_s"),
            note="quote channel is DEGRADED by measured behavior, not "
                "load-bearing for any decision")

    def get_coverage(self):
        from apex.intraday.universe_coverage import compute_universe_coverage
        import pandas as pd
        bars_idx = {}
        for s in self._fabric.symbols:
            b = self._fabric.bars_1m(s)
            bars_idx[s] = (b["event_time_utc"] if len(b)
                          else pd.Series([], dtype="datetime64[ns, UTC]"))
        return compute_universe_coverage(
            intended_universe=self._fabric.symbols,
            authorized_universe=self._fabric.symbols,
            streamed_universe=self._fabric.symbols,
            bar_index_by_symbol=bars_idx, as_of=pd.Timestamp.now(tz="UTC"),
            source=self.PROVIDER_NAME, transport=self.PROVIDER_NAME)

    def get_event_time(self, symbol: str) -> str | None:
        bars = self._fabric.bars_1m(symbol, minutes=1)
        if not len(bars):
            return None
        return str(bars["event_time_utc"].iloc[-1])

    def get_known_from(self, symbol: str) -> str | None:
        import pandas as pd
        with self._fabric._lock:
            tr = self._fabric.trades.get(symbol.upper().replace(".US", ""))
        if not tr:
            return None
        return str(pd.Timestamp(tr[-1]["known_from_s"], unit="s", tz="UTC"))

    def get_latency(self, symbol: str) -> float | None:
        with self._fabric._lock:
            tr = self._fabric.trades.get(symbol.upper().replace(".US", ""))
        if not tr:
            return None
        last = tr[-1]
        return round(last["known_from_s"] - last["event_s"], 3)

    def get_entitlement(self) -> ProviderEntitlement:
        return ProviderEntitlement(
            provider=self.PROVIDER_NAME,
            trade_symbol_cap=self.MEASURED_TRADE_CAP,
            quote_symbol_cap=self.MEASURED_QUOTE_CAP_UPPER_BOUND,
            max_connections=None,           # not measured; see DATA-2 report
            measured=True, measured_at="2026-08-17",
            note="trade cap measured stable at 50; quote cap measured "
                "unreliable above 20-30, exact boundary not pinned; "
                "no official API exposes WebSocket entitlement directly "
                "(checked /api/user -- billing fields only, no "
                "WebSocket-specific limit field)")


class AlpacaBroadProvider:
    """PRIMARY_BROAD_SENSOR (operator-authorized, Algo Trader Plus).
    Wraps apex.intraday.alpaca_fabric.AlpacaRealtimeFabric -- same
    provider-neutral seam as EODHDBroadProvider, so Scout/World never
    know or care which is active.

    ENTITLEMENT: per Alpaca's own published plan table (not yet
    independently re-measured -- see DATA-2 LIVE CERTIFICATION, pending
    APCA_API_SECRET_KEY): full SIP tape, WebSocket subscriptions
    UNLIMITED on a single connection. No sharding required for 164
    symbols, unlike EODHD.
    """

    PROVIDER_NAME = "ALPACA_WEBSOCKET_SIP_V1"

    def __init__(self, fabric):
        self._fabric = fabric

    def subscribe_trades(self, symbols: list) -> None:
        # Alpaca subscribes trades+quotes together; symbol set is fixed
        # at fabric construction for this first implementation (the
        # authorized target is ALL 164 on one connection, not rotation)
        raise NotImplementedError(
            "AlpacaRealtimeFabric subscribes its full symbol set at "
            "construction; dynamic resubscribe is not yet built -- not "
            "needed for the 164-symbol full-coverage target")

    def subscribe_quotes(self, symbols: list) -> None:
        self.subscribe_trades(symbols)

    def get_health(self) -> ProviderHealth:
        h = self._fabric.health()
        return ProviderHealth(
            provider=self.PROVIDER_NAME, status=h["status"],
            symbol_count=h["symbol_count"],
            last_message_age_s=h.get("last_message_age_s"),
            note="full SIP trades + quotes on one connection")

    def get_coverage(self):
        from apex.intraday.universe_coverage import compute_universe_coverage
        import pandas as pd
        bars_idx = {}
        for s in self._fabric.symbols:
            b = self._fabric.bars_1m(s)
            bars_idx[s] = (b["event_time_utc"] if len(b)
                          else pd.Series([], dtype="datetime64[ns, UTC]"))
        return compute_universe_coverage(
            intended_universe=self._fabric.symbols,
            authorized_universe=self._fabric.symbols,
            streamed_universe=self._fabric.symbols,
            bar_index_by_symbol=bars_idx, as_of=pd.Timestamp.now(tz="UTC"),
            source=self.PROVIDER_NAME, transport=self.PROVIDER_NAME)

    def get_event_time(self, symbol: str) -> str | None:
        bars = self._fabric.bars_1m(symbol, minutes=1)
        if not len(bars):
            return None
        return str(bars["event_time_utc"].iloc[-1])

    def get_known_from(self, symbol: str) -> str | None:
        import pandas as pd
        with self._fabric._lock:
            tr = self._fabric.trades.get(symbol.upper().replace(".US", ""))
        if not tr:
            return None
        return str(pd.Timestamp(tr[-1]["known_from_s"], unit="s", tz="UTC"))

    def get_latency(self, symbol: str) -> float | None:
        with self._fabric._lock:
            tr = self._fabric.trades.get(symbol.upper().replace(".US", ""))
        if not tr:
            return None
        last = tr[-1]
        return round(last["known_from_s"] - last["event_s"], 3)

    def get_entitlement(self) -> ProviderEntitlement:
        return ProviderEntitlement(
            provider=self.PROVIDER_NAME,
            trade_symbol_cap=None, quote_symbol_cap=None,  # "unlimited"
            max_connections=1,
            measured=False,       # per Alpaca's published table; NOT yet
                                  # independently re-measured (no secret key)
            measured_at=None,
            note="per Alpaca's published entitlement table: full SIP, "
                "unlimited WebSocket symbols, 1 connection per session -- "
                "NOT independently measured by APEX; live certification "
                "pending APCA_API_SECRET_KEY")
