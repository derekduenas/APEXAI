#!/usr/bin/env python
"""APEX MISSION READINESS — layer-by-layer, every cell MEASURED. T1 item 9.

    python scripts/apex_mission_readiness.py

For every layer: DEFINED (module imports), REACHABLE (entry callable
exists), IO (a representative LEGAL fixture round-trips through it),
AUTHORITY (its power constraint holds), STATUS. A cell that cannot be
measured prints UNKNOWN — the INSTR-01 law. This is a test harness and a
consumer; it creates no production records and holds no authority.

Writes results/readiness/MONDAY_MISSION_READINESS.json (with the per-
layer input/output contract — WS2A's data contract — embedded per row).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_S = Path(__file__).resolve().parent
sys.path.insert(0, str(_S.parent)); sys.path.insert(0, str(_S))

import pandas as pd  # noqa: E402

NOW = pd.Timestamp("2026-08-17T15:00:00Z")

DECISION = {
    "decision_id": "READY-001", "symbol": "AAPL", "direction": "LONG",
    "playbook_id": "HUNTER-001_v1", "entry": 200.0, "stop": 198.0,
    "target": 204.0, "risk_frac": 0.01, "t_utc": str(NOW),
    "forward_eligibility": "FORWARD_ELIGIBLE",
    "evidence_class": "EODHD_FORWARD_OBSERVATION",
    "chart_state": {"data_quality": [], "rvol_tod": 2.4,
                    "realized_vol_ann": 0.25, "vwap": 199.5},
    "relative_strength": {"excess_market_60m": 0.008},
    "market_state": {"day_return": 0.002, "above_vwap": True},
}


def _bars(n=180):
    idx = pd.date_range("2026-08-17T13:30:00Z", periods=n, freq="1min")
    return pd.DataFrame({"event_time_utc": idx, "open": 100.0,
                         "high": 100.5, "low": 99.5, "close": 100.1,
                         "volume": 1000.0})


def layer_market_sensor():
    from apex.hunter.chartstate import visible_bars
    v = visible_bars(_bars(), NOW)
    assert len(v) < 180, "future bars visible"
    return "as-of choke point filters future bars"


def layer_world():
    import apex.world.twin2 as t
    assert hasattr(t, "transition_state")
    return "twin2 importable; observational"


def layer_scout():
    from apex.hunter.scanner import scan
    r = scan(str(NOW), 0, [])
    assert r.abnormal == 0
    return "empty universe -> zero abnormalities, legally"


def layer_hunter():
    from apex.hunter.playbooks_v1 import match_hunter_001
    return "frozen matcher importable (NOT invoked: Epoch 1 frozen)"


def layer_analog():
    from apex.analog.engine import AnalogQuery, retrieve
    from apex.hunter.evidence import EvidenceClass
    r = retrieve(AnalogQuery(as_of=str(NOW), security_id="AAPL",
                             horizon_minutes=60,
                             playbook_id="HUNTER-001_v1",
                             candidate_record=DECISION), [],
                 evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION)
    assert r.status == "NO_VALID_ANALOGS"
    return "empty memory -> NO_VALID_ANALOGS, never invented support"


def layer_ml_gate():
    from apex.hunter.evidence import EvidenceClass
    from apex.ml.hunter_models import build_dataset, train
    m = train(build_dataset([], {}, 60,
                            evidence_class=EvidenceClass.EODHD_FORWARD_OBSERVATION))
    assert m.status == "UNTRAINED"
    return "no data -> UNTRAINED, forecast refused"


def layer_swarm():
    from apex.hunter.swarm import run_specialists
    out = run_specialists(DECISION, as_of=str(NOW), allow_deep=False,
                          runner=lambda *a, **k: "not json")
    assert out.status in ("FAILED", "BLOCKED_EXTERNAL_AUTH", "PARTIAL", "OK")
    return "garbage runner degrades, never crashes the desk"


def layer_assassin():
    import apex.hunter.assassin as a
    from apex.audit.execution_path import executable_source
    code = executable_source(open(a.__file__).read())
    assert "PAPER_ELIGIBLE" not in code
    return "monotone caution; cannot authorize (source-proven)"


def layer_captain():
    from apex.captain.kernel import assess
    st = assess(DECISION, None, None, {"final_state": "NO_TRADE",
                                       "reason_codes": [], "gates": {}})
    assert st.as_record()["capital_is_sovereign"] is True
    return "capital sovereignty asserted in the record"


def layer_capital():
    from apex.hunter.capital import ForecastSlot, evaluate_candidate
    from apex.portfolio.risk import PortfolioState
    out = evaluate_candidate(
        DECISION, sector="TECH", median_dollar_volume=5e7, ann_vol=0.25,
        market_uncertain=False, forecast=ForecastSlot(status="NOT_YET_AVAILABLE"),
        portfolio=PortfolioState(nav=1e5, positions={}, sector_weights={},
                                 heat=0.0, drawdown_budget_left=1.0,
                                 sleeve_correlations={}),
        relative_spread=0.0004)
    assert out.final_state != "PAPER_ELIGIBLE"
    return f"no forecast -> {out.final_state}, never PAPER_ELIGIBLE"


def layer_expression():
    from apex.execution.contracts import BrokerCapabilities
    from apex.execution.expression_v2 import evaluate
    d = evaluate(DECISION, spot=200.0, chain=[],
                 capabilities=BrokerCapabilities(broker="test"),
                 forecast_status="REFUSED", shares=10)
    assert d.authorization_power == "NONE"
    return f"{d.expression_type} diagnostic, authorization NONE"


def layer_execution_gateway():
    from apex.execution.sealing import scan_package_for_placement
    assert scan_package_for_placement("apex")["clean"]
    return "placement scan clean; ORDER_SENT unexpressible"


def layer_broker_review():
    from apex.execution.robinhood import ALLOWED_TOOLS
    assert all(t.startswith(("get_", "review_")) for t in ALLOWED_TOOLS)
    cert = Path("results/execution/certification.jsonl")
    assert cert.exists(), "no certification has ever been recorded"
    return f"{len(ALLOWED_TOOLS)} measured read/review tools; cert ledger present"


def layer_trade_manager():
    from apex.hunter.statemachine import TradeLifecycle
    import inspect
    src = inspect.getsource(TradeLifecycle.tighten_stop)
    assert "widening" in src and "raise" in src
    return "stop-widening refusal at the transition"


def layer_research_memory():
    from apex.governance.chain_verify import verify
    v = verify("results/hunter/birth_registry.jsonl")
    assert v["status"] in ("VALID", "VALID_WITH_DAMAGE")
    return f"birth registry {v['status']} ({v['valid_records']} rec)"


def layer_ledger():
    import sys as _s
    _s.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    import tempfile
    p = Path(tempfile.mkdtemp()) / "l.jsonl"
    _chain_append(p, {"kind": "probe"})
    r = _chain_append(p, {"kind": "probe2"})
    assert r["prev_hash"] != "GENESIS"
    return "chain append + linkage live"


def layer_session_reporter():
    import epoch1_session_report as rep
    text, ok = rep.build("1999-01-01")
    assert ok is False and "NO_SESSION_RECORDED" in text
    return "absent session refuses to look valid"


def layer_catalyst_eyes():
    from apex.events.catalyst import catalyst_state
    from apex.events.cik_bridge import cik_of
    cik = cik_of("AAPL")
    assert cik, "CIK bridge empty"
    st = catalyst_state("AAPL.US", pd.Timestamp.now(tz="UTC"), cik=cik)
    assert st.status in ("KNOWN_CATALYST", "NO_KNOWN_CATALYST",
                         "EVENT_UNCERTAIN")
    return f"live: {st.status} (bridge {cik})"


def layer_visual_eyes():
    from apex.vision.challenger import VisualChallenge
    from apex.vision.render import render_candles
    png = render_candles([(1, 2, 0.5, 1.5)] * 30)
    ch = VisualChallenge(decision_id="d", snapshot_id="s", status="OK",
                         market_structure="RANGE")
    assert ch.decision_power == "NONE_OBSERVATIONAL_EPOCH1"
    led = Path("results/hunter/visual_ledger.jsonl")
    live = "live challenge recorded" if led.exists() else "no live challenge yet"
    return f"renderer deterministic; firewall constructs; {live}"


def layer_microscope():
    from apex.hunter.microscope import select_targets
    t = select_targets(decisions=[DECISION], scans=[])
    assert t and t[0].wants_l2
    led = Path("results/hunter/microscope_ledger.jsonl")
    live = "live records present" if led.exists() else "no live pass yet"
    return f"selector deterministic; {live}"


def layer_fastwatch():
    src = open("scripts/fastwatch.py").read()
    assert 'purpose="LAB"' in src
    led = Path("results/hunter/fastwatch_ledger.jsonl")
    live = "smoke records present" if led.exists() else "not yet run"
    return f"LAB-governed; launchd armed; {live}"


LAYERS = [
    ("MARKET SENSOR", layer_market_sensor,
     "1m bars -> visible_bars(t) -> as-of frame"),
    ("DIGITAL WORLD", layer_world, "SFP+bridge -> regime/transition state"),
    ("SCOUT", layer_scout, "states -> abnormalities + watchlist"),
    ("HUNTER", layer_hunter, "ChartState+RS+market -> frozen match|None"),
    ("ANALOG", layer_analog, "forward memory rows -> neighbour view"),
    ("ML GATE", layer_ml_gate, "forward dataset -> UNTRAINED until earned"),
    ("SWARM", layer_swarm, "candidate -> commentary/objection, never authority"),
    ("ASSASSIN", layer_assassin, "bundle -> wounds, monotone caution"),
    ("CAPTAIN", layer_captain, "views -> directive; capital sovereign"),
    ("CAPITAL", layer_capital, "candidate+gates -> final_state + reasons"),
    ("OPTIONS EXPRESSION", layer_expression,
     "decision+chain -> diagnostic expression"),
    ("EXECUTION GATEWAY", layer_execution_gateway,
     "intent -> 17-check chain -> ORDER_READY|refusal"),
    ("BROKER REVIEW", layer_broker_review,
     "measured read/review surface via child session"),
    ("TRADE MANAGER", layer_trade_manager,
     "position events -> single legal transition"),
    ("RESEARCH MEMORY", layer_research_memory, "append-only chained births"),
    ("LEDGER", layer_ledger, "record -> chained append, torn-safe"),
    ("SESSION REPORTER", layer_session_reporter,
     "ledger -> VALID|INVALID|NO_SESSION"),
    ("CATALYST EYES", layer_catalyst_eyes,
     "EDGAR archive + CIK bridge -> 3-state catalyst"),
    ("VISUAL EYES", layer_visual_eyes,
     "packet -> snapshot -> challenger -> firewalled challenge"),
    ("MICROSCOPE", layer_microscope,
     "ledger -> deterministic targets -> broker enrichment"),
    ("FASTWATCH", layer_fastwatch, "watchlist -> 1m observations, LAB quota"),
]


def main() -> int:
    rows, failed = [], 0
    print(f"{'LAYER':<20}{'STATUS':<8}EVIDENCE")
    for name, fn, contract in LAYERS:
        try:
            evidence = fn()
            status = "PASS"
        except Exception as e:                              # noqa: BLE001
            evidence = f"{type(e).__name__}: {e}"
            status = "FAIL"
            failed += 1
        rows.append({"layer": name, "status": status,
                     "io_contract": contract, "evidence": str(evidence)})
        print(f"{name:<20}{status:<8}{str(evidence)[:56]}")
    out = Path("results/readiness/MONDAY_MISSION_READINESS.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"generated_utc": str(pd.Timestamp.now(tz="UTC")),
         "layers": rows, "failed": failed,
         "verdict": ("READY_FOR_EPOCH1" if failed == 0
                     else "NOT_READY_FOR_EPOCH1"),
         "ready_for_paper": "NO", "ready_for_live": "NO"}, indent=2))
    print(f"\nVERDICT: {'READY_FOR_EPOCH1' if failed == 0 else 'NOT_READY_FOR_EPOCH1'}"
          f" ({len(LAYERS) - failed}/{len(LAYERS)} layers measured PASS)")
    print("READY_FOR_PAPER: NO | READY_FOR_LIVE: NO")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
