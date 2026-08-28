"""THE ALLOCATOR — where the organism becomes one animal.

    SLEEVE CANDIDATES (Options, Equity, BTC)
            |
    CATALYST CONTEXT  (consulted, causal, never obeyed)
            |
    CAPITAL ARENA     (which claim deserves the next paper dollar)
            |
    RISK KERNEL       (can the book afford it -- arena cannot override)
            |
    PAPER BOOK        (fund / refuse, sealed either way)

FAIL CLOSED IS THE PRIME DIRECTIVE. If the arena cannot run, the
kernel cannot run, or the book cannot be read, NO new paper capital is
funded -- candidates are refused with the failure named. A capital
allocator that degrades to "fund anyway" is not an allocator; it is a
leak. Sleeves never wait on this organ and never learn its answer:
their own paper records continue regardless.

INCUMBENT LOGIC UNTOUCHED. This is wiring and authority, not trading
rules: no sleeve threshold, no arena rule, no catalyst prompt changes
here.

decision_power: PAPER_ALLOCATION_ONLY -- no real order surface exists
anywhere beneath this module, and none is added by it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.capital.arena import INDEX_FAMILY, PortfolioState, compete
from apex.catalyst import context as catalyst_context
from apex.governance.chain_ledger import chain_append
from apex.organism import book, candidate, risk_kernel
from apex.organism.cross_predator import SleeveObservation, assemble

DECISION_LEDGER = Path("results/organism/allocator_decisions.jsonl")

V1_OUTBOX = Path("results/outbox/v1_decisions.jsonl")
EQUITY_OUTBOX = Path("results/outbox/equity_shadow_decisions.jsonl")
BTC_LEDGER = Path("results/btc/paper_ledger.jsonl")


class AllocatorViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def gather_candidates(*, roots: dict | None = None) -> dict:
    """Adapt every sleeve's new attack records into envelopes.

    A record that cannot adapt is REPORTED, not skipped silently and
    not allowed to stall the others -- one malformed candidate is one
    malformed candidate.
    """
    r = roots or {}
    envs, errors = [], []

    def rows(path):
        p = Path(path)
        if not p.exists():
            return []
        out = []
        for line in p.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    for rec in rows(r.get("v1_outbox", V1_OUTBOX)):
        p = rec.get("payload") or {}
        if rec.get("record_kind") == "options_evaluation" \
                and p.get("verdict") == "PAPER_ATTACKED":
            try:
                envs.append(candidate.from_options(
                    rec, attack_ledger=r.get("attack_ledger")))
            except candidate.CandidateViolation as e:
                errors.append(f"OPTIONS {p.get('evaluation_id')}: {e}")

    for rec in rows(r.get("equity_outbox", EQUITY_OUTBOX)):
        p = rec.get("payload") or {}
        if rec.get("record_kind") == "equity_shadow_decision" \
                and p.get("decision") == "ATTACK_READY_SHADOW":
            try:
                envs.append(candidate.from_equity(rec))
            except candidate.CandidateViolation as e:
                errors.append(f"EQUITY {p.get('decision_id')}: {e}")

    for rec in rows(r.get("btc_ledger", BTC_LEDGER)):
        if rec.get("kind") == "btc_paper_decision" \
                and rec.get("cohort") in candidate.BTC_ATTACK_COHORTS:
            try:
                envs.append(candidate.from_btc(rec))
            except candidate.CandidateViolation as e:
                errors.append(f"BTC {rec.get('T')}: {e}")

    return {"candidates": envs, "adapter_errors": errors}


def cross_sleeve_relations(envs: list) -> list:
    """The organism should know when its organs agree, disagree, or
    are secretly the same bet. Reuses the commissioned cross-predator
    faculty rather than inventing a second redundancy opinion."""
    if len(envs) < 2:
        return []
    obs = [SleeveObservation(
        sleeve=e["sleeve"].lower(), subject=e["symbol"],
        T=str(e["known_from"]), direction_view=e["direction"],
        evidence_class="PROSPECTIVE_PAPER") for e in envs]
    try:
        ctx = assemble(obs)
        rels = getattr(ctx, "relations", None) or []
        return [getattr(x, "__dict__", x) for x in rels]
    except Exception as e:                              # noqa: BLE001
        return [{"cross_predator_error": f"{type(e).__name__}: {e}"}]


def allocate(envs: list, *, session: str,
             book_ledger: Path | None = None,
             decision_ledger: Path | None = None,
             catalyst_roots: dict | None = None,
             release_sha: str = "UNKNOWN") -> dict:
    """Run the full pipeline over new candidate envelopes.

    Every candidate ends in exactly one sealed state: FUNDED,
    PARTIALLY_FUNDED, REFUSED (with the refusing stage named), or
    DUPLICATE. Nothing exits unrecorded.
    """
    dl = decision_ledger or DECISION_LEDGER
    results = []

    # -------- FAIL CLOSED: prove the organs exist before any funding
    try:
        st = book.state(ledger=book_ledger, session=session)
        assert callable(compete) and callable(risk_kernel.check)
    except Exception as e:                              # noqa: BLE001
        for env in envs:
            book.refuse(env, stage="FAIL_CLOSED",
                        reasons=[f"allocator organs unavailable: "
                                 f"{type(e).__name__}: {e}"],
                        session=session, ledger=book_ledger)
            results.append({"candidate_id": env["candidate_id"],
                            "state": "REFUSED_FAIL_CLOSED"})
        return {"kind": "allocation_run", "session": session,
                "fail_closed": True, "results": results}

    relations = cross_sleeve_relations(envs)

    # cheapest-risk first: the cheapest way to learn goes first (the
    # arena's own incumbent ordering law)
    # idempotence FIRST: a candidate the book has already answered is
    # a redelivery, and counting it as a fresh arena/kernel refusal
    # would pollute the refusal statistics with transport noise
    answered = set()
    from apex.organism.book import _rows as _book_rows
    for r in _book_rows(book_ledger or book.LEDGER):
        if r.get("kind") in ("paper_funding", "paper_refusal"):
            answered.add(r.get("candidate_id"))

    for env in sorted(envs, key=lambda e: e["declared_risk"]):
        cid = env["candidate_id"]
        # THE FRESHNESS FENCE. A candidate from a prior session has a
        # publicly resolved outcome; funding it is hindsight wearing a
        # transport delay. Caught LIVE on first deployment: the initial
        # cursor drain delivered Thursday's attacks and the book funded
        # both. Prospective means the outcome CANNOT yet be known --
        # same-session or refused.
        cand_session = str(env["known_from"])[:10]
        if cand_session != str(session)[:10]:
            book.refuse(env, stage="STALE_CANDIDATE",
                        reasons=[f"candidate is from {cand_session}, "
                                 f"current session is {session}: its "
                                 f"outcome may already be knowable and "
                                 f"funding it would be hindsight"],
                        session=session, ledger=book_ledger)
            results.append({"candidate_id": cid,
                            "sleeve": env["sleeve"],
                            "symbol": env["symbol"],
                            "state": "REFUSED_STALE"})
            answered.add(cid)
            continue
        if cid in answered:
            results.append({"candidate_id": cid,
                            "sleeve": env["sleeve"],
                            "symbol": env["symbol"],
                            "state": "DUPLICATE"})
            continue
        answered.add(cid)
        st = book.state(ledger=book_ledger, session=session)

        ctx = None
        try:
            ctx = catalyst_context.context(
                symbol=env["symbol"], as_of=str(env["known_from"]),
                **(catalyst_roots or {}))
            environment = ctx["environment"]
        except Exception as e:                          # noqa: BLE001
            # Catalyst down degrades CONTEXT, never allocation: the
            # arena runs with UNKNOWN rather than the organism halting
            environment = "UNKNOWN"

        arena_pf = PortfolioState(
            available_capital=st["available_capital"],
            open_positions=[{**p, "declared_risk": p["funded_risk"],
                             "beta_family": INDEX_FAMILY.get(
                                 p["symbol"], "UNKNOWN")}
                            for p in st["positions"]])
        arena = compete(candidates=[candidate.arena_candidate(env)],
                        portfolio=arena_pf,
                        catalyst_environment=environment)
        d = arena["decisions"][0]

        if d["action"] not in ("FUND", "PARTIALLY_FUND"):
            book.refuse(env, stage="CAPITAL_ARENA",
                        reasons=d["reasons"], session=session,
                        ledger=book_ledger)
            state_out = f"REFUSED_ARENA_{d['action']}"
        else:
            fam = INDEX_FAMILY.get(env["symbol"], "UNKNOWN")
            k = risk_kernel.check(
                declared_risk=env["declared_risk"],
                symbol=env["symbol"], beta_family=fam,
                open_risk=st["open_risk"],
                same_underlying_risk=st["risk_by_symbol"].get(
                    env["symbol"], 0.0),
                same_family_risk=st["risk_by_family"].get(fam, 0.0),
                session_realized_pnl=st["session_realized_pnl"],
                available_capital=st["available_capital"])
            if not k["approved"]:
                book.refuse(env, stage="RISK_KERNEL",
                            reasons=k["refusals"], session=session,
                            ledger=book_ledger)
                state_out = "REFUSED_RISK_KERNEL"
            else:
                f = book.fund(env, arena_action=d["action"],
                              arena_reasons=d["reasons"], kernel=k,
                              catalyst_ctx=ctx, session=session,
                              release_sha=release_sha,
                              ledger=book_ledger)
                state_out = ("DUPLICATE" if f.get("duplicate")
                             else d["action"] + "ED"
                             if d["action"] == "FUND"
                             else "PARTIALLY_FUNDED")

        results.append({"candidate_id": cid, "sleeve": env["sleeve"],
                        "symbol": env["symbol"], "state": state_out})

    run = {"kind": "allocation_run", "session": session,
           "run_utc": _now(), "candidates": len(envs),
           "cross_sleeve_relations": relations,
           "results": results, "fail_closed": False,
           "release_sha": release_sha,
           "decision_power": "PAPER_ALLOCATION_ONLY"}
    chain_append(dl, run)
    return run
