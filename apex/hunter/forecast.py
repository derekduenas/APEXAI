"""ForecastBundle — every predictive view in one typed object, with
disagreement as a first-class citizen and NO fake ensemble.

The bundle never averages its sources into one "super probability":
analogues, ML, playbook, simulation, and Swarm remain independently
inspectable with their own statuses. Any future combination rule must be
declared, versioned, pre-specified, and calibration-aware — until one
earns legitimacy, downstream consumers get SEPARATE VIEWS + DISAGREEMENT
+ a CONSERVATIVE ENVELOPE.

Disagreement can only maintain or increase caution, never aggression:
that monotonicity is enforced where sizing happens (capital), and the
bundle's job is to make hiding disagreement structurally impossible.

Distribution source statuses (frozen list): ANALOG_EMPIRICAL_EXPLORATORY,
ANALOG_FORWARD, ML_UNCALIBRATED, ML_CALIBRATED, HYBRID_UNCALIBRATED,
HYBRID_CALIBRATED, SIMULATED_UNCALIBRATED, REFUSED. No status stripping
downstream; an uncalibrated distribution cannot masquerade as calibrated
(mint_calibrated in the existing estimator remains the only mint).

Causal/mechanism status per candidate: DESCRIPTIVE, ASSOCIATIONAL,
MECHANISM_SUPPORTED, CAUSAL_IDENTIFICATION_AVAILABLE, REFUSED. A stated
playbook mechanism is ASSOCIATIONAL — prediction never claims causality.

Swarm: the deterministic Hunter is the FAST PATH and never waits. The
Swarm is optional enrichment; missing auth or a missed deadline yields
BLOCKED_EXTERNAL_AUTH / NOT_AVAILABLE_IN_TIME, never a fabricated view
and never a rewritten decision.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

FORECAST_BUNDLE_VERSION = "hunter_forecast_bundle_v1"

DISTRIBUTION_SOURCE_STATUSES = (
    "ANALOG_EMPIRICAL_EXPLORATORY", "ANALOG_FORWARD", "ML_UNCALIBRATED",
    "ML_CALIBRATED", "HYBRID_UNCALIBRATED", "HYBRID_CALIBRATED",
    "SIMULATED_UNCALIBRATED", "REFUSED")

MECHANISM_STATUSES = ("DESCRIPTIVE", "ASSOCIATIONAL", "MECHANISM_SUPPORTED",
                      "CAUSAL_IDENTIFICATION_AVAILABLE", "REFUSED")

SWARM_STATUSES = ("OK", "BLOCKED_EXTERNAL_AUTH", "NOT_AVAILABLE_IN_TIME",
                  "NOT_REQUESTED", "FAILED")


@dataclass(frozen=True)
class SwarmAssessment:
    candidate_id: str
    as_of: str
    status: str                       # from SWARM_STATUSES
    agents_run: tuple = ()
    claims: tuple = ()                # (agent, claim, provenance) triples
    disagreements: tuple = ()
    adversarial_flags: tuple = ()
    unresolved_questions: tuple = ()
    latency_seconds: float | None = None
    provenance: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in SWARM_STATUSES:
            raise ValueError(f"undeclared swarm status {self.status!r}")
        if self.status != "OK" and (self.claims or self.agents_run):
            raise ValueError("a non-OK swarm status cannot carry claims: "
                             "no fabricated views")


@dataclass(frozen=True)
class ForecastDisagreement:
    direction_disagreement: bool | None     # sources point opposite ways
    probability_dispersion: float | None    # max-min of available P(+)
    n_sources_with_view: int
    level: str                              # NONE/LOW/HIGH/UNMEASURABLE
    detail: tuple = ()


def measure_disagreement(playbook_direction: str | None,
                         analog_p: float | None,
                         ml_p: float | None,
                         swarm_adversarial: bool) -> ForecastDisagreement:
    ps = [p for p in (analog_p, ml_p) if p is not None]
    detail = []
    direction = None
    if playbook_direction and ps:
        want_up = playbook_direction == "LONG"
        opposed = [p for p in ps if (p < 0.5) == want_up]
        direction = bool(opposed)
        if opposed:
            detail.append("a probabilistic source opposes the playbook "
                          "direction")
    dispersion = round(max(ps) - min(ps), 4) if len(ps) >= 2 else None
    if swarm_adversarial:
        detail.append("swarm raised adversarial flags")
    if not ps and not swarm_adversarial:
        level = "UNMEASURABLE"
    elif direction or (dispersion is not None and dispersion > 0.15) \
            or swarm_adversarial:
        level = "HIGH"
    elif dispersion is not None and dispersion > 0.05:
        level = "LOW"
    else:
        level = "NONE"
    return ForecastDisagreement(
        direction_disagreement=direction,
        probability_dispersion=dispersion,
        n_sources_with_view=len(ps) + (1 if playbook_direction else 0),
        level=level, detail=tuple(detail))


@dataclass(frozen=True)
class ForecastBundle:
    candidate_id: str
    as_of: str
    horizon_minutes: int
    playbook_view: dict               # {playbook_id, direction, mechanism_status}
    analog_view: dict                 # AnalogResult summary incl. status/class
    ml_view: dict                     # HunterModel.predict output incl. status
    simulation_view: dict | None      # WorldSimulationResult summary or None
    swarm_view: dict                  # SwarmAssessment as dict
    mechanism_status: str
    disagreement: dict                # ForecastDisagreement as dict
    distribution_source_status: str   # from the frozen list
    provenance: dict
    bundle_version: str = field(default=FORECAST_BUNDLE_VERSION)

    def __post_init__(self):
        if self.distribution_source_status not in DISTRIBUTION_SOURCE_STATUSES:
            raise ValueError(
                f"undeclared distribution source status "
                f"{self.distribution_source_status!r}")
        if self.mechanism_status not in MECHANISM_STATUSES:
            raise ValueError(f"undeclared mechanism status "
                             f"{self.mechanism_status!r}")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "forecast_bundle"
        return d


def assemble_bundle(candidate: dict, *, analog_result=None, ml_prediction=None,
                    simulation=None, swarm: SwarmAssessment | None = None,
                    as_of: str | None = None,
                    horizon_minutes: int = 60) -> ForecastBundle:
    """The Monday-truth assembler: absent sources become typed absences.
    The distribution source status is derived, never asserted: with no
    admissible probabilistic source it is REFUSED — and that is the
    expected, successful Monday state."""
    analog_view = ({"status": "NOT_AVAILABLE"} if analog_result is None
                   else {"status": analog_result.status,
                         "evidence_class": analog_result.evidence_class,
                         "n_raw": analog_result.n_raw,
                         "n_effective": analog_result.n_effective,
                         "p_positive": analog_result.p_positive,
                         "median_return": analog_result.median_return,
                         "mean_distance": analog_result.mean_distance,
                         "uncertainty": analog_result.uncertainty,
                         "survivorship_limitation":
                             analog_result.survivorship_limitation})
    ml_view = ml_prediction or {"status": "UNTRAINED", "p_positive": None,
                                "reasons": ["INSUFFICIENT_FORWARD_DATA"]}
    swarm = swarm or SwarmAssessment(
        candidate_id=candidate.get("decision_id", "?"),
        as_of=as_of or candidate.get("t_utc", "?"),
        status="BLOCKED_EXTERNAL_AUTH")
    sim_view = None
    if simulation is not None:
        sim_view = {"status": simulation.calibration_status,
                    "source": simulation.source,
                    "n_paths": simulation.n_paths,
                    "branch_scenario_frequencies":
                        simulation.branch_scenario_frequencies,
                    "note": "scenario frequency, NOT calibrated probability"}

    analog_p = analog_view.get("p_positive")
    # sparse analogues may not claim a probability downstream
    if analog_view.get("status") in ("ANALOG_SUPPORT_LOW",
                                     "NO_VALID_ANALOGS", "NOT_AVAILABLE"):
        analog_p_for_view = None
    else:
        analog_p_for_view = analog_p
    ml_p = ml_view.get("p_positive")

    # derived, never asserted
    if analog_p_for_view is not None and ml_p is not None:
        src = "HYBRID_UNCALIBRATED"
    elif ml_p is not None:
        src = "ML_UNCALIBRATED"
    elif analog_p_for_view is not None:
        src = ("ANALOG_FORWARD"
               if analog_view.get("evidence_class")
               == "EODHD_FORWARD_OBSERVATION"
               else "ANALOG_EMPIRICAL_EXPLORATORY")
    else:
        src = "REFUSED"

    dis = measure_disagreement(
        candidate.get("direction"), analog_p_for_view, ml_p,
        bool(swarm.adversarial_flags))
    return ForecastBundle(
        candidate_id=candidate.get("decision_id", "?"),
        as_of=as_of or candidate.get("t_utc", "?"),
        horizon_minutes=horizon_minutes,
        playbook_view={"playbook_id": candidate.get("playbook_id"),
                       "direction": candidate.get("direction"),
                       "mechanism_status": "ASSOCIATIONAL"},
        analog_view=analog_view, ml_view=ml_view,
        simulation_view=sim_view, swarm_view=asdict(swarm),
        mechanism_status="ASSOCIATIONAL",
        disagreement=asdict(dis),
        distribution_source_status=src,
        provenance={"bundle": FORECAST_BUNDLE_VERSION,
                    "assembled_from_typed_absences": True})
