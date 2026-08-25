"""FOUR LEARNING ZONES — where EdgeForge may go crazy, and where it
may not move a muscle.

  ZONE_A_DISCOVERY   search anything: interactions, sequences,
                     nonlinearities, tail precursors. Cheap curiosity.
  ZONE_B_VALIDATION  the hypothesis FREEZES -- variables, direction,
                     threshold family, mechanism, horizon, payoff
                     definition. Test on unseen time. If it dies, it
                     dies; 'improving' it here is the oldest laundering
                     move in quant research.
  ZONE_C_SEALED_TEST walk-forward. An edge exists from its BIRTH date
                     and may never use anything learned after birth to
                     explain what followed. A changed edge is a NEW
                     DESCENDANT with its own birth, not an edit.
  ZONE_D_LOCKBOX     a final period nothing trains on, tunes on, or
                     peeks at. Opened once, by explicit operator
                     authorization, at the end.

PURGING AND EMBARGO. Adjacent observations share outcome information
when horizons overlap: a train sample whose 20-minute forward window
crosses the validation boundary has already seen validation's answer.
Purge removes those; the embargo adds explicit dead time between
zones. A fold without both is a leak with a schedule.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from apex.chronos.clock import ChronosViolation, _parse

ZONES = ("ZONE_A_DISCOVERY", "ZONE_B_VALIDATION", "ZONE_C_SEALED_TEST",
         "ZONE_D_LOCKBOX")

FROZEN_FIELDS = ("variables", "direction", "threshold_family",
                 "mechanism", "horizon", "payoff_definition")


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_start: str
    train_end: str
    validate_start: str
    validate_end: str
    test_start: str
    test_end: str
    purge_horizon: str          # e.g. "20min" -- the outcome horizon
    embargo: str                # explicit dead time between zones

    def as_record(self) -> dict:
        return {"kind": "chronos_fold", **self.__dict__}


def _td(spec: str) -> timedelta:
    unit = spec[-3:] if spec.endswith("min") else spec[-1]
    n = float(spec[: -len(unit)])
    return {"min": timedelta(minutes=n), "h": timedelta(hours=n),
            "d": timedelta(days=n)}[unit]


def build_folds(*, start: str, end: str, train_days: int,
                validate_days: int, test_days: int,
                purge_horizon: str, embargo: str) -> list:
    """Rolling folds across [start, end). The last partial window is
    DROPPED, not stretched -- a stretched final fold quietly changes
    the experiment to fit the data that happens to exist."""
    s, e = _parse(start), _parse(end)
    span = timedelta(days=train_days + validate_days + test_days)
    step = timedelta(days=test_days)
    folds, i = [], 0
    cur = s
    while cur + span <= e:
        t0 = cur
        t1 = t0 + timedelta(days=train_days)
        v1 = t1 + timedelta(days=validate_days)
        x1 = v1 + timedelta(days=test_days)
        folds.append(Fold(
            fold_id=f"FOLD_{i:03d}",
            train_start=t0.isoformat(), train_end=t1.isoformat(),
            validate_start=t1.isoformat(), validate_end=v1.isoformat(),
            test_start=v1.isoformat(), test_end=x1.isoformat(),
            purge_horizon=purge_horizon, embargo=embargo))
        cur += step
        i += 1
    if not folds:
        raise ChronosViolation(
            "the requested span holds zero complete folds; running a "
            "partial fold anyway would be fitting the design to the "
            "data")
    return folds


def assign_zone(fold: Fold, *, decision_time: str,
                outcome_horizon_end: str) -> str:
    """Which zone an observation belongs to -- with purge and embargo
    applied. PURGED and EMBARGOED are answers, not errors: they mean
    'this observation may not teach anyone anything in this fold'."""
    t = _parse(decision_time)
    h_end = _parse(outcome_horizon_end)
    emb = _td(fold.embargo)

    tr0, tr1 = _parse(fold.train_start), _parse(fold.train_end)
    va0, va1 = _parse(fold.validate_start), _parse(fold.validate_end)
    te0, te1 = _parse(fold.test_start), _parse(fold.test_end)

    if tr0 <= t < tr1:
        # PURGE: a train observation whose outcome window crosses into
        # validation has already seen validation's answer.
        if h_end >= va0:
            return "PURGED"
        return "ZONE_A_DISCOVERY"
    if va0 <= t < va1:
        if t < tr1 + emb:
            return "EMBARGOED"
        if h_end >= te0:
            return "PURGED"
        return "ZONE_B_VALIDATION"
    if te0 <= t < te1:
        if t < va1 + emb:
            return "EMBARGOED"
        return "ZONE_C_SEALED_TEST"
    return "OUT_OF_FOLD"


# ==================================================== FROZEN HYPOTHESES

def freeze_hypothesis(*, hypothesis_id: str, birth_time: str,
                      spec: dict) -> dict:
    """Seal a hypothesis before it meets unseen time.

    The hash covers exactly the FROZEN_FIELDS. A spec missing any of
    them is refused: an unfrozen degree of freedom is a knob someone
    will eventually turn."""
    missing = [f for f in FROZEN_FIELDS if f not in spec]
    if missing:
        raise ChronosViolation(
            f"hypothesis {hypothesis_id} cannot freeze with unfrozen "
            f"degrees of freedom: {missing}")
    frozen = {k: spec[k] for k in FROZEN_FIELDS}
    h = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, default=str).encode()
    ).hexdigest()
    return {"kind": "frozen_hypothesis", "hypothesis_id": hypothesis_id,
            "birth_time": birth_time, "frozen_hash": h,
            "frozen_fields": frozen,
            "law": "if it dies in validation, it dies; improving it "
                   "there creates a NEW hypothesis with a NEW birth",
            "decision_power": "NONE_RESEARCH"}


def verify_frozen(frozen: dict, spec_now: dict) -> dict:
    """Did anyone turn a knob between freeze and test?"""
    now = {k: spec_now.get(k) for k in FROZEN_FIELDS}
    h = hashlib.sha256(
        json.dumps(now, sort_keys=True, default=str).encode()
    ).hexdigest()
    if h == frozen["frozen_hash"]:
        return {"verdict": "FROZEN_INTACT",
                "hypothesis_id": frozen["hypothesis_id"]}
    changed = [k for k in FROZEN_FIELDS
               if now.get(k) != frozen["frozen_fields"].get(k)]
    return {"verdict": "FROZEN_VIOLATED", "changed_fields": changed,
            "hypothesis_id": frozen["hypothesis_id"],
            "remedy": "this is a DESCENDANT: register it with a new id "
                      "and a new birth; the parent's evidence does not "
                      "transfer",
            "decision_power": "NONE_RESEARCH"}


def descend(frozen: dict, *, child_spec: dict, child_suffix: str,
            birth_time: str, mutation_reason: str) -> dict:
    """Evolution is births, never edits. EDGE_00931 -> EDGE_00931B.

    The child starts with ZERO inherited evidence. Lineage is for
    understanding how the organism's ideas evolved, not for letting a
    child borrow its parent's track record."""
    if _parse(birth_time) is None:
        raise ChronosViolation("a descendant needs a birth time")
    child = freeze_hypothesis(
        hypothesis_id=f"{frozen['hypothesis_id']}{child_suffix}",
        birth_time=birth_time, spec=child_spec)
    child["parent"] = frozen["hypothesis_id"]
    child["parent_frozen_hash"] = frozen["frozen_hash"]
    child["mutation_reason"] = mutation_reason
    child["inherited_evidence"] = 0
    child["law"] = ("a descendant is a new organism with a new birth; "
                    "the parent's evidence does not transfer")
    return child


