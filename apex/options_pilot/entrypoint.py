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
from .risk_gate import ProductionRiskAuthority

ROUTE_PILOT = "PILOT_BOUNDARY"
ROUTE_LEGACY = "LEGACY_GEOMETRY_LOOP"


class ProviderNotIntegrated(RuntimeError):
    pass


def route(args) -> str:
    """The ONE place that decides which loop runs."""
    return ROUTE_PILOT if getattr(args, "pilot_boundary", False) else ROUTE_LEGACY


def _production_forecast(symbol, as_of):
    raise ProviderNotIntegrated(
        "NO_REVIEWED_INFERENCE_ADAPTER: the retained parameter artifact has no reviewed live-bar inference "
        "adapter in this brick; the production pilot cannot produce a forecast and therefore cannot trade")


class ProductionSources:
    """Live-feed sources for the pilot path. Forecast provider not
    integrated; risk authority refuses. Both are named refusals."""
    provenance = "LIVE_FEED"

    def __init__(self):
        self.clock = Clock(time.time)
        self.risk_authority = ProductionRiskAuthority()

    def sources(self) -> dict:
        def no_quote(contract):
            raise ProviderNotIntegrated("NO_QUOTE_ADAPTER: no reviewed quote adapter on the pilot path in this brick")
        return {"forecast_fn": _production_forecast,
                "signal_fn": lambda s, t: None, "chain_fn": lambda s, t: [], "spot_fn": lambda s, t: None,
                "quote_fn": no_quote, "exit_quote_fn": no_quote}


def build_boundary(ledger, *, provider, session_id: str, release: str) -> Boundary:
    return Boundary(ledger, clock=provider.clock, provenance=provider.provenance,
                    risk_authority=provider.risk_authority, session_id=session_id, release=release)


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
    for fr in fills:
        try:
            o = S.resolve(bd, fill_receipt=fr, exit_quote_fn=src["exit_quote_fn"])
            report["outcomes"].append({"fill_seq": fr["seq"], "status": o["status"], "seq": o["seq"],
                                       "discharges_position": o.get("discharges_position"), "attempt": o.get("attempt")})
        except Exception as e:                                                 # noqa: BLE001
            report["outcomes"].append({"fill_seq": fr["seq"], "status": "REFUSED", "why": "%s: %s" % (type(e).__name__, str(e)[:160])})
    still_open = S.recover_positions(bd)
    report["unresolved_positions"] = [{k: r.get(k) for k in ("seq", "intent_id", "scan_id", "fill_id", "contract_id",
                                                                "valuation_attempts", "last_attempt_why")} for r in still_open["own"]]
    report["session_close"] = S.close_session(bd)
    close_rec = S.L.read_all(ledger)[report["session_close"]["seq"] - 1]
    report["completion"] = close_rec.get("completion")
    report["outstanding_obligations"] = close_rec.get("outstanding_obligations")
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

    def sources(self) -> dict:
        return self.h.sources()
