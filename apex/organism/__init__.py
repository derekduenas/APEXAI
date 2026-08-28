"""APEX ORGANISM — the system-level intelligence layer (V2).

Everything in this package is SHADOW or OBSERVE only. Nothing here may
alter an incumbent Predator's decision path, and the freeze is enforced
by test (test_organism_shadow.py::test_no_incumbent_decision_path_
imports_the_organism), not by promise.

decision_power: NONE, package-wide.
"""

ORGANISM_POWER = "NONE_SHADOW"


# ===================================================================
# EVOLUTION ENGINE V2 (2026-08-28) -- one integrated paper organism
ORGANISM_VERSION = "2.0.0"
OPTIONS_AUTHORITY = "PAPER_ACTIVE"
EQUITY_AUTHORITY = "PAPER_ACTIVE_EXPLORATORY"
BTC_AUTHORITY = "PAPER_ACTIVE_EXPLORATORY"    # incumbent logic frozen
CATALYST_AUTHORITY = "ACTIVE_DECISION_INTELLIGENCE"
CAPITAL_ARENA_AUTHORITY = "ACTIVE_PAPER_ALLOCATOR"
CIO_AUTHORITY = "RESEARCH_DIRECTION_ONLY"
EDGEFORGE_AUTHORITY = "ACTIVE_RESEARCH_SKEPTIC"
REAL_CAPITAL_AUTHORITY = "LOCKED"
