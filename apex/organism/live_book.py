"""THE LIVE BOOK — broker execution accounting. NO ORDER SURFACE.

TRUTH HIERARCHY (constitutional, in order):
    1. BROKER FILLS        what actually executed (Robinhood records)
    2. SEALED INTENTS      what APEX asked for, before outcomes
    3. MODELS              everything else

The paper book models execution; this book records it. They are
permanently labeled, never merged, and their divergence on the same
candidate IS the execution evidence tiny-live exists to buy.

THIS MODULE CANNOT PLACE ORDERS. It contains no broker client, no MCP
transport, no network call. Orders happen in the operator's session,
per approved intent, one at a time. This file is a ledger and a gate.

THE ELIGIBILITY LAW (operator-sealed 2026-08-29):
    CLOSING THE LIVE PRECONDITIONS MAKES TINY_LIVE ELIGIBLE.
    IT DOES NOT AUTOMATICALLY CREATE OR REQUIRE A REAL TRADE.
A first real order must ADDITIONALLY be: generated naturally by the
frozen authorized sleeve; valid under incumbent decision logic; passed
through the canonical Arena/Kernel path; attributable end-to-end;
previewed against the broker; minimum practical size; explicitly
approved by the human operator; reconciled from actual broker fills.
No synthetic trade is ever generated to test the pipe. If there is no
valid candidate, we wait.

decision_power: LIVE_EXECUTION_ACCOUNTING_ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

AUTHORITY = "LIVE_EXECUTION_ACCOUNTING_ONLY"
REAL_ORDER_AUTHORITY = "NONE"          # and no code path can change it

INTENTS = Path("results/live/intents.jsonl")
FILLS = Path("results/live/fills.jsonl")

NATURAL_STREAMS = ("options_evaluation", "equity_shadow_decision",
                   "btc_paper_decision")

FIRST_TRADE_CHECKLIST = (
    "NATURAL_CANDIDATE_FROM_FROZEN_SLEEVE",
    "VALID_UNDER_INCUMBENT_LOGIC",
    "PASSED_CANONICAL_ARENA_KERNEL_PATH",
    "ATTRIBUTABLE_END_TO_END",
    "BROKER_PREVIEWED",
    "MINIMUM_PRACTICAL_SIZE",
    "HUMAN_OPERATOR_APPROVED",
    "RECONCILED_FROM_ACTUAL_BROKER_FILLS")


class LiveBookViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ------------------------------------------------------------ intents

def seal_intent(*, candidate_id: str, sleeve: str, symbol: str,
                expression: str, direction: str,
                source_stream: str, known_from: str,
                declared_risk: float, max_loss_dollars: float,
                broker_preview: dict, operator_approved: bool,
                card_hash: str | None = None,
                ledger: Path | None = None) -> dict:
    """Seal ONE approved execution intent. Refuses anything synthetic:
    the candidate must name its canonical stream, its provenance, and
    carry explicit human approval. An intent is a record of permission
    for one order -- it places nothing."""
    if source_stream not in NATURAL_STREAMS:
        raise LiveBookViolation(
            f"source_stream {source_stream!r} is not a canonical "
            f"sleeve stream: no synthetic trade is ever generated to "
            f"test the pipe. If there is no valid candidate, we wait.")
    if not operator_approved:
        raise LiveBookViolation(
            "operator_approved must be explicitly True -- eligibility "
            "is not a trigger, and code cannot approve itself")
    if not isinstance(max_loss_dollars, (int, float)) \
            or max_loss_dollars <= 0:
        raise LiveBookViolation(
            "max_loss_dollars must be a positive number known BEFORE "
            "the order -- a live order without a bounded loss is not "
            "tiny-live, it is gambling with extra steps")
    if not isinstance(broker_preview, dict) or not broker_preview:
        raise LiveBookViolation(
            "broker_preview is required: the order must have been "
            "previewed against the broker before approval")
    path = ledger or INTENTS
    if any(r.get("candidate_id") == candidate_id
           and r.get("kind") == "live_intent" for r in _rows(path)):
        return {"kind": "live_intent", "duplicate": True,
                "candidate_id": candidate_id}
    rec = {"kind": "live_intent", "candidate_id": candidate_id,
           "sleeve": sleeve, "symbol": symbol,
           "expression": expression, "direction": direction,
           "source_stream": source_stream, "card_hash": card_hash,
           "known_from": str(known_from),
           "declared_risk": float(declared_risk),
           "max_loss_dollars": float(max_loss_dollars),
           "broker_preview": broker_preview,
           "operator_approved": True,
           "approved_utc": _now(),
           "status": "APPROVED_AWAITING_EXECUTION",
           "checklist": list(FIRST_TRADE_CHECKLIST),
           "truth_hierarchy": "broker fills > sealed intents > models",
           "decision_power": AUTHORITY}
    return chain_append(path, rec)


# ------------------------------------------------------------- fills

def reconcile(*, broker_fills: list, session: str,
              intents_ledger: Path | None = None,
              fills_ledger: Path | None = None) -> dict:
    """Join broker-reported fills onto sealed intents. Broker numbers
    are TRUTH; APEX numbers are the model being tested. Matching is
    one-to-one on (symbol, expression side); any ambiguity or orphan
    is sealed UNRECONCILED and surfaced -- never guessed, never
    dropped, never netted into a plausible-looking figure."""
    ipath = intents_ledger or INTENTS
    fpath = fills_ledger or FILLS
    intents = [r for r in _rows(ipath) if r.get("kind") == "live_intent"
               and not r.get("duplicate")]
    already = {r.get("broker_ref") for r in _rows(fpath)}
    matched = unmatched = dup = 0
    for f in broker_fills:
        ref = str(f.get("broker_ref") or f.get("order_id") or "")
        if not ref:
            unmatched += 1
            chain_append(fpath, {
                "kind": "live_fill_unreconciled", "session": session,
                "why": "broker fill carries no order reference",
                "fill": f, "decision_power": AUTHORITY})
            continue
        if ref in already:
            dup += 1
            continue
        cands = [i for i in intents
                 if i["symbol"] == f.get("symbol")
                 and (f.get("expression") is None
                      or i["expression"] == f.get("expression"))]
        if len(cands) != 1:
            unmatched += 1
            chain_append(fpath, {
                "kind": "live_fill_unreconciled", "session": session,
                "broker_ref": ref,
                "why": f"matched {len(cands)} intents; exactly one "
                       f"required -- reconciliation will not guess",
                "fill": f, "decision_power": AUTHORITY})
            continue
        i = cands[0]
        matched += 1
        already.add(ref)
        chain_append(fpath, {
            "kind": "live_fill", "session": session,
            "broker_ref": ref, "candidate_id": i["candidate_id"],
            "sleeve": i["sleeve"], "symbol": f.get("symbol"),
            "expression": i["expression"],
            "side": f.get("side"), "quantity": f.get("quantity"),
            "fill_price": f.get("price"),
            "fill_time": f.get("time"),
            "broker_realized_pnl": f.get("realized_pnl",
                                         "NOT_YET_REALIZED"),
            "modeled_reference": {
                "declared_risk": i["declared_risk"],
                "max_loss_dollars": i["max_loss_dollars"],
                "preview": i.get("broker_preview")},
            "truth": "BROKER -- this row outranks every model",
            "decision_power": AUTHORITY})
    return {"kind": "live_reconciliation", "session": session,
            "fills_presented": len(broker_fills),
            "matched": matched, "unreconciled": unmatched,
            "duplicates_skipped": dup,
            "law": "unreconciled rows are surfaced, never guessed; "
                   "live and paper books are never merged",
            "decision_power": AUTHORITY}


# ------------------------------------------------------------- state

def state(*, intents_ledger: Path | None = None,
          fills_ledger: Path | None = None) -> dict:
    intents = [r for r in _rows(intents_ledger or INTENTS)
               if r.get("kind") == "live_intent"
               and not r.get("duplicate")]
    fills = _rows(fills_ledger or FILLS)
    realized = [f.get("broker_realized_pnl") for f in fills
                if f.get("kind") == "live_fill"
                and isinstance(f.get("broker_realized_pnl"),
                               (int, float))]
    return {"kind": "live_book_state", "as_of": _now(),
            "intents": len(intents),
            "fills": sum(1 for f in fills
                         if f.get("kind") == "live_fill"),
            "unreconciled": sum(1 for f in fills if f.get("kind")
                                == "live_fill_unreconciled"),
            "broker_realized_pnl": (round(sum(realized), 2)
                                    if realized else "NOT_ESTIMABLE"),
            "law": "broker fills are truth; this book and the paper "
                   "book are never merged into one P&L history",
            "real_order_authority": REAL_ORDER_AUTHORITY,
            "decision_power": AUTHORITY}
