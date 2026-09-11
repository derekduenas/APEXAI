"""TWIN-BACKED SOURCES for the pilot entry point (M2).

One object supplies the boundary's injected functions from a BarStore + snapshot + frozen
artifact, for BOTH provenances:
    SYNTHETIC_FIXTURE   bars from SyntheticBarProvider, quotes from the synthetic quote fixture,
                        risk = certified authority + SYNTHETIC fee schedule
    LIVE_FEED           bars/NBBO from AlpacaBarsAdapter, chain from ThetaChainAdapter, both
                        behind LiveGate (disabled by default -> ProviderUnavailable -> the scan
                        REFUSES with a persisted reason); fee schedule UNVERIFIED -> intents refuse

The direction label stays a HEURISTIC: sign of ret_15 when VALID, else None (the rule then
refuses NO_DIRECTION_SIGNAL). It is recorded on the forecast as `direction_signal` and is not
part of the distribution."""
from __future__ import annotations

import time

from apex.options_pilot.clock import Clock
from apex.options_pilot.fees import SYNTHETIC_FEES, UNVERIFIED_FEES
from apex.options_pilot.risk_authority import CertifiedRiskAuthority

from .ingest import BarStore
from .inference import default_artifact
from .providers import AlpacaBarsAdapter, LiveGate, ProviderUnavailable, SyntheticBarProvider, ThetaChainAdapter, load_bars
from .snapshot import compose, usable_value

DIRECTION_RULE = "HEURISTIC_DIRECTION_V1: LONG if ret_15 > 0, SHORT if ret_15 < 0, None otherwise; not a forecast"


class TwinSources:
    def __init__(self, *, provenance: str, clock: Clock, bar_source, chain_fn, quote_fn, exit_quote_fn,
                 fee_schedule, sleep_fn=time.sleep, book_fn=None, warmup_minutes: int = 65, artifact=None):
        self.provenance = provenance
        self.clock = clock
        self.bar_source = bar_source
        self._chain_fn, self._quote_fn, self._exit_quote_fn, self._book_fn = chain_fn, quote_fn, exit_quote_fn, book_fn
        self.fee_schedule = fee_schedule
        self.sleep_fn = sleep_fn
        self.warmup_minutes = warmup_minutes
        self.artifact = artifact or default_artifact()
        self.risk_authority = CertifiedRiskAuthority(fee_schedule=fee_schedule, provenance=provenance)
        self.stores: dict = {}
        self.last_snapshot: dict = {}

    # ------------------------------------------------------------ state
    def store(self, symbol: str) -> BarStore:
        if symbol not in self.stores:
            self.stores[symbol] = BarStore(symbol, source=getattr(self.bar_source, "provider", "bars"))
        return self.stores[symbol]

    def snapshot(self, symbol: str, as_of: float) -> dict:
        st = self.store(symbol)
        bars = self.bar_source.bars(symbol, start_epoch=as_of - self.warmup_minutes * 60, end_epoch=as_of)
        load_bars(st, bars)
        book = self._book_fn(symbol, as_of) if self._book_fn else None
        snap = compose(symbol=symbol, as_of=as_of, bars=st.bars_available_by(as_of), source=st.source, book=book)
        self.last_snapshot[symbol] = snap
        return snap

    # ------------------------------------------------------------ the injected functions
    def forecast_fn(self, symbol: str, as_of: float) -> dict:
        snap = self.snapshot(symbol, as_of)
        return self.artifact.forecast(snap, created_epoch=self.clock.now(), direction_signal=self.signal_fn(symbol, as_of, snap))

    def signal_fn(self, symbol: str, as_of: float, snap: dict | None = None):
        snap = snap or self.last_snapshot.get(symbol) or self.snapshot(symbol, as_of)
        r15 = usable_value(snap, "ret_15")
        if r15 is None or r15 == 0:
            return None
        return "LONG" if r15 > 0 else "SHORT"

    def spot_fn(self, symbol: str, as_of: float):
        snap = self.last_snapshot.get(symbol) or self.snapshot(symbol, as_of)
        return usable_value(snap, "last_bar_close")

    def chain_fn(self, symbol: str, as_of: float):
        return self._chain_fn(symbol, as_of)

    def sources(self) -> dict:
        return {"forecast_fn": self.forecast_fn, "signal_fn": lambda s, t: self.signal_fn(s, t),
                "chain_fn": self.chain_fn, "spot_fn": self.spot_fn, "quote_fn": self._quote_fn, "exit_quote_fn": self._exit_quote_fn}


def synthetic_twin_sources(*, clock: Clock, quote_fn, exit_quote_fn, chain_fn, sleep_fn, seed: int = 7) -> TwinSources:
    return TwinSources(provenance="SYNTHETIC_FIXTURE", clock=clock, bar_source=SyntheticBarProvider(seed=seed), chain_fn=chain_fn,
                       quote_fn=quote_fn, exit_quote_fn=exit_quote_fn, fee_schedule=SYNTHETIC_FEES, sleep_fn=sleep_fn)


class _LiveBars:
    def __init__(self, adapter: AlpacaBarsAdapter):
        self.adapter = adapter
        self.provider = adapter.provider

    def bars(self, symbol, *, start_epoch, end_epoch):
        return self.adapter.bars(symbol, start_epoch=start_epoch, end_epoch=end_epoch)


def live_twin_sources(*, gate: LiveGate | None = None, http_get=None, headers_fn=None) -> TwinSources:
    """LIVE_FEED sources. Connectivity is gated: with the default environment every provider call raises
    ProviderUnavailable before any network access, and the boundary persists the refusal."""
    gate = gate or LiveGate()

    def _no_http(url, headers=None):
        raise ProviderUnavailable("HTTP_CLIENT_NOT_WIRED: no live HTTP client is attached in this build; %s not contacted" % url.split("?")[0])

    http_get = http_get or _no_http
    headers_fn = headers_fn or (lambda: {})
    alpaca = AlpacaBarsAdapter(gate=gate, http_get=http_get, headers_fn=headers_fn)
    theta = ThetaChainAdapter(gate=gate, http_get=http_get)

    def chain_fn(symbol, as_of):
        gate.require("ThetaData chain")
        raise ProviderUnavailable("CHAIN_ADAPTER_NOT_COMMISSIONED: expiration listing + chain snapshot parsing exist; the read-only smoke is not authorized yet")

    def quote_fn(contract):
        gate.require("ThetaData quote")
        raise ProviderUnavailable("QUOTE_ADAPTER_NOT_COMMISSIONED")

    return TwinSources(provenance="LIVE_FEED", clock=Clock(time.time), bar_source=_LiveBars(alpaca), chain_fn=chain_fn,
                       quote_fn=quote_fn, exit_quote_fn=quote_fn, fee_schedule=UNVERIFIED_FEES, sleep_fn=time.sleep,
                       book_fn=lambda s, t: alpaca.nbbo(s))
