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
from apex.options_pilot.fees import LIVE_DEFAULT_FEES, SYNTHETIC_FEES, UNVERIFIED_FEES
from apex.options_pilot.risk_authority import CertifiedRiskAuthority

from .ingest import BarStore
from .inference import default_artifact
from .providers import AlpacaBarsAdapter, LiveGate, ProviderUnavailable, SyntheticBarProvider, ThetaChainAdapter, load_bars
from .snapshot import compose, usable_value

DIRECTION_RULE = "HEURISTIC_DIRECTION_V1: LONG if ret_15 > 0, SHORT if ret_15 < 0, None otherwise; not a forecast"


SELECTION_POLICIES = ("PILOT_RULE_V1", "PILOT_RULE_V2", "FULL_FUNNEL_V1", "JOINT_FUNNEL_V1")
RULE_POLICIES = ("PILOT_RULE_V1", "PILOT_RULE_V2")            # deterministic expression rules; dispatched by name, never by default


class TwinSources:
    def __init__(self, *, provenance: str, clock: Clock, bar_source, chain_fn, quote_fn, exit_quote_fn,
                 fee_schedule, sleep_fn=time.sleep, book_fn=None, warmup_minutes: int = 65, artifact=None,
                 selection_policy: str = "PILOT_RULE_V2", funnel_engine=None, funnel_history_days: int = 7,
                 joint_engine=None, joint_context_fn=None, event_snapshot_fn=None, event_gate_authority: str = "SHADOW",
                 external_context_fn=None, external_context_max_age_s: float = 900.0,
                 premarket_root=None):
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
            raise ValueError("JOINT_FUNNEL_V1 requires joint_engine and joint_context_fn (R4 contract a0228fac, Amendment A1)")
        self._funnel_fitted_day: dict = {}
        self.last_chain_report: dict = {}
        # EVENT AWARENESS (Brick 2): factual context from the catalyst layer, joined into the same Twin the decision reads.
        # None -> the twin records the stream as NOT_WIRED (never silently "no events").
        self.event_snapshot_fn = event_snapshot_fn
        self.event_gate_authority = event_gate_authority
        self.last_event_context: dict = {}
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
        # EXTERNAL CONTEXT (TradingView): EXTERNAL_CONTEXT_ONLY, bound to the snapshot_id of the state the
        # decision is being made on. None -> the twin records NOT_WIRED, never silently "no external context".
        self.external_context_fn = external_context_fn
        self.external_context_max_age_s = float(external_context_max_age_s)
        self.last_external_context: dict = {}
        self.premarket_root = premarket_root

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
        from .premarket_context import read_context
        snap["premarket_context"] = read_context(root=self.premarket_root, symbol=symbol,
                                               as_of=as_of, snapshot_id=snap["snapshot_id"], clock=self.clock)
        self.last_snapshot[symbol] = snap
        return snap

    # ------------------------------------------------------------ the injected functions
    def forecast_fn(self, symbol: str, as_of: float) -> dict:
        snap = self.snapshot(symbol, as_of)
        # under either funnel the heuristic label is NOT the selector: it is recorded on the trace, not on the forecast
        signal = None if self.selection_policy in ("FULL_FUNNEL_V1", "JOINT_FUNNEL_V1") else self.signal_fn(symbol, as_of, snap)
        forecast = self.artifact.forecast(snap, created_epoch=self.clock.now(), direction_signal=signal)
        forecast["inputs"]["premarket_context"] = snap["premarket_context"]
        return forecast

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

    def event_context(self, symbol: str, as_of: float) -> dict:
        """The event snapshot at as_of plus the EVENT_GATE_V0 evaluation (shadow unless configured ACTIVE)."""
        from apex.catalyst.twin_snapshot import evaluate_gate
        if self.event_snapshot_fn is None:
            ctx = {"kind": "EVENT_SNAPSHOT_V1", "symbol": symbol, "as_of_epoch": as_of, "wired": False,
                   "scheduled": {"status": "UNAVAILABLE", "why": "event stream NOT_WIRED on this twin", "events": []},
                   "unscheduled": {"status": "UNAVAILABLE", "why": "event stream NOT_WIRED on this twin", "events": []},
                   "authority": "FACTUAL_CONTEXT_ONLY"}
        else:
            try:
                ctx = {**self.event_snapshot_fn(symbol=symbol, as_of=as_of), "wired": True}
            except Exception as e:                                             # noqa: BLE001 - a failing sense is reported, never silent
                ctx = {"kind": "EVENT_SNAPSHOT_V1", "symbol": symbol, "as_of_epoch": as_of, "wired": True,
                       "scheduled": {"status": "UNAVAILABLE", "why": "%s: %s" % (type(e).__name__, str(e)[:160]), "events": []},
                       "unscheduled": {"status": "UNAVAILABLE", "why": "%s: %s" % (type(e).__name__, str(e)[:160]), "events": []},
                       "authority": "FACTUAL_CONTEXT_ONLY"}
        ctx["gate"] = evaluate_gate(ctx, authority=self.event_gate_authority)
        self.last_event_context[symbol] = ctx
        return ctx

    def external_context(self, symbol: str, as_of: float) -> dict:
        """TradingView context for the state at `as_of`, bound to that state's `snapshot_id`.

        The snapshot is taken FIRST and the context is bound to its id, so the packet can never describe a
        different market state than the one the decision reads. This method never raises: every failure is a
        named status on a returned packet, because an eye that fails must report, not interrupt."""
        from apex.tradingview import context as TVC
        snap = self.last_snapshot.get(symbol) or self.snapshot(symbol, as_of)
        ctx = TVC.external_context(symbol=symbol, as_of=as_of, snapshot=snap,
                                   fetch_fn=self.external_context_fn,
                                   model_identities=self.model_identities(),
                                   max_age_s=self.external_context_max_age_s)
        self.last_external_context[symbol] = ctx
        return ctx

    def model_identities(self) -> dict:
        """WHICH models were in force. Unknown is stated, never omitted -- a decision whose model identity is
        unknown is a different thing from one made with no model."""
        a = self.artifact
        UNK = "UNAVAILABLE: the forecast artifact does not expose this identity"
        out = {"selection_policy": self.selection_policy}
        for key, attr in (("forecast_model_id", "model_id"), ("model_hash", "model_hash"),
                          ("params_hash", "params_hash"), ("artifact_digest", "artifact_digest")):
            v = getattr(a, attr, None)
            out[key] = UNK if v is None else v
        return out

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
        priced = [c for c in chain if _num_pos(c.get("bid")) is not None and _num_pos(c.get("ask")) is not None]
        kept, conflicts = apply_duplicate_policy(priced)                    # the SAME policy the provider boundary applies
        conflicted = set(conflicts) | set(getattr(chain, "conflicted", ()))
        for c in kept:
            key = (c["expiration"], float(c["strike"]), c["right"])
            # fields are carried AS RECEIVED: a missing timestamp or size stays missing and the engine's validator rejects the quote
            quotes[key] = {k2: c[k2] for k2 in ("bid", "ask", "bid_size", "ask_size", "timestamp_epoch") if k2 in c}
            quotes[key].update(indicative=True, source="CHAIN")
        for key in conflicted:
            quotes[key] = {"indicative": True, "source": "REJECTED: DUPLICATE_CONFLICT under %s" % DUPLICATE_POLICY_ID}   # no fields -> validator rejects it
        self.last_chain_report[symbol] = {**(chain.report() if hasattr(chain, "report") else {"n_rows": len(chain)}),
                                          "funnel_conflicts": sorted(map(str, conflicts))}
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
                if key in quotes or key in conflicted or not any(c["expiration"] == exp and float(c["strike"]) == k and c["right"] == right for c in chain):
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
                                  "history_days": self.funnel_history_days, "chain_size": len(chain),
                                  "chain_report": self.last_chain_report.get(symbol),
                                  "event_context": self.last_event_context.get(symbol) or self.event_context(symbol, as_of)}
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
               "chain_fn": self.chain_fn, "spot_fn": self.spot_fn, "quote_fn": self._quote_fn, "exit_quote_fn": self._exit_quote_fn,
               "event_context_fn": self.event_context}
        if self.selection_policy == "FULL_FUNNEL_V1":
            out["funnel_fn"] = self.funnel_fn
        elif self.selection_policy == "JOINT_FUNNEL_V1":
            out["funnel_fn"] = self.joint_fn
        return out


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _num_pos(x):
    return x if (isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0) else None


