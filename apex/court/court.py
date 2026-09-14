"""THE COURT — drive the REAL connected path and emit a receipt per layer.

WHAT IS REAL HERE: the entry point's lifecycle scheduler, TwinSources, the FunnelEngine and its models, the
expression rule, the Boundary, the CertifiedRiskAuthority, the ledger, the Book and the exit policy.

WHAT IS SUBSTITUTED, and nothing else: synthetic bars, a controlled clock, synthetic quote/chain adapters, and an
explicitly synthetic fee authorization fixture.

INSTRUMENTATION IS NOT STUBBING. The court wraps the provider callables the production code ALREADY takes by
injection, records what went in and came out, and passes the real value through untouched. It never supplies a
model output, a selection, a risk approval or a Book reconciliation."""
from __future__ import annotations

import json
import pathlib
import time

from apex.options_pilot import exit_policy as EP
from apex.options_pilot import ledger as L
from apex.options_pilot import lifecycle as LC
from apex.options_pilot.fees import AUTHORIZED, FeeAuthorization, FeeSchedule, ROBINHOOD_RHF_2026
from apex.options_pilot.synthetic_harness import SyntheticHarness
from apex.court import receipt as R
from apex.court import world as W


def synthetic_fee_authorization() -> FeeSchedule:
    """A COURT FIXTURE. Explicitly synthetic provenance, so it can never be the live default and never functions
    as an operational authorization: `requires_authorization` is False for a SYNTHETIC_FIXTURE schedule, and the
    live default remains UNVERIFIED_FEES untouched."""
    return FeeSchedule(**{**ROBINHOOD_RHF_2026.__dict__, "provenance": "SYNTHETIC_FIXTURE",
                          "schedule_id": "COURT_SYNTHETIC_FEES", "authorization": None,
                          "note": "COURT FIXTURE. Synthetic provenance. Never a live default, never an authorization."})


