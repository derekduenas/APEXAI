"""THE GOVERNOR'S DOCTRINE — show up, observe, learn, and build less.

Two instruments:

  DAILY_KPI      six questions, asked every market day, answered from
                 artifacts rather than impressions.
  build_request  the DEFER gate. APEX's problem on 2026-08-25 was not
                 a shortage of trading intelligence -- it was that the
                 intelligence it already had never started. Every
                 proposed capability must name the PROVEN gap that
                 requires it, and the default answer is DEFER.

ARCHITECTURE FREEZE is in force. EdgeForge exists. CHRONOS exists.
Equity, Options, BTC, the simulator, the adversary, the scientific
controls all exist. The organism does not need more organs; it needs
experience. The Governor is expected to argue AGAINST new building,
including against its own enthusiasm.

decision_power: TIER1_OPERATIONAL.
"""
from __future__ import annotations

from datetime import datetime, timezone

DAILY_KPI = (
    "DID_WE_SHOW_UP",
    "DID_WE_OBSERVE",
    "DID_WE_HAVE_VALID_OPPORTUNITIES",
    "DID_WE_ATTACK_WHEN_WARRANTED",
    "DID_WE_REFUSE_WHEN_WARRANTED",
    "DID_WE_LEARN_FROM_THE_RESULTS",
)

ANSWERS = ("YES", "NO", "NOT_ESTIMABLE")

FREEZE_IN_FORCE = True
FREEZE_DECLARED = "2026-08-26"

PROVEN_GAP_KINDS = (
    "IMPLEMENTATION_DEFECT", "DATA_DEFECT", "SEMANTIC_DEFECT",
    "OPS_DEFECT", "MEASUREMENT_GAP_BLOCKING_PREREGISTERED_RESEARCH",
)


class DoctrineViolation(RuntimeError):
    pass


def daily_scorecard(*, session: str, answers: dict,
                    evidence: dict) -> dict:
    """The six questions. Every one must be answered WITH an artifact.

    An unanswered question is not a pass -- that conflation is exactly
    how a day with zero options sessions and zero research
    observations could still have felt like a normal Tuesday."""
    missing = [k for k in DAILY_KPI if k not in answers]
    if missing:
        raise DoctrineViolation(
            f"unanswered KPI questions {missing}: an unasked question "
            f"is not a passed one")
    rows = {}
    for k in DAILY_KPI:
        v = answers[k]
        if v not in ANSWERS:
            raise DoctrineViolation(
                f"{k}: answer must be one of {ANSWERS}, got {v!r}")
        ev = evidence.get(k)
        if not ev:
            raise DoctrineViolation(
                f"{k}: an answer without an artifact is an impression")
        rows[k] = {"answer": v, "evidence": ev}
    no = [k for k, r in rows.items() if r["answer"] == "NO"]
    unknown = [k for k, r in rows.items()
               if r["answer"] == "NOT_ESTIMABLE"]
    return {"kind": "governor_daily_scorecard", "session": session,
            "questions": rows, "failed": no, "not_estimable": unknown,
            "verdict": ("CLEAN_DAY" if not no and not unknown else
                        "DAY_WITH_GAPS"),
            "law": "answered from artifacts, never impressions",
            "decision_power": "TIER1_OPERATIONAL"}


def build_request(*, capability: str, motivation: str,
                  proven_gap: dict | None,
                  cheaper_alternative_considered: str) -> dict:
    """Should APEX build this? The default is no.

    A proven gap is a DEFECT or a measurement gap that blocks
    preregistered research -- not a hunch, not an elegance argument,
    and explicitly not 'it would be interesting'. Curiosity is
    routed to Tier 2 research, where it is free; production
    engineering is not."""
    if not cheaper_alternative_considered:
        raise DoctrineViolation(
            "state the cheaper alternative you considered; 'none' is "
            "an acceptable answer but must be said out loud")
    if not proven_gap:
        return {"kind": "governor_build_decision",
                "capability": capability, "verdict": "DEFER",
                "why": "no proven defect or blocking measurement gap "
                       "was named. Under ARCHITECTURE FREEZE the "
                       "burden is on the build, not on the refusal",
                "freeze_in_force": FREEZE_IN_FORCE,
                "route": "if this is curiosity, it belongs in TIER2 "
                         "research where it is free",
                "decided_utc": datetime.now(timezone.utc).isoformat(),
                "decision_power": "TIER1_OPERATIONAL"}
    kind = proven_gap.get("kind")
    if kind not in PROVEN_GAP_KINDS:
        return {"kind": "governor_build_decision",
                "capability": capability, "verdict": "DEFER",
                "why": f"{kind!r} is not a proven gap kind "
                       f"{PROVEN_GAP_KINDS}. A market loss, a hunch, "
                       f"or an elegance argument is not a defect",
                "freeze_in_force": FREEZE_IN_FORCE,
                "decided_utc": datetime.now(timezone.utc).isoformat(),
                "decision_power": "TIER1_OPERATIONAL"}
    if not proven_gap.get("evidence"):
        return {"kind": "governor_build_decision",
                "capability": capability, "verdict": "DEFER",
                "why": "the gap names no evidence; a defect without "
                       "an artifact is a suspicion",
                "freeze_in_force": FREEZE_IN_FORCE,
                "decided_utc": datetime.now(timezone.utc).isoformat(),
                "decision_power": "TIER1_OPERATIONAL"}
    return {"kind": "governor_build_decision",
            "capability": capability, "verdict": "PROCEED",
            "proven_gap": proven_gap, "motivation": motivation,
            "cheaper_alternative_considered":
                cheaper_alternative_considered,
            "scope": "repair the named gap and nothing adjacent",
            "freeze_in_force": FREEZE_IN_FORCE,
            "decided_utc": datetime.now(timezone.utc).isoformat(),
            "decision_power": "TIER1_OPERATIONAL"}
