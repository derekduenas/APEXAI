"""OPERATOR VIEW (M6) — a read-only rendering of PERSISTED records. No gauges, no fabricated fills.

`build_view(ledger, *, session_id, now_epoch, release, model_versions, feed_status)` returns a dict
whose every displayed forecast, intent, fill, outcome and refusal carries the ledger seq it came from,
so the operator can open the underlying record. `render_text` prints it. There is no service here:
the repository's previous loopback dashboard script is not present on this branch, so this module is
the view layer and a later reviewed change may serve it read-only."""
from __future__ import annotations

from datetime import datetime, timezone

from . import ledger as L
from . import session as S
from .book import load_book
from .fees import SYNTHETIC_FEES, UNVERIFIED_FEES


def _iso(e):
    return datetime.fromtimestamp(e, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(e, (int, float)) else None


def build_view(ledger, *, session_id: str, now_epoch: float, release: str, model_versions: dict | None = None,
               feed_status: dict | None = None, fee_schedule=None) -> dict:
    rows = L.read_all(ledger)
    fs = fee_schedule or SYNTHETIC_FEES
    book = load_book(ledger, session_id=session_id, rows=rows, fee_schedules={fs.schedule_id: fs, UNVERIFIED_FEES.schedule_id: UNVERIFIED_FEES})
    def rec(i):
        return {"seq": i + 1, "entry_hash": rows[i].get("entry_hash", "")[:12]}
    forecasts = [{**rec(i), "scan_id": r.get("scan_id"), "model_id": r.get("model_id"), "params_hash": r.get("params_hash"),
                  "location": r.get("location"), "scale": r.get("scale"), "nu": r.get("nu"), "reference": r.get("reference_time_utc"),
                  "provenance": r.get("data_provenance"), "validation": (r.get("validation_status") or "")[:60]}
                 for i, r in enumerate(rows) if r.get("kind") == "pilot_forecast" and r.get("session_id") == session_id][-10:]
    intents = [{**rec(i), "scan_id": r.get("scan_id"), "contract_id": r.get("contract_id"), "expression": r.get("expression"),
                "envelope": (r.get("risk_envelope") or {}).get("envelope_debit"), "risk": (r.get("risk") or {}).get("risk_provenance"),
                "expiry": r.get("expiry_utc")} for i, r in enumerate(rows) if r.get("kind") == "pilot_intent" and r.get("session_id") == session_id][-10:]
    fills = [{**rec(i), "scan_id": r.get("scan_id"), "status": r.get("status"), "decision": r.get("decision"), "price": r.get("price"),
              "net_debit": r.get("net_debit"), "fees": (r.get("fees_entry") or {}).get("total"), "why": (r.get("why") or "")[:80],
              "simulated": r.get("simulated"), "exit_due": (r.get("exit_schedule") or {}).get("exit_due_epoch")}
             for i, r in enumerate(rows) if r.get("kind") == "pilot_fill" and r.get("session_id") == session_id][-10:]
    outcomes = [{**rec(i), "scan_id": r.get("scan_id"), "status": r.get("status"), "attempt": r.get("attempt"), "pnl": r.get("pnl"),
                 "discharges": r.get("discharges_position"), "why": (r.get("why") or "")[:80]}
                for i, r in enumerate(rows) if r.get("kind") == "pilot_outcome" and r.get("session_id") == session_id][-10:]
    refusals = [{**rec(i), "scan_id": r.get("scan_id"), "stage": r.get("stage"), "reason": (r.get("reason") or "")[:100]}
                for i, r in enumerate(rows) if r.get("kind") == "pilot_refusal" and r.get("session_id") == session_id][-10:]
    decisions = [{**rec(i), "scan_id": r.get("scan_id"), "decision": r.get("decision"), "why": (r.get("why") or "")[:80]}
                 for i, r in enumerate(rows) if r.get("kind") == "pilot_decision" and r.get("session_id") == session_id][-10:]
    positions = [{"fill_seq": p["fill_seq"], "contract": p.get("symbol"), "debit": p["debit"], "attempts": p["valuation_attempts"],
                  "exit_exhausted": p["exit_exhausted"], "exit_due": (p.get("exit_schedule") or {}).get("exit_due_epoch")} for p in book.positions]
    last_feed_age = None
    if feed_status and isinstance(feed_status.get("last_bar_available_epoch"), (int, float)):
        last_feed_age = now_epoch - feed_status["last_bar_available_epoch"]
    return {"kind": "operator_view", "as_of_utc": _iso(now_epoch), "session_id": session_id, "release": release,
            "model_versions": model_versions or {"forecast": "NONE_LOADED"}, "feed": {**(feed_status or {"status": "NOT_CONNECTED"}), "last_bar_age_s": last_feed_age},
            "policy": {"exit": "EXIT_AT_HORIZON_15M_V1", "execution": "EXECUTION_POLICY_V1", "fee_schedule": fs.schedule_id, "fee_provenance": fs.provenance},
            "book": book.summary(), "reservations": book.reservations, "positions": positions,
            "unresolved_exits": [p for p in positions], "recent": {"forecasts": forecasts, "intents": intents, "fills": fills, "outcomes": outcomes,
                                                                    "refusals": refusals, "decisions": decisions},
            "process_health": {"records": len(rows), "chain_verified": _chain_ok(ledger, rows)},
            "law": "every item links to a persisted record by seq; nothing shown is computed without one"}


def _chain_ok(ledger, rows) -> bool:
    try:
        L.verify_chain(ledger, rows=rows); return True
    except L.LedgerRefused:
        return False


def render_text(view: dict) -> str:
    b = view["book"]
    lines = ["OPTIONS PILOT — operator view @ %s  session=%s  release=%s" % (view["as_of_utc"], view["session_id"], view["release"]),
             "feed: %s  last_bar_age_s=%s   models: %s" % (view["feed"].get("status"), view["feed"].get("last_bar_age_s"), view["model_versions"]),
             "policy: exit=%s exec=%s fees=%s(%s)" % (view["policy"]["exit"], view["policy"]["execution"], view["policy"]["fee_schedule"], view["policy"]["fee_provenance"]),
             "book: cash=%s reserved=%s open_cost=%s realized(session)=%s obligations=%s integrity=%s chain_ok=%s" % (
                 b["cash"], b["reserved"], b["open_cost"], b["session_realized_pnl"], b["outstanding"], b["integrity_problems"], view["process_health"]["chain_verified"])]
    for name, items in view["recent"].items():
        lines.append("-- %s (%d)" % (name, len(items)))
        for it in items:
            lines.append("   seq=%-5s %s" % (it["seq"], " ".join("%s=%s" % (k, v) for k, v in it.items() if k not in ("seq", "entry_hash"))))
    return "\n".join(lines)
