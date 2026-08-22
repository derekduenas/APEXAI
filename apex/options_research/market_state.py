"""OptionMarketState — F O5: one option contract's observed state at a
moment. Every Greek/IV/OI/spread field is `None` when the source did
not provide it -- NEVER 0. Strike/expiry/call_put are parsed from the
OCC-standard contract symbol (deterministic, no reference-endpoint
dependency), since the credential this build has access to cannot
reach a dedicated contract-reference endpoint (see the architecture
map's CURRENT DATA AVAILABILITY section).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from apex.options_research import OPTIONS_RESEARCH_POWER

# OCC symbol: ROOT (1-6 chars) + YYMMDD + C/P + strike*1000 (8 digits)
_OCC_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


class OptionMarketStateError(RuntimeError):
    pass


def parse_occ_symbol(option_symbol: str) -> dict:
    """Deterministic parse -- no network, no guess. Raises on a symbol
    that does not match the OCC standard shape."""
    m = _OCC_RE.match(option_symbol)
    if not m:
        raise OptionMarketStateError(f"not an OCC-shaped symbol: {option_symbol!r}")
    root, yymmdd, cp, strike8 = m.groups()
    expiration = f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
    strike = int(strike8) / 1000.0
    return {"root": root, "expiration": expiration,
           "call_put": "CALL" if cp == "C" else "PUT", "strike": strike}


@dataclass(frozen=True)
class OptionMarketState:
    symbol: str
    underlying_price: float | None
    contract_id: str
    option_symbol: str
    call_put: str
    strike: float
    expiration: str
    dte: int | None

    bid: float | None
    ask: float | None
    bid_size: int | None
    ask_size: int | None
    mid: float | None

    last_trade: float | None
    last_trade_size: int | None

    volume: int | None
    open_interest: int | None

    implied_volatility: float | None

    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    rho: float | None

    quote_time: str | None
    trade_time: str | None
    event_time: str
    known_from: str
    as_of: str

    source: str
    provider: str
    data_quality: str
    staleness_s: float | None
    schema_version: str = "OPTION_MARKET_SCHEMA_V1"
    decision_power: str = OPTIONS_RESEARCH_POWER

    def __post_init__(self):
        if self.call_put not in ("CALL", "PUT"):
            raise OptionMarketStateError(f"bad call_put {self.call_put!r}")

    def as_record(self) -> dict:
        return {"kind": "option_market_state", **asdict(self)}


def from_alpaca_snapshot(option_symbol: str, snapshot: dict, *, underlying_price,
                         now, known_from, event_time=None) -> OptionMarketState:
    """`snapshot`: one entry of Alpaca's /v1beta1/options/snapshots/{symbol}
    response, e.g. snapshot["AAPL260819C00210000"].

    CORRECTED 2026-08-18 (live runtime build): an earlier same-session
    check (3 contracts) concluded Alpaca never carries Greeks/IV. A
    broader live check (100-contract AAPL chain) found `greeks`
    (delta/gamma/theta/vega/rho) and `impliedVolatility` present for
    41/100 contracts -- specifically the actively-quoted ones (real
    bid/ask, recent trades); the 59 illiquid/stale-quote contracts
    genuinely omit both. This adapter reads them when present and
    stays honestly None when absent -- it never assumes either state
    from the earlier, narrower finding."""
    import pandas as pd
    parsed = parse_occ_symbol(option_symbol)
    now = pd.Timestamp(now)
    exp = pd.Timestamp(parsed["expiration"]).tz_localize(now.tzinfo)
    dte = (exp.normalize() - now.normalize()).days

    q = snapshot.get("latestQuote") or {}
    t = snapshot.get("latestTrade") or {}
    g = snapshot.get("greeks") or {}
    bid, ask = q.get("bp"), q.get("ap")
    mid = (bid + ask) / 2 if (bid is not None and ask is not None) else None
    quote_time = q.get("t")
    staleness = None
    if quote_time:
        staleness = (now - pd.Timestamp(quote_time)).total_seconds()

    et = pd.Timestamp(event_time) if event_time is not None else (
        pd.Timestamp(quote_time) if quote_time else now)

    return OptionMarketState(
        symbol=parsed["root"], underlying_price=underlying_price,
        contract_id=option_symbol, option_symbol=option_symbol,
        call_put=parsed["call_put"], strike=parsed["strike"],
        expiration=parsed["expiration"], dte=dte,
        bid=bid, ask=ask, bid_size=q.get("bs"), ask_size=q.get("as"), mid=mid,
        last_trade=t.get("p"), last_trade_size=t.get("s"),
        volume=None, open_interest=None,       # not in this payload -- honest None
        implied_volatility=snapshot.get("impliedVolatility"),
        delta=g.get("delta"), gamma=g.get("gamma"), theta=g.get("theta"), vega=g.get("vega"),
        rho=g.get("rho"),
        quote_time=quote_time, trade_time=t.get("t"), event_time=str(et),
        known_from=str(pd.Timestamp(known_from)), as_of=str(now),
        source="ALPACA_WEBSOCKET_SIP_V1", provider="ALPACA",
        data_quality=("FULL" if bid is not None and ask is not None else "PARTIAL"),
        staleness_s=staleness)
