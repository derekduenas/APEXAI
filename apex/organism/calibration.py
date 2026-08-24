"""CALIBRATION / UNCERTAINTY LEDGER (V2 #5).

MISSION: make APEX know when it actually knows something.

TWO REFUSALS DEFINE THIS MODULE.

  It refuses the single confidence number. "confidence = 87%"
  compresses five different ignorances -- data, epistemic, aleatoric,
  execution, mechanism -- into one digit that answers none of them.
  "I understand the mechanism but outcomes are naturally volatile" and
  "I do not actually know what is happening" are radically different
  states that demand different responses, and a scalar cannot tell
  them apart. The uncertainty record therefore has five named axes and
  no total.

  It refuses hindsight registration. A probabilistic claim counts for
  calibration ONLY if it was registered before its outcome was known
  -- the register/resolve split is structural, resolution refuses an
  unregistered id, and registration is append-only into a hash chain.

THE STANDARD: a model that says 60% and is right 60% of the time is
useful; a model that says 90% and is right 60% is dangerous. Reliability
is computed per predicted-probability bucket with sample-size honesty --
below the pre-declared floor the verdict is INSUFFICIENT_SAMPLE, never
a curve drawn through noise.

Confidence without calibration receives no capital authority.

decision_power: NONE_SHADOW.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

NOT_ESTIMABLE = "NOT_ESTIMABLE"

UNCERTAINTY_AXES = ("data", "epistemic", "aleatoric", "execution",
                    "mechanism")
AXIS_LEVELS = ("LOW", "MODERATE", "HIGH", NOT_ESTIMABLE)

# RULE CLASSIFICATION (operator correction 2026-08-24): this floor is a
# REPORTING_SUFFICIENCY_PRIOR -- a human-chosen conservatism about when
# a reliability curve is worth drawing. It is NOT a learned economic
# threshold and NOT a universal statistical law, and it applies to
# INDEPENDENT sessions, because twenty highly dependent observations
# from one session must not masquerade as twenty calibration events.
MIN_BUCKET_N = 20
MIN_BUCKET_N_CLASSIFICATION = "REPORTING_SUFFICIENCY_PRIOR"

# Pedigrees under which a claim of exactly 0 or 1 is legitimate:
# certainty that follows from definition or mechanism, not from a
# model's enthusiasm. P(option expires by its expiration) = 1.0 is a
# fact of the contract; P(+2R before -1R) = 1.0 is hubris.
CERTAINTY_CAPABLE_PEDIGREES = ("DETERMINISTIC_BY_CONSTRUCTION",)


class CalibrationViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class UncertaintyState:
    """Five named ignorances. Deliberately no total, no scalar."""
    data: str = NOT_ESTIMABLE
    epistemic: str = NOT_ESTIMABLE
    aleatoric: str = NOT_ESTIMABLE
    execution: str = NOT_ESTIMABLE
    mechanism: str = NOT_ESTIMABLE
    notes: dict = field(default_factory=dict)
    law: str = ("five different ignorances; compressing them into one "
                "confidence number answers none of them")

    def __post_init__(self):
        for ax in UNCERTAINTY_AXES:
            if getattr(self, ax) not in AXIS_LEVELS:
                raise CalibrationViolation(
                    f"unknown level for {ax}: {getattr(self, ax)!r}")
        forbidden = {"confidence", "overall", "total", "score"}
        if forbidden & {k.lower() for k in self.notes}:
            raise CalibrationViolation(
                "a single confidence/overall score is refused by "
                "construction -- name the axis instead")

    def as_record(self) -> dict:
        return {"kind": "uncertainty_state", **asdict(self)}


def register(ledger: Path, *, claim_id: str, p: float, event: str,
             sleeve: str, pedigree: str,
             regime_tags: list | None = None,
             session: str | None = None) -> dict:
    """Register a probabilistic claim BEFORE its outcome is known.

    PROBABILITY DOMAIN LAW (corrected 2026-08-24; the first version
    wrongly banned 0 and 1 as "non-probabilities"). Mathematically
    0.0 <= p <= 1.0 is the valid domain. What is prohibited is
    UNSUPPORTED CERTAINTY: an empirical or model-derived forecast of
    exactly 0 or 1 claims something no uncalibrated model has earned,
    while a deterministic statement -- certainty following from
    definition or mechanism -- may legitimately sit at the boundary.
    The law is CERTAINTY MUST BE EARNED, not "0 and 1 are invalid".

    `session` identifies the independent observation unit, so that
    reliability can count sessions rather than letting one session's
    correlated claims impersonate a sample."""
    if not (0.0 <= p <= 1.0):
        raise CalibrationViolation(
            f"p={p} is outside [0, 1] and is genuinely not a "
            f"probability")
    extreme = p in (0.0, 1.0)
    if extreme and pedigree not in CERTAINTY_CAPABLE_PEDIGREES:
        raise CalibrationViolation(
            f"p={p} with pedigree {pedigree!r} is an UNSUPPORTED "
            f"CERTAINTY: certainty must be earned, and an empirical "
            f"forecast has not earned it. Deterministic claims use "
            f"pedigree DETERMINISTIC_BY_CONSTRUCTION.")
    rec = {"kind": "calibration_claim", "claim_id": claim_id,
           "p": round(float(p), 4), "event": event, "sleeve": sleeve,
           "pedigree": pedigree,
           "certainty_flag": ("EXTREME_CERTAINTY_CLAIM" if extreme
                              else "VALID_PROBABILITY"),
           "regime_tags": sorted(regime_tags or []),
           "session": session,
           "registered_utc": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_SHADOW"}
    chain_append(ledger, rec)
    return rec


def resolve(ledger: Path, *, claim_id: str, occurred: bool) -> dict:
    """Resolve a claim. Refuses one that was never registered -- a
    probability written down after the outcome is not a forecast."""
    registered = None
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "calibration_claim" \
                    and r.get("claim_id") == claim_id:
                registered = r
            if r.get("kind") == "calibration_resolution" \
                    and r.get("claim_id") == claim_id:
                raise CalibrationViolation(
                    f"claim {claim_id} already resolved -- outcomes "
                    f"do not get second chances")
    if registered is None:
        raise CalibrationViolation(
            f"claim {claim_id} was never registered; a probability "
            f"written down after the outcome is not a forecast")
    rec = {"kind": "calibration_resolution", "claim_id": claim_id,
           "p_registered": registered["p"], "occurred": bool(occurred),
           "session": registered.get("session"),
           "regime_tags": registered.get("regime_tags", []),
           "brier": round((registered["p"] - (1.0 if occurred else 0.0))
                          ** 2, 6),
           "resolved_utc": datetime.now(timezone.utc).isoformat(),
           "decision_power": "NONE_SHADOW"}
    chain_append(ledger, rec)
    return rec


def reliability(ledger: Path, *, buckets: int = 10) -> dict:
    """Observed frequency vs predicted probability, with sample-size
    honesty. Never draws a curve through noise."""
    res = []
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("kind") == "calibration_resolution":
                    res.append(r)
    n = len(res)
    sessions = {r.get("session") for r in res} - {None}
    out = {"kind": "reliability_report",
           "n_raw": n,
           "n_effective_lower_bound": len(sessions) if sessions else
           ("NOT_ESTIMABLE" if n else 0),
           "independent_session_count": len(sessions),
           "min_bucket_n": MIN_BUCKET_N,
           "min_bucket_n_classification": MIN_BUCKET_N_CLASSIFICATION,
           "decision_power": "NONE_SHADOW",
           "law": "a model that says 90% and is right 60% is "
                  "dangerous; below the sufficiency prior no curve is "
                  "drawn, and dependent observations never impersonate "
                  "independent ones"}
    if n == 0:
        out["verdict"] = "NO_RESOLVED_CLAIMS"
        return out
    out["brier_mean"] = round(sum(r["brier"] for r in res) / n, 6)
    rows = []
    width = 1.0 / buckets
    for b in range(buckets):
        lo, hi = b * width, (b + 1) * width
        inb = [r for r in res if lo <= r["p_registered"] < hi
               or (b == buckets - 1 and r["p_registered"] == 1.0)]
        if not inb:
            continue
        bses = {r.get("session") for r in inb} - {None}
        # the sufficiency prior applies to INDEPENDENT sessions when
        # session tags exist; untagged claims fall back to raw count
        # and say so
        eff = len(bses) if bses else len(inb)
        regs = [t for r in inb for t in r.get("regime_tags", [])]
        conc = (round(max(regs.count(t) for t in set(regs))
                      / len(regs), 3) if regs else NOT_ESTIMABLE)
        row = {"bucket": f"[{lo:.1f},{hi:.1f})", "n_raw": len(inb),
               "n_effective_lower_bound": eff,
               "effective_basis": ("independent sessions" if bses else
                                   "raw count -- claims were untagged"),
               "regime_concentration": conc,
               "p_mean": round(sum(r["p_registered"] for r in inb)
                               / len(inb), 4)}
        if eff >= MIN_BUCKET_N:
            row["observed_freq"] = round(
                sum(1 for r in inb if r["occurred"]) / len(inb), 4)
            row["gap"] = round(row["observed_freq"] - row["p_mean"], 4)
        else:
            row["observed_freq"] = "INSUFFICIENT_SAMPLE"
            row["gap"] = NOT_ESTIMABLE
        rows.append(row)
    out["buckets"] = rows
    estimable = [r for r in rows if isinstance(r["gap"], float)]
    out["verdict"] = ("CALIBRATION_MEASURABLE" if estimable
                      else "INSUFFICIENT_SAMPLE_EVERYWHERE")
    return out
