"""WorldLabState — F6: bounded competing future branches, NOT a
narrative collapsed to one outcome.

Deliberately does NOT reimplement scenario simulation. It WRAPS
apex.world.simulator.simulate()'s already-built, already-tested
conditional block-bootstrap output (apex/world/simulator.py -- untouched
by this build, imported read-only) into the operator's scenario
taxonomy. The simulator's own BRANCHES enum
(STRONG_CONTINUATION/MODERATE_CONTINUATION/RANGE/FAILED_BREAKOUT/
REVERSAL/SHOCK) maps onto the requested CONTINUATION/FAILED_MOVE/
REVERSAL/NOISE/VOL_EXPANSION set; ROTATION, VOL_COMPRESSION, SQUEEZE and
LIQUIDITY_EVENT have no real signal behind them tonight (no constituent
map, no options surface, no liquidity feed, and the simulator itself has
no compression branch) and are declared UNREACHABLE, not faked.

ALL SIX BRANCHES ARE ALWAYS PRESERVED as competing scenarios, even at
zero support -- collapsing to "the likely one" is exactly what this
module refuses to do. `support_class` stays UNCALIBRATED_SCENARIO_WEIGHT
always (inherited verbatim from the simulator's own honesty label); an
ORDINAL_SUPPORT tier is added alongside it, never replacing the raw,
still-uncalibrated number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/world_lab_ledger.jsonl")

SCENARIO_TYPES = ("CONTINUATION", "FAILED_MOVE", "ROTATION", "REVERSAL",
                  "VOL_EXPANSION", "VOL_COMPRESSION", "SQUEEZE",
                  "LIQUIDITY_EVENT", "NOISE", "UNKNOWN")

BRANCH_TO_SCENARIO = {
    "STRONG_CONTINUATION": "CONTINUATION",
    "MODERATE_CONTINUATION": "CONTINUATION",
    "RANGE": "NOISE",
    "FAILED_BREAKOUT": "FAILED_MOVE",
    "REVERSAL": "REVERSAL",
    "SHOCK": "VOL_EXPANSION",
}

UNREACHABLE_SCENARIOS = {
    "ROTATION": "NO_CONSTITUENT_MAP",
    "VOL_COMPRESSION": "SIMULATOR_HAS_NO_COMPRESSION_BRANCH",
    "SQUEEZE": "NO_SHORT_INTEREST_OR_OPTIONS_SURFACE",
    "LIQUIDITY_EVENT": "NO_LIQUIDITY_FEED",
}

SUPPORT_CLASSES = ("ORDINAL_SUPPORT", "UNCALIBRATED_SCENARIO_WEIGHT")
ORDINAL_TIERS = ("NONE", "LOW", "MODERATE", "HIGH")

_NARRATIVE = {
    "CONTINUATION": dict(
        expected_market_behavior="price extends in the current direction "
        "with limited retracement",
        candidate_implications="entries aligned with the prevailing "
        "direction retain favorable path structure in this branch",
        participant_implications="trend-following flow likely persists",
        falsification="price closes back through the pre-move reference level"),
    "FAILED_MOVE": dict(
        expected_market_behavior="an attempted breakout/breakdown gives "
        "back most or all of its initial progress",
        candidate_implications="breakout-style entries in this branch are "
        "vulnerable to a snap-back stop-out",
        participant_implications="early movers may become trapped and "
        "forced to unwind",
        falsification="price holds beyond the breakout level for the "
        "remainder of the horizon"),
    "REVERSAL": dict(
        expected_market_behavior="price terminates the horizon net "
        "opposite to the current direction",
        candidate_implications="continuation-direction entries in this "
        "branch underperform",
        participant_implications="the dominant recent flow may be "
        "exhausted or overpowered",
        falsification="price makes a new extreme in the original direction"),
    "VOL_EXPANSION": dict(
        expected_market_behavior="realized range materially exceeds the "
        "recent baseline in either direction",
        candidate_implications="fixed stops/targets sized for calmer "
        "conditions may be too tight for this branch",
        participant_implications="forced hedging or risk-limit-driven "
        "flow becomes more likely",
        falsification="realized range stays within the recent baseline"),
    "NOISE": dict(
        expected_market_behavior="price oscillates without a durable "
        "directional resolution",
        candidate_implications="directional entries have weak expected "
        "edge in this branch specifically",
        participant_implications="no single participant class is "
        "obviously dominant",
        falsification="a sustained directional move develops"),
    "UNKNOWN": dict(
        expected_market_behavior="UNKNOWN", candidate_implications="UNKNOWN",
        participant_implications="UNKNOWN", falsification="UNKNOWN"),
}
for _s, _reason in UNREACHABLE_SCENARIOS.items():
    _NARRATIVE[_s] = dict(
        expected_market_behavior=f"UNREACHABLE: {_reason}",
        candidate_implications=f"UNREACHABLE: {_reason}",
        participant_implications=f"UNREACHABLE: {_reason}",
        falsification=f"UNREACHABLE: {_reason}")


class WorldLabError(RuntimeError):
    pass


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scenario_type: str
    required_conditions: tuple
    current_support: float
    support_ordinal: str
    contradictions: tuple
    expected_market_behavior: str
    expected_sector_behavior: str
    candidate_implications: str
    participant_implications: str
    falsification: str
    quality: str
    support_class: str
    known_from: str

    def __post_init__(self):
        if self.scenario_type not in SCENARIO_TYPES:
            raise WorldLabError(f"unknown scenario_type {self.scenario_type!r}")
        if self.support_class not in SUPPORT_CLASSES:
            raise WorldLabError("bad support_class")
        if self.support_ordinal not in ORDINAL_TIERS:
            raise WorldLabError("bad support_ordinal")

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorldLabState:
    subject: str
    as_of: str
    known_from: str
    scenarios: tuple
    simulator_source: str
    simulator_version: str
    quality: str
    decision_power: str = FRONTIER2_POWER

    def as_record(self) -> dict:
        return {"kind": "world_lab_state", "subject": self.subject,
               "as_of": self.as_of, "known_from": self.known_from,
               "scenarios": [s for s in self.scenarios],
               "simulator_source": self.simulator_source,
               "simulator_version": self.simulator_version,
               "quality": self.quality, "decision_power": self.decision_power}


def _ordinal(support: float) -> str:
    if support <= 0:
        return "NONE"
    if support < 0.15:
        return "LOW"
    if support < 0.35:
        return "MODERATE"
    return "HIGH"


def from_simulation(sim, *, subject: str, quality: str = "UNKNOWN"
                    ) -> WorldLabState:
    """`sim`: an apex.world.simulator.WorldSimulationResult, already
    computed by a caller that has the real bars/history/TwinSnapshot in
    hand -- this function does no simulation itself, only reshaping."""
    if sim.calibration_status != "UNCALIBRATED_SCENARIO_WEIGHT":
        raise WorldLabError(
            f"refusing to wrap a simulation with calibration_status "
            f"{sim.calibration_status!r} -- only the uncalibrated "
            f"contract is honored until a real calibration report exists")

    scenarios = []
    for branch, freq in sim.branch_scenario_frequencies.items():
        stype = BRANCH_TO_SCENARIO.get(branch, "UNKNOWN")
        narrative = _NARRATIVE[stype]
        reachable = stype not in UNREACHABLE_SCENARIOS
        scenarios.append(Scenario(
            scenario_id=f"{sim.simulation_id}:{branch}", scenario_type=stype,
            required_conditions=(f"donor_sessions>=5 (had "
                                 f"{sim.provenance.get('donor_sessions')})",),
            current_support=float(freq) if reachable else 0.0,
            support_ordinal=_ordinal(float(freq)) if reachable else "NONE",
            contradictions=(), expected_market_behavior=narrative["expected_market_behavior"],
            expected_sector_behavior="UNKNOWN: no sector/constituent map wired",
            candidate_implications=narrative["candidate_implications"],
            participant_implications=narrative["participant_implications"],
            falsification=narrative["falsification"], quality=quality,
            support_class="UNCALIBRATED_SCENARIO_WEIGHT",
            known_from=sim.as_of).as_record())

    # the four scenario types the SIMULATOR ITSELF never produces --
    # always present, always zero support, always UNREACHABLE-labeled,
    # so "competing scenarios" means ALL ten types, not just the six
    # the bootstrap happens to model.
    for stype, reason in UNREACHABLE_SCENARIOS.items():
        narrative = _NARRATIVE[stype]
        scenarios.append(Scenario(
            scenario_id=f"{sim.simulation_id}:{stype}", scenario_type=stype,
            required_conditions=(f"UNREACHABLE: {reason}",),
            current_support=0.0, support_ordinal="NONE", contradictions=(),
            expected_market_behavior=narrative["expected_market_behavior"],
            expected_sector_behavior="UNKNOWN: no sector/constituent map wired",
            candidate_implications=narrative["candidate_implications"],
            participant_implications=narrative["participant_implications"],
            falsification=narrative["falsification"], quality=quality,
            support_class="UNCALIBRATED_SCENARIO_WEIGHT",
            known_from=sim.as_of).as_record())

    return WorldLabState(
        subject=subject, as_of=sim.as_of, known_from=sim.as_of,
        scenarios=tuple(scenarios), simulator_source=sim.source,
        simulator_version=sim.simulator_version, quality=quality)


def persist(state: WorldLabState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
