"""THE AUTHORITY LADDER -- five explicit levels, explicit transitions.

Operator doctrine (2026-08-21): "Paper early. Real money late." APEX is
a small-account predator that learns by attacking safely in paper -- as
long as sandbox learning is never confused with proof. The old binary
(NO AUTHORITY vs LIVE SEALED) becomes a ladder:

    OBSERVE             watch, decide, seal cards -- no orders anywhere
    PAPER_EXPLORATORY   real APEX opportunities may generate PAPER orders;
                        tracked like real trades; NOT eligible for
                        live-capital promotion; not proof of edge
    PAPER_AUTHORIZED    forecast gates passed + Capital formally approved
                        + expression auction won + risk sized -- the
                        cohort that can eventually argue for real money
    TINY_LIVE           small real capital, earned
    LIVE_SCALE          scaled only because APEX earned it

EVERY transition is an explicit operator-authorized record in the
transition ledger. Code may never self-promote. The CURRENT level is
whatever the last valid transition says -- and with no ledger at all,
the level is OBSERVE, forever, by construction.

COMMISSIONING_TEST orders are infrastructure tests, permitted at any
level, and never enter strategy performance.
"""
from __future__ import annotations

import json
from pathlib import Path

LEVELS = ("OBSERVE", "PAPER_EXPLORATORY", "PAPER_AUTHORIZED",
          "TINY_LIVE", "LIVE_SCALE")

LEDGER = Path("results/governance/authority_transitions.jsonl")


class AuthorityViolation(RuntimeError):
    pass


def current_level() -> str:
    """The last valid transition's target; OBSERVE when none exists."""
    if not LEDGER.exists():
        return "OBSERVE"
    level = "OBSERVE"
    for line in LEDGER.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (r.get("kind") == "authority_transition"
                and r.get("to") in LEVELS
                and r.get("operator_authorization")):
            level = r["to"]
    return level


def record_transition(*, to: str, operator_authorization: str,
                      evidence: str, now) -> dict:
    """Append one explicit transition. `operator_authorization` must be
    the operator's actual authorizing statement (quoted), never a
    paraphrase invented by code. Only adjacent-step promotions are
    allowed; demotion to any lower level is always allowed (safety)."""
    if to not in LEVELS:
        raise AuthorityViolation(f"unknown level {to!r}")
    if not operator_authorization or len(operator_authorization) < 10:
        raise AuthorityViolation(
            "a transition requires the operator's actual authorizing "
            "statement")
    cur = current_level()
    if LEVELS.index(to) > LEVELS.index(cur) + 1:
        raise AuthorityViolation(
            f"{cur} -> {to} skips a level; promotions are one step at a "
            f"time, each earned separately")
    from apex.governance.chain_ledger import chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    return chain_append(LEDGER, {
        "kind": "authority_transition", "from": cur, "to": to,
        "operator_authorization": operator_authorization,
        "evidence": evidence, "at": str(pd.Timestamp(now)),
    })


def may_submit(mode: str) -> bool:
    """May an order of `mode` be submitted at the current level?
    COMMISSIONING_TEST is infrastructure and allowed everywhere; paper
    modes require their ladder level; live modes have NO code path at
    all (there is deliberately no LIVE order mode in the paper harness)."""
    cur = current_level()
    if mode == "COMMISSIONING_TEST":
        return True
    if mode == "PAPER_EXPLORATORY":
        return LEVELS.index(cur) >= LEVELS.index("PAPER_EXPLORATORY")
    if mode == "PAPER_AUTHORIZED":
        return LEVELS.index(cur) >= LEVELS.index("PAPER_AUTHORIZED")
    return False
