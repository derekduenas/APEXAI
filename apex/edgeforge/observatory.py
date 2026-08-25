"""OBSERVATORY — every meaningful incumbent state becomes research.

Phase 1. The Predators decide; the Observatory records what they saw,
what they chose, how close the choice was to flipping, what else could
explain the state, and -- once reality returns -- what actually
happened. Attacks and refusals are recorded identically, because a
research programme that only preserves the trades it took can never
learn whether its refusals were worth making.

ONE COHORT PER STATE. Every observation lands in exactly one cohort, so
counts are partitions rather than overlapping tallies that quietly
double-count.

ANALOG QUALITY IS REPORTED, NEVER ASSUMED. Forty analogs drawn from one
volatility regime are not forty independent observations. Every analog
report carries n_raw, n_effective, unique sessions and years, regime
distribution, distance distribution, coverage, missingness, top-5
influence, concentration and nearest-neighbour stability -- because the
number that matters is almost never the raw count.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append

NOT_ESTIMABLE = "NOT_ESTIMABLE"

COHORTS = ("PAPER_ATTACKED", "ATTACK_READY_NOT_TAKEN", "WAIT_FOR_ENTRY",
           "GEOMETRY_REFUSED", "NEAR_MISS", "NO_DIRECTIONAL_THESIS",
           "PIPELINE_STOP")

OUTCOME_STATUS = ("PENDING", "RESOLVED", "UNRESOLVABLE")


class ObservatoryViolation(RuntimeError):
    pass


@dataclass
class Observation:
    """One incumbent decision, preserved for research."""
    observation_id: str
    session: str
    subject: str
    T: str
    cohort: str
    genome_hash: str
    genome: dict
    incumbent_inputs: dict = field(default_factory=dict)
    research_observations: dict = field(default_factory=dict)
    boundary_map: dict | None = None
    hypotheses: dict | None = None
    disagreements: tuple = ()
    outcome_status: str = "PENDING"
    outcome: dict | None = None
    source_lineage: str = "LIVE_SEALED"
    evidence_class: str = "PROSPECTIVE_OBSERVATION"
    decision_power: str = "NONE_RESEARCH"

    def __post_init__(self):
        if self.cohort not in COHORTS:
            raise ObservatoryViolation(
                f"cohort {self.cohort!r} is not declared; an "
                f"unclassifiable state cannot join a partition")
        if self.outcome_status not in OUTCOME_STATUS:
            raise ObservatoryViolation(
                f"outcome status {self.outcome_status!r} undeclared")

    def resolve(self, outcome: dict, *, status: str = "RESOLVED") -> None:
        """Attach reality. Refuses to overwrite -- an outcome that can
        be revised is not an outcome."""
        if self.outcome_status != "PENDING":
            raise ObservatoryViolation(
                f"{self.observation_id} already {self.outcome_status}; "
                f"outcomes do not get second chances")
        self.outcome_status = status
        self.outcome = outcome

    def as_record(self) -> dict:
        return {"kind": "edgeforge_observation", **asdict(self)}


def record(ledger: Path, obs: Observation) -> dict:
    return chain_append(ledger, obs.as_record())


def cohort_partition(observations: list) -> dict:
    """Counts as a partition, with resolution status alongside -- an
    unresolved cohort is not evidence, however large."""
    counts, resolved = {}, {}
    for o in observations:
        counts[o.cohort] = counts.get(o.cohort, 0) + 1
        if o.outcome_status == "RESOLVED":
            resolved[o.cohort] = resolved.get(o.cohort, 0) + 1
    sessions = {(o.subject, o.session) for o in observations}
    return {"kind": "cohort_partition",
            "counts": counts, "resolved": resolved,
            "n_raw": len(observations),
            "n_effective_lower_bound": len({o.session
                                            for o in observations}),
            "unique_symbol_sessions": len(sessions),
            "law": "counts partition the states; unresolved cohorts are "
                   "not evidence",
            "decision_power": "NONE_RESEARCH"}


# --------------------------------------------------------- analog QC

def analog_quality(selection: dict, *,
                   regime_of: dict | None = None) -> dict:
    """The report that decides whether an analog set means anything.

    Forty neighbours from one regime are one observation wearing forty
    hats; concentration and nearest-neighbour stability are what tell
    the difference."""
    analogs = selection.get("analogs", [])
    if not analogs:
        return {"kind": "analog_quality", "verdict": "NO_ANALOGS",
                "n_raw": 0}
    dists = [a.distance for a in analogs]
    sessions = [a.session for a in analogs]
    years = sorted({s[:4] for s in sessions})
    covs = [a.feature_coverage for a in analogs]

    regimes = {}
    if regime_of:
        for s in sessions:
            r = regime_of.get(s, "UNKNOWN")
            regimes[r] = regimes.get(r, 0) + 1
    dominant = (max(regimes.values()) / len(sessions)) if regimes else \
        NOT_ESTIMABLE

    # top-5 influence: how much of the neighbourhood's total closeness
    # is carried by its five nearest members
    inv = [1.0 / (d + 1e-9) for d in dists]
    tot = sum(inv) or 1.0
    top5 = round(sum(sorted(inv, reverse=True)[:5]) / tot, 4)

    # nearest-neighbour stability: the gap between the 1st and kth
    # distances relative to the spread. A cliff means membership is
    # fragile to the cutoff.
    stability = NOT_ESTIMABLE
    if len(dists) >= 5:
        srt = sorted(dists)
        spread = (srt[-1] - srt[0]) or 1e-9
        stability = round(1.0 - (srt[4] - srt[0]) / spread, 4)

    concerns = []
    if isinstance(dominant, float) and dominant >= 0.5:
        concerns.append(
            f"REGIME_CONCENTRATION: {dominant:.0%} of analogs share one "
            f"regime; this neighbourhood may describe a regime, not a "
            f"setup")
    if top5 >= 0.6:
        concerns.append(
            f"TOP5_DOMINANCE: {top5:.0%} of closeness sits in five "
            f"members; the result is hostage to a handful of days")
    if len(set(years)) <= 2:
        concerns.append("NARROW_ERA: analogs span two years or fewer")
    if min(covs) < 0.9:
        concerns.append(
            f"COVERAGE: lowest analog feature coverage {min(covs):.2f}")

    return {"kind": "analog_quality",
            "n_raw": len(analogs),
            "n_effective_lower_bound": len(set(sessions)),
            "unique_sessions": len(set(sessions)),
            "unique_years": len(set(years)), "years": years,
            "regime_distribution": regimes or NOT_ESTIMABLE,
            "regime_concentration": (round(dominant, 4)
                                     if isinstance(dominant, float)
                                     else dominant),
            "distance_min": round(min(dists), 6),
            "distance_median": round(statistics.median(dists), 6),
            "distance_max": round(max(dists), 6),
            "feature_coverage_min": round(min(covs), 4),
            "top_5_influence": top5,
            "nearest_neighbour_stability": stability,
            "concerns": concerns,
            "verdict": "QUALIFIED" if not concerns else "QUALIFIED_WITH_CONCERNS",
            "law": "no analog fraction is a calibrated probability",
            "decision_power": "NONE_RESEARCH"}
