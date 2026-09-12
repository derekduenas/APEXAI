"""REPRESENTATIVE-SCALE SYNTHETIC RUN through the real entry point (M6 commissioning evidence).

Runs N sessions of the pilot path on the twin-backed synthetic sources (SYNTHETIC_FIXTURE provenance,
certified risk authority, synthetic fee schedule), then independently recomputes counts, the Book,
the chain and record bindings. Prints a JSON summary; writes it next to the ledger. No network, no
service, no live ledger."""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.options_pilot import ledger as L                                       # noqa: E402
from apex.options_pilot.book import load_book                                    # noqa: E402
from apex.options_pilot.fees import SYNTHETIC_FEES                                # noqa: E402
from apex.options_pilot.operator_view import build_view                          # noqa: E402
from apex.options_pilot.synthetic_harness import SyntheticHarness, T0             # noqa: E402
from apex.pulse_options.sources import synthetic_twin_sources                    # noqa: E402
from scripts import options_paper_session as sess                                # noqa: E402


class _Prov:
    provenance = "SYNTHETIC_FIXTURE"

    def __init__(self, twin):
        self.twin = twin
        self.clock, self.risk_authority, self.fee_schedule, self.sleep_fn = twin.clock, twin.risk_authority, twin.fee_schedule, twin.sleep_fn

    def sources(self):
        return self.twin.sources()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--sessions", type=int, default=10)
    ap.add_argument("--symbols", default="SPY,QQQ,IWM")
    ap.add_argument("--cycles", type=int, default=3)
    a = ap.parse_args(argv)
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    led = out / "scale_ledger.jsonl"
    t0 = time.time()
    per_session = []
    for k in range(a.sessions):
        sid = "SCALE-%03d" % (k + 1)
        h = SyntheticHarness(led, session_id=sid, t0=T0 + k * 6 * 3600 + 3600 * 14.5, risk="certified")
        h.quotes.age = 1.0 if k % 4 else 20.0                                     # every 4th session: stale quotes -> WAIT
        twin = synthetic_twin_sources(clock=h.clock, quote_fn=h.quotes, exit_quote_fn=h.exit_quotes, chain_fn=h.chain_fn, sleep_fn=h.advance, seed=k + 1)
        argv2 = ["--ledger", str(led), "--out", str(out / ("report_%s.json" % sid)), "--symbols", a.symbols, "--minutes", str(a.cycles * 15),
                 "--interval-min", "15", "--pilot-boundary", "--pilot-session-id", sid, "--pilot-release", "scale-check"]
        rc = sess.main(argv2, pilot_sources=_Prov(twin))
        rep = json.loads((out / ("report_%s.json" % sid)).read_text())
        per_session.append({"session": sid, "rc": rc, "decisions": {d: sum(1 for x in rep["decisions"] if x["decision"] == d) for d in ("TRADE", "WAIT", "REFUSE")},
                            "completion": rep["completion"], "outstanding": rep["outstanding_obligations"], "cash": rep["book"]["cash"],
                            "integrity": rep["book"]["integrity_problems"], "cash_identity": rep["book"]["cash_identity"]["holds"]})
    rows = L.read_all(led)
    L.verify_chain(led, rows=rows)
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    # independent binding checks across the whole ledger
    problems = []
    intents = [(i + 1, r) for i, r in enumerate(rows) if r["kind"] == "pilot_intent"]
    for seq, it in intents:
        f = rows[it["forecast_ref"]["seq"] - 1]
        if f["kind"] != "pilot_forecast" or f["entry_hash"] != it["forecast_ref"]["entry_hash"] or f["forecast_id"] != it["forecast_ref"]["forecast_id"]:
            problems.append("intent seq %d forecast binding" % seq)
        if it["risk"].get("risk_provenance") != "CERTIFIED_KERNEL" or not it["risk"].get("kernel_check_at_commit", {}).get("approved"):
            problems.append("intent seq %d risk" % seq)
    for i, r in enumerate(rows):
        if r["kind"] == "pilot_fill":
            it = rows[r["intent_ref"]["seq"] - 1]
            if it["kind"] != "pilot_intent" or it["entry_hash"] != r["intent_ref"]["entry_hash"]:
                problems.append("fill seq %d intent binding" % (i + 1))
        if r["kind"] == "pilot_outcome":
            fl = rows[r["fill_ref"]["seq"] - 1]
            if fl["kind"] != "pilot_fill" or fl["entry_hash"] != r["fill_ref"]["entry_hash"]:
                problems.append("outcome seq %d fill binding" % (i + 1))
    book_all = load_book(led, session_id=None, rows=rows, fee_schedules={"SYNTHETIC_FEES_V1": SYNTHETIC_FEES})
    view = build_view(led, session_id=per_session[-1]["session"], now_epoch=T0 + 10 * 6 * 3600, release="scale-check", model_versions={"forecast": "EXP002_L ca04fc6e713e1a5c"},
                      feed_status={"status": "SYNTHETIC_FIXTURE"})
    ru = resource.getrusage(resource.RUSAGE_SELF)
    summary = {"sessions": a.sessions, "symbols": a.symbols.split(","), "cycles": a.cycles, "records": len(rows), "kinds": kinds,
               "per_session": per_session, "binding_problems": problems, "chain_verified": True,
               "book_all_sessions": {"cash": book_all.cash, "total_realized_pnl": book_all.total_realized_pnl, "positions_open": len(book_all.positions),
                                     "integrity_problems": book_all.problems, "cash_identity": book_all.cash_identity()},
               "operator_view_ok": view["process_health"]["chain_verified"], "elapsed_s": round(time.time() - t0, 2),
               "max_rss_bytes": ru.ru_maxrss * (1024 if sys.platform != "darwin" else 1), "ledger_bytes": led.stat().st_size,
               "provenance": "SYNTHETIC_FIXTURE", "evidence_class": "PROSPECTIVE_PAPER (synthetic orchestration, not market evidence)"}
    (out / "scale_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: summary[k] for k in ("sessions", "records", "kinds", "binding_problems", "chain_verified", "book_all_sessions", "elapsed_s", "max_rss_bytes", "ledger_bytes")}, indent=1, default=str))
    return 0 if not problems and not book_all.problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