def returns_rows(bars: list) -> list:
    """Consecutive-minute log returns only: a gap (overnight, halt, missing bar) yields no return, so pooled fits never see a jump
    that is an artifact of the calendar. Rows carry event_time/available for the models' data firewall."""
    rows = []
    for a, b in zip(bars, bars[1:]):
        if b["event_time"] - a["event_time"] == 60.0 and a["close"] > 0 and b["close"] > 0:
            rows.append({"event_time": b["event_time"], "available": b["available"], "ret_1": math.log(b["close"] / a["close"])})
    return rows


def synthetic_twin_sources(*, clock: Clock, quote_fn, exit_quote_fn, chain_fn, sleep_fn, seed: int = 7, selection_policy: str = "PILOT_RULE_V2",
                           funnel_engine=None, joint_engine=None, joint_context_fn=None, premarket_root=None) -> TwinSources:
    return TwinSources(provenance="SYNTHETIC_FIXTURE", clock=clock, bar_source=SyntheticBarProvider(seed=seed), chain_fn=chain_fn,
                       quote_fn=quote_fn, exit_quote_fn=exit_quote_fn, fee_schedule=SYNTHETIC_FEES, sleep_fn=sleep_fn,
                       selection_policy=selection_policy, funnel_engine=funnel_engine,
                       joint_engine=joint_engine, joint_context_fn=joint_context_fn, premarket_root=premarket_root)


