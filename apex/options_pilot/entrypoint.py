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

from . import session as S
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


class ProductionSources:
    """LIVE_FEED sources = the twin-backed sources behind LiveGate. With the default environment
    every provider call raises ProviderUnavailable BEFORE any network access, so each scan ends
    REFUSE with a persisted reason; and the fee schedule is UNVERIFIED, so no intent could be
    approved even with data. Both are named refusals, not fallbacks."""
    provenance = "LIVE_FEED"

    def __init__(self):
        from apex.pulse_options.sources import live_twin_sources
        self._twin = live_twin_sources()
        self.clock = self._twin.clock
        self.risk_authority = self._twin.risk_authority
        self.fee_schedule = self._twin.fee_schedule
        self.sleep_fn = time.sleep

    def sources(self) -> dict:
        return self._twin.sources()


def build_boundary(ledger, *, provider, session_id: str, release: str) -> Boundary:
    return Boundary(ledger, clock=provider.clock, provenance=provider.provenance,
                    risk_authority=provider.risk_authority, session_id=session_id, release=release,
                    fee_schedule=getattr(provider, "fee_schedule", UNVERIFIED_FEES))


def run_pilot(*, ledger, out, symbols: list, provider, session_id: str, release: str, cycles: int = 1,
              interval_s: float = 0.0, sleep_fn=time.sleep) -> dict:
    """Open (idempotent) -> resume unfinished intents -> scan each symbol
    per cycle -> resolve fills -> close. Returns and writes the report."""
    ledger = Path(ledger)
    bd = build_boundary(ledger, provider=provider, session_id=session_id, release=release)
    src = provider.sources()
    report = {"route": ROUTE_PILOT, "session_id": session_id, "release": release,
              "execution_mode": bd.labels["execution_mode"], "data_provenance": bd.labels["data_provenance"],
              "evidence_class": bd.labels["evidence_class"], "decision_power": bd.labels["decision_power"],
              "synthetic": bd.labels["synthetic"], "legacy_geometry_path_called": False,
              "risk_authority": type(provider.risk_authority).__name__, "resumed": [], "decisions": [], "outcomes": []}
    report["session_open"] = S.open_session(bd, symbols=symbols)
    report["resumed"] = S.resume(bd, quote_fn=src["quote_fn"])
    # LIFECYCLE RECOVERY: every unresolved POSITION on disk (including ones a resume just created, and ones left
    # by an earlier process of this session) is an obligation this run must try to resolve and must report.
    recovered = S.recover_positions(bd)
    fills = list(recovered["own"])
    report["recovered_positions"] = [{k: r.get(k) for k in ("seq", "intent_id", "scan_id", "fill_id", "contract_id",
                                                               "valuation_attempts", "last_attempt_why")} for r in fills]
    report["foreign_unresolved_positions"] = recovered["foreign"]
    # A session that is already CLOSED on disk is not reopened for new scans: this run is recovery-only. New intents
    # would be refused at the boundary (SESSION_CLOSED) and would then sit as unfinished obligations of their own.
    already_closed = session_id in S.closed_sessions(S.L.read_all(ledger))
    report["mode"] = "RECOVERY_ONLY" if already_closed else "SCAN_AND_RESOLVE"
    for cycle in range(0 if already_closed else max(1, cycles)):
        for sym in symbols:
            seq = S.next_seq(ledger, session_id=session_id)
            d = S.scan(bd, symbol=sym, seq=seq, forecast_fn=src["forecast_fn"], signal_fn=src["signal_fn"],
                       chain_fn=src["chain_fn"], spot_fn=src["spot_fn"], quote_fn=src["quote_fn"])
            report["decisions"].append({k: d.get(k) for k in ("scan_id", "symbol", "decision", "why", "forecast_id",
                                                              "intent_id", "fill_id", "decision_persisted",
                                                              "refusal_persisted")})
            if d["decision"] == "TRADE" and d.get("receipts", {}).get("fill"):
                fills.append(d["receipts"]["fill"])
        if cycle + 1 < cycles and interval_s > 0:
            sleep_fn(interval_s)
    sleep = getattr(provider, "sleep_fn", None) or sleep_fn
    # RECOVERED positions (from earlier processes) get one labelled recovery attempt each; positions this run created are
    # driven through the frozen exit policy (wait until due, value, retry inside the window, record exhaustion).
    new_fills = [f for f in fills if f["seq"] not in {r["seq"] for r in recovered["own"]}]
    for entry in S.attempt_exits(bd, exit_quote_fn=src["exit_quote_fn"], sleep_fn=sleep, recovery=True, positions=recovered["own"]):
        report["outcomes"].append({"fill_seq": entry["fill_seq"], "recovery": True, "final": entry["final"], "attempts": entry["attempts"]})
    for entry in S.attempt_exits(bd, exit_quote_fn=src["exit_quote_fn"], sleep_fn=sleep, recovery=False, positions=new_fills):
        report["outcomes"].append({"fill_seq": entry["fill_seq"], "recovery": False, "final": entry["final"], "attempts": entry["attempts"]})
    still_open = S.recover_positions(bd)
    report["unresolved_positions"] = [{k: r.get(k) for k in ("seq", "intent_id", "scan_id", "fill_id", "contract_id",
                                                                "valuation_attempts", "last_attempt_why")} for r in still_open["own"]]
    report["session_close"] = S.close_session(bd)
    close_rec = S.L.read_all(ledger)[report["session_close"]["seq"] - 1]
    report["completion"] = close_rec.get("completion")
    report["outstanding_obligations"] = close_rec.get("outstanding_obligations")
    report["book"] = close_rec.get("book")
    report["fee_schedule"] = bd.fee_schedule.describe()
    report["exit_policy"] = bd.exit_policy.describe()
    report["execution_policy"] = bd.execution_policy.describe()
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
        provider = _HarnessProvider(make_harness(Path(a.ledger), symbols=syms))
    else:
        provider = ProductionSources()
    session_id = getattr(a, "pilot_session_id", None) or time.strftime("PILOT-%Y%m%dT%H%M%SZ", time.gmtime())
    release = getattr(a, "pilot_release", None) or "UNPINNED"
    cycles = 1 if a.dry_run else max(1, int(a.minutes // max(1, a.interval_min)))
    rep = run_pilot(ledger=a.ledger, out=a.out, symbols=syms, provider=provider, session_id=session_id, release=release,
                    cycles=cycles, interval_s=0.0 if a.dry_run else a.interval_min * 60.0)
    print(json.dumps({k: rep[k] for k in ("route", "session_id", "data_provenance", "execution_mode", "decisions")},
                     indent=1, default=str), flush=True)
    return 0


class _HarnessProvider:
    """Adapts a SyntheticHarness to the provider interface used above."""
    provenance = "SYNTHETIC_FIXTURE"

    def __init__(self, h):
        self.h = h
        self.clock = h.clock
        self.risk_authority = h.risk
        self.fee_schedule = h.fee_schedule
        self.sleep_fn = h.advance                      # the controlled clock 'sleeps' by advancing

    def sources(self) -> dict:
        return self.h.sources()
