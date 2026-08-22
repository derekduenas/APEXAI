"""BREADTH STATE -- participation, and its divergence from the index.

HONESTY ABOUT WHAT "BREADTH" MEANS HERE. APEX observes 164 symbols plus
11 sector ETFs. It does NOT observe S&P 500 constituents. So this module
computes two clearly separated things and refuses to conflate them:

    SECTOR breadth    -- across the 11 SPDRs (complete, every sector)
    UNIVERSE breadth  -- across APEX's own 164-symbol watchlist
                         (a LIQUIDITY-SELECTED set, not the market)

The universe measure is labelled `universe_scope: APEX_164_LIQUIDITY_
SELECTED` on every record, because calling a large-cap-tilted watchlist
"market breadth" would be exactly the kind of quiet overclaim this whole
system is built to avoid. Index-constituent breadth is recorded as a
declared missing input, not silently approximated.

The observation that matters most is DIVERGENCE: on 2026-08-19 the index
was roughly flat while sector participation fell from 9/11 to 4/11. The
index and the cross-section were telling different stories, and nothing
in APEX was positioned to notice.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

SECTOR_SCOPE = "SECTOR_ETF_11"
UNIVERSE_SCOPE = "APEX_164_LIQUIDITY_SELECTED"
INDEX_CONSTITUENT_SCOPE = "INDEX_CONSTITUENTS"     # declared, never observed

STATES = ("BROAD_PARTICIPATION", "NARROWING", "DETERIORATING", "IMPROVING",
          "COLLAPSING", "RESILIENT", "DIVERGENT_INDEX_UP",
          "DIVERGENT_INDEX_DOWN", "NEUTRAL", "UNKNOWN")

# DECLARED, pre-registered, never fitted.
BROAD_MIN = 0.70
NARROW_MAX = 0.35
COLLAPSE_MAX = 0.20
VELOCITY_MATERIAL = 0.15        # change in advancing fraction that counts
MIN_MEMBERS = 8


@dataclass(frozen=True)
class BreadthMeasure:
    scope: str
    members_observed: int
    members_expected: int
    advancing: int
    declining: int
    advancing_fraction: float | None
    pct_above_obs_vwap: float | None
    pct_above_opening_range: float | None
    quality: str
    status: str

    def as_dict(self) -> dict:
        return {**self.__dict__, "decision_power": OBSERVATORY_POWER}


@dataclass(frozen=True)
class BreadthState:
    as_of: str
    known_from: str
    state: str
    sector: BreadthMeasure
    universe: BreadthMeasure
    index_constituents: dict
    index_return: float | None
    velocity: float | None
    acceleration: float | None
    divergence: str
    reasoning: tuple
    quality: str

    def as_dict(self) -> dict:
        return {"kind": "breadth_state", "as_of": self.as_of,
                "known_from": self.known_from, "state": self.state,
                "sector": self.sector.as_dict(),
                "universe": self.universe.as_dict(),
                "index_constituents": self.index_constituents,
                "index_return": self.index_return,
                "velocity": self.velocity, "acceleration": self.acceleration,
                "divergence": self.divergence,
                "reasoning": list(self.reasoning), "quality": self.quality,
                "decision_power": OBSERVATORY_POWER}


def measure(scope: str, rows: list, *, members_expected: int,
            quality: str) -> BreadthMeasure:
    """`rows`: [{return_from_open, above_obs_vwap, above_opening_range}, …]"""
    usable = [r for r in rows if r.get("return_from_open") is not None]
    n = len(usable)
    if n < MIN_MEMBERS:
        return BreadthMeasure(
            scope=scope, members_observed=n, members_expected=members_expected,
            advancing=0, declining=0, advancing_fraction=None,
            pct_above_obs_vwap=None, pct_above_opening_range=None,
            quality=quality, status="NOT_ESTIMABLE")
    adv = sum(1 for r in usable if r["return_from_open"] > 0)
    vw = [r for r in usable if r.get("above_obs_vwap") is not None]
    orr = [r for r in usable if r.get("above_opening_range") is not None]
    return BreadthMeasure(
        scope=scope, members_observed=n, members_expected=members_expected,
        advancing=adv, declining=n - adv, advancing_fraction=adv / n,
        pct_above_obs_vwap=(sum(1 for r in vw if r["above_obs_vwap"]) / len(vw)
                            if vw else None),
        pct_above_opening_range=(
            sum(1 for r in orr if r["above_opening_range"]) / len(orr)
            if orr else None),
        quality=quality, status="OK")


def compute(*, sector_rows: list, universe_rows: list,
            index_return: float | None, prior_fraction: float | None = None,
            prior_velocity: float | None = None, as_of, known_from,
            universe_expected: int = 164, quality: str = "UNKNOWN"
            ) -> BreadthState:
    sector = measure(SECTOR_SCOPE, sector_rows, members_expected=11,
                     quality=quality)
    universe = measure(UNIVERSE_SCOPE, universe_rows,
                       members_expected=universe_expected, quality=quality)

    # Sector breadth is the PRIMARY measure: it is complete (all 11
    # sectors observed) where the universe measure is a selected sample.
    frac = sector.advancing_fraction
    if frac is None:
        frac = universe.advancing_fraction

    velocity = (None if (frac is None or prior_fraction is None)
                else frac - prior_fraction)
    acceleration = (None if (velocity is None or prior_velocity is None)
                    else velocity - prior_velocity)

    reasoning, state, divergence = [], "UNKNOWN", "NONE"

    if frac is None:
        reasoning.append("neither sector nor universe breadth is estimable")
    else:
        if frac >= BROAD_MIN:
            state = "BROAD_PARTICIPATION"
        elif frac <= COLLAPSE_MAX:
            state = "COLLAPSING"
        elif frac <= NARROW_MAX:
            state = "NARROWING"
        else:
            state = "NEUTRAL"
        reasoning.append(f"{sector.advancing}/{sector.members_observed} "
                         f"sectors advancing ({frac:.0%})")

        if velocity is not None and abs(velocity) >= VELOCITY_MATERIAL:
            if velocity < 0:
                state = "DETERIORATING"
                reasoning.append(f"participation fell {abs(velocity):.0%} "
                                 f"since the prior observation")
            else:
                state = "IMPROVING"
                reasoning.append(f"participation rose {velocity:.0%} "
                                 f"since the prior observation")

        if index_return is not None:
            if index_return > 0 and frac < 0.40:
                divergence = "INDEX_UP_BREADTH_WEAK"
                state = "DIVERGENT_INDEX_UP"
                reasoning.append("index positive while participation is weak")
            elif index_return < 0 and frac > 0.60:
                divergence = "INDEX_DOWN_BREADTH_RESILIENT"
                state = "DIVERGENT_INDEX_DOWN"
                reasoning.append("index negative while participation holds")
            elif index_return < 0 and frac <= NARROW_MAX:
                reasoning.append("index and participation agree, both weak")

    return BreadthState(
        as_of=str(as_of), known_from=str(known_from), state=state,
        sector=sector, universe=universe,
        index_constituents={
            "scope": INDEX_CONSTITUENT_SCOPE, "status": "NOT_ACQUIRED",
            "reason": "APEX observes a 164-symbol liquidity-selected "
                      "universe, not index constituents. Approximating "
                      "index breadth from it would overstate coverage.",
            "decision_power": OBSERVATORY_POWER},
        index_return=index_return, velocity=velocity,
        acceleration=acceleration, divergence=divergence,
        reasoning=tuple(reasoning), quality=quality)
