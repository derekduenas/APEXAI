"""THE SHADOW CONSUMER — Capital Arena meets real prospective candidates.

    V1  ->  neutral durable outbox  ->  cursor  ->  CAPITAL ARENA

V1 does not know this consumer exists, and no import runs the other
way. V1 writes what it decided; the arena reads it later and records
what it would have done instead. Baseline paper trading proceeds
regardless of the shadow answer, always.

PROSPECTIVE OR NOTHING. A decision is sealed from a candidate record
whose outcome is not yet known, and the outcome is appended afterwards
against that seal. A portfolio manager graded on decisions it made
after seeing the result is not a portfolio manager; it is a narrator
with a spreadsheet. The consumer therefore REFUSES any candidate
record that already carries an outcome.

THE SHADOW BOOK IS THE ARENA'S OWN. It funds against its own capital
and its own open positions, not V1's, because the whole question being
asked is what a different portfolio would have looked like.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apex.capital.arena import (Candidate, CapitalViolation,
                                PortfolioState, compete)
from apex.capital.counterfactual import seal_decision
from apex.ops.outbox import Cursor, consume

V1_OUTBOX = Path("results/outbox/v1_decisions.jsonl")
SHADOW_CURSOR = Path("results/capital/consumer_cursor.json")
ATTACK_LEDGER = Path("results/options_live_ledger.jsonl")

# THE GOVERNED CANDIDATE STATE. Not "attack_ready" -- that field has
# never existed. The arena missed both of Thursday's real attacks
# because this predicate was written from an assumed field name rather
# than the contract V1 actually writes, which is the same defect class
# as matching `kind` instead of `record_kind`.
CANDIDATE_VERDICT = "PAPER_ATTACKED"

# what a candidate record must carry before the arena will judge it
REQUIRED = ("evaluation_id", "symbol")

# fields whose presence proves the record is retrospective
OUTCOME_FIELDS = ("realized_pnl", "realized_r", "outcome", "exit_price",
                  "resolution")

STARTING_SHADOW_CAPITAL = 10_000.0


class ConsumerViolation(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_prospective(payload: dict) -> dict:
    """A candidate the market has already answered is not a decision."""
    present = [f for f in OUTCOME_FIELDS
               if payload.get(f) not in (None, "", "PENDING")]
    return {"prospective": not present,
            "outcome_fields_present": present,
            "why": ("no outcome present -- safe to seal" if not present
                    else f"record already carries {present}: sealing "
                         f"a decision against a known outcome would "
                         f"measure hindsight, not judgement")}


def is_candidate(record: dict) -> bool:
    """The governed state, read from the record V1 actually writes."""
    return (record.get("record_kind") == "options_evaluation"
            and (record.get("payload") or {}).get("verdict")
            == CANDIDATE_VERDICT)


def join_attack_card(payload: dict, *, ledger: Path | None = None,
                     decision_time: str | None = None) -> dict:
    """Recover declared risk from the SEALED attack card.

    V1 already records everything the arena needs -- declared_1R,
    expression, net_debit, geometry, card_hash -- in its own governed
    options_live_attack artifact. So the arena reads that instead of V1
    growing a new field for its benefit, and Options V1 is not touched.

    The join is (symbol, event_time == T): proven deterministic and
    one-to-one on both of Thursday's attacks.

    EVERY invariant is checked, and any failure yields NOT_ESTIMABLE
    rather than a guess. An arena that estimates a risk it could not
    read is worse than an arena that abstains.
    """
    path = Path(ledger) if ledger is not None else ATTACK_LEDGER
    sym, t = payload.get("symbol"), str(payload.get("event_time", ""))
    if not path.exists():
        return {"joined": False, "why": f"no attack ledger at {path}",
                "capital_decision": "NOT_ESTIMABLE"}

    cards = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (r.get("kind") == "options_live_attack"
                and r.get("symbol") == sym and str(r.get("T")) == t):
            cards.append(r)

    if len(cards) != 1:
        return {"joined": False, "matches": len(cards),
                "why": (f"join on ({sym}, {t}) matched {len(cards)} "
                        f"attack cards; exactly one is required and "
                        f"the arena will not guess which"),
                "capital_decision": "NOT_ESTIMABLE"}

    card = cards[0]
    if card.get("status") != CANDIDATE_VERDICT:
        return {"joined": False,
                "why": f"card status {card.get('status')!r} is not "
                       f"{CANDIDATE_VERDICT}",
                "capital_decision": "NOT_ESTIMABLE"}

    risk = card.get("declared_1R")
    if not isinstance(risk, (int, float)) or risk <= 0:
        return {"joined": False,
                "why": f"declared_1R {risk!r} is not a positive number",
                "capital_decision": "NOT_ESTIMABLE"}

    leaked = [f for f in OUTCOME_FIELDS
              if card.get(f) not in (None, "", "PENDING")]
    if leaked:
        return {"joined": False,
                "why": f"attack card carries outcome fields {leaked}: "
                       f"joining it would make the decision hindsight",
                "capital_decision": "NOT_ESTIMABLE"}

    if decision_time is not None and str(card.get("T")) > decision_time:
        return {"joined": False,
                "why": "attack card was sealed AFTER the capital "
                       "decision time; a decision cannot consume a "
                       "card that did not yet exist",
                "capital_decision": "NOT_ESTIMABLE"}

    return {"joined": True, "declared_risk": float(risk),
            "expression": card.get("expression", "UNKNOWN"),
            "net_debit": card.get("net_debit"),
            "card_hash": card.get("card_hash"),
            "card_T": card.get("T"),
            "law": "declared risk is READ from a sealed governed "
                   "artifact, never synthesized"}


def to_candidate(payload: dict, *, declared_risk=None,
                 expression: str | None = None) -> Candidate:
    """Build an arena candidate from a V1 evaluation record.

    Fields V1 never recorded stay UNKNOWN. The consumer may not invent
    a Greek, a correlation or a half-life to make its own reasoning
    look better informed than the evidence.
    """
    missing = [f for f in REQUIRED if not payload.get(f)]
    if missing:
        raise ConsumerViolation(
            f"candidate record lacks {missing}: the arena judges "
            f"recorded evidence, it does not fill gaps")

    risk = (declared_risk if declared_risk is not None
            else payload.get("declared_risk"))
    if not isinstance(risk, (int, float)) or risk <= 0:
        raise ConsumerViolation(
            "declared_risk absent or non-positive: without a 1R "
            "denominator there is nothing to allocate against. It is "
            "READ from the sealed attack card, never synthesized")

    return Candidate(
        candidate_id=str(payload["evaluation_id"]),
        symbol=str(payload["symbol"]),
        direction=str(payload.get("direction", "UNKNOWN")),
        expression=str(expression or payload.get("expression")
                       or "UNKNOWN"),
        declared_risk=float(risk),
        max_gain=payload.get("max_gain", "NOT_ESTIMABLE"),
        edge_pedigree=payload.get("edge_pedigree", "UNPROVEN"),
        signal_half_life_min=payload.get("signal_half_life_min",
                                         "NOT_ESTIMABLE"),
        capital_lockup_min=payload.get("capital_lockup_min",
                                       "NOT_ESTIMABLE"),
        execution_burden=payload.get("execution_burden",
                                     "NOT_ESTIMABLE"),
        catalyst_exposure=payload.get("catalyst_exposure", "UNKNOWN"),
        why_small_wins=payload.get("why_small_wins", "UNKNOWN"),
        entry_quality=payload.get("entry_quality", "UNKNOWN"))


def load_shadow_portfolio(path: Path | None = None) -> PortfolioState:
    """The arena's own book, rebuilt from its sealed decisions."""
    from apex.capital.counterfactual import LEDGER
    p = path or LEDGER
    if not p.exists():
        return PortfolioState(available_capital=STARTING_SHADOW_CAPITAL)
    funded, spent = [], 0.0
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") != "shadow_capital_decision":
            continue
        if r.get("shadow_action") in ("FUND", "PARTIALLY_FUND"):
            snap = r.get("portfolio_snapshot") or {}
            funded.append({"candidate_id": r.get("candidate_id"),
                           "symbol": r.get("symbol"),
                           "direction": snap.get("direction", "UNKNOWN"),
                           "beta_family": snap.get("beta_family",
                                                   "UNKNOWN"),
                           "sector": snap.get("sector", "UNKNOWN"),
                           "declared_risk": r.get("declared_risk", 0.0)})
            spent += float(r.get("declared_risk") or 0.0)
    return PortfolioState(
        available_capital=max(STARTING_SHADOW_CAPITAL - spent, 0.0),
        open_positions=funded)


