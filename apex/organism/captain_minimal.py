"""CAPTAIN_MINIMAL_V0 -- one neuron, zero authority.

The smallest possible in-flight manager. It holds exactly ONE
decision right and no others:

    HOLD  |  EXIT_TO_CASH

for an already-entered, eligible, bearish option position.

IT IS A CONTRADICTION RULE, NOT A REMAINING-EDGE MODEL. No
distribution is estimated here and none is implied; calling this
"expected remaining edge" would be a lie about what it computes.
The honest name is CONTRADICTION_EXIT / REUNDERWRITE_150.

Frozen verbatim from REUNDERWRITE-150-PROSPECTIVE-SHADOW-
REGISTRATION (binding birth 2026-08-31T02:49:43Z): if the
underlying has moved AGAINST the bearish thesis by MORE THAN
+150 bps from entry as of the 10:00 ET checkpoint, exit at the
10:00 option NBBO (sell at bid); otherwise hold to the sealed
15:55 exit.

This module has NO capability to rotate, resize, average, trail,
re-enter, re-express, or reprioritize. Each of those would be a
separate organ trial.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

VERSION = "CAPTAIN_MINIMAL_V0"
RULE_ID = "REUNDERWRITE_150"
THRESHOLD_BPS = 150.0          # frozen; never swept
CHECKPOINT = "10:00"           # frozen
ELIGIBLE_EXPRESSIONS = ("long_put", "put_debit_spread")

ACTIONS = ("HOLD", "EXIT_TO_CASH", "NOT_ELIGIBLE",
           "NOT_ESTIMABLE")


def evaluate(*, expression: str, thesis_direction: str,
             underlying_move_bps_from_entry, checkpoint: str,
             exit_quote_available: bool) -> dict:
    """One position, one checkpoint, one verdict.

    underlying_move_bps_from_entry: signed move of the UNDERLYING
    since entry (positive = up). For a bearish thesis, positive is
    adverse.
    """
    out = {"version": VERSION, "rule": RULE_ID,
           "checkpoint": checkpoint,
           "threshold_bps": THRESHOLD_BPS,
           "decision_power": "SHADOW_COUNTERFACTUAL_ONLY"}

    if checkpoint != CHECKPOINT:
        out.update({"action": "NOT_ELIGIBLE",
                    "why": f"rule is frozen to the {CHECKPOINT} "
                           f"checkpoint"})
        return out
    if expression not in ELIGIBLE_EXPRESSIONS \
            or thesis_direction != "SHORT":
        out.update({"action": "NOT_ELIGIBLE",
                    "why": f"{expression}/{thesis_direction} is "
                           f"not an eligible bearish option "
                           f"position"})
        return out
    if not isinstance(underlying_move_bps_from_entry,
                      (int, float)):
        out.update({"action": "NOT_ESTIMABLE",
                    "why": "underlying move at checkpoint unknown"})
        return out

    adverse = underlying_move_bps_from_entry > THRESHOLD_BPS
    out["underlying_move_bps"] = round(
        underlying_move_bps_from_entry, 1)
    out["contradicted"] = adverse
    if not adverse:
        out.update({"action": "HOLD",
                    "why": "the position has not objectively "
                           "contradicted itself past the frozen "
                           "threshold"})
        return out
    if not exit_quote_available:
        out.update({"action": "NOT_ESTIMABLE",
                    "why": "contradicted, but no executable option "
                           "bid at the checkpoint -- an exit "
                           "cannot be assumed without a quote"})
        return out
    out.update({"action": "EXIT_TO_CASH",
                "why": f"underlying moved "
                       f"{underlying_move_bps_from_entry:.0f} bps "
                       f"against a bearish thesis, beyond the "
                       f"frozen {THRESHOLD_BPS:.0f} bps "
                       f"contradiction threshold"})
    return out
