"""APEXDecisionCard — the atomic record of APEX intelligence at time T.

One sealed artifact per serious candidate: everything the desk KNEW,
SAW, FEARED, LIKED and DECIDED at the moment — then, later, what the
future did. The BEFORE card is immutable once sealed; the outcome is a
SEPARATE record referencing the BEFORE card's hash, so hindsight cannot
be written backwards into the belief.

Absence law throughout: UNKNOWN stays UNKNOWN. A missing imbalance is
never zero; an unavailable eye is never "no objection".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apex.frontier import FRONTIER_POWER

CARDS_ROOT = Path("results/decision_cards")

SECTIONS = ("identity", "timing", "premarket", "world", "scout",
            "dislocation",
            "hunter", "fastwatch", "microscope", "catalyst", "visual",
            "oracle", "assassin", "captain", "opportunity_competition",
            "capital", "expression", "execution", "before_statement")

# the bounded trader brief at the bottom of every BEFORE card
BRIEF_KEYS = ("what_i_see", "why_it_matters", "what_could_make_me_wrong",
              "entry_attractiveness", "what_would_make_it_better")

FORBIDDEN_IN_BEFORE = ("ret_15m", "ret_30m", "ret_60m", "ret_90m",
                       "mfe", "mae", "outcome", "realized", "target_first",
                       "stop_first")


class CardViolation(RuntimeError):
    """A card tried to know the future, or an outcome tried to rewrite
    the past."""


def _hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def seal_before(decision_id: str, session_date: str, sections: dict,
                *, official_epoch_candidate: bool,
                frontier_shadow_candidate: bool) -> dict:
    """Build and SEAL the BEFORE card. Missing sections are stored as
    {"status": "UNKNOWN"} — visible holes, never silent ones."""
    body = {"kind": "apex_decision_card_before",
            "decision_id": decision_id, "session_date": session_date,
            "official_epoch_candidate": bool(official_epoch_candidate),
            "frontier_shadow_candidate": bool(frontier_shadow_candidate),
            "decision_power": FRONTIER_POWER,
            "card_lineage": "apex_decision_card_v1"}
    for name in SECTIONS:
        body[name] = sections.get(name) or {"status": "UNKNOWN"}

    # NO FUTURE INFORMATION: scan every leaf key
    blob = json.dumps(body, sort_keys=True, default=str).lower()
    for bad in FORBIDDEN_IN_BEFORE:
        if f'"{bad}"' in blob:
            raise CardViolation(
                f"BEFORE card contains outcome field {bad!r}: the card "
                f"must be sealable before the future happens")

    brief = body["before_statement"]
    if brief.get("status") != "UNKNOWN":
        missing = [k for k in BRIEF_KEYS if k not in brief]
        if missing:
            raise CardViolation(f"before_statement missing {missing}")

    body["sealed"] = "SEALED_BEFORE_OUTCOME"
    body["card_sha256"] = _hash({k: v for k, v in body.items()
                                 if k != "card_sha256"})
    return body


def attach_outcome(card: dict, outcome: dict) -> dict:
    """The AFTER record. References the BEFORE hash; never mutates the
    card. `latency_cost` fields are observations, not alpha claims."""
    if card.get("sealed") != "SEALED_BEFORE_OUTCOME":
        raise CardViolation("outcome offered for an unsealed card")
    expect = _hash({k: v for k, v in card.items() if k != "card_sha256"})
    if expect != card.get("card_sha256"):
        raise CardViolation(
            "BEFORE card hash mismatch: the card was edited after sealing")
    return {"kind": "apex_decision_outcome",
            "decision_id": card["decision_id"],
            "decision_card_hash": card["card_sha256"],
            "decision_power": FRONTIER_POWER,
            "outcome": dict(outcome),
            "observations_not_conclusions": True}


def persist(card: dict, outcome: dict | None = None) -> Path:
    day = card["session_date"]
    d = CARDS_ROOT / day
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{card['decision_id']}.json"
    payload = {"before": card}
    if p.exists():                       # BEFORE is immutable on disk too
        prior = json.loads(p.read_text())
        if prior.get("before", {}).get("card_sha256") != card["card_sha256"]:
            raise CardViolation(
                f"a different BEFORE card already exists for "
                f"{card['decision_id']}; cards are never re-sealed")
        payload = prior
    if outcome is not None:
        payload["after"] = attach_outcome(card, outcome)
    p.write_text(json.dumps(payload, indent=2, default=str))
    (d / f"{card['decision_id']}.html").write_text(render_html(payload))
    return p


def render_html(payload: dict) -> str:
    """Human form. Deliberately dependency-free."""
    c = payload["before"]
    rows = []
    for name in SECTIONS:
        sec = c.get(name, {})
        body = json.dumps(sec, indent=1, default=str)[:4000]
        rows.append(f"<h3>{name.upper()}</h3><pre>{body}</pre>")
    after = ""
    if "after" in payload:
        after = ("<h2>OUTCOME (attached after the future)</h2><pre>"
                 + json.dumps(payload["after"], indent=1, default=str)[:4000]
                 + "</pre>")
    return (f"<html><body style='font-family:monospace;background:#14161c;"
            f"color:#c8cdd7;padding:2em'>"
            f"<h1>APEX DECISION CARD — {c['decision_id']}</h1>"
            f"<p><b>SEALED BEFORE OUTCOME</b> sha256={c['card_sha256']}</p>"
            f"<p>desk: official={c['official_epoch_candidate']} "
            f"frontier={c['frontier_shadow_candidate']} | "
            f"power={c['decision_power']}</p>"
            + "".join(rows) + after + "</body></html>")


# ===================== CANDIDATE TRACE (the denominator) ====================

FUNNEL_STAGES = ("SCOUT_ABNORMAL", "WATCHLIST", "NEAR_CANDIDATE",
                 "HUNTER", "FRONTIER_SERIOUS")
TRACES = Path("results/decision_cards")


def seal_trace(*, symbol: str, session_date: str, entered_because: str,
               stage_reached: str, died_at: str | None, when: str,
               what_was_known: dict) -> dict:
    """The lightweight sealed record for EVERY material funnel member —
    including the ones that die. Finalists proving out means nothing
    without the denominator: selectivity is only demonstrable if the
    rejected cohort is preserved with what was known when it was rejected.
    """
    if stage_reached not in FUNNEL_STAGES:
        raise CardViolation(f"unknown funnel stage {stage_reached!r}")
    if died_at is not None and died_at not in FUNNEL_STAGES:
        raise CardViolation(f"unknown death stage {died_at!r}")
    body = {"kind": "candidate_trace", "symbol": symbol,
            "session_date": session_date,
            "entered_funnel_because": entered_because,
            "stage_reached": stage_reached,
            "died_at": died_at, "alive": died_at is None,
            "when": when, "what_was_known": dict(what_was_known),
            "decision_power": FRONTIER_POWER}
    blob = json.dumps(body, sort_keys=True, default=str).lower()
    for bad in FORBIDDEN_IN_BEFORE:
        if f'"{bad}"' in blob:
            raise CardViolation(
                f"candidate trace contains outcome field {bad!r}")
    body["trace_sha256"] = _hash(body)
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    d = TRACES / session_date
    d.mkdir(parents=True, exist_ok=True)
    _chain_append(d / "traces.jsonl", body)
    return body
