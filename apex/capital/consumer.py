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


def to_candidate(payload: dict) -> Candidate:
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

    risk = payload.get("declared_risk")
    if not isinstance(risk, (int, float)) or risk <= 0:
        raise ConsumerViolation(
            "declared_risk absent or non-positive: without a 1R "
            "denominator there is nothing to allocate against")

    return Candidate(
        candidate_id=str(payload["evaluation_id"]),
        symbol=str(payload["symbol"]),
        direction=str(payload.get("direction", "UNKNOWN")),
        expression=str(payload.get("expression", "UNKNOWN")),
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
          ledger: Path | None = None) -> dict:
    """Seal one shadow decision against one prospective candidate."""
    p = is_prospective(payload)
    if not p["prospective"]:
        raise ConsumerViolation(p["why"])

    cand = to_candidate(payload)
    arena = compete(candidates=[cand], portfolio=portfolio,
                    session_minutes_left=session_minutes_left,
                    catalyst_environment=catalyst_environment)
    d = arena["decisions"][0]
    baseline = payload.get("v1_action") or payload.get("action") \
        or "UNKNOWN"

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
                            "prospective": True},
        ledger=ledger)
    return {"kind": "shadow_judgement", "sealed": sealed,
            "baseline_action": baseline, "shadow_action": d["action"],
            "reasons": d["reasons"], "candidate_id": cand.candidate_id,
            "decision_time": _now(),
            "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}


def run(*, session: str, outbox: Path | None = None,
        cursor_path: Path | None = None, ledger: Path | None = None,
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
        if record.get("record_kind") != "options_evaluation" \
                or not payload.get("attack_ready"):
            skipped += 1
            return 0
        portfolio = load_shadow_portfolio(ledger)
        try:
            judged.append(judge(
                payload, session=session, portfolio=portfolio,
                session_minutes_left=session_minutes_left,
                catalyst_environment=catalyst_environment,
                ledger=ledger))
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
