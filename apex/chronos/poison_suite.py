"""THE ADVERSARIAL CAUSAL SUITE — CHRONOS attacks itself, on schedule.

"Our causal code has tests" is a claim about optimism. The stronger
standard: every replay plants a catalog of future-information traps,
and a self-attack routine PERIODICALLY TRIES TO CONSUME THEM through
the same read path everything else uses. A firewall that has not been
attacked recently is a firewall of unknown current strength -- code
drifts, and yesterday's proof does not cover today's commit.

The catalog is the census of ways the future leaks into research:
direct future prices, resolutions known early, revised data served at
pre-revision timestamps, corporate knowledge before publication,
forward-filled state, survivorship knowledge before the delisting.

No partial credit, ever: one consumed poison invalidates the entire
run. Not "only one feature leaked". Not "remove the column and keep
the results". Dead.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

from apex.chronos.clock import (ChronosViolation, KnowledgeHorizon,
                                PoisonConsumed)

POISON_CATALOG = {
    "future_return": "the direct forward return over the decision "
                     "horizon",
    "future_high": "the forward window's high, before the window",
    "future_low": "the forward window's low, before the window",
    "future_event_resolution": "an event's outcome served before the "
                               "event resolves",
    "revised_economic_data": "the revised figure served at the "
                             "pre-revision timestamp",
    "future_earnings_result": "an earnings result before publication",
    "future_oi_value": "open interest before the provider published "
                       "it",
    "forward_filled_state": "a later state forward-filled over the "
                            "gap where it was not yet known",
    "delisting_knowledge": "knowledge of a delisting before the "
                           "announcement (survivorship in disguise)",
}


def plant_full_catalog(horizon: KnowledgeHorizon,
                       values: dict | None = None) -> dict:
    """Plant every catalogued poison. Values default to sentinels;
    real replays pass real future values so the trap has real bait --
    a trap baited with an obvious sentinel only catches honest code."""
    values = values or {}
    for name, why in POISON_CATALOG.items():
        horizon.register_poison(name, values.get(name, 1.0), why=why)
    return {"kind": "poison_catalog_planted",
            "planted": sorted(POISON_CATALOG),
            "n": len(POISON_CATALOG),
            "decision_power": "NONE_RESEARCH"}


def self_attack(horizon: KnowledgeHorizon, *, attacker: str) -> dict:
    """Try to consume every planted poison through the ordinary read
    path. EVERY attempt must die; a single survivor means the firewall
    has a hole RIGHT NOW, whatever any old test said.

    This is the routine that runs periodically inside a campaign --
    the firewall is re-proven per epoch, not per code review."""
    results, survivors = {}, []
    for name in sorted(POISON_CATALOG):
        try:
            horizon.get(name, consumer=attacker)
            survivors.append(name)
            results[name] = "CONSUMED_WITHOUT_FAILURE"
        except PoisonConsumed:
            results[name] = "TRAP_FIRED"
        except ChronosViolation:
            results[name] = "NOT_PLANTED"
            survivors.append(f"{name} (not planted)")
    verdict = ("FIREWALL_HELD" if not survivors
               else "FIREWALL_BREACHED")
    out = {"kind": "causal_self_attack", "attacker": attacker,
           "results": results, "survivors": survivors,
           "verdict": verdict,
           "law": "a firewall that has not been attacked recently is "
                  "a firewall of unknown current strength; one "
                  "survivor kills the run, no partial credit",
           "decision_power": "NONE_RESEARCH"}
    if survivors:
        raise ChronosViolation(
            f"CAUSAL FIREWALL BREACHED: {survivors} survived the "
            f"self-attack. The entire run is invalid -- not one "
            f"column, not one feature: the run")
    return out
