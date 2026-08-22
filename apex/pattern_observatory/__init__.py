"""PATTERN OBSERVATORY -- APEX's cross-market intelligence organ.

WHAT THIS IS. The layer that says: "Curve reports X, sector rotation
reports Y, breadth is deteriorating, the options surface is repricing,
an expectation violation appeared, propagation is weakening, FastWatch
density is rising -- these are not six trades. They are ONE developing
market configuration."

WHAT THIS IS NOT. It is not a strategy, not a signal generator, and not
a source of probability. It watches the field and remembers exactly what
it knew and when it knew it.

THE CORE LAW: we are building the hunter's EYES and MEMORY, not giving
it the trigger.

decision_power is NONE_PATTERN_OBSERVATORY everywhere, without exception
and without a configuration flag that could change it. There is no
capital authority, no broker authority, and no path into Hunter,
Captain, Frontier, Execution, or the official Options Analytics runtime.
Those are enforced by firewall tests over the AST import closure, not by
this docstring.
"""
from __future__ import annotations

OBSERVATORY_POWER = "NONE_PATTERN_OBSERVATORY"
CAPITAL_AUTHORITY = "NONE"
BROKER_AUTHORITY = "NONE"

# Adopted verbatim from tests/test_frontier2_firewall.py. The Observatory
# reads production ARTIFACTS as files -- which crosses no import
# boundary, the same pattern daily_forensics_v2.py already uses -- but it
# may never import the production decision stack.
PRODUCTION_STACK_FORBIDDEN = (
    "apex.hunter", "apex.captain", "apex.execution", "apex.hunter.capital",
    "apex.frontier", "apex.frontier2",
)

WRITE_ROOT = "results/pattern_observatory"
