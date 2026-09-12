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

import math
import time
from datetime import datetime

from apex.options_pilot.clock import Clock, to_utc_string
from apex.options_pilot.fees import SYNTHETIC_FEES, UNVERIFIED_FEES
from apex.options_pilot.risk_authority import CertifiedRiskAuthority

from .ingest import BarStore
from .inference import default_artifact
from .providers import AlpacaBarsAdapter, LiveGate, ProviderUnavailable, SyntheticBarProvider, ThetaChainAdapter, load_bars
from .snapshot import compose, usable_value

DIRECTION_RULE = "HEURISTIC_DIRECTION_V1: LONG if ret_15 > 0, SHORT if ret_15 < 0, None otherwise; not a forecast"


SELECTION_POLICIES = ("PILOT_RULE_V1", "FULL_FUNNEL_V1", "JOINT_FUNNEL_V1")


class TwinSources:
    def __init__(self, *, provenance: str, clock: Clock, bar_source, chain_fn, quote_fn, exit_quote_fn,
                 fee_schedule, sleep_fn=time.sleep, book_fn=None, warmup_minutes: int = 65, artifact=None,
                 selection_policy: str = "PILOT_RULE_V1", funnel_engine=None, funnel_history_days: int = 7,
                 joint_engine=None, joint_context_fn=None):
        if selection_policy not in SELECTION_POLICIES:
            raise ValueError("SELECTION_POLICY_UNKNOWN: %r" % (selection_policy,))
        self.selection_policy = selection_policy
        self.funnel_engine = funnel_engine
        if selection_policy == "FULL_FUNNEL_V1" and self.funnel_engine is None:
            from apex.decision_wb.engine import FunnelEngine
            self.funnel_engine = FunnelEngine()
        self.funnel_history_days = funnel_history_days
        # JOINT_FUNNEL_V1 (R4) is selection-BY-NAME and needs its engine and its market-state context supplied
        self.joint_engine, self.joint_context_fn = joint_engine, joint_context_fn
        if selection_policy == "JOINT_FUNNEL_V1" and (joint_engine is None or joint_context_fn is None):
            raise ValueError("JOINT_FUNNEL_V1 requires joint_engine and joint_context_fn (R4 contract 902256e3)")
        self._funnel_fitted_day: dict = {}
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
        # under either funnel the heuristic label is NOT the selector: it is recorded on the trace, not on the forecast
        signal = None if self.selection_policy in ("FULL_FUNNEL_V1", "JOINT_FUNNEL_V1") else self.signal_fn(symbol, as_of, snap)
        return self.artifact.forecast(snap, created_epoch=self.clock.now(), direction_signal=signal)

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

    # ------------------------------------------------------------ THE FUNNEL (FULL_FUNNEL_V1): every layer decides together
    def _fit_funnel_for_day(self, symbol: str, day_start: float, day: str) -> dict:
        st = self.store(symbol)
        hist = self.bar_source.bars(symbol, start_epoch=day_start - self.funnel_history_days * 86400.0, end_epoch=day_start)
        load_bars(st, hist)
        rows = returns_rows(st.bars_available_by(day_start))            # strictly prior to the session day
        info = self.funnel_engine.fit(rows, cutoff_epoch=day_start, label="%s %s" % (symbol, day))
        self._funnel_fitted_day[symbol] = day
        return info

    def _funnel_quotes(self, symbol: str, as_of: float, spot, chain: list) -> dict:
        """Indicative quotes for the engine: chain entries carrying bid+ask are used as-is; the eligible set around ATM at the
        first expiry with DTE >= 21 is completed through the quote provider (INDICATIVE: the fill happens after the intent)."""
        from apex.decision_wb.engine import DTE_MIN_DAYS
        from datetime import date
        quotes = {}
        for c in chain:
            key = (c["expiration"], float(c["strike"]), c["right"])
            if _num(c.get("bid")) and _num(c.get("ask")):
                # fields are carried AS RECEIVED: a missing timestamp or size stays missing and the engine's validator rejects the quote
                quotes[key] = {k2: c[k2] for k2 in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch") if k2 in c}
                quotes[key].update(indicative=True, source="CHAIN")
        today = date.fromisoformat(to_utc_string(as_of)[:10])
        exps = sorted({c["expiration"] for c in chain if (date.fromisoformat(c["expiration"]) - today).days >= DTE_MIN_DAYS})
        if not exps or not _num(spot):
            return quotes
        exp = exps[0]
        strikes = sorted({float(c["strike"]) for c in chain if c["expiration"] == exp})
        atm = min(strikes, key=lambda k: (abs(k - spot), k)); i = strikes.index(atm); k_side = self.funnel_engine.k_side
        for k in strikes[max(0, i - k_side): i + k_side + 1]:
            for right in ("CALL", "PUT"):
                key = (exp, k, right)
                if key in quotes or not any(c["expiration"] == exp and float(c["strike"]) == k and c["right"] == right for c in chain):
                    continue
                try:
                    q = self._quote_fn({"symbol": symbol, "expiration": exp, "strike": k, "right": right})
                except Exception as e:                                     # noqa: BLE001 - a missing indicative quote is a rejected candidate, not a crash
                    quotes[key] = {"indicative": True, "source": "QUOTE_FAILED: %s" % type(e).__name__}       # no fields -> validator rejects it
                    continue
                if isinstance(q, dict):
                    quotes[key] = {k2: q[k2] for k2 in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch") if k2 in q}
                    quotes[key].update(indicative=True, source="QUOTE_PROVIDER")
        return quotes

    def funnel_fn(self, symbol: str, as_of: float, forecast: dict, book_summary: dict | None = None, **_ignored) -> dict:
        day = to_utc_string(as_of)[:10]
        day_start = datetime.fromisoformat(day + "T00:00:00+00:00").timestamp()
        if self._funnel_fitted_day.get(symbol) != day:
            self._fit_funnel_for_day(symbol, day_start, day)
        snap = self.last_snapshot.get(symbol) or self.snapshot(symbol, as_of)
        st = self.store(symbol)
        prefix = [r["ret_1"] for r in returns_rows([b for b in st.bars_available_by(as_of) if b["event_time"] >= day_start])]
        spot = usable_value(snap, "last_bar_close")
        chain = self._chain_fn(symbol, as_of)
        quotes = self._funnel_quotes(symbol, as_of, spot, chain)
        res = self.funnel_engine.decide(symbol=symbol, as_of=as_of, day=day, snapshot=snap, forecast=forecast, spot=spot, quotes=quotes,
                                        prefix_returns=prefix, fee_schedule=self.fee_schedule, book_summary=book_summary,
                                        heuristic_direction=self.signal_fn(symbol, as_of, snap))
        res["trace"]["inputs"] = {"n_quotes": len(quotes), "quote_sources": sorted({q["source"] for q in quotes.values()}), "prefix_bars": len(prefix),
                                  "history_days": self.funnel_history_days, "chain_size": len(chain)}
        res["engine"] = self.funnel_engine.describe()
        return res

    def joint_fn(self, symbol: str, as_of: float, forecast: dict, book_summary: dict | None = None,
                 certified_risk_fn=None, scan_id: str | None = None) -> dict:
        """R4 selection policy. The context callable supplies the market state and the variance inputs the
        contract requires; this object does not invent them."""
        ctx = self.joint_context_fn(symbol, as_of, forecast)
        res = self.joint_engine.decide(market_state=ctx["market_state"], variance_state=ctx["variance_state"],
                                       v_hat=ctx["v_hat"], nu=ctx.get("nu"), drift_per_bar=ctx.get("drift_per_bar", 0.0),
                                       fee_schedule=self.fee_schedule, book_summary=book_summary,
                                       scan_id=scan_id or ctx.get("scan_id") or "%s:%.0f" % (symbol, as_of),
                                       certified_risk_fn=certified_risk_fn, forecast=forecast)
        res["engine"] = self.joint_engine.describe()
        return res

    def sources(self) -> dict:
        out = {"forecast_fn": self.forecast_fn, "signal_fn": lambda s, t: self.signal_fn(s, t),
               "chain_fn": self.chain_fn, "spot_fn": self.spot_fn, "quote_fn": self._quote_fn, "exit_quote_fn": self._exit_quote_fn}
        if self.selection_policy == "FULL_FUNNEL_V1":
            out["funnel_fn"] = self.funnel_fn
        elif self.selection_policy == "JOINT_FUNNEL_V1":
            out["funnel_fn"] = self.joint_fn
        return out


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def returns_rows(bars: list) -> list:
    """Consecutive-minute log returns only: a gap (overnight, halt, missing bar) yields no return, so pooled fits never see a jump
    that is an artifact of the calendar. Rows carry event_time/available for the models' data firewall."""
    rows = []
    for a, b in zip(bars, bars[1:]):
        if b["event_time"] - a["event_time"] == 60.0 and a["close"] > 0 and b["close"] > 0:
            rows.append({"event_time": b["event_time"], "available": b["available"], "ret_1": math.log(b["close"] / a["close"])})
    return rows


def synthetic_twin_sources(*, clock: Clock, quote_fn, exit_quote_fn, chain_fn, sleep_fn, seed: int = 7, selection_policy: str = "PILOT_RULE_V1",
                           funnel_engine=None, joint_engine=None, joint_context_fn=None) -> TwinSources:
    return TwinSources(provenance="SYNTHETIC_FIXTURE", clock=clock, bar_source=SyntheticBarProvider(seed=seed), chain_fn=chain_fn,
                       quote_fn=quote_fn, exit_quote_fn=exit_quote_fn, fee_schedule=SYNTHETIC_FEES, sleep_fn=sleep_fn,
                       selection_policy=selection_policy, funnel_engine=funnel_engine,
                       joint_engine=joint_engine, joint_context_fn=joint_context_fn)


class _LiveBars:
    def __init__(self, adapter: AlpacaBarsAdapter):
        self.adapter = adapter
        self.provider = adapter.provider

    def bars(self, symbol, *, start_epoch, end_epoch):
        return self.adapter.bars(symbol, start_epoch=start_epoch, end_epoch=end_epoch)


def live_twin_sources(*, gate: LiveGate | None = None, http_get=None, headers_fn=None, selection_policy: str = "PILOT_RULE_V1") -> TwinSources:
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
                       book_fn=lambda s, t: alpaca.nbbo(s), selection_policy=selection_policy)
