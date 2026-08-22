"""COMPONENT REGISTRY -- the producer/consumer invariant (Build Addendum C).

WHAT THIS WOULD HAVE CAUGHT, had it existed:

    LeadingEdgeMap          imported by the runtime, lemod.rank() never
                            called -> SERIOUS and WAIT_FOR_ENTRY were
                            mathematically unreachable for an entire
                            session and nobody knew
    FastWatch attribution   module built and tested, no writer, ledger
                            never created
    Options Expression      run() and seal() have zero callers anywhere
    EV / PP / Propagation   98,000 rows written per session, no reader
    System Cognition        1,203 rows, no reader
    Options surfaces        21,354 rows, no reader

Every one of those was found by hand, days or weeks late. The invariant
below turns that archaeology into a test.

THE RULE. A component declares what it IS, and the tests refuse to let
the declaration be flattering:

  * LIVE_ACTIVE with no live caller is a lie -> test fails
  * LIVE_ACTIVE, non-terminal, zero consumers is an orphan -> test fails
  * imported but never called must declare NOT_WIRED
  * INTERFACE_ONLY may have no producer but must state data availability
  * nothing here may write into the production decision path

This registry is deliberately generic. The intention is that it becomes
reusable across APEX rather than staying an Observatory-local idea.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import (
    OBSERVATORY_POWER, PRODUCTION_STACK_FORBIDDEN, WRITE_ROOT,
)

LIVE_ACTIVE = "LIVE_ACTIVE"
LIVE_TERMINAL = "LIVE_TERMINAL"
WIRED_NOT_RUNNING = "WIRED_NOT_RUNNING"
NOT_WIRED = "NOT_WIRED"
DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
INTERFACE_ONLY = "INTERFACE_ONLY"

STATUSES = (LIVE_ACTIVE, LIVE_TERMINAL, WIRED_NOT_RUNNING, NOT_WIRED,
            DEPENDENCY_MISSING, INTERFACE_ONLY)

# A TERMINAL role is a legitimate end of a chain: something a human or an
# audit reads. It is the only honest way for a live component to have no
# downstream code consumer.
TERMINAL_ROLES = ("OPERATOR_REPORT", "AUDIT_EVIDENCE", "PROSPECTIVE_MEMORY",
                  "ACCEPTANCE_BOARD", None)


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class Component:
    component_name: str
    status: str
    producer: str | None
    live_caller: str | None
    inputs: tuple
    outputs: tuple
    consumers: tuple
    terminal_role: str | None
    decision_power: str = OBSERVATORY_POWER
    data_availability: str | None = None
    notes: str | None = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise RegistryError(f"{self.component_name}: bad status "
                                f"{self.status!r}")
        if self.terminal_role not in TERMINAL_ROLES:
            raise RegistryError(f"{self.component_name}: unknown terminal "
                                f"role {self.terminal_role!r}")
        if self.decision_power != OBSERVATORY_POWER:
            raise RegistryError(f"{self.component_name}: decision_power must "
                                f"be {OBSERVATORY_POWER}")

    def as_dict(self) -> dict:
        return {"kind": "observatory_component", **self.__dict__,
                "inputs": list(self.inputs), "outputs": list(self.outputs),
                "consumers": list(self.consumers)}


RUNTIME = "scripts/pattern_observatory_shadow_runtime.py"

COMPONENTS = (
    Component("quality", LIVE_ACTIVE, "apex.pattern_observatory.quality",
              RUNTIME, ("canonical 1m bars (gap_duration_ms, coverage_status)",),
              ("PatternInputQuality",),
              ("world_state", "pattern_state", "pattern_assassin"), None),
    Component("obs_features", LIVE_ACTIVE,
              "apex.pattern_observatory.obs_features", RUNTIME,
              ("canonical 1m bars",),
              ("OBS_VWAP", "OBS_OPENING_RANGE", "OBS_RVOL",
               "OBS_RETURN_FROM_OPEN", "OBS_DISPERSION"),
              ("sector_rotation", "breadth"), None,
              notes="Observatory-derived, NOT canonical, NOT Hunter-equivalent"),
    Component("sector_rotation", LIVE_ACTIVE,
              "apex.pattern_observatory.sector_rotation", RUNTIME,
              ("11 sector ETF bars", "SPY bars", "obs_features"),
              ("SectorRotationState",), ("world_state", "conjunction"), None,
              notes="CONVERGENCE INTENT (2026-08-20): apex.market_state "
                    "is now the canonical cross-sectional producer "
                    "(Curve already consumes it). This module migrates "
                    "to reading market_state once the Observatory's "
                    "day-over-day comparability window allows -- kept "
                    "unchanged for day 2 so its first cross-session "
                    "comparison is sensor-stable."),
    Component("breadth", LIVE_ACTIVE, "apex.pattern_observatory.breadth",
              RUNTIME, ("sector rows", "universe rows", "index return"),
              ("BreadthState",), ("world_state", "conjunction"), None,
              notes="same market_state convergence intent as "
                    "sector_rotation; unchanged for day-2 comparability"),
    Component("options_surface", LIVE_ACTIVE,
              "apex.pattern_observatory.options_surface", RUNTIME,
              ("results/option_analytics/live/states.jsonl",),
              ("OptionsSurfacePatternState",),
              ("world_state", "conjunction"), None,
              notes="FIRST reader of an artifact that had zero consumers"),
    Component("positioning", LIVE_ACTIVE,
              "apex.pattern_observatory.positioning", RUNTIME,
              ("cftc_positioning", "finra_short_pressure"),
              ("InstitutionalPositioningState", "CrowdingState",
               "ForcedFlowState"),
              ("world_state",), None,
              data_availability="CFTC TFF and FINRA short volume NOW WIRED; "
                                "13F/"
                                "Form4/ETF-flows NOT_ACQUIRED (free, "
                                "obtainable); short-INTEREST/borrow/prime-"
                                "broker/CTA UNAVAILABLE (paid or "
                                "institutional); perp funding/OI/liquidations "
                                "NOT_ACQUIRED (sleeve not built)"),
    Component("publication_lag", LIVE_ACTIVE,
              "apex.pattern_observatory.publication_lag", RUNTIME,
              ("EXTERNAL:publisher-declared release schedules",),
              ("PublicationPolicy", "LaggedObservation", "source_state"),
              ("cftc_positioning", "finra_short_pressure"), None,
              notes="event_time = when it was TRUE; known_from = when APEX "
                    "could have OBTAINED it. Construction raises on "
                    "lookahead. Expected publication latency is classified, "
                    "never written to an error ledger."),
    Component("cftc_positioning", LIVE_ACTIVE,
              "apex.pattern_observatory.cftc_positioning", RUNTIME,
              ("EXTERNAL:CFTC Socrata gpe5-46if (TFF futures-only)",
               "publication_lag"),
              ("PositioningFact",), ("positioning", "world_state"), None,
              data_availability="AVAILABLE_LAGGED -- positions as of Tuesday, "
                                "released Friday; measured lag 9 days on "
                                "2026-08-19. NOT live, NOT smart money.",
              notes="first real institutional positioning data APEX has had"),
    Component("finra_short_pressure", LIVE_ACTIVE,
              "apex.pattern_observatory.finra_short_pressure", RUNTIME,
              ("EXTERNAL:cdn.finra.org daily short-sale volume",
               "publication_lag"),
              ("ShortPressureState",), ("positioning", "world_state"), None,
              data_availability="AVAILABLE -- same-day, but OFF-EXCHANGE ONLY "
                                "and short VOLUME is not short INTEREST",
              notes="produces short PRESSURE only; crowding needs short "
                    "interest + borrow, both still UNAVAILABLE"),
    Component("probability", LIVE_ACTIVE,
              "apex.pattern_observatory.probability", RUNTIME,
              ("PatternState", "PatternOutcome"),
              ("ForwardDistribution",), ("pattern_state", "summary"), None,
              notes="architecture complete; evidence gate CLOSED -- every "
                    "answer is PROBABILITY_NOT_ESTIMABLE until "
                    "prospective_n>=30 across >=10 sessions and >=2 regimes"),
    Component("information_lead", LIVE_ACTIVE,
              "apex.pattern_observatory.information_lead", RUNTIME,
              ("PatternState", "canonical bars"),
              ("InformationLead",), ("summary",), None,
              notes="measures whether an organ is EARLY, not merely correct; "
                    "negative leads are retained as the finding"),
    Component("world_state", LIVE_ACTIVE,
              "apex.pattern_observatory.world_state", RUNTIME,
              ("sector_rotation", "breadth", "options_surface", "positioning",
               "cftc_positioning", "finra_short_pressure",
               "frontier2 artifacts", "crypto artifacts"),
              ("PatternWorldState", "pattern_world_state.jsonl"),
              ("conjunction", "abnormality"), None),
    Component("abnormality", LIVE_ACTIVE,
              "apex.pattern_observatory.abnormality", RUNTIME,
              ("world_state facets", "prior observations"),
              ("Abnormality",), ("conjunction", "pattern_state"), None),
    Component("independence", LIVE_ACTIVE,
              "apex.pattern_observatory.independence", RUNTIME,
              ("component names",), ("mechanism_independence",),
              ("conjunction", "pattern_assassin", "contradiction"), None),
    Component("conjunction", LIVE_ACTIVE,
              "apex.pattern_observatory.conjunction", RUNTIME,
              ("world_state", "abnormality", "independence"),
              ("Conjunction",), ("pattern_state", "sequence"), None),
    Component("sequence", LIVE_ACTIVE, "apex.pattern_observatory.sequence",
              RUNTIME, ("conjunction", "families"),
              ("PatternSequenceState", "pattern_sequence_ledger.jsonl"),
              ("pattern_state", "pattern_assassin"), None),
    Component("families", LIVE_ACTIVE, "apex.pattern_observatory.families",
              RUNTIME, ("pre-registered declarations",),
              ("PatternFamily", "pattern_family_registry.jsonl"),
              ("conjunction", "pattern_state", "contradiction", "sleeves"),
              None),
    Component("contradiction", LIVE_ACTIVE,
              "apex.pattern_observatory.contradiction", RUNTIME,
              ("active components", "independence", "quality"),
              ("ContradictionReport",), ("pattern_state",), None),
    Component("support", LIVE_ACTIVE, "apex.pattern_observatory.support",
              RUNTIME,
              ("pattern_ledger.jsonl (own history, known_from-filtered)",),
              ("pattern_support_aggregation",), ("pattern_state",), None,
              notes="closes the evidence-accumulation loop found by the "
                    "2026-08-19 audit -- without this, prospective_n was "
                    "permanently 0 and the probability gate could never "
                    "open regardless of elapsed time"),
    Component("pattern_state", LIVE_ACTIVE,
              "apex.pattern_observatory.pattern_state", RUNTIME,
              ("conjunction", "families", "quality", "sequence",
               "contradiction", "support"),
              ("PatternState", "pattern_ledger.jsonl"),
              ("pattern_assassin", "outcomes", "summary", "memory"), None),
    Component("pattern_assassin", LIVE_ACTIVE,
              "apex.pattern_observatory.pattern_assassin", RUNTIME,
              ("pattern_state", "sequence"),
              ("PatternAssassinReview", "pattern_assassin_ledger.jsonl"),
              ("summary",), None,
              notes="scale-free wounds only; PREDICTION_RESIDUAL_BREAK "
                    "explicitly forbidden"),
    Component("outcomes", LIVE_ACTIVE, "apex.pattern_observatory.outcomes",
              RUNTIME, ("pattern_ledger.jsonl", "canonical bars"),
              ("PatternOutcome", "pattern_outcomes.jsonl"),
              ("resolution",), None,
              notes="REGISTRY CONFESSION (2026-08-21): this row said "
                    "LIVE_ACTIVE for two days while resolve() had ZERO "
                    "call sites -- the invariant checked declarations, "
                    "not code. tests/test_living_organism_2026_08_21.py "
                    "now proves the call sites by AST. Genuinely live "
                    "via the resolution loop since 2026-08-21."),
    Component("resolution", LIVE_ACTIVE,
              "apex.pattern_observatory.resolution", RUNTIME,
              ("pattern_ledger.jsonl", "pattern_outcomes.jsonl",
               "canonical bars", "outcomes"),
              ("pattern_outcomes.jsonl rows", "outcome_corpus",
               "newly_terminal signal"),
              ("probability", "information_lead", "summary"), None,
              notes="the learning loop's pump: resolves every episode x "
                    "horizon exactly once, session-boundary horizons "
                    "become terminally UNRESOLVABLE after a full "
                    "overnight (never re-checked forever, never "
                    "extrapolated)"),
    Component("crypto_sensor", LIVE_ACTIVE,
              "apex.pattern_observatory.crypto_sensor", RUNTIME,
              ("EXTERNAL:crypto arena daemon "
               "(results/crypto/crypto_health.json, read-only)",
               "results/crypto/arena_ledger.jsonl (read-only)"),
              ("crypto facet state",), ("world_state",), None,
              data_availability="LIVE Coinbase forward-observation arena "
                                "(sleeve observability only); market "
                                "features funding/OI/basis NOT_DERIVED "
                                "yet, declared honestly",
              notes="lights the crypto facet from the sensor that ran "
                    "healthy for days while the facet sat DARK; "
                    "read-only by AST test"),
    Component("birth", LIVE_ACTIVE, "apex.pattern_observatory.birth", RUNTIME,
              ("wall clock",), ("birth.json",),
              ("memory", "pattern_state", "world_state"), None),
    Component("memory", LIVE_ACTIVE, "apex.pattern_observatory.memory",
              RUNTIME,
              ("PatternState", "PatternSequenceState",
               "PatternAssassinReview", "PatternOutcome", "PatternWorldState",
               "PatternFamily"),
              ("pattern_ledger.jsonl", "pattern_sequence_ledger.jsonl",
               "pattern_outcomes.jsonl", "pattern_family_registry.jsonl",
               "pattern_assassin_ledger.jsonl", "pattern_world_state.jsonl"),
              (), "PROSPECTIVE_MEMORY"),
    Component("sleeves", LIVE_ACTIVE, "apex.pattern_observatory.sleeves",
              RUNTIME, ("families",), ("sleeve_relevance",),
              ("pattern_state",), None,
              data_availability="EQUITIES_INTRADAY LIVE; OPTIONS "
                                "LIVE_OBSERVATIONAL; BTC_PERPS NOT_AVAILABLE"),
    Component("summary", LIVE_TERMINAL, "apex.pattern_observatory.summary",
              RUNTIME, ("pattern_state", "pattern_assassin", "world_state"),
              ("PatternObservatorySummary",), (), "OPERATOR_REPORT",
              notes="no current Captain consumer BY DESIGN"),
    Component("registry", LIVE_TERMINAL, "apex.pattern_observatory.registry",
              RUNTIME, ("component declarations",), ("component_registry",),
              (), "AUDIT_EVIDENCE"),
)

BY_NAME = {c.component_name: c for c in COMPONENTS}


def snapshot() -> dict:
    by_status: dict = {}
    for c in COMPONENTS:
        by_status.setdefault(c.status, []).append(c.component_name)
    return {"kind": "observatory_component_registry",
            "n_components": len(COMPONENTS),
            "by_status": {k: sorted(v) for k, v in sorted(by_status.items())},
            "components": [c.as_dict() for c in COMPONENTS],
            "write_root": WRITE_ROOT,
            "forbidden_imports": list(PRODUCTION_STACK_FORBIDDEN),
            "decision_power": OBSERVATORY_POWER}


def violations() -> list:
    """Every way a declaration can be flattering. Empty list == honest."""
    out = []
    names = set(BY_NAME)
    for c in COMPONENTS:
        if c.status == LIVE_ACTIVE and not c.live_caller:
            out.append({"component": c.component_name,
                        "violation": "LIVE_ACTIVE_WITHOUT_LIVE_CALLER"})
        if (c.status == LIVE_ACTIVE and not c.consumers
                and c.terminal_role is None):
            out.append({"component": c.component_name,
                        "violation": "ORPHAN_OUTPUT_NO_CONSUMER",
                        "detail": f"outputs {list(c.outputs)} are read by "
                                  f"nobody and no terminal role is declared"})
        if c.status == LIVE_TERMINAL and c.terminal_role is None:
            out.append({"component": c.component_name,
                        "violation": "TERMINAL_WITHOUT_ROLE"})
        if c.status == INTERFACE_ONLY and not c.data_availability:
            out.append({"component": c.component_name,
                        "violation": "INTERFACE_ONLY_WITHOUT_AVAILABILITY"})
        for dep in c.inputs:
            if dep in names and BY_NAME[dep].status == NOT_WIRED:
                out.append({"component": c.component_name,
                            "violation": "DEPENDS_ON_NOT_WIRED",
                            "detail": dep})
        # a consumer that does not exist is the mirror image of an orphan
        for con in c.consumers:
            if con not in names:
                out.append({"component": c.component_name,
                            "violation": "CONSUMER_DOES_NOT_EXIST",
                            "detail": con})
    return out


def hungry_consumers() -> list:
    """Components declaring an input that no component produces.

    An input prefixed `EXTERNAL:` names a third-party source outside
    APEX and is exempt by construction -- the convention exists so the
    exemption is DECLARED per input rather than inferred from keyword
    guessing, which is how a real orphan would eventually slip through.
    """
    produced = set()
    for c in COMPONENTS:
        produced.add(c.component_name)
        produced.update(c.outputs)
    out = []
    for c in COMPONENTS:
        for dep in c.inputs:
            if dep.startswith("EXTERNAL:"):
                continue
            if dep not in produced and not any(
                    tok in dep for tok in ("bars", "jsonl", "artifacts",
                                           "clock", "declarations", "rows",
                                           "return", "names", "none",
                                           "components", "facets",
                                           "observations")):
                out.append({"component": c.component_name, "missing_input": dep})
    return out


def external_sources() -> list:
    """Every third-party dependency, declared. Useful on its own: it is
    the list of things that can break APEX from outside."""
    return sorted({dep[len("EXTERNAL:"):] for c in COMPONENTS
                   for dep in c.inputs if dep.startswith("EXTERNAL:")})
