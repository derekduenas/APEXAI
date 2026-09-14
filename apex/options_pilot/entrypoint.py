"""THE PILOT PATH THROUGH THE REAL SESSION ENTRY POINT.

`scripts/options_paper_session.py --pilot-boundary` routes here BEFORE the
legacy loop is reachable. With the flag off (default) the legacy loop runs
unchanged. With it on, every scan goes through the recording boundary:
forecast -> risk-bound intent -> quote -> atomic fill -> decision, and the
legacy `_scan_symbol` / `paper_execution.simulate_entry` geometry path is
never called -- there is no fallback to geometry-only fills.

EXECUTION MODE vs DATA PROVENANCE. The mode here is always
PROSPECTIVE_ORCHESTRATION (the loop runs forward in time over a controlled
clock). Provenance says where the inputs came from:
    LIVE_FEED          production sources. In THIS brick the production
                       forecast provider is NOT integrated (no reviewed
                       inference adapter) and the production risk authority
                       refuses, so every scan ends REFUSE with a persisted
                       refusal. That is the honest state of the pilot.
    SYNTHETIC_FIXTURE  the explicit synthetic harness, injected by a test or
                       selected with --pilot-synthetic-fixture; records are
                       labelled synthetic and are not evidence."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import instant as I
from . import ledger as L
from . import lifecycle as LC
from . import session as S
from .accounting import net_result
from .boundary import Boundary
from .clock import Clock
from .fees import UNVERIFIED_FEES
from .risk_authority import CertifiedRiskAuthority   # re-exported for tests and operators

ROUTE_PILOT = "PILOT_BOUNDARY"
ROUTE_LEGACY = "LEGACY_GEOMETRY_LOOP"


class ProviderNotIntegrated(RuntimeError):
    pass


def route(args) -> str:
    """The ONE place that decides which loop runs."""
    return ROUTE_PILOT if getattr(args, "pilot_boundary", False) else ROUTE_LEGACY


class LiveWiring:
    """EXPLICIT, REVIEWED live wiring for ProductionSources (Brick 1). Every dependency the live path needs is named
    here and reported; nothing is attached by default that is not listed. `attach_market_data_http=True` attaches the
    options-feed HTTP client and Alpaca headers to the bars/NBBO adapter and the ThetaData chain/quote functions;
    every call still passes LiveGate (switch + credentials) first. JOINT needs a fitted engine and a context callable
    built from an authorized fit; without them the TwinSources constructor refusal is PRESERVED and reported."""

    def __init__(self, *, attach_market_data_http: bool = False, joint_engine=None, joint_context_fn=None,
                 joint_fit_status: dict | None = None, funnel_engine=None, fee_schedule=None, event_snapshot_fn=None,
                 event_gate_authority: str = "SHADOW", premarket_root=None):
        self.attach_market_data_http = attach_market_data_http
        self.fee_schedule = fee_schedule                       # None -> UNVERIFIED_FEES (the live default); an explicit choice is reported
        self.event_snapshot_fn = event_snapshot_fn
        self.event_gate_authority = event_gate_authority
        self.premarket_root = premarket_root
        self.joint_engine, self.joint_context_fn = joint_engine, joint_context_fn
        self.joint_fit_status = joint_fit_status or {"status": "NOT_SUPPLIED",
                                                     "why": "no R4 fit authorized (R4-FIT-001 not granted); no completed training sessions supplied"}
        self.funnel_engine = funnel_engine

    def describe(self) -> dict:
        return {"attach_market_data_http": self.attach_market_data_http,
                "bars_nbbo_client": ("apex.pulse_options.http_policy.guarded_get over apex.intraday.options_feed (HTTP_POLICY_V1, gated)" if self.attach_market_data_http else "_no_http (NOT ATTACHED)"),
                "fee_schedule": (self.fee_schedule.describe() if self.fee_schedule is not None else "LIVE_DEFAULT (see provider.fee_schedule: the authorized schedule unless overridden)"),
                "event_stream": ("wired: %s" % getattr(self.event_snapshot_fn, "__name__", "callable") if self.event_snapshot_fn is not None else "NOT_WIRED"),
                "event_gate_authority": self.event_gate_authority,
                "premarket_root": str(self.premarket_root) if self.premarket_root is not None else None,
                "premarket_authority": "PRIOR_CONTEXT_ONLY",
                "chain_quote_client": "apex.intraday.options_feed.option_expirations/option_chain_snapshot (gated; injectable)",
                "joint_engine": (type(self.joint_engine).__name__ if self.joint_engine is not None else None),
                "joint_context_fn": (getattr(self.joint_context_fn, "__name__", "callable") if self.joint_context_fn is not None else None),
                "joint_fit_status": self.joint_fit_status,
                "funnel_engine": (self.funnel_engine.describe() if self.funnel_engine is not None and hasattr(self.funnel_engine, "describe") else None)}


class ProductionSources:
    """LIVE_FEED sources = the twin-backed sources behind LiveGate. With the default environment every provider call
    raises ProviderUnavailable BEFORE any network access, so each scan ends REFUSE with a persisted reason; and the
    fee schedule is UNVERIFIED, so no intent could be approved even with data. Both are named refusals, not
    fallbacks. The wiring is explicit (LiveWiring) and reported; the default is PILOT_RULE_V2 unless a separate
    explicit selection is supplied; JOINT/FULL are never routed through V2."""
    provenance = "LIVE_FEED"

    def __init__(self, selection_policy: str = "PILOT_RULE_V2", wiring: LiveWiring | None = None):
        from apex.pulse_options.sources import live_twin_sources
        self.wiring = wiring or LiveWiring()
        http_get = headers_fn = None
        gate = None
        if self.wiring.attach_market_data_http:
            from apex.intraday import options_feed as OF
            from apex.pulse_options.http_policy import EndpointHealth, guarded_get
            from apex.pulse_options.providers import LiveGate
            gate = LiveGate(secret_fn=OF._secret)                 # credentials from the secret backend (presence only); switch from env
            self.health = EndpointHealth()

            def http_get(url, headers=None):
                body, _ = guarded_get(url, headers=headers, endpoint=url.split("?")[0], health=self.health)
                return body
            headers_fn = OF._alpaca_headers
        # a JOINT request without engine+context reaches the TwinSources guard and is refused there (preserved)
        self._twin = live_twin_sources(gate=gate, selection_policy=selection_policy, http_get=http_get, headers_fn=headers_fn,
                                       joint_engine=self.wiring.joint_engine, joint_context_fn=self.wiring.joint_context_fn,
                                       funnel_engine=self.wiring.funnel_engine, fee_schedule=self.wiring.fee_schedule,
                                       event_snapshot_fn=self.wiring.event_snapshot_fn, event_gate_authority=self.wiring.event_gate_authority,
                                       premarket_root=self.wiring.premarket_root)
        self.selection_policy = selection_policy
        self.funnel_engine = self._twin.funnel_engine
        self.clock = self._twin.clock
        self.risk_authority = self._twin.risk_authority
        self.fee_schedule = self._twin.fee_schedule

    def sources(self) -> dict:
        return self._twin.sources()

    def describe(self) -> dict:
        return {"provenance": self.provenance, "selection_policy": self.selection_policy, "wiring": self.wiring.describe(),
                "fee_schedule": {"id": self.fee_schedule.schedule_id, "provenance": self.fee_schedule.provenance}}


def build_boundary(ledger, *, provider, session_id: str, release: str) -> Boundary:
    return Boundary(ledger, clock=provider.clock, provenance=provider.provenance,
                    risk_authority=provider.risk_authority, session_id=session_id, release=release,
                    fee_schedule=getattr(provider, "fee_schedule", UNVERIFIED_FEES))


class AdaptedClock(LC.MonotonicClock):
    """The provider's own clock, driven through the lifecycle's monotonic guard.

    A controlled harness clock advances when its `sleep_fn` is called; the wall clock advances by itself and
    `time.sleep` waits for it. Both are the same thing to the scheduler: `now()` reads the provider's clock and
    `advance_to()` asks the provider to move to an instant. Neither can go backwards."""

    def __init__(self, clock, sleep_fn):
        self._clock, self._sleep = clock, sleep_fn
        self.KIND = "PROVIDER"
        super().__init__(clock.now())

    def now(self) -> float:
        t = self._clock.now()
        if I.canonical_micros(t, field="provider.now") > I.canonical_micros(self._t, field="provider.last"):
            self._t = t
        return self._t

    def _wait(self, target_epoch: float) -> None:
        remaining = target_epoch - self._clock.now()
        n = 0
        while remaining > 0 and n < 1000:
            self._sleep(remaining)
            after = self._clock.now()
            if after <= target_epoch - remaining:                # a sleep_fn that does not move time
                break
            remaining = target_epoch - after
            n += 1


def run_pilot(*, ledger, out, symbols: list, provider, session_id: str, release: str, cycles: int = 1,
              interval_s: float = 0.0, sleep_fn=time.sleep) -> dict:
    """Open (idempotent) -> resume unfinished intents -> scan each symbol per cycle -> service every obligation at its
    own deadline -> close. Returns and writes the report.

    THE ORDERING IS THE SHARED LIFECYCLE SCHEDULER's (apex.options_pilot.lifecycle), not a cycle loop's. Scans,
    exit deadlines, retries, intent expiry and session closure are one chronological event stream: an obligation that
    falls due between two scans is serviced when it falls due, and every due obligation at an instant is processed
    before new risk is admitted at that instant. The clock never rewinds."""
    ledger = Path(ledger)
    bd = build_boundary(ledger, provider=provider, session_id=session_id, release=release)
    from .runtime_identity import runtime_identity
    identity = runtime_identity(artifacts=getattr(provider, "artifacts", None))
    bd.runtime_identity = identity
    src = provider.sources()
    from apex.pulse_options.sources import SELECTION_POLICIES, RULE_POLICIES
    from .expression_rule import RULE_IDS
    policy = getattr(provider, "selection_policy", None) or "PILOT_RULE_V2"
    if policy not in SELECTION_POLICIES:
        raise ValueError("SELECTION_POLICY_UNKNOWN: %r (known: %s)" % (policy, SELECTION_POLICIES))
    if policy in RULE_POLICIES and src.get("funnel_fn") is not None:
        raise ValueError("SELECTION_POLICY_CONFLICT: %r is a deterministic rule but the provider supplies a funnel" % (policy,))
    if policy not in RULE_POLICIES and src.get("funnel_fn") is None:
        raise ValueError("SELECTION_POLICY_CONFLICT: %r needs a funnel_fn and the provider supplies none" % (policy,))
    sleep = getattr(provider, "sleep_fn", None) or sleep_fn        # a controlled clock 'sleeps' by advancing
    report = {"route": ROUTE_PILOT, "session_id": session_id, "release": release,
              "execution_mode": bd.labels["execution_mode"], "data_provenance": bd.labels["data_provenance"],
              "evidence_class": bd.labels["evidence_class"], "decision_power": bd.labels["decision_power"],
              "synthetic": bd.labels["synthetic"], "legacy_geometry_path_called": False,
              "risk_authority": type(provider.risk_authority).__name__, "resumed": [], "decisions": [], "outcomes": []}
    # A session that is already CLOSED on disk is not reopened for new scans: this run is recovery-only. New intents
    # would be refused at the boundary (SESSION_CLOSED) and would then sit as unfinished obligations of their own.
    already_closed = session_id in S.closed_sessions(S.L.read_all(ledger))
    report["mode"] = "RECOVERY_ONLY" if already_closed else "SCAN_AND_RESOLVE"
    recovered_before = {r["seq"] for r in S.recover_positions(bd)["own"]}
    lclock = AdaptedClock(bd.clock, sleep)
    bd.clock = lclock.clock()                                  # the boundary reads the lifecycle clock, and only it
    t0 = lclock.now()
    n_cycles = 0 if already_closed else max(1, int(cycles))
    step = 0.0                                                  # a cadence, not an economic quantity
    if I.is_real(interval_s) and interval_s > 0:
        step = float(interval_s)
    scan_epochs = [t0 + i * step for i in range(n_cycles)]
    # EXIT-SCHEDULING-003: the process identity every exit attempt will carry. Deterministic from the session and
    # the start instant, so the same restart replayed names the same process.
    runner = LC.LifecycleRunner(boundary=bd, sources=src, clock=lclock, symbols=symbols, selection_policy=policy,
                                scan_epochs=scan_epochs,
                                process_id="%s@%dus" % (session_id, I.canonical_micros(t0)))
    lrep = runner.run()
    report["lifecycle"] = {k: lrep[k] for k in ("ordering_policy", "clock_kind", "n_events", "final_clock_utc",
                                                "data_available", "clock_advances")}
    report["event_trace"] = LC.event_trace(lrep)
    report["session_open"] = lrep["session_open"]
    report["resumed"] = lrep["resumed"]
    report["recovered_positions"] = lrep["recovered_positions"]
    report["foreign_unresolved_positions"] = lrep["foreign_unresolved_positions"]
    report["decisions"] = lrep["decisions"]
    report["housekeeping"] = lrep["expiries"]
    # ONE ENTRY PER POSITION, however many attempts it took, in the shape the operator report has always used.
    report["outcomes"] = list(lrep["exit_entries"])
    report["unresolved_positions"] = lrep["unresolved_positions"]
    report["session_close"] = lrep["session_close"]
    close_rec = S.L.read_all(ledger)[report["session_close"]["seq"] - 1]
    report["completion"] = close_rec.get("completion")
    report["outstanding_obligations"] = close_rec.get("outstanding_obligations")
    report["book"] = close_rec.get("book")
    # PRESERVED UNKNOWN ACCOUNTING: the aggregate never drops an unresolved position or an unknown fee, and never
    # presents a partial account as a total.
    report["net_result"] = net_result(bd.book())
    report["fee_schedule"] = bd.fee_schedule.describe()
    report["exit_policy"] = bd.exit_policy.describe()
    report["execution_policy"] = bd.execution_policy.describe()
    report["selection_policy"] = policy
    report["runtime_identity"] = identity
    report["wiring"] = (provider.describe() if hasattr(provider, "describe") else {"provider": type(provider).__name__})
    report["provider_health"] = (provider.health.summary() if getattr(provider, "health", None) is not None else "NO_HTTP_CLIENT_ATTACHED")
    # IDENTITY CHECK: every persisted intent of this session must name the rule of the policy that was run
    if policy in RULE_IDS:
        expected_rule = RULE_IDS[policy]
    elif policy == "FULL_FUNNEL_V1":
        from apex.decision_wb.engine import FUNNEL_RULE_ID as expected_rule
    else:
        from apex.joint_wb.engine import JOINT_RULE_ID as expected_rule
    mism = []
    for r in L.read_all(ledger):
        if r.get("kind") == "pilot_intent" and r.get("session_id") == session_id:
            got = r.get("expression_rule")
            if got != expected_rule:
                mism.append({"seq": r.get("seq"), "intent_id": r.get("intent_id"), "expression_rule": got})
    report["policy_identity"] = {"policy": policy, "expected_rule_id": expected_rule, "intents_checked": sum(1 for r in L.read_all(ledger) if r.get("kind") == "pilot_intent" and r.get("session_id") == session_id),
                                 "mismatches": mism, "consistent": not mism}
    if mism:
        raise RuntimeError("POLICY_IDENTITY_MISMATCH: %d intent(s) do not carry the rule of policy %r" % (len(mism), policy))
    if hasattr(provider, "funnel_engine") and provider.funnel_engine is not None:
        report["funnel_engine"] = provider.funnel_engine.describe()
    if out:
        Path(out).write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False, default=str))
    return report


def run_from_args(a, *, pilot_sources=None) -> int:
    """Called by scripts/options_paper_session.main when --pilot-boundary is set."""
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    if pilot_sources is not None:
        provider = pilot_sources
    elif getattr(a, "pilot_synthetic_fixture", False):
        from .synthetic_harness import make_harness
        h = make_harness(Path(a.ledger), symbols=syms)
        if getattr(a, "pilot_selection_policy", "PILOT_RULE_V2") == "FULL_FUNNEL_V1":
            from apex.pulse_options.sources import synthetic_twin_sources
            provider = TwinProvider(synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn,
                                                           sleep_fn=h.advance, selection_policy="FULL_FUNNEL_V1"))
        else:
            provider = _HarnessProvider(h, selection_policy=getattr(a, "pilot_selection_policy", "PILOT_RULE_V2"))
    else:
        wiring = None
        if getattr(a, "pilot_live_wiring", False):
            from apex.catalyst.twin_snapshot import event_snapshot
            wiring = LiveWiring(attach_market_data_http=True, event_snapshot_fn=event_snapshot, event_gate_authority="SHADOW")
        provider = ProductionSources(selection_policy=getattr(a, "pilot_selection_policy", "PILOT_RULE_V2"), wiring=wiring)
    session_id = getattr(a, "pilot_session_id", None) or time.strftime("PILOT-%Y%m%dT%H%M%SZ", time.gmtime())
    release = getattr(a, "pilot_release", None) or "UNPINNED"
    cycles = 1 if a.dry_run else max(1, int(a.minutes // max(1, a.interval_min)))
    rep = run_pilot(ledger=a.ledger, out=a.out, symbols=syms, provider=provider, session_id=session_id, release=release,
                    cycles=cycles, interval_s=0.0 if a.dry_run else a.interval_min * 60.0)
    print(json.dumps({k: rep[k] for k in ("route", "session_id", "data_provenance", "execution_mode", "decisions")},
                     indent=1, default=str), flush=True)
    return 0


class TwinProvider:
    """Adapts TwinSources (either provenance) to the provider interface used above."""

    def __init__(self, twin):
        self._twin = twin
        self.provenance = twin.provenance
        self.clock = twin.clock
        self.risk_authority = twin.risk_authority
        self.fee_schedule = twin.fee_schedule
        self.sleep_fn = twin.sleep_fn
        self.selection_policy = twin.selection_policy
        self.funnel_engine = twin.funnel_engine

    def sources(self) -> dict:
        return self._twin.sources()


class _HarnessProvider:
    """Adapts a SyntheticHarness to the provider interface used above."""
    provenance = "SYNTHETIC_FIXTURE"

    def __init__(self, h, selection_policy: str = "PILOT_RULE_V2"):
        self.h = h
        self.selection_policy = selection_policy
        self.clock = h.clock
        self.risk_authority = h.risk
        self.fee_schedule = h.fee_schedule
        self.sleep_fn = h.advance                      # the controlled clock 'sleeps' by advancing

    def sources(self) -> dict:
        return self.h.sources()
