"""PATTERN OBSERVATORY SUMMARY -- a read-only interface Captain COULD use.

Deliberately has NO CURRENT CONSUMER. The official Captain is untouched;
nothing imports this into a decision path; it is registered LIVE_TERMINAL
with role OPERATOR_REPORT so the producer/consumer invariant does not
flag it as an orphan while also not pretending it is wired.

When the Observatory eventually earns a consumer, that will be a
deliberate wiring act with its own evidence, not a default.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from apex.pattern_observatory import OBSERVATORY_POWER


def build(*, as_of, known_from, world, pattern_states: list,
          assassin_reviews: list, session_date: str) -> dict:
    by_id = {r.pattern_id: r for r in assassin_reviews}
    forming = [p for p in pattern_states
               if p.current_status in ("FORMING", "DEVELOPING",
                                       "HIGH_ALIGNMENT")]
    broken = [p for p in pattern_states
              if p.current_status in ("BROKEN", "EXPIRED")]

    def rank_key(p):
        # OBSERVATIONAL ranking only. Deliberately excludes anything
        # resembling expected profit -- there is no calibrated
        # distribution to rank by, and inventing one is the exact
        # overclaim this system forbids.
        r = by_id.get(p.pattern_id)
        return (
            {"HIGH_ALIGNMENT": 3, "DEVELOPING": 2, "FORMING": 1}.get(
                p.current_status, 0),
            p.independence.get("independent_mechanism_count", 0),
            1 if (r and r.verdict == "SURVIVED") else 0,
            -len(p.contradicting_evidence),
            p.sequence_progress.get("completion_fraction", 0.0) or 0.0,
        )

    top = sorted(forming, key=rank_key, reverse=True)[:10]
    return {
        "kind": "pattern_observatory_summary",
        "as_of": str(as_of), "known_from": str(known_from),
        "session_date": session_date,
        "top_forming_patterns": [
            {"pattern_id": p.pattern_id, "family_id": p.family_id,
             "subject": p.subject, "status": p.current_status,
             "independent_mechanisms":
                 p.independence.get("independent_mechanism_count"),
             "assassin_verdict": (by_id[p.pattern_id].verdict
                                  if p.pattern_id in by_id else None),
             "contradictions": len(p.contradicting_evidence),
             "input_quality": p.input_quality.get("combined_quality"),
             "probability": p.forward_distribution_status}
            for p in top],
        "top_broken_patterns": [
            {"pattern_id": p.pattern_id, "family_id": p.family_id,
             "subject": p.subject, "status": p.current_status}
            for p in broken[:10]],
        "sector_rotation": world.facets.get("sectors", {}).get("state"),
        "breadth_state": world.facets.get("breadth", {}).get("state"),
        "options_surface_state": world.facets.get("options", {}).get("state"),
        "institutional_positioning": world.facets.get("positioning", {}),
        "forced_flow_states": [],
        "facet_coverage": f"{len(world.facets_live)}/11",
        "facets_dark": list(world.facets_dark),
        "ranked_by": "evidence quality, completeness, mechanism independence "
                     "and contradiction burden -- NOT expected profit",
        "current_captain_consumer": None,
        "captain_impact": "NONE",
        "capital_authority": "NONE",
        "decision_power": OBSERVATORY_POWER,
    }
