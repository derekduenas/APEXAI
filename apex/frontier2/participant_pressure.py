"""ParticipantPressureState — F3: bounded inference about who may be
forced to act next, WITHOUT claiming actual participant identity.

THE HONESTY LAW: `possible_driver` defaults to UNKNOWN and stays there
unless a specific, named, price-action-only pattern legitimately
narrows it. APEX has zero options/dealer/CTA/ETF-flow feed tonight, so
DEALER_HEDGING, VOL_CONTROL, CTA_TREND, PASSIVE_FLOW and ETF_FLOW can
never be inferred by this build -- they exist in the enum as declared
future capability, not as reachable outputs (a test proves this).
Only two drivers are ever actually reachable from price/volume alone:
SHORT_COVERING (a failed breakdown that reclaims, on elevated
participation -- a textbook, named inference) and MOMENTUM_CHASE (an
accelerating move on elevated participation, same direction). Every
other driver, and `pressure_direction` / `trap_state` when the
underlying signals do not fire, resolve honestly to UNKNOWN or NONE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from apex.frontier2 import FRONTIER2_POWER

LEDGER = Path("results/frontier2/participant_pressure_ledger.jsonl")

DRIVERS = ("INSTITUTIONAL_ACCUMULATION", "INSTITUTIONAL_DISTRIBUTION",
          "SHORT_COVERING", "SHORT_PRESSURE", "MOMENTUM_CHASE",
          "PASSIVE_FLOW", "ETF_FLOW", "DEALER_HEDGING", "VOL_CONTROL",
          "CTA_TREND", "RETAIL_MOMENTUM", "EVENT_FLOW", "UNKNOWN")

# drivers this build can NEVER honestly infer tonight, and why. A test
# asserts no code path ever returns one of these.
UNREACHABLE_DRIVERS = {
    "INSTITUTIONAL_ACCUMULATION": "NO_BLOCK_PRINT_OR_DARK_POOL_FEED",
    "INSTITUTIONAL_DISTRIBUTION": "NO_BLOCK_PRINT_OR_DARK_POOL_FEED",
    "SHORT_PRESSURE": "NO_SHORT_INTEREST_OR_BORROW_FEED",
    "PASSIVE_FLOW": "NO_ETF_CREATION_REDEMPTION_FEED",
    "ETF_FLOW": "NO_ETF_CREATION_REDEMPTION_FEED",
    "DEALER_HEDGING": "NO_OPTIONS_SURFACE",
    "VOL_CONTROL": "NO_OPTIONS_SURFACE",
    "CTA_TREND": "NO_CTA_POSITIONING_FEED",
    "RETAIL_MOMENTUM": "NO_RETAIL_ORDER_FLOW_FEED",
    "EVENT_FLOW": "NO_TIMESTAMPED_CATALYST_SOURCE_WIRED",
}

DIRECTIONS = ("UP", "DOWN", "NONE", "UNKNOWN")
TRAP_STATES = ("NONE", "POSSIBLE_LONG_TRAP", "POSSIBLE_SHORT_TRAP",
              "CONFIRMED_BY_PRICE_ACTION", "UNCLEAR")
POTENTIAL = ("NONE", "LOW", "MODERATE", "HIGH", "UNKNOWN")
UNCERTAINTY = ("LOW", "MODERATE", "HIGH")

RVOL_ELEVATED = 2.0


class ParticipantPressureError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParticipantPressureState:
    candidate: str
    possible_driver: str
    pressure_direction: str
    forced_action_potential: str
    trap_state: str
    support: tuple
    contradictions: tuple
    falsification: str
    quality: str
    uncertainty: str
    event_time: str
    known_from: str
    as_of: str
    decision_power: str = FRONTIER2_POWER

    def __post_init__(self):
        if self.possible_driver not in DRIVERS:
            raise ParticipantPressureError(
                f"unknown driver {self.possible_driver!r}")
        if self.possible_driver in UNREACHABLE_DRIVERS:
            raise ParticipantPressureError(
                f"{self.possible_driver} is declared UNREACHABLE tonight "
                f"({UNREACHABLE_DRIVERS[self.possible_driver]}) -- a "
                f"caller tried to assert it anyway")
        if self.pressure_direction not in DIRECTIONS:
            raise ParticipantPressureError("bad pressure_direction")
        if self.trap_state not in TRAP_STATES:
            raise ParticipantPressureError("bad trap_state")
        if self.forced_action_potential not in POTENTIAL:
            raise ParticipantPressureError("bad forced_action_potential")
        if self.uncertainty not in UNCERTAINTY:
            raise ParticipantPressureError("bad uncertainty")

    def as_record(self) -> dict:
        return {"kind": "participant_pressure_state", **asdict(self)}


def infer(candidate: str, *, or_break_up: bool | None = None,
         or_break_down: bool | None = None, or_failure: bool | None = None,
         vwap_reclaim: bool | None = None, vwap_rejection: bool | None = None,
         rvol_tod: float | None = None, trend_slope: float | None = None,
         subsequent_hold: bool | None = None, quality: str = "UNKNOWN",
         event_time, known_from, now) -> ParticipantPressureState:
    """Every input is an already-canonical ChartState field (or None if
    unavailable -- never fabricated). `subsequent_hold`: an optional
    LATER observation the caller supplies (did the reclaim/break hold
    on a following bar) -- this function does no time-series scanning
    of its own; that discipline stays with whatever caller walks the
    bar series, keeping this function pure and testable at one instant."""
    import pandas as pd
    now = pd.Timestamp(now)
    elevated = rvol_tod is not None and rvol_tod >= RVOL_ELEVATED
    support: list = []
    contradictions: list = []
    driver = "UNKNOWN"
    direction = "UNKNOWN"
    trap = "NONE"
    falsification = "no pattern currently active"
    potential = "UNKNOWN"

    if or_break_up and or_failure:
        trap = "POSSIBLE_LONG_TRAP"
        direction = "DOWN"
        support.append("or_break_up_then_failure")
        falsification = "price reclaims the opening-range high and holds"
        potential = "HIGH" if elevated else "MODERATE"
        if subsequent_hold is True:
            trap = "CONFIRMED_BY_PRICE_ACTION"
            support.append("subsequent_hold_confirmed")
        elif subsequent_hold is False:
            trap = "UNCLEAR"
            contradictions.append("subsequent_hold_failed_to_confirm")

    elif or_break_down and or_failure:
        trap = "POSSIBLE_SHORT_TRAP"
        direction = "UP"
        support.append("or_break_down_then_failure")
        falsification = "price breaks back below the opening-range low and holds"
        potential = "HIGH" if elevated else "MODERATE"
        if elevated:
            driver = "SHORT_COVERING"
            support.append("rvol_elevated")
        if subsequent_hold is True:
            trap = "CONFIRMED_BY_PRICE_ACTION"
            support.append("subsequent_hold_confirmed")
        elif subsequent_hold is False:
            trap = "UNCLEAR"
            contradictions.append("subsequent_hold_failed_to_confirm")

    elif vwap_reclaim and elevated and (trend_slope or 0) > 0:
        direction = "UP"
        support.extend(["vwap_reclaim", "rvol_elevated", "trend_slope_positive"])
        falsification = "price rejects back below VWAP"
        potential = "MODERATE"
        driver = "MOMENTUM_CHASE"

    elif vwap_rejection and elevated and (trend_slope or 0) < 0:
        direction = "DOWN"
        support.extend(["vwap_rejection", "rvol_elevated", "trend_slope_negative"])
        falsification = "price reclaims back above VWAP"
        potential = "MODERATE"
        driver = "MOMENTUM_CHASE"

    else:
        potential = "NONE" if rvol_tod is not None else "UNKNOWN"
        direction = "NONE" if rvol_tod is not None else "UNKNOWN"

    uncertainty = ("LOW" if len(support) >= 2 else
                  "MODERATE" if len(support) == 1 else "HIGH")

    et = pd.Timestamp(event_time)
    return ParticipantPressureState(
        candidate=candidate, possible_driver=driver,
        pressure_direction=direction, forced_action_potential=potential,
        trap_state=trap, support=tuple(support),
        contradictions=tuple(contradictions), falsification=falsification,
        quality=quality, uncertainty=uncertainty, event_time=str(et),
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))


def persist(state: ParticipantPressureState) -> dict:
    import sys
    sys.path.insert(0, "scripts")
    from nightly_pull import _chain_append
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    return _chain_append(LEDGER, state.as_record())
