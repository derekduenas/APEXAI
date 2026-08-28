"""THE EVOLUTIONARY CIO — the drive to improve. No hands on anything.

Mandate: MAKE APEX ECONOMICALLY BETTER. Not: protect the architecture.

The CIO reads the whole organism -- book, refusals, census, board,
catalyst, cross-sleeve relations -- and produces DIRECTIVES: economic
attribution, the biggest current leak, and the highest-value research
question. EdgeForge then attacks whatever it proposes.

WHAT IT STRUCTURALLY CANNOT DO, asserted by test: place trades, alter
the funded portfolio, change production logic, spend capital, promote
anything, or exceed the research budget. A director who can also touch
the book is not a director; he is an unsupervised trader.

decision_power: RESEARCH_DIRECTION_ONLY.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

DIRECTIVES = Path("results/organism/cio_directives.jsonl")

AUTHORITY = "RESEARCH_DIRECTION_ONLY"

# The Evolutionary CIO's canonical identity (2026-08-28). Historical
# generic-CIO artifacts keep their names -- renaming sealed records
# would damage provenance for a cosmetic gain.
NAME = "AURELIUS"
TITLE = "AURELIUS — APEX Chief Investment & Evolution Officer"

# hard research budget -- no recursive agent explosion
MAX_ACTIVE_PRIMARY_HYPOTHESES = 5
MAX_COMPETING_AGENTS_PER_HYPOTHESIS = 4
MAX_ACTIVE_CHALLENGERS_PER_MECHANISM = 1

ATTRIBUTION_CLASSES = (
    "THESIS_FAILURE", "TIMING_FAILURE", "GEOMETRY_FAILURE",
    "CATALYST_INTERPRETATION_FAILURE", "EXPRESSION_FAILURE",
    "CAPITAL_ALLOCATION_FAILURE", "EXECUTION_FAILURE", "DATA_FAILURE",
    "NO_REAL_FAILURE")


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


def daily_directive(*, session: str,
                    book_ledger: Path | None = None,
                    board_ledger: Path | None = None,
                    ledger: Path | None = None) -> dict:
    """One sealed directive per session: what happened economically,
    where the biggest leak is, and what to learn next. Attribution is
    forced into named classes -- 'trade lost' is not an explanation."""
    from apex.organism import book as B

    st = B.state(ledger=book_ledger, session=session)
    rows = _rows(book_ledger or B.LEDGER)
    voided = {r["candidate_id"] for r in rows
              if r.get("kind") == "paper_funding_void"}
    fundings = [r for r in rows if r.get("kind") == "paper_funding"
                and r.get("session") == session
                and r["candidate_id"] not in voided]
    refusals = [r for r in rows if r.get("kind") == "paper_refusal"
                and r.get("session") == session]
    outcomes = {r["candidate_id"]: r for r in rows
                if r.get("kind") == "paper_outcome"
                and r.get("session") == session}

    attribution = Counter()
    for f in fundings:
        o = outcomes.get(f["candidate_id"])
        if not o:
            attribution["PENDING"] += 1
        elif o.get("outcome_class") in ATTRIBUTION_CLASSES:
            attribution[o["outcome_class"]] += 1
        else:
            attribution["NO_REAL_FAILURE" if
                        isinstance(o.get("executable_pnl"),
                                   (int, float))
                        and o["executable_pnl"] > 0
                        else "UNCLASSIFIED"] += 1

    refusal_stages = Counter(r.get("refused_at_stage")
                             for r in refusals)

    board = _rows(board_ledger
                  or Path("results/edgeforge/research_board.jsonl"))
    open_hyp = []
    for r in board:
        if r.get("kind") == "registered_hypothesis":
            open_hyp.append(r.get("id"))
    open_hyp = sorted(set(open_hyp))[:MAX_ACTIVE_PRIMARY_HYPOTHESES]

    # the biggest leak: the funnel stage refusing the most claims, or
    # the dominant loss attribution -- stated, never acted on
    leak = (refusal_stages.most_common(1)[0]
            if refusal_stages else ("NONE_OBSERVED", 0))

    rec = {"kind": "cio_directive", "cio": NAME,
           "session": session,
           "sealed_utc": datetime.now(timezone.utc).isoformat(),
           "book": {k: st[k] for k in
                    ("capital", "realized_pnl", "open_positions",
                     "open_risk", "resolved", "execution_failures")},
           "funded": len(fundings), "refused": len(refusals),
           "refusal_stages": dict(refusal_stages),
           "attribution": dict(attribution),
           "biggest_current_leak": {"stage": leak[0], "n": leak[1]},
           "open_hypotheses": open_hyp,
           "budget": {"max_primary": MAX_ACTIVE_PRIMARY_HYPOTHESES,
                      "in_use": len(open_hyp)},
           "highest_evi_question": (
               open_hyp[0] if open_hyp else "NONE_REGISTERED"),
           "authority": AUTHORITY,
           "cannot": ["trade", "alter the funded portfolio",
                      "change production logic", "spend capital",
                      "promote anything"],
           "law": "the CIO proposes; EdgeForge attacks; the operator "
                  "decides; the book never hears from either",
           "decision_power": AUTHORITY}
    chain_append(ledger or DIRECTIVES, rec)
    return rec
