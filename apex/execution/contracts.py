"""Provider-neutral execution contracts.

APEX strategy logic never imports a broker by name. The chain is:

    APEX -> ExecutionGateway -> <Broker>Adapter -> venue

Robinhood is the hands; APEX is the brain. Every type here describes
what a VENUE can express, never what the strategy wants — TradeThesis
owns intent, capabilities own feasibility, and a capability that does
not exist produces BROKER_CAPABILITY_UNAVAILABLE rather than a silent
emulation.

ERD-1 terminal state is ORDER_READY. ORDER_SENT does not exist in this
package.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

CONTRACTS_VERSION = "apex_execution_contracts_v1"


class ReadinessState(Enum):
    REFUSED = "REFUSED"
    BLOCKED_BROKER_AUTH = "BLOCKED_BROKER_AUTH"
    CAPABILITY_UNAVAILABLE = "BROKER_CAPABILITY_UNAVAILABLE"
    STALE = "REFUSED_STALE"
    DUPLICATE = "REFUSED_DUPLICATE_INTENT"
    KILLED = "REFUSED_KILL_SWITCH"
    ORDER_READY = "ORDER_READY"
    # ORDER_SENT deliberately absent: live placement is sealed in ERD-1.


class BrokerReview(Enum):
    PASS = "BROKER_REVIEW_PASS"
    WARNING = "BROKER_REVIEW_WARNING"
    REFUSED = "BROKER_REVIEW_REFUSED"
    UNAVAILABLE = "BROKER_REVIEW_UNAVAILABLE"


@dataclass(frozen=True)
class BrokerCapabilities:
    """Explicit, never assumed. UNKNOWN is not True."""
    broker: str
    equity_market: bool | None = None
    equity_limit: bool | None = None
    equity_stop: bool | None = None
    equity_stop_limit: bool | None = None
    equity_trailing_stop: bool | None = None
    equity_native_bracket: bool | None = None
    equity_moo: bool | None = None
    equity_moc: bool | None = None
    options_long_call: bool | None = None
    options_long_put: bool | None = None
    options_debit_spread: bool | None = None
    options_multi_leg: bool | None = None
    fractional: bool | None = None
    extended_hours: bool | None = None
    source: str = "UNVERIFIED"          # DOC | PROBED | UNVERIFIED
    verified_at: str | None = None

    def supports(self, capability: str) -> tuple:
        val = getattr(self, capability, None)
        if val is True:
            return True, None
        return False, (f"BROKER_CAPABILITY_UNAVAILABLE: {self.broker} "
                       f"{capability}="
                       f"{'UNKNOWN' if val is None else 'False'} "
                       f"(source={self.source}); native emulation is "
                       f"forbidden without a governed Trade Manager path")


@dataclass(frozen=True)
class BrokerAccountState:
    status: str                          # OK | UNAVAILABLE | BLOCKED_AUTH
    buying_power: float | None = None
    cash: float | None = None
    positions: tuple = ()
    open_orders: tuple = ()
    options_level: int | None = None
    as_of: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class BrokerQuote:
    status: str                          # OK | UNAVAILABLE | STALE
    symbol: str = ""
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    as_of: str | None = None
    age_seconds: float | None = None

    @property
    def spread_bps(self) -> float | None:
        if self.bid and self.ask and self.bid > 0:
            mid = (self.bid + self.ask) / 2
            return round((self.ask - self.bid) / mid * 1e4, 3)
        return None


@dataclass(frozen=True)
class BrokerTradability:
    status: str                          # TRADABLE | HALTED | UNKNOWN
    symbol: str = ""
    reason: str = ""


@dataclass(frozen=True)
class OrderIntent:
    """What APEX would ask a venue to do. Never sent in ERD-1."""
    intent_id: str
    decision_id: str
    expression_id: str
    intent_version: int
    symbol: str
    side: str                            # BUY | SELL
    quantity: float
    order_type: str                      # LIMIT | MARKET | STOP_LIMIT ...
    limit_price: float | None
    stop_price: float | None
    time_in_force: str
    asset_class: str                     # EQUITY | OPTION
    legs: tuple = ()                     # option legs, if any
    lineage: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "order_intent"
        return d


@dataclass(frozen=True)
class BrokerOrderPreview:
    status: str                          # OK | UNAVAILABLE | REFUSED
    estimated_cost: float | None = None
    estimated_fees: float | None = None
    buying_power_effect: float | None = None
    warnings: tuple = ()
    raw_detail: str = ""


@dataclass(frozen=True)
class BrokerReviewResult:
    review: str                          # BrokerReview value
    preview: BrokerOrderPreview | None = None
    reasons: tuple = ()

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "broker_review"
        return d


@dataclass(frozen=True)
class ExecutionReadinessResult:
    state: str                           # ReadinessState value
    intent: dict | None
    reasons: tuple
    kill_chain: dict
    broker_review: dict | None
    live_placement: str = "SEALED"
    authorization_power: str = "NONE_ERD1"
    version: str = field(default=CONTRACTS_VERSION)

    def __post_init__(self):
        if self.live_placement != "SEALED":
            raise ValueError("CONSTITUTIONAL: live placement is sealed in "
                             "ERD-1; this field may not be altered")
        if self.state not in {s.value for s in ReadinessState}:
            raise ValueError(f"undeclared readiness state {self.state!r}")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "execution_readiness"
        return d