class _LiveBars:
    def __init__(self, adapter: AlpacaBarsAdapter):
        self.adapter = adapter
        self.provider = adapter.provider

    def bars(self, symbol, *, start_epoch, end_epoch):
        return self.adapter.bars(symbol, start_epoch=start_epoch, end_epoch=end_epoch)


RIGHT_ENCODINGS = {"C": "CALL", "CALL": "CALL", "P": "PUT", "PUT": "PUT"}          # declared; anything else is REFUSED, never guessed
INDICATIVE_MAX_AGE_S = 120.0                                                        # §1.1: indicative option quotes, 120 s


class ChainRows(list):
    """A list of VALID normalised chain rows plus the exclusions that produced it. Nothing is repaired: a row that
    fails any check is excluded with a named reason and the reason is recorded (provider boundary). `conflicted`
    holds the contract keys excluded under DUPLICATE_POLICY_V1 so no consumer can re-admit them from this snapshot."""

    def __init__(self, rows=(), exclusions=None, conflicted=None):
        super().__init__(rows)
        self.exclusions = list(exclusions or [])
        self.conflicted = set(conflicted or ())

    def report(self) -> dict:
        return {"n_rows": len(self), "n_excluded": len(self.exclusions), "n_conflicted_contracts": len(self.conflicted),
                "exclusion_reasons": sorted({x["why"].split(":")[0] for x in self.exclusions}), "duplicate_policy": DUPLICATE_POLICY_ID}


