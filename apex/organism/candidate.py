"""ONE CANDIDATE ENVELOPE — three sleeves, one competition.

Every sleeve keeps its own decision record, its own ledger and its own
vocabulary; the organism does not flatten specialists into a lowest
common denominator. What it needs is narrower: enough shared fields for
Capital Arena to compare a SPY call vertical, an NVDA stock long and a
BTC perp attack AS CLAIMS ON THE SAME PAPER DOLLAR.

Adapters read what each sleeve ACTUALLY writes -- learned three times
over (`record_kind`, `attack_ready`, `action`): build from captured
records, never from memory of a schema.

decision_power: NONE -- an adapter converts, it decides nothing.
"""
from __future__ import annotations

from apex.capital.arena import Candidate

SLEEVES = ("OPTIONS", "EQUITY", "BTC")


class CandidateViolation(RuntimeError):
    pass


def _base(payload: dict, *, sleeve: str, candidate_id: str,
          symbol: str, direction: str, expression: str,
          declared_risk: float, known_from, event_time,
          extra: dict) -> dict:
    if not isinstance(declared_risk, (int, float)) or declared_risk <= 0:
        raise CandidateViolation(
            f"{sleeve} candidate {candidate_id}: declared risk "
            f"{declared_risk!r} is not a positive number -- without a "
            f"1R denominator there is no claim on capital")
    return {"kind": "opportunity_candidate", "sleeve": sleeve,
            "candidate_id": candidate_id, "symbol": symbol,
            "direction": direction, "expression": expression,
            "declared_risk": float(declared_risk),
            "known_from": str(known_from), "event_time": str(event_time),
            "prospective": True, "sleeve_payload": extra,
            "decision_power": "NONE"}


def arena_candidate(env: dict) -> Candidate:
    """The competition object Capital Arena already understands."""
    p = env["sleeve_payload"]
    return Candidate(
        candidate_id=env["candidate_id"], symbol=env["symbol"],
        direction=env["direction"], expression=env["expression"],
        declared_risk=env["declared_risk"],
        edge_pedigree=p.get("edge_pedigree", "UNPROVEN"),
        entry_quality=p.get("entry_quality", "UNKNOWN"),
        catalyst_exposure=p.get("catalyst_exposure", "UNKNOWN"),
        capital_lockup_min=p.get("capital_lockup_min", "NOT_ESTIMABLE"),
        signal_half_life_min=p.get("signal_half_life_min",
                                   "NOT_ESTIMABLE"))


# ------------------------------------------------------------ OPTIONS

def from_options(outbox_record: dict, *, attack_ledger=None) -> dict:
    """V1's governed candidate state is verdict == PAPER_ATTACKED; the
    risk lives in the sealed attack card, joined -- never synthesized."""
    from apex.capital.consumer import join_attack_card
    p = outbox_record.get("payload") or {}
    if p.get("verdict") != "PAPER_ATTACKED":
        raise CandidateViolation("not a PAPER_ATTACKED record")
    j = join_attack_card(p, ledger=attack_ledger)
    if not j.get("joined"):
        raise CandidateViolation(f"attack-card join failed: {j['why']}")
    return _base(p, sleeve="OPTIONS",
                 candidate_id=str(p["evaluation_id"]),
                 symbol=str(p["symbol"]), direction=str(p["direction"]),
                 expression=j["expression"],
                 declared_risk=j["declared_risk"],
                 known_from=outbox_record.get("known_from"),
                 event_time=p.get("event_time"),
                 extra={"entry_quality": p.get("entry_quality",
                                               "UNKNOWN"),
                        "chase_risk": p.get("chase_risk"),
                        "card_hash": j.get("card_hash"),
                        "net_debit": j.get("net_debit"),
                        "risk_source": "options_live_attack"})


# ------------------------------------------------------------- EQUITY

def from_equity(outbox_record: dict) -> dict:
    """The Equity sleeve's sealed shadow attack carries everything."""
    p = outbox_record.get("payload") or {}
    if p.get("decision") != "ATTACK_READY_SHADOW":
        raise CandidateViolation("not an ATTACK_READY_SHADOW record")
    return _base(p, sleeve="EQUITY",
                 candidate_id=str(p["decision_id"]),
                 symbol=str(p["symbol"]), direction=str(p["direction"]),
                 expression="STOCK",
                 declared_risk=p.get("declared_1R"),
                 known_from=p.get("known_from"),
                 event_time=p.get("event_time"),
                 extra={"entry_quality": p.get("entry_quality",
                                               "UNKNOWN"),
                        "setup_type": p.get("setup_type"),
                        "entry_fill": p.get("entry_fill"),
                        "stop": p.get("stop"),
                        "quantity": p.get("quantity"),
                        "chase_risk": p.get("chase_risk"),
                        "risk_source": "equity_shadow_decision"})


# --------------------------------------------------------------- BTC

BTC_ATTACK_COHORTS = ("ATTACK", "SUSCEPTIBLE_ATTACKED")


def from_btc(ledger_record: dict) -> dict:
    """A BTC decision is a candidate only when its cohort attacked and
    its attack geometry carries a planned invalidation risk."""
    if ledger_record.get("kind") != "btc_paper_decision":
        raise CandidateViolation("not a btc_paper_decision record")
    cohort = ledger_record.get("cohort")
    if cohort not in BTC_ATTACK_COHORTS:
        raise CandidateViolation(f"cohort {cohort!r} is not an attack")
    geo = ledger_record.get("attack_geometry") or {}
    risk = geo.get("declared_1R") or geo.get("risk_usd") \
        or geo.get("planned_risk")
    direction = (geo.get("direction")
                 or ledger_record.get("pressured_side") or "UNKNOWN")
    return _base(ledger_record, sleeve="BTC",
                 candidate_id=f"BTC:{ledger_record.get('T')}",
                 symbol="PBTCUCZ50", direction=str(direction),
                 expression="BTC_PERP",
                 declared_risk=risk,
                 known_from=ledger_record.get("T"),
                 event_time=ledger_record.get("T"),
                 extra={"cohort": cohort,
                        "participant_state":
                            ledger_record.get("participant_state"),
                        "thesis_state": ledger_record.get("thesis_state"),
                        "signal_half_life":
                            ledger_record.get("signal_half_life"),
                        "risk_source": "btc_paper_decision"})
