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
RISK_POLICY = Path("results/live/risk_policy.json")

# THE LIVE FITNESS GATE (authority semantics, operator-ratified):
#   CANONICAL STRATEGY sets the ceiling (thesis, expression, declared
#   risk). LIVE FITNESS may only REFUSE or REDUCE. It can NEVER
#   increase canonical risk, and it NEVER reads the broker at decision
#   time -- account equity enters only as the operator-attested figure
#   in the approved preview snapshot.
#
# POLICY SHAPE (operator decision 2026-08-29): TWO ABSOLUTE-DOLLAR
# CEILINGS, deliberately NOT scaled by account equity -- funding the
# account with more cash is never permission for more experimental
# risk. The account exists to buy EXECUTION LESSONS whose expected
# cost is friction; the ceilings bound the tail:
#   max_loss_per_intent_dollars   ceiling per intent, tracks the
#                                 INSTRUMENT (one-contract quantum)
#   experiment_budget_dollars     worst-case total for the ENTIRE
#                                 tiny-live phase; exhaustion forces
#                                 operator review, never a quiet reset
# Open intents count against the budget as COMMITTED worst-case until
# resolved -- otherwise two simultaneous intents could pass a budget
# neither violates alone. Any increase is a separate operator decision.
REDUCE_ONLY_TOLERANCE = 0.02           # matches the 1R monitoring tol

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


# ------------------------------------------------------- risk policy

def seal_risk_policy(*, max_loss_per_intent_dollars: float,
                     experiment_budget_dollars: float,
                     sealed_by_operator: bool,
                     policy_path: Path | None = None) -> dict:
    """The operator's tiny-live ceilings, sealed before any intent.
    Absolute dollars by design: the experiment's risk never inflates
    with account funding."""
    if not sealed_by_operator:
        raise LiveBookViolation(
            "the live risk policy is an operator decision; code "
            "cannot seal it for itself")
    if not (isinstance(max_loss_per_intent_dollars, (int, float))
            and max_loss_per_intent_dollars > 0
            and isinstance(experiment_budget_dollars, (int, float))
            and experiment_budget_dollars
            >= max_loss_per_intent_dollars):
        raise LiveBookViolation(
            "ceilings must be positive and the experiment budget must "
            "afford at least one worst-case intent")
    path = policy_path or RISK_POLICY
    rec = {"kind": "live_risk_policy",
           "max_loss_per_intent_dollars":
           float(max_loss_per_intent_dollars),
           "experiment_budget_dollars":
           float(experiment_budget_dollars),
           "meaning": "CEILINGS for an execution experiment, never "
                      "capital-allocation targets; funding level is "
                      "not permission; increases are a separate "
                      "operator decision after review",
           "sealed_utc": _now(), "sealed_by_operator": True,
           "decision_power": AUTHORITY}
    chain_append(path, rec)
    return rec


def experiment_exposure(*, intents_ledger: Path | None = None,
                        fills_ledger: Path | None = None) -> dict:
    """Realized live losses + committed worst-case of unresolved
    intents. Open intents COUNT -- two simultaneous intents must not
    pass a budget neither violates alone."""
    intents = [r for r in _rows(intents_ledger or INTENTS)
               if r.get("kind") == "live_intent"
               and not r.get("duplicate")]
    fills = _rows(fills_ledger or FILLS)
    resolved_ids = {f.get("candidate_id") for f in fills
                    if f.get("kind") == "live_fill"
                    and isinstance(f.get("broker_realized_pnl"),
                                   (int, float))}
    realized_losses = -sum(
        min(0.0, f["broker_realized_pnl"]) for f in fills
        if f.get("kind") == "live_fill"
        and isinstance(f.get("broker_realized_pnl"), (int, float)))
    committed = sum(i["max_loss_dollars"] for i in intents
                    if i["candidate_id"] not in resolved_ids)
    return {"realized_losses": round(realized_losses, 2),
            "committed_open_worst_case": round(committed, 2),
            "total_at_risk": round(realized_losses + committed, 2)}


def _load_policy(policy_path: Path | None = None) -> dict:
    path = policy_path or RISK_POLICY
    rows = _rows(path)
    pol = [r for r in rows if r.get("kind") == "live_risk_policy"]
    if not pol:
        raise LiveBookViolation(
            "no sealed live risk policy exists -- the gate FAILS "
            "CLOSED. Seal one with seal_risk_policy() (operator "
            "decision) before any intent.")
    return pol[-1]                       # latest sealed policy governs


# ------------------------------------------------------------ intents

def seal_intent(*, candidate_id: str, sleeve: str, symbol: str,
                expression: str, direction: str,
                source_stream: str, known_from: str,
                declared_risk: float, max_loss_dollars: float,
                account_equity_at_approval: float,
                broker_preview: dict, operator_approved: bool,
                card_hash: str | None = None,
                ledger: Path | None = None,
                policy_path: Path | None = None) -> dict:
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

    # ---- THE LIVE FITNESS GATE: refuse or reduce, never increase.
    if max_loss_dollars > declared_risk * (1 + REDUCE_ONLY_TOLERANCE):
        raise LiveBookViolation(
            f"REDUCE-ONLY VIOLATION: live max loss "
            f"{max_loss_dollars} exceeds canonical declared risk "
            f"{declared_risk} -- live execution can never increase "
            f"canonical authority")
    if not isinstance(account_equity_at_approval, (int, float)) \
            or account_equity_at_approval <= 0:
        raise LiveBookViolation(
            "account_equity_at_approval must be the positive, "
            "operator-attested Agentic equity from the approval "
            "moment -- the gate never reads the broker itself")
    pol = _load_policy(policy_path)
    path = ledger or INTENTS

    def _refuse(refusal, why, extra=None):
        rec = {"kind": "live_intent_refused", "refusal": refusal,
               "candidate_id": candidate_id, "sleeve": sleeve,
               "symbol": symbol, "expression": expression,
               "max_loss_dollars": float(max_loss_dollars),
               "account_equity_at_approval":
               float(account_equity_at_approval),
               "why": why, "refused_utc": _now(),
               "decision_power": AUTHORITY}
        rec.update(extra or {})
        chain_append(path, rec)
        return rec

    if max_loss_dollars > pol["max_loss_per_intent_dollars"]:
        # a natural candidate the experiment cannot safely express is
        # REFUSED for live, first-class -- while paper continues.
        return _refuse(
            "REFUSED_LIVE_MIN_SIZE",
            "minimum executable size exceeds the sealed per-intent "
            "ceiling; live yields, paper continues",
            {"per_intent_ceiling":
             pol["max_loss_per_intent_dollars"]})
    exp = experiment_exposure(intents_ledger=path,
                              fills_ledger=None)
    if exp["total_at_risk"] + max_loss_dollars \
            > pol["experiment_budget_dollars"]:
        return _refuse(
            "REFUSED_LIVE_BUDGET",
            "realized losses plus committed open worst-case plus "
            "this intent would exceed the sealed experiment budget; "
            "exhaustion forces operator review, never a quiet reset",
            {"experiment_budget":
             pol["experiment_budget_dollars"],
             "exposure_before_intent": exp})
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