def _finite_float(x):
    """A finite float from a vendor string or number; bools, NaN, inf, and unparsable input are None."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, str):
        t = x.strip().lower()
        if t in ("", "nan", "inf", "+inf", "-inf", "infinity", "-infinity"):
            return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _size_int(x):
    """A non-negative integer size. Digits only (a vendor sends "58"); bools, fractions, negatives, floats REFUSED."""
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, int):
        return x if x >= 0 else None
    if isinstance(x, str) and x.strip().isdigit():
        return int(x.strip())
    return None


def _norm_exp(e) -> str | None:
    if e is None:
        return None
    e = str(e).strip()
    if len(e) == 8 and e.isdigit():
        e = "%s-%s-%s" % (e[:4], e[4:6], e[6:8])
    try:
        from datetime import date
        date.fromisoformat(e)
    except ValueError:
        return None
    return e


def live_chain_rows(rows: list, *, symbol: str, receipt_time: float) -> ChainRows:
    """Normalise options-feed snapshot rows (strings, as the vendor sends them) into the shapes the pilot's validators
    accept. PROVIDER BOUNDARY VALIDATION: only declared right encodings; finite positive strike and ask; finite
    non-negative bid with ask >= bid; digit-only non-negative integer sizes; a parseable provider timestamp that is not
    in the future of the receipt clock and not older than the indicative limit. A row failing any check is EXCLUDED
    with a named reason, never repaired, and the exclusion is carried on the returned ChainRows."""
    out, excl = [], []
    for i, r in enumerate(rows):
        why = None
        right = RIGHT_ENCODINGS.get(str(r.get("right", "")).strip().upper()) if r.get("right") is not None else None
        exp = _norm_exp(r.get("expiration"))
        k = _finite_float(r.get("strike")); bid = _finite_float(r.get("bid")); ask = _finite_float(r.get("ask"))
        bs = _size_int(r.get("bid_size")); as_ = _size_int(r.get("ask_size"))
        ts = r.get("timestamp")
        ts_epoch = None
        if ts is not None:
            try:
                ts_epoch = ThetaChainAdapter.et_naive_to_epoch(str(ts))
            except (ValueError, TypeError):
                ts_epoch = None
        if right is None: why = "RIGHT_NOT_DECLARED: %r" % (r.get("right"),)
        elif exp is None: why = "EXPIRATION_INVALID: %r" % (r.get("expiration"),)
        elif k is None or k <= 0: why = "STRIKE_INVALID: %r" % (r.get("strike"),)
        elif ask is None or ask <= 0: why = "ASK_INVALID: %r" % (r.get("ask"),)
        elif bid is None or bid < 0: why = "BID_INVALID: %r" % (r.get("bid"),)
        elif ask < bid: why = "QUOTE_CROSSED: bid %r > ask %r" % (bid, ask)
        elif bs is None or as_ is None: why = "SIZE_INVALID: bid_size %r ask_size %r" % (r.get("bid_size"), r.get("ask_size"))
        elif ts_epoch is None: why = "TIMESTAMP_INVALID: %r" % (ts,)
        elif ts_epoch > receipt_time: why = "QUOTE_FROM_THE_FUTURE: %.3fs after receipt" % (ts_epoch - receipt_time)
        elif receipt_time - ts_epoch > INDICATIVE_MAX_AGE_S: why = "INDICATIVE_STALE: %.1fs > %.0fs" % (receipt_time - ts_epoch, INDICATIVE_MAX_AGE_S)
        if why:
            excl.append({"row": i, "why": why, "strike": r.get("strike"), "right": r.get("right"), "expiration": r.get("expiration")})
            continue
        out.append({"symbol": symbol, "expiration": exp, "strike": k, "right": right, "bid": bid, "ask": ask, "bid_size": bs, "ask_size": as_,
                    "timestamp_epoch": ts_epoch, "timestamp_raw": ts, "receipt_time": receipt_time, "provider": "THETADATA_V3", "indicative": True,
                    "source_row": i})
    rows_out, conflicts = apply_duplicate_policy(out)
    for key in sorted(conflicts):
        excl.append({"row": None, "why": "DUPLICATE_CONFLICT: contract %s|%s|%s observed with different quotes in one snapshot; excluded, "
                                         "never resolved by arrival order or best price" % key,
                     "strike": key[1], "right": key[2], "expiration": key[0], "observations": conflicts[key]})
    return ChainRows(rows_out, excl, conflicted=set(conflicts))


DUPLICATE_POLICY_ID = "DUPLICATE_POLICY_V1"
DUPLICATE_POLICY = ("DUPLICATE_POLICY_V1: within one snapshot, rows with the same contract identity (expiration, strike, right) and "
                    "identical observation (bid, ask, bid_size, ask_size, timestamp) collapse to one row; rows with the same identity "
                    "and DIFFERENT observations are a CONFLICT: the contract is excluded from the snapshot with a named exclusion "
                    "carrying every observation, and no consumer (selector, funnel pricing, entry/exit quote) may re-admit it from "
                    "the same snapshot. Nothing chooses the best price and nothing chooses by order.")


def contract_key(r: dict) -> tuple:
    return (str(r.get("expiration")), float(r.get("strike")), str(r.get("right")))


def apply_duplicate_policy(rows: list) -> tuple:
    """Returns (rows_without_conflicts, {key: [observations...]}) under DUPLICATE_POLICY_V1. Order-independent."""
    seen, obs_by = {}, {}
    for r in rows:
        key = contract_key(r)
        obs = (r.get("bid"), r.get("ask"), r.get("bid_size"), r.get("ask_size"), r.get("timestamp_epoch"))
        obs_by.setdefault(key, []).append({"bid": obs[0], "ask": obs[1], "bid_size": obs[2], "ask_size": obs[3], "timestamp_epoch": obs[4],
                                           "source_row": r.get("source_row")})
        seen.setdefault(key, set()).add(obs)
    conflicts = {k: obs_by[k] for k, v in seen.items() if len(v) > 1}
    kept, emitted = [], set()
    for r in rows:
        key = contract_key(r)
        if key in conflicts or key in emitted:
            continue
        emitted.add(key); kept.append(r)
    return kept, conflicts


def live_twin_sources(*, gate: LiveGate | None = None, http_get=None, headers_fn=None, selection_policy: str = "PILOT_RULE_V2",
                      expirations_fn=None, chain_snapshot_fn=None, clock=None, joint_engine=None, joint_context_fn=None,
                      funnel_engine=None, fee_schedule=None, event_snapshot_fn=None, event_gate_authority: str = "SHADOW",
                      premarket_root=None) -> TwinSources:
    """LIVE_FEED sources. Connectivity is gated: with the default environment every provider call raises
    ProviderUnavailable before any network access, and the boundary persists the refusal.

    COMMISSIONED 2026-09-11 (operator-authorized, read-only): `chain_fn` and `quote_fn` are wired to the same
    options-feed adapters the pilot collector used on 2026-09-11 (`apex.intraday.options_feed.option_expirations` /
    `option_chain_snapshot`), injectable for tests. There is NO order path here. The fee schedule stays
    UNVERIFIED_FEES, so the certified authority keeps refusing every LIVE_FEED intent until the operator authorizes
    the broker's published fee document; nothing here stubs, mocks or defaults a fee number."""
    gate = gate or LiveGate()
    clock = clock or Clock(time.time)

    def _no_http(url, headers=None):
        raise ProviderUnavailable("HTTP_CLIENT_NOT_WIRED: no live HTTP client is attached in this build; %s not contacted" % url.split("?")[0])

    http_get = http_get or _no_http
    headers_fn = headers_fn or (lambda: {})
    alpaca = AlpacaBarsAdapter(gate=gate, http_get=http_get, headers_fn=headers_fn)

    def _default_expirations(symbol):
        from apex.intraday import options_feed as OF
        return OF.option_expirations(symbol)

    def _default_snapshot(symbol, expiration):
        from apex.intraday import options_feed as OF
        return OF.option_chain_snapshot(symbol, expiration)

    expirations_fn = expirations_fn or _default_expirations
    chain_snapshot_fn = chain_snapshot_fn or _default_snapshot

    def _first_eligible_expiry(symbol, as_of):
        from apex.options_pilot.expression_rule import DTE_MIN_DAYS
        from datetime import date
        today = date.fromisoformat(to_utc_string(as_of)[:10])
        exps = sorted(_norm_exp(e) for e in expirations_fn(symbol))
        for e in exps:
            if (date.fromisoformat(e) - today).days >= DTE_MIN_DAYS:
                return e
        raise ProviderUnavailable("NO_ELIGIBLE_EXPIRY_LISTED: none with DTE >= %d among %s" % (DTE_MIN_DAYS, exps[:4]))

    def chain_fn(symbol, as_of):
        gate.require("ThetaData chain")
        exp = _first_eligible_expiry(symbol, as_of)
        rows = live_chain_rows(chain_snapshot_fn(symbol, exp), symbol=symbol, receipt_time=clock.now())
        if not rows:
            raise ProviderUnavailable("CHAIN_EMPTY: %s %s returned no valid rows (%d excluded: %s)"
                                      % (symbol, exp, len(rows.exclusions), sorted({x["why"].split(":")[0] for x in rows.exclusions})[:4]))
        return rows

    def quote_fn(contract):
        gate.require("ThetaData quote")
        rows = live_chain_rows(chain_snapshot_fn(contract["symbol"], contract["expiration"]), symbol=contract["symbol"], receipt_time=clock.now())
        want = (_norm_exp(contract["expiration"]), float(contract["strike"]), contract["right"])
        if want in rows.conflicted:
            raise ProviderUnavailable("QUOTE_CONFLICTED_IN_SNAPSHOT: %s %s %s %s excluded under %s; not re-admitted" % (contract["symbol"], *want, DUPLICATE_POLICY_ID))
        matches = [r for r in rows if (r["expiration"], r["strike"], r["right"]) == want]
        if len(matches) == 1:
            return {**matches[0], "chain_report": rows.report()}
        if not matches:
            raise ProviderUnavailable("QUOTE_NOT_IN_SNAPSHOT: %s %s %s %s (%s)" % (contract["symbol"], *want, rows.report()))
        raise ProviderUnavailable("QUOTE_AMBIGUOUS: %d rows for %s after the duplicate policy; refused" % (len(matches), want))

    return TwinSources(provenance="LIVE_FEED", clock=clock, bar_source=_LiveBars(alpaca), chain_fn=chain_fn,
                       quote_fn=quote_fn, exit_quote_fn=quote_fn, fee_schedule=(fee_schedule or LIVE_DEFAULT_FEES), sleep_fn=time.sleep,
                       book_fn=lambda s, t: alpaca.nbbo(s), selection_policy=selection_policy,
                       joint_engine=joint_engine, joint_context_fn=joint_context_fn, funnel_engine=funnel_engine,
                       event_snapshot_fn=event_snapshot_fn, event_gate_authority=event_gate_authority,
                       premarket_root=premarket_root)