# ==================================================== ZONE D LOCKBOX

def seal_lockbox(*, start: str, end: str, sealed_by: str,
                 sealed_utc: str) -> dict:
    """Declare the final holdout. The declaration itself is hashed so
    the boundary cannot quietly drift later."""
    if _parse(start) >= _parse(end):
        raise ChronosViolation("an empty lockbox protects nothing")
    body = {"kind": "chronos_lockbox", "start": start, "end": end,
            "sealed_by": sealed_by, "sealed_utc": sealed_utc,
            "status": "SEALED",
            "law": "never trained on, never validated on, never used "
                   "to tune the simulator or discovery; opened once, "
                   "by explicit operator authorization, at the end"}
    body["seal_hash"] = hashlib.sha256(
        json.dumps({k: body[k] for k in ("start", "end", "sealed_utc")},
                   sort_keys=True).encode()).hexdigest()
    return body


def lockbox_guard(lockbox: dict, *, decision_time: str,
                  operator_token: str | None = None) -> None:
    """Refuse any touch of lockbox time without explicit operator
    authorization. The token is not a password -- it is a deliberate,
    logged act that cannot happen by accident inside a loop."""
    t = _parse(decision_time)
    if _parse(lockbox["start"]) <= t < _parse(lockbox["end"]):
        if operator_token != "OPERATOR_AUTHORIZED_LOCKBOX_OPEN":
            raise ChronosViolation(
                f"LOCKBOX: {decision_time} lies inside the sealed "
                f"final holdout [{lockbox['start']}, {lockbox['end']}). "
                f"No training, validation, tuning, or discovery may "
                f"touch it. Opening it is a one-time explicit operator "
                f"act")