class Court:
    def __init__(self, *, run_id: str, world: str, policy: str = "PILOT_RULE_V2", out_root="results/court",
                 t0: float = 1_789_000_020.0, n_bars: int = 40):
        self.run_id, self.world_name, self.policy = run_id, world, policy
        self.w = dict(W.WORLDS[world])
        self.t0, self.n_bars = t0, n_bars
        self.log = R.ReceiptLog(run_id=run_id)
        self.dir = pathlib.Path(out_root) / run_id
        if self.dir.exists():
            raise RuntimeError("RUN_DIR_EXISTS: %s -- run directories are never overwritten" % self.dir)
        self.dir.mkdir(parents=True)
        self.notes: list = []

    # ------------------------------------------------------------------ the run
    def run(self, *, arrivals=None, hung_context=False, no_exit_quote=False, break_input=None) -> dict:
        h = SyntheticHarness(self.dir / "ledger.jsonl", session_id=self.run_id, t0=self.t0, risk="certified",
                             fee_schedule=synthetic_fee_authorization())
        h.chain = [{**c, "ask": self.w["chain_ask"]} for c in h.chain]
        h.quotes.bid, h.quotes.ask = self.w["quote"]
        h.exit_quotes.bid, h.exit_quotes.ask = self.w["exit_quote"]
        lc = LC.MonotonicClock(h.now()); h.clock = lc.clock(); h.bd.clock = h.clock
        h.now, h.advance = lc.now, lc.sleep
        h.bd.exit_policy = EP.EXIT_POLICY_V2

        bars = W.bars(n=self.n_bars, end_epoch=self.t0, drift_bp_per_bar=self.w["drift_bp_per_bar"],
                      vol_bp_per_bar=self.w["vol_bp_per_bar"])
        self._receipt_data(bars, break_input)

        src = dict(h.sources())
        src["forecast_fn"] = self._wrap_forecast(h, bars, break_input)
        src["chain_fn"] = self._wrap("CHAIN", "chain_fn", src["chain_fn"])
        src["spot_fn"] = self._wrap("TWIN_SPOT", "spot_fn", src["spot_fn"])
        src["external_context_fn"] = self._external(hung_context)

        feed = None
        if arrivals is not None:
            from tests.test_exit_scheduling_002 import Feed
            feed = Feed(h, arrivals=list(arrivals), quote_lag_s=0.1,
                        bid=self.w["exit_quote"][0], ask=self.w["exit_quote"][1])
            src["exit_quote_fn"] = feed
        if no_exit_quote:
            def refuse_quote(*a, **k):
                raise RuntimeError("NO_EXECUTABLE_EXIT_QUOTE: the court's world supplies none")
            src["exit_quote_fn"] = refuse_quote

        runner = LC.LifecycleRunner(boundary=h.bd, sources=src, clock=lc, symbols=["SPY"],
                                    selection_policy=self.policy, scan_epochs=[self.t0],
                                    observation_feed=(feed.feed_for("SPY|2026-10-09|650.0|CALL") if feed else None))
        report = runner.run()
        rows = L.read_all(h.bd.ledger)
        self._receipt_persisted(rows)
        consumption = self.log.discover_consumption(rows)
        out = {"run_id": self.run_id, "world": self.world_name, "policy": self.policy,
               "declared_world": {**W.DECLARED, **self.w},
               "fixture_revisions": self.notes,
               "decision": (report.get("decisions") or [{}])[0].get("decision"),
               "why": (report.get("decisions") or [{}])[0].get("why"),
               "consumption": consumption, "receipts": self.log.receipts,
               "ledger_kinds": {k: len([r for r in rows if r.get("kind") == k])
                                for k in sorted({r.get("kind") for r in rows})},
               "lifecycle_report": {k: report.get(k) for k in ("n_events", "decisions", "exits")},
               "verdict_limits": R.LIMITS}
        (self.dir / "court_run.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
        return out

    # ------------------------------------------------------------------ receipts
    def _receipt_data(self, bars, break_input):
        bad = break_input == "FUTURE_BAR"
        rows = list(bars)
        if bad:
            rows = rows + [{**rows[-1], "event_time": self.t0 + 600.0, "available": self.t0 + 660.0}]
            self.notes.append("break_input=FUTURE_BAR: one bar available AFTER as_of was injected deliberately")
        ok = all(b["available"] <= self.t0 for b in rows)
        self.log.emit(layer="REALITY_DATA", operation="synthetic bar generation + availability validation",
                      code_identity=W.RECIPE, available=R.AVAILABLE if rows else R.UNAVAILABLE,
                      executed=R.EXECUTED, valid=R.VALID if ok else R.INVALID,
                      why_invalid=None if ok else "BAR_AVAILABLE_AFTER_AS_OF",
                      inputs=[{"id": "seed", "digest": R.digest(W.SEED)}],
                      output={"n": len(rows), "first": rows[0]["event_time"], "last": rows[-1]["event_time"]},
                      output_id="bars:%s" % R.digest(rows)[:16], availability_cutoff=self.t0,
                      declared={"synthetic": True, "law": W.DECLARED["law"]})
        self.bars = rows

    def _wrap_forecast(self, h, bars, break_input):
        base = h.base_forecast
        from apex.pulse_options.snapshot import compose

        def forecast_fn(symbol, as_of):
            t0 = time.time()
            if break_input == "FUTURE_BAR":
                # DELIBERATELY UNFILTERED, so the REAL causality guard in compose() fires. Filtering first would
                # have tested the court's own filter and reported it as the system refusing.
                usable = list(self.bars)
            else:
                usable = [b for b in self.bars if b["available"] <= as_of]
            try:
                snap = compose(symbol=symbol, as_of=as_of, bars=usable, source="court-synthetic")
            except ValueError as e:
                self.log.emit(layer="DIGITAL_TWIN", operation="snapshot.compose",
                              code_identity="apex.pulse_options.snapshot.compose",
                              available=R.AVAILABLE, executed=R.EXECUTED, valid=R.INVALID,
                              why_invalid=str(e)[:120], refusal=str(e)[:120],
                              inputs=[{"id": "bars", "digest": R.digest(usable)}],
                              started=t0, ended=time.time(), availability_cutoff=as_of)
                raise
            self.log.emit(layer="DIGITAL_TWIN", operation="snapshot.compose", scan_id=None,
                          snapshot_id=snap.get("snapshot_id"), code_identity="apex.pulse_options.snapshot.compose",
                          inputs=[{"id": "bars:%s" % R.digest(self.bars)[:16], "digest": R.digest(usable)}],
                          output={"state_hash": snap["state_hash"], "missingness": snap["missingness"]},
                          output_id=snap.get("snapshot_id"), started=t0, ended=time.time(),
                          availability_cutoff=as_of,
                          valid=R.VALID if snap.get("state_hash") else R.INVALID)
            f = base(symbol, as_of)
            inputs = dict(f["inputs"])
            if break_input == "INVALID_MODEL_OUTPUT":
                f = {**f, "scale": float("nan")}
                self.notes.append("break_input=INVALID_MODEL_OUTPUT: forecast scale set to NaN deliberately")
            f = {**f, "inputs": {**inputs, "state_hash": snap["state_hash"], "snapshot_id": snap["snapshot_id"]}}
            self.log.emit(layer="LOCATION_VOLATILITY_FORECAST", operation="forecast provider",
                          snapshot_id=snap.get("snapshot_id"),
                          code_identity=f.get("model_id"), model_identity={"model_hash": f.get("model_hash"),
                                                                           "params_hash": f.get("params_hash"),
                                                                           "artifact": f.get("artifact_digest")},
                          inputs=[{"id": snap["snapshot_id"], "digest": snap["state_hash"]}],
                          output={k: f.get(k) for k in ("location", "scale", "nu", "family")},
                          output_id="forecast:%s" % R.digest(f)[:16], started=t0, ended=time.time(),
                          availability_cutoff=as_of,
                          valid=R.VALID if _finite(f.get("scale")) else R.INVALID,
                          why_invalid=None if _finite(f.get("scale")) else "NON_FINITE_SCALE")
            return f
        return forecast_fn

    def _wrap(self, layer, op, fn):
        def wrapped(*a, **k):
            t0 = time.time(); out = fn(*a, **k)
            self.log.emit(layer=layer, operation=op, code_identity=getattr(fn, "__qualname__", op),
                          inputs=[{"id": "args", "digest": R.digest([a, sorted(k)])}],
                          output=out, output_id="%s:%s" % (layer.lower(), R.digest(out)[:16]),
                          started=t0, ended=time.time(), valid=R.VALID if out is not None else R.INVALID)
            return out
        return wrapped

    def _external(self, hung):
        from apex.tradingview import context as TVC
        import threading
        gate = {"release": threading.Event()}

        def fetch(symbol, as_of):
            if hung:
                gate["release"].wait(timeout=30.0)      # BOUNDED: never an unbounded abandoned worker
                return []
            return []

        def ctx_fn(symbol, as_of):
            t0 = time.time()
            c = TVC.external_context(symbol=symbol, as_of=as_of, snapshot={"snapshot_id": "snap:court"},
                                     fetch_fn=fetch, deadline_s=0.3)
            self.log.emit(layer="TRADINGVIEW_EXTERNAL_CONTEXT", operation="external_context",
                          code_identity="apex.tradingview.context.external_context",
                          available=R.AVAILABLE if c["status"] == "AVAILABLE" else R.UNAVAILABLE,
                          why_unavailable=None if c["status"] == "AVAILABLE" else c.get("why"),
                          executed=R.EXECUTED, valid=R.VALID,
                          inputs=[{"id": "symbol", "digest": R.digest(symbol)}],
                          output={"status": c["status"], "n_used": c.get("n_used")},
                          output_id="extctx:%s" % R.digest(c)[:16], started=t0, ended=time.time(),
                          refusal=c.get("why"),
                          declared={"authority": "EXTERNAL_CONTEXT_ONLY",
                                    "note": "USED here can only ever be 0: no production consumer is registered"})
            gate["release"].set()
            return c
        self._gate = gate
        return ctx_fn

    def _receipt_persisted(self, rows):
        for kind, layer in (("pilot_forecast", "PERSISTED_FORECAST"), ("pilot_funnel", "FUNNEL_ENGINE"),
                            ("pilot_intent", "PERSISTED_INTENT"), ("pilot_fill", "PAPER_FILL"),
                            ("pilot_outcome", "EXIT_AND_BOOK"), ("pilot_decision", "DECISION_RECORD")):
            recs = [r for r in rows if r.get("kind") == kind]
            self.log.emit(layer=layer, operation="persisted by the real path",
                          scan_id=(recs[0].get("scan_id") if recs else None),
                          available=R.AVAILABLE if recs else R.UNAVAILABLE,
                          why_unavailable=None if recs else "no %s record was written" % kind,
                          executed=R.EXECUTED if recs else R.NOT_EXECUTED,
                          valid=R.VALID if recs else R.NOT_ASSESSED,
                          inputs=[], output=({"n": len(recs)} if recs else None),
                          output_id=(recs[0].get("txn_id") or kind if recs else None))


class FunnelCourt:
    """The FULL funnel route, driven through the REAL TwinSources rather than the harness providers.

    The rule route and the funnel route are separate flights on purpose: the rule route never constructs a
    FunnelEngine, so running one and reporting the other would claim reach the run never had."""

    def __init__(self, *, run_id: str, n_bars: int = 500, t0: float = 1_789_000_020.0, out_root="results/court",
                 policy: str = "FULL_FUNNEL_V1", premarket_root=None, synthetic_bars=None, synthetic_chain=None):
        self.run_id, self.n_bars, self.t0, self.policy = run_id, n_bars, t0, policy
        self.premarket_root = premarket_root
        self.synthetic_bars = synthetic_bars
        self.synthetic_chain = synthetic_chain
        self.dir = pathlib.Path(out_root) / run_id
        if self.dir.exists():
            raise RuntimeError("RUN_DIR_EXISTS: %s" % self.dir)
        self.dir.mkdir(parents=True)
        self.log = R.ReceiptLog(run_id=run_id)

    def run(self) -> dict:
        from apex.pulse_options.sources import TwinSources
        from apex.options_pilot import boundary as B
        from apex.options_pilot.risk_authority import CertifiedRiskAuthority
        fees = synthetic_fee_authorization()
        h = SyntheticHarness(self.dir / "ledger.jsonl", session_id=self.run_id, t0=self.t0, risk="certified",
                             fee_schedule=fees)
        h.chain = [{**c, "ask": 2.45} for c in h.chain]
        if self.synthetic_chain is not None:
            h.chain = self.synthetic_chain
        lc = LC.MonotonicClock(h.now()); h.clock = lc.clock(); h.bd.clock = h.clock
        h.now, h.advance = lc.now, lc.sleep
        h.bd.exit_policy = EP.EXIT_POLICY_V2
        bars = W.bars(n=self.n_bars, end_epoch=self.t0, drift_bp_per_bar=0.8, vol_bp_per_bar=4.0)
        if self.synthetic_bars is not None:
            bars = self.synthetic_bars

        class Feed:
            provider = "court-synthetic"
            def bars(self, symbol, start_epoch, end_epoch):
                return [b for b in bars if start_epoch <= b["event_time"] <= end_epoch]

        try:
            tw = TwinSources(provenance="SYNTHETIC_FIXTURE", clock=h.clock, bar_source=Feed(),
                             chain_fn=h.chain_fn, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes,
                             fee_schedule=fees, selection_policy=self.policy, sleep_fn=lambda s: None,
                             premarket_root=self.premarket_root)
        except Exception as e:
            self.log.emit(layer="SELECTION_POLICY", operation="TwinSources construction",
                          available=R.UNAVAILABLE, executed=R.NOT_EXECUTED, valid=R.NOT_ASSESSED,
                          why_unavailable=str(e)[:200], refusal=str(e)[:200])
            out = {"run_id": self.run_id, "policy": self.policy, "reachable": False, "refusal": str(e)[:200],
                   "receipts": self.log.receipts}
            (self.dir / "court_run.json").write_text(json.dumps(out, indent=1, default=str) + chr(10))
            return out

        src = tw.sources()
        src.pop("exit_quote_fn", None)
        runner = LC.LifecycleRunner(boundary=h.bd, sources={**tw.sources()}, clock=lc, symbols=["SPY"],
                                    selection_policy=self.policy, scan_epochs=[self.t0])
        report = runner.run()
        rows = L.read_all(h.bd.ledger)
        fn = [r for r in rows if r.get("kind") == "pilot_funnel"]
        tr = (fn[0].get("trace") if fn else {}) or {}
        fit = tr.get("fit") or {}
        for stage, key in (("REGIME", "regime"), ("VARIANCE_MODEL", "variance"), ("MARKET_IMPLIED", "implied"),
                           ("MULTIVERSE_SIMULATION", "simulation"), ("EXPRESSION_WAR", "expression_war")):
            v = tr.get(key)
            self.log.emit(layer=stage, operation="FunnelEngine.decide stage",
                          available=R.AVAILABLE if v else R.UNAVAILABLE,
                          why_unavailable=None if v else "stage not reached or not emitted by the engine",
                          executed=R.EXECUTED if v else R.NOT_EXECUTED,
                          valid=R.VALID if v else R.NOT_ASSESSED,
                          output=v, output_id="%s:%s" % (stage.lower(), R.digest(v)[:12]) if v else None)
        out = {"run_id": self.run_id, "policy": self.policy, "reachable": True,
               "engine": tw.funnel_engine.describe() if tw.funnel_engine else None,
               "fit_status": fit.get("status") if isinstance(fit, dict) else str(fit)[:120],
               "funnel_decision": (fn[0].get("decision") if fn else None),
               "funnel_why": (fn[0].get("why") if fn else None),
               "trace_stages_present": sorted([k for k, v in tr.items() if v]),
               "decision": (report.get("decisions") or [{}])[0].get("decision"),
               "why": (report.get("decisions") or [{}])[0].get("why"),
               "ledger_kinds": {k: len([r for r in rows if r.get("kind") == k])
                                for k in sorted({r.get("kind") for r in rows})},
               "receipts": self.log.receipts, "verdict_limits": R.LIMITS}
        (self.dir / "court_run.json").write_text(json.dumps(out, indent=1, default=str) + chr(10))
        return out


def _finite(x):
    try:
        return x == x and abs(float(x)) != float("inf")
    except Exception:
        return False
