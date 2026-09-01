"""THE PAPER BOOK — one organism, one capital state.

Every funded position across every sleeve lives here; sleeve ledgers
remain each specialist's own evidence, and this book is the canonical
answer to "what is the organism's paper capital doing right now".

Funding is IDEMPOTENT on candidate_id -- a redelivered outbox record or
a restart must never fund the same claim twice -- and outcomes are
APPENDED against sealed fundings, never merged into them.

NUMERIC INTEGRITY (BOOK_NUMERIC_INTEGRITY_V2). Every number written
here is validated at the write boundary, because this ledger is
append-only: a malformed value sealed into the chain cannot be edited
out afterwards, only annotated. One NaN executable_pnl silently
disabled both the session drawdown halt and the available-capital
check by propagating through state()'s sums, since NaN defeats every
comparison by returning False. Prevention at the write is the only
real fix; state() additionally REPORTS contamination it inherits from
records sealed before this contract existed, and never hides it by
dropping them -- a silently cleaned state would be a fabricated one.

decision_power: ACCOUNTING_ONLY -- the book records allocation, it
neither selects nor sizes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.capital.arena import INDEX_FAMILY
from apex.governance.chain_ledger import chain_append
from apex.organism.numeric_integrity import (require_book_numbers,
                                             scan_ledger_integrity)
from apex.organism.risk_kernel import STARTING_PAPER_CAPITAL

LEDGER = Path("results/organism/paper_book.jsonl")


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


def state(*, ledger: Path | None = None,
          session: str | None = None) -> dict:
    """The book, rebuilt from its ledger. Restart-safe by construction:
    the ledger IS the state, so reconciliation is a replay, not a
    guess."""
    rows = _rows(ledger or LEDGER)
    funded, outcomes, voided = {}, {}, set()
    for r in rows:
        if r.get("kind") == "paper_funding":
            funded[r["candidate_id"]] = r
        elif r.get("kind") == "paper_outcome":
            outcomes[r["candidate_id"]] = r
        elif r.get("kind") == "paper_funding_void":
            voided.add(r["candidate_id"])
    for cid in voided:                 # a voided funding never existed
        funded.pop(cid, None)          # economically; the record stays
        outcomes.pop(cid, None)        # as the correction's evidence

    open_pos, closed = [], []
    for cid, f in funded.items():
        (closed if cid in outcomes else open_pos).append(f)

    open_risk = sum(f["funded_risk"] for f in open_pos)
    realized = sum(o.get("executable_pnl") or 0.0
                   for o in outcomes.values()
                   if isinstance(o.get("executable_pnl"), (int, float)))
    sess_real = sum(
        o.get("executable_pnl") or 0.0 for o in outcomes.values()
        if isinstance(o.get("executable_pnl"), (int, float))
        and (session is None or o.get("session") == session))

    def _risk(pred):
        return sum(f["funded_risk"] for f in open_pos if pred(f))

    # CERTIFIED aggregate exposure. The semantically correct basis for
    # aggregate risk is a sum of verified BOUNDS, not a sum of labels
    # -- so only positions whose sealed certificate carries authority
    # contribute. Everything else is counted separately as research
    # exposure rather than being folded in at its label value, which
    # is exactly the accounting fiction that hid 148x leverage.
    def _er(f):
        er = f.get("economic_risk")
        return er if isinstance(er, dict) else {}

    certified_open = [f for f in open_pos
                      if _er(f).get("certified_risk_authority")
                      and isinstance(_er(f).get("certified_max_loss"),
                                     (int, float))]
    uncertified_open = [f for f in open_pos if f not in certified_open]
    open_certified_risk = sum(_er(f)["certified_max_loss"]
                              for f in certified_open)
    uncertified_notional = sum(
        _er(f).get("gross_notional") or 0.0 for f in uncertified_open)

    # Contamination is REPORTED, never repaired here. If a legacy row
    # carries a malformed number the aggregates above stay poisoned on
    # purpose, and RISK_INPUT_INTEGRITY_V2 refuses downstream -- which
    # is the fail-closed outcome. Dropping the row would produce a
    # clean-looking state that no longer describes the ledger.
    integrity = scan_ledger_integrity(rows)

    return {"kind": "paper_book_state", "as_of": _now(),
            "starting_capital": STARTING_PAPER_CAPITAL,
            "realized_pnl": round(realized, 2),
            "session_realized_pnl": round(sess_real, 2),
            "capital": round(STARTING_PAPER_CAPITAL + realized, 2),
            "open_positions": len(open_pos),
            "open_risk": round(open_risk, 2),
            "available_capital": round(
                STARTING_PAPER_CAPITAL + realized - open_risk, 2),
            "risk_by_symbol": {s: round(_risk(
                lambda f, s=s: f["symbol"] == s), 2)
                for s in {f["symbol"] for f in open_pos}},
            "risk_by_family": {fam: round(_risk(
                lambda f, fam=fam: INDEX_FAMILY.get(
                    f["symbol"], "UNKNOWN") == fam), 2)
                for fam in {INDEX_FAMILY.get(f["symbol"], "UNKNOWN")
                            for f in open_pos}},
            # sleeve_payload rides along because the per-trade outcome
            # join needs the attack-card hash it carries; a keep-list
            # that strips it is how the options attribution stayed
            # blind (the AURELIUS keep-list lesson, third occurrence)
            "positions": [{k: f.get(k) for k in
                           ("candidate_id", "sleeve", "symbol",
                            "direction", "expression", "funded_risk",
                            "sleeve_payload")}
                          for f in open_pos],
            "open_certified_risk": round(open_certified_risk, 2),
            "certified_aggregate_basis":
                "SUM_OF_VERIFIED_CERTIFIED_MAX_LOSS",
            "open_uncertified_positions": len(uncertified_open),
            "open_uncertified_notional": round(uncertified_notional, 2),
            "resolved": len(outcomes),
            "execution_failures": sum(
                1 for o in outcomes.values()
                if o.get("outcome_class") == "EXECUTION_FAILURE"),
            "integrity": integrity["integrity"],
            "integrity_violations": integrity["contaminated_records"],
            "decision_power": "ACCOUNTING_ONLY"}


def fund(env: dict, *, arena_action: str, arena_reasons: list,
         kernel: dict, catalyst_ctx: dict | None = None,
         session: str = "UNKNOWN", release_sha: str = "UNKNOWN",
         ledger: Path | None = None) -> dict:
    """Seal one funding. Idempotent: an already-funded candidate_id is
    a no-op, never a doubled position."""
    path = ledger or LEDGER
    if any(r.get("kind") == "paper_funding"
           and r.get("candidate_id") == env["candidate_id"]
           for r in _rows(path)):
        return {"kind": "paper_funding", "duplicate": True,
                "candidate_id": env["candidate_id"],
                "law": "a redelivered record is not a second position"}

    frac = 1.0 if arena_action == "FUND" else 0.5
    rec = {"kind": "paper_funding", "session": session,
           "candidate_id": env["candidate_id"],
           "sleeve": env["sleeve"], "symbol": env["symbol"],
           "direction": env["direction"],
           "expression": env["expression"],
           "declared_risk": env["declared_risk"],
           "funded_risk": round(env["declared_risk"] * frac, 2),
           "funding_fraction": frac,
           "arena_action": arena_action,
           "arena_reasons": arena_reasons,
           "risk_kernel": {"threshold_set": kernel["threshold_set"],
                           "approved": kernel["approved"]},
           # the BOUND is sealed beside the label, so the record can
           # never again be read as if declared_risk were the maximum
           # the organism could lose
           "economic_risk": kernel.get("economic_risk",
                                       {"certificate": "ABSENT"}),
           "risk_warnings": kernel.get("warnings", []),
           "catalyst_context": ({k: catalyst_ctx[k] for k in
                                 ("directional_support", "environment",
                                  "events_known",
                                  "reaction_disagreements")}
                                if catalyst_ctx else "UNAVAILABLE"),
           "known_from": env["known_from"],
           "funded_utc": _now(), "release_sha": release_sha,
           "sleeve_payload": env["sleeve_payload"],
           "prospective": True, "outcome": "PENDING",
           "decision_power": "ACCOUNTING_ONLY"}
    require_book_numbers(rec)
    return chain_append(path, rec)


def refuse(env: dict, *, stage: str, reasons: list,
           session: str = "UNKNOWN",
           ledger: Path | None = None) -> dict:
    """A refusal is first-class evidence -- sealed with the same care
    as a funding, because refusal value is measured, not assumed.

    Deliberately NOT numerically validated: a malformed declared_risk
    is frequently the REASON for the refusal, and a validator here
    would make the organism unable to record the very defect it just
    caught. Refusals record; only fundings commit capital."""
    rec = {"kind": "paper_refusal", "session": session,
           "candidate_id": env["candidate_id"], "sleeve": env["sleeve"],
           "symbol": env["symbol"], "direction": env["direction"],
           "declared_risk": env["declared_risk"],
           # the exact value as it arrived, so a malformed size stays
           # legible even where the numeric field cannot represent it
           "declared_risk_repr": repr(env["declared_risk"]),
           "refused_at_stage": stage, "reasons": reasons,
           "known_from": env["known_from"], "refused_utc": _now(),
           "decision_power": "ACCOUNTING_ONLY"}
    return chain_append(ledger or LEDGER, rec)


def attach_outcome(*, candidate_id: str, session: str,
                   executable_pnl, outcome_class: str,
                   detail: dict | None = None,
                   ledger: Path | None = None) -> dict:
    """Append what the market answered. EXECUTION_FAILURE keeps
    NOT_ESTIMABLE -- it is the absence of a market, not a zero."""
    rec = {"kind": "paper_outcome", "session": session,
           "candidate_id": candidate_id,
           "executable_pnl": executable_pnl,
           "outcome_class": outcome_class,
           "detail": detail or {},
           "attached_utc": _now(),
           "law": "appended against a sealed funding, never merged",
           "decision_power": "ACCOUNTING_ONLY"}
    require_book_numbers(rec, allow_not_estimable=True)
    return chain_append(ledger or LEDGER, rec)


def void_funding(*, candidate_id: str, why: str,
                 ledger: Path | None = None) -> dict:
    """Append-only correction: the funding record stays in the chain,
    and this record removes it from the ECONOMIC state. Used when a
    funding is discovered to have violated the prospective law -- the
    one thing the book must never contain is a position whose outcome
    was knowable at funding time."""
    rec = {"kind": "paper_funding_void", "candidate_id": candidate_id,
           "why": why, "voided_utc": _now(),
           "law": "corrections append; history is never rewritten",
           "decision_power": "ACCOUNTING_ONLY"}
    return chain_append(ledger or LEDGER, rec)
