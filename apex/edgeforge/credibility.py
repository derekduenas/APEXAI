"""CREDIBILITY MARKET — epistemic standing, earned prospectively.

Phase 8. Not financial capital. Every forecasting faculty may
pre-register claims; claims resolve exactly once; scoring is by
predeclared rule. A faculty's standing is then something it earned
against reality rather than something asserted in its docstring.

CONDITIONAL, NEVER GLOBAL. "Model A = 0.71 weight" is a fiction that
averages a faculty's competence across regimes where it is excellent
and regimes where it is useless. Standing is therefore learned per
CONTEXT -- and a context with too few independent sessions returns
INSUFFICIENT_EVIDENCE rather than a number.

n_raw IS NOT n_effective. Twenty correlated predictions inside one
session is one session's worth of evidence. No faculty earns standing
from a busy afternoon.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

NOT_ESTIMABLE = "NOT_ESTIMABLE"

CLAIM_TYPES = ("PROBABILISTIC", "ORDINAL", "DIRECTIONAL", "POINT")

# REPORTING_SUFFICIENCY_PRIOR, per the calibration precedent: applies to
# INDEPENDENT SESSIONS, not raw claims.
MIN_INDEPENDENT_SESSIONS = 20
SUFFICIENCY_CLASSIFICATION = "REPORTING_SUFFICIENCY_PRIOR"


class CredibilityViolation(RuntimeError):
    pass


def register_claim(ledger: Path, *, claim_id: str, faculty: str,
                   claim_type: str, prediction, resolution_rule: str,
                   context: dict, session: str,
                   pedigree: str = "UNCALIBRATED",
                   probability: float | None = None) -> dict:
    """Pre-register BEFORE the outcome. A claim written afterwards is
    not a forecast, and the ledger will not accept one later."""
    if claim_type not in CLAIM_TYPES:
        raise CredibilityViolation(f"unknown claim type {claim_type!r}")
    if not resolution_rule:
        raise CredibilityViolation(
            "a claim with no resolution rule can never be scored, and "
            "an unscoreable claim is free credibility")
    if claim_type == "PROBABILISTIC":
        if probability is None:
            raise CredibilityViolation(
                "a PROBABILISTIC claim needs a probability")
        if not (0.0 <= probability <= 1.0):
            raise CredibilityViolation(
                f"p={probability} is outside [0,1]")
        if probability in (0.0, 1.0) and \
                pedigree != "DETERMINISTIC_BY_CONSTRUCTION":
            raise CredibilityViolation(
                "unsupported certainty: certainty must be earned")
    rec = {"kind": "credibility_claim", "claim_id": claim_id,
           "faculty": faculty, "claim_type": claim_type,
           "prediction": prediction, "probability": probability,
           "resolution_rule": resolution_rule, "context": context,
           "session": session, "pedigree": pedigree,
           "registered_utc": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_RESEARCH"}
    chain_append(ledger, rec)
    return rec


def resolve_claim(ledger: Path, *, claim_id: str, outcome,
                  occurred: bool | None = None) -> dict:
    reg = None
    for line in (ledger.read_text().splitlines()
                 if ledger.exists() else []):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") == "credibility_claim" and \
                r.get("claim_id") == claim_id:
            reg = r
        if r.get("kind") == "credibility_resolution" and \
                r.get("claim_id") == claim_id:
            raise CredibilityViolation(
                f"{claim_id} already resolved; outcomes do not get "
                f"second chances")
    if reg is None:
        raise CredibilityViolation(
            f"{claim_id} was never registered -- scoring an "
            f"unregistered claim rewards hindsight")
    rec = {"kind": "credibility_resolution", "claim_id": claim_id,
           "faculty": reg["faculty"], "claim_type": reg["claim_type"],
           "context": reg["context"], "session": reg["session"],
           "prediction": reg["prediction"], "outcome": outcome,
           "occurred": occurred,
           "resolved_utc": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_RESEARCH"}
    if reg["claim_type"] == "PROBABILISTIC" and occurred is not None:
        p = reg["probability"]
        rec["brier"] = round((p - (1.0 if occurred else 0.0)) ** 2, 6)
        rec["log_score"] = round(
            -math.log(max(p if occurred else 1 - p, 1e-9)), 6)
        rec["p_registered"] = p
    elif reg["claim_type"] in ("ORDINAL", "DIRECTIONAL"):
        rec["correct"] = (reg["prediction"] == outcome)
    chain_append(ledger, rec)
    return rec


def standing(ledger: Path, *, faculty: str,
             context_key: str | None = None) -> dict:
    """Conditional standing, with sample honesty. Returns
    INSUFFICIENT_EVIDENCE rather than a flattering small-sample score."""
    res = []
    for line in (ledger.read_text().splitlines()
                 if ledger.exists() else []):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("kind") != "credibility_resolution":
            continue
        if r.get("faculty") != faculty:
            continue
        res.append(r)

    buckets = {}
    for r in res:
        key = (r["context"].get(context_key, "UNKNOWN")
               if context_key else "ALL")
        buckets.setdefault(key, []).append(r)

    out = {}
    for key, rs in buckets.items():
        sessions = {r["session"] for r in rs if r.get("session")}
        n_eff = len(sessions)
        entry = {"n_raw": len(rs), "n_effective_lower_bound": n_eff,
                 "independent_sessions": n_eff}
        if n_eff < MIN_INDEPENDENT_SESSIONS:
            entry.update({
                "verdict": "INSUFFICIENT_EVIDENCE",
                "why": (f"{n_eff} independent sessions < "
                        f"{MIN_INDEPENDENT_SESSIONS}; twenty correlated "
                        f"predictions in one afternoon is one session's "
                        f"worth of evidence")})
        else:
            briers = [r["brier"] for r in rs if "brier" in r]
            corrects = [r["correct"] for r in rs if "correct" in r]
            entry.update({
                "verdict": "MEASURED",
                "brier_mean": (round(statistics.mean(briers), 6)
                               if briers else NOT_ESTIMABLE),
                "hit_rate": (round(sum(corrects) / len(corrects), 4)
                             if corrects else NOT_ESTIMABLE)})
        out[key] = entry

    return {"kind": "faculty_standing", "faculty": faculty,
            "context_key": context_key or "ALL",
            "by_context": out,
            "sufficiency_prior": MIN_INDEPENDENT_SESSIONS,
            "sufficiency_classification": SUFFICIENCY_CLASSIFICATION,
            "law": "standing is CONDITIONAL; a global weight averages a "
                   "faculty's competence across regimes where it excels "
                   "and regimes where it is useless",
            "grants_authority": False,
            "decision_power": "NONE_RESEARCH"}
