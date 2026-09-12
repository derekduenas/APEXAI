"""OPERATING-LOOP-001 — one synthetic event trace, end to end, through the real lifecycle path.

    python scripts/operating_loop_trace.py <out_base_dir> [run_id]

Shows, on ONE monotonic synthetic timeline:
    forecast -> decision -> intent -> reservation -> fill -> due exit -> outcome -> released capital -> next decision

SYNTHETIC INPUTS ONLY. No provider is contacted, nothing is fitted, no limit is changed, no fee is authorized and no
order exists. The run writes to a RUN-SCOPED directory and refuses a collision; it never removes anything."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
from apex.options_pilot import accounting as ACC  # noqa: E402
from apex.options_pilot import instant as I  # noqa: E402
from apex.options_pilot import ledger as L  # noqa: E402
from apex.options_pilot import lifecycle as LC  # noqa: E402
from apex.options_pilot import run_dir as RD  # noqa: E402
from apex.options_pilot.synthetic_harness import SyntheticHarness  # noqa: E402

BASE = Path(sys.argv[1])
RUN_ID = sys.argv[2] if len(sys.argv) > 2 else "operating_loop_trace"
T = 1_789_000_020.0
HOLD = 900.0

CONFIG = {"policy": "PILOT_RULE_V2", "scans": ["t0", "t0+930s"], "hold_s": HOLD, "provenance": "SYNTHETIC_FIXTURE",
          "limits": "UNCHANGED (kernel defaults)", "fee_schedule": "SYNTHETIC_FEES", "note": "orchestration only"}

rd = RD.new_run(BASE, run_id=RUN_ID, now_epoch=T, config=CONFIG,
                note="OPERATING-LOOP-001 synthetic event trace; no provider request, no fitting, no authorization")
try:
    ledger = rd.path_for("ledger.jsonl")
    h = SyntheticHarness(ledger, session_id="OPLOOP-TRACE", t0=T, risk="certified")
    # the demonstration's binding condition: two of these exceed the $600 same-underlying cap
    h.chain = [{**c, "ask": 4.95} for c in h.chain]
    h.quotes.ask, h.quotes.bid = 4.95, 4.90
    h.exit_quotes.ask, h.exit_quotes.bid = 4.78, 4.73

    lc = LC.MonotonicClock(T)
    h.clock = lc.clock(); h.bd.clock = h.clock; h.now = lc.now; h.advance = lc.sleep
    runner = LC.LifecycleRunner(boundary=h.bd, sources=h.sources(), clock=lc, symbols=["SPY"],
                                selection_policy="PILOT_RULE_V2", scan_epochs=[T, T + HOLD + 30.0])
    report = runner.run()

    rows = L.read_all(ledger)
    book = h.bd.book()
    steps = []
    for i, r in enumerate(rows, start=1):
        k = r["kind"]
        if k == "pilot_forecast":
            steps.append({"step": "FORECAST", "seq": i, "at": r["created_utc"], "model": r["model_id"],
                          "location": r["location"], "scale": r["scale"], "direction_signal": r.get("direction_signal")})
        elif k == "pilot_intent":
            env = r.get("risk_envelope") or {}
            steps.append({"step": "INTENT", "seq": i, "contract": r["contract_id"], "expression": r.get("expression"),
                          "expiry_utc": r.get("expiry_utc")})
            steps.append({"step": "RESERVATION", "seq": i, "envelope_debit": env.get("envelope_debit"),
                          "max_entry_price": env.get("max_entry_price"),
                          "certified_max_loss": (r.get("risk") or {}).get("certified_max_loss"),
                          "fee_identity": (r.get("fees") or {}).get("schedule_id")})
        elif k == "pilot_fill":
            steps.append({"step": "FILL", "seq": i, "status": r["status"], "price": r.get("price"),
                          "net_debit": r.get("net_debit"), "fees_entry": (r.get("fees_entry") or {}).get("total"),
                          "committed_utc": r.get("committed_utc"),
                          "exit_due_utc": (I.canonical_utc(r["committed_epoch"] + HOLD) if r.get("committed_epoch") else None)})
        elif k == "pilot_outcome":
            steps.append({"step": "OUTCOME", "seq": i, "status": r.get("status"), "attempt": r.get("attempt"),
                          "exit_price": r.get("exit_price"), "fees_exit": (r.get("fees_exit") or {}).get("total"),
                          "pnl": r.get("pnl"), "at": r.get("resolved_utc"), "discharges": r.get("discharges_position")})
        elif k == "pilot_decision":
            steps.append({"step": "DECISION", "seq": i, "scan_id": r["scan_id"], "decision": r["decision"],
                          "why": (r.get("why") or "")[:120]})
        elif k == "pilot_exit_exhausted":
            steps.append({"step": "EXIT_EXHAUSTED", "seq": i, "obligation": r.get("obligation")})

    agg = ACC.net_result(book)
    ACC.assert_no_phantom_zero(agg)
    recon = ACC.reconcile(book, rows, fee_schedules={h.fee_schedule.schedule_id: h.fee_schedule})
    out = {"kind": "OPERATING_LOOP_TRACE", "run_id": RUN_ID, "config": CONFIG,
           "ordering_policy": LC.ORDERING_POLICY, "timestamp_rule": I.CONVERSION_RULE,
           "event_stream": LC.event_trace(report),
           "ledger_steps": steps,
           "capacity": {"released_at": [e["at_utc"] for e in report["events"]
                                        if e["kind"].startswith("EXIT") and e["outcome"].get("capacity_released")],
                        "reserved_after": book.reserved, "open_cost_after": book.open_cost},
           "book": book.summary(), "net_result": agg, "independent_reconciliation": recon,
           "chain_verified": L.verify_chain(ledger),
           "clock_advances": report["clock_advances"], "clock_rewinds": 0,
           "decisions": report["decisions"], "completion": report["completion"]}
    rd.write_json("trace.json", out)
    rd.write_json("lifecycle_report.json", report)
    rd.complete(now_epoch=lc.now(), summary={"decisions": [d["decision"] for d in report["decisions"]],
                                             "n_events": report["n_events"], "completion": report["completion"],
                                             "total_net_status": agg["total_net_status"]})
    print(json.dumps({"run_dir": str(rd.path), "decisions": [d["decision"] for d in report["decisions"]],
                      "n_events": report["n_events"], "completion": report["completion"],
                      "net": agg["total_net_pnl"], "net_status": agg["total_net_status"],
                      "independent_agrees": recon["agrees"], "integrity_problems": book.summary()["integrity_problems"]},
                     indent=1))
except BaseException as e:                                                     # noqa: BLE001
    rd.failed(now_epoch=T, error=e)
    raise