def judge(payload: dict, *, session: str, portfolio: PortfolioState,
          session_minutes_left=None, catalyst_environment="UNKNOWN",
          ledger: Path | None = None,
          attack_ledger: Path | None = None) -> dict:
    """Seal one shadow decision against one prospective candidate.

    Risk comes from the sealed attack card. If the join cannot satisfy
    every invariant, the decision is recorded as NOT_ESTIMABLE -- a
    real, sealed state -- rather than estimated from nothing.
    """
    p = is_prospective(payload)
    if not p["prospective"]:
        raise ConsumerViolation(p["why"])

    decided = _now()
    join = join_attack_card(payload, ledger=attack_ledger,
                            decision_time=decided)
    if not join["joined"]:
        rec = seal_decision(
            session=session,
            candidate_id=str(payload.get("evaluation_id")),
            symbol=str(payload.get("symbol")),
            baseline_action=str(payload.get("verdict") or "UNKNOWN"),
            shadow_action="NOT_ESTIMABLE",
            reasons=[join["why"]],
            declared_risk=0.0,
            portfolio_snapshot={**portfolio.as_record(),
                                "join": join, "prospective": True},
            ledger=ledger)
        return {"kind": "shadow_judgement", "sealed": rec,
                "baseline_action": payload.get("verdict"),
                "shadow_action": "NOT_ESTIMABLE",
                "reasons": [join["why"]],
                "candidate_id": payload.get("evaluation_id"),
                "decision_time": decided,
                "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}

    cand = to_candidate(payload, declared_risk=join["declared_risk"],
                        expression=join["expression"])
    arena = compete(candidates=[cand], portfolio=portfolio,
                    session_minutes_left=session_minutes_left,
                    catalyst_environment=catalyst_environment)
    d = arena["decisions"][0]
    # the baseline action IS the governed verdict V1 sealed
    baseline = (payload.get("verdict") or payload.get("v1_action")
                or payload.get("action") or "UNKNOWN")

    sealed = seal_decision(
        session=session, candidate_id=cand.candidate_id,
        symbol=cand.symbol, baseline_action=str(baseline),
        shadow_action=d["action"], reasons=d["reasons"],
        declared_risk=cand.declared_risk,
        portfolio_snapshot={**portfolio.as_record(),
                            "direction": cand.direction,
                            "beta_family": cand.beta_family,
                            "sector": cand.sector,
                            "redundancy": d["redundancy"]["classification"],
                            "tail": d["tail_dependence"]["stress_behaviour"],
                            "opportunity_cost": d["opportunity_cost"],
                            "catalyst_environment": catalyst_environment,
                            "known_from": payload.get("known_from"),
                            "risk_source": "options_live_attack",
                            "card_hash": join["card_hash"],
                            "expression": join["expression"],
                            "prospective": True},
        ledger=ledger)
    return {"kind": "shadow_judgement", "sealed": sealed,
            "baseline_action": baseline, "shadow_action": d["action"],
            "reasons": d["reasons"], "candidate_id": cand.candidate_id,
            "decision_time": _now(),
            "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}


def run(*, session: str, outbox: Path | None = None,
        cursor_path: Path | None = None, ledger: Path | None = None,
        attack_ledger: Path | None = None,
        session_minutes_left=None,
        catalyst_environment: str = "UNKNOWN") -> dict:
    """Drain new V1 evaluations and seal a shadow decision for each.

    Uses the durable cursor, so a crashed consumer resumes rather than
    skipping. Errors on one record never stop the drain.
    """
    ob = outbox or V1_OUTBOX
    cur = Cursor(cursor_path or SHADOW_CURSOR, "capital_arena_shadow")
    judged, skipped, errors = [], 0, []

    def handle(record):
        nonlocal skipped
        payload = record.get("payload") or {}
        # the outbox wraps V1's kind as record_kind; `kind` is always
        # "outbox_record" and matching on it would drain nothing
        if not is_candidate(record):
            skipped += 1
            return 0
        portfolio = load_shadow_portfolio(ledger)
        try:
            judged.append(judge(
                payload, session=session, portfolio=portfolio,
                session_minutes_left=session_minutes_left,
                catalyst_environment=catalyst_environment,
                ledger=ledger, attack_ledger=attack_ledger))
            return 1
        except (ConsumerViolation, CapitalViolation) as e:
            # a malformed candidate is a finding about V1's record, not
            # a reason to stall the whole drain behind it forever
            errors.append(f"{payload.get('evaluation_id')}: "
                          f"{str(e)[:160]}")
            return 0

    result = consume(ob, cur, handle) if ob.exists() else {
        "records_processed": 0, "note": "outbox does not exist yet"}

    return {"kind": "capital_consumer_run", "session": session,
            "records_consumed": result.get("records_processed", 0),
            "drain": result,
            "judged": len(judged), "skipped_not_candidates": skipped,
            "errors": errors, "decisions": judged,
            "outbox": str(ob),
            "law": "V1 never waits for and never reads this consumer",
            "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}
