"""DIAGNOSTIC BASELINES — what Capital Arena and Catalyst must beat.

Predeclared 2026-08-29, BEFORE the evidence that will be judged against
them exists. Choosing a benchmark after seeing which way the results
lean is a compromised test; these are sealed now so "integrated and
sophisticated" can later be distinguished from "actually adds
incremental economic value".

THESE NEVER FUND ANYTHING. Each baseline is a counterfactual policy
computed beside every real allocation run and sealed as diagnostics;
the real paper book hears only from the real arena.

CAPITAL ARENA baselines:
    CASH                      fund nothing, ever
    EQUAL_RISK_ALL_ELIGIBLE   fund every kernel-passing candidate at
                              equal declared risk
    FIRST_VALID_CANDIDATE     fund only the first kernel-passing
                              candidate per run, in arrival order

CATALYST baseline:
    MARKET_ONLY               the decision context with no catalyst
                              information at all -- what the organism
                              would have known from price alone

decision_power: NONE_DIAGNOSTIC.
"""
from __future__ import annotations

from apex.organism import risk_kernel
from apex.organism.risk_certificate import certify

POLICIES = ("CASH", "EQUAL_RISK_ALL_ELIGIBLE", "FIRST_VALID_CANDIDATE")
CATALYST_BASELINE = "MARKET_ONLY"


def _kernel_ok(env: dict, book_state: dict) -> bool:
    from apex.capital.arena import INDEX_FAMILY
    fam = INDEX_FAMILY.get(env["symbol"], "UNKNOWN")
    k = risk_kernel.check(
        certificate=certify(expression=env["expression"],
                            direction=env["direction"],
                            declared_risk=env["declared_risk"],
                            sleeve_payload=env.get("sleeve_payload")),
        expression=env["expression"], direction=env["direction"],
        sleeve_payload=env.get("sleeve_payload"),
        open_certified_risk=book_state["open_certified_risk"],
        declared_risk=env["declared_risk"], symbol=env["symbol"],
        beta_family=fam,
        open_risk=book_state["open_risk"],
        same_underlying_risk=book_state["risk_by_symbol"].get(
            env["symbol"], 0.0),
        same_family_risk=book_state["risk_by_family"].get(fam, 0.0),
        session_realized_pnl=book_state["session_realized_pnl"],
        available_capital=book_state["available_capital"])
    return k["approved"]


def baseline_decisions(envs: list, book_state: dict) -> dict:
    """What each dumb-and-simple policy would have funded from this
    run's candidates. The SAME kernel constrains every policy -- the
    baselines compete on ALLOCATION intelligence, not on being allowed
    to ignore survival."""
    ordered = sorted(envs, key=lambda e: str(e["known_from"]))
    eligible = [e["candidate_id"] for e in ordered
                if _kernel_ok(e, book_state)]
    return {"kind": "baseline_diagnostics",
            "policies": {
                "CASH": {"funds": []},
                "EQUAL_RISK_ALL_ELIGIBLE": {"funds": eligible},
                "FIRST_VALID_CANDIDATE": {"funds": eligible[:1]}},
            "eligible_denominator": len(eligible),
            "presented": len(envs),
            "law": "diagnostic only -- no baseline ever funds the "
                   "real book; sealed beside the real decision so the "
                   "comparison can never be chosen after the fact",
            "decision_power": "NONE_DIAGNOSTIC"}
