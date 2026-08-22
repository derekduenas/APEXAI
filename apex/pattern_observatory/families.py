"""PATTERN FAMILY REGISTRY -- twelve observational hypotheses, frozen.

Every family here is OBSERVATIONAL. None has been validated, none has a
probability, none may be promoted by the Observatory itself. They are
declared BEFORE any prospective observation so that a family cannot be
invented after the fact to describe something that already happened --
the same pre-registration discipline the rest of APEX runs on.

Each family declares `required_features`, which is what makes the
quality gate bite: a family requiring `volume` is NOT_ESTIMABLE on a
session losing 45% of its tape, and says so rather than quietly running
on corrupt inputs.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

OBSERVATIONAL = "OBSERVATIONAL"
NOT_ESTIMABLE = "NOT_ESTIMABLE"
NO_AUTHORITY = "NO_AUTHORITY"


@dataclass(frozen=True)
class PatternFamily:
    family_id: str
    name: str
    mechanism: str
    components_required: tuple
    components_optional: tuple
    sequence_steps: tuple
    required_features: tuple
    sleeves: tuple
    status: str = OBSERVATIONAL
    calibration_status: str = NOT_ESTIMABLE
    authority: str = NO_AUTHORITY

    def as_dict(self) -> dict:
        return {"kind": "pattern_family", **self.__dict__,
                "components_required": list(self.components_required),
                "components_optional": list(self.components_optional),
                "sequence_steps": list(self.sequence_steps),
                "required_features": list(self.required_features),
                "sleeves": list(self.sleeves),
                "decision_power": OBSERVATORY_POWER}


EQ = "EQUITIES_INTRADAY"
OPT = "OPTIONS"
PERP = "BTC_PERPS"

FAMILIES = (
    PatternFamily(
        "P001", "CROWDED_SHORT + PRICE_REFUSAL",
        "Shorts are crowded and price declines to fall on bad news; the "
        "marginal seller is exhausted and covering becomes forced.",
        ("crowded_short", "price_refusal"),
        ("breadth_improving", "sector_leadership_change", "vol_repricing"),
        ("positioning_extreme", "price_refusal", "breadth_improving",
         "curve_positive", "forced_flow"),
        ("price_direction", "positioning"), (EQ, OPT, PERP)),
    PatternFamily(
        "P002", "CROWDED_LONG + LEADERSHIP_FAILURE",
        "Consensus longs stop working while the index still holds; "
        "de-grossing begins in the leaders first.",
        ("crowded_long", "sector_leadership_change"),
        ("breadth_deteriorating", "vol_repricing"),
        ("positioning_extreme", "sector_leadership_change",
         "breadth_deteriorating", "curve_negative", "forced_flow"),
        ("price_direction", "positioning", "sector_leadership"), (EQ, OPT, PERP)),
    PatternFamily(
        "P003", "BREADTH_DIVERGENCE + INDEX_COMPRESSION",
        "The index is held up by few names while participation erodes -- "
        "the cross-section and the headline disagree.",
        ("breadth_divergence", "curve_state_change"),
        ("sector_dispersion", "volume_divergence"),
        ("breadth_deteriorating", "breadth_divergence", "curve_state_change"),
        ("price_direction", "breadth"), (EQ, OPT)),
    PatternFamily(
        "P004", "DEFENSIVE_ROTATION + TECH_BREAKDOWN",
        "Capital moves to staples/utilities/health while the tech complex "
        "breaks -- the 2026-08-19 cross-section exactly.",
        ("sector_rotation", "sector_leadership_change"),
        ("breadth_deteriorating", "vol_repricing"),
        ("sector_leadership_change", "sector_rotation",
         "breadth_deteriorating", "curve_negative"),
        ("price_direction", "sector_leadership"), (EQ, OPT)),
    PatternFamily(
        "P005", "SECTOR_LEADERSHIP_INFLECTION + INDEX_LAG",
        "A sector inflects before the index reflects it.",
        ("sector_leadership_change", "propagation_lead_lag"),
        ("breadth_improving", "sector_dispersion"),
        ("sector_leadership_change", "propagation_lead_lag",
         "curve_state_change"),
        ("price_direction", "sector_leadership"), (EQ,)),
    PatternFamily(
        "P006", "OPTIONS_SURFACE_REPRICING + UNDERLYING_LAG",
        "The option surface reprices risk before the underlying moves.",
        ("options_surface_state", "vol_repricing"),
        ("skew_change", "options_dislocation"),
        ("vol_repricing", "skew_change", "curve_state_change"),
        ("options_surface", "price_direction"), (EQ, OPT)),
    PatternFamily(
        "P007", "FASTWATCH_EARLY_STRUCTURE + LATER_HUNTER_EVENT",
        "Fast observation sees structure before the slow official "
        "playbook does. Pure attribution measurement -- FastWatch is not "
        "treated as a signal, only as a timestamp.",
        ("fastwatch_density",), ("curve_state_change", "obs_rvol_elevated"),
        ("fastwatch_density", "curve_state_change"),
        ("price_direction",), (EQ,)),
    PatternFamily(
        "P008", "CROSS_ASSET_RISK_OFF_PROPAGATION",
        "Risk-off propagates across asset classes in a repeatable order.",
        ("cross_asset_risk_off", "propagation_lead_lag"),
        ("vol_repricing", "breadth_deteriorating"),
        ("cross_asset_risk_off", "propagation_lead_lag",
         "breadth_deteriorating"),
        ("price_direction", "propagation"), (EQ, OPT, PERP)),
    PatternFamily(
        "P009", "SHORT_COVERING_SEQUENCE",
        "The ordered unwind of a crowded short: refusal, then breadth, "
        "then leadership, then forced buying.",
        ("crowded_short", "forced_flow"),
        ("breadth_improving", "obs_rvol_elevated"),
        ("positioning_extreme", "price_refusal", "breadth_improving",
         "sector_leadership_change", "forced_flow"),
        ("price_direction", "positioning", "volume"), (EQ, PERP)),
    PatternFamily(
        "P010", "DEGROSSING_SEQUENCE",
        "The ordered unwind of crowded longs: leadership fails, breadth "
        "weakens, vol reprices, liquidity thins, then the break.",
        ("crowded_long", "forced_flow"),
        ("breadth_deteriorating", "vol_repricing"),
        ("positioning_extreme", "sector_leadership_change",
         "breadth_deteriorating", "curve_negative", "vol_repricing",
         "forced_flow"),
        ("price_direction", "positioning", "sector_leadership"), (EQ, OPT, PERP)),
    PatternFamily(
        "P011", "VOL_COMPRESSION + LIQUIDITY_SHIFT",
        "Realised and implied vol compress while liquidity conditions "
        "change underneath.",
        ("vol_repricing", "term_structure"), ("volume_divergence",),
        ("term_structure", "vol_repricing", "curve_state_change"),
        ("options_surface", "volume"), (EQ, OPT, PERP)),
    PatternFamily(
        "P012", "POSITIONING_EXTREME + EXPECTATION_VIOLATION",
        "Positioning is stretched AND the market fails to respond as the "
        "consensus requires -- the cleanest setup for forced action.",
        ("positioning_extreme", "expectation_violation"),
        ("breadth_divergence", "vol_repricing"),
        ("positioning_extreme", "expectation_violation", "curve_state_change",
         "forced_flow"),
        ("price_direction", "positioning"), (EQ, OPT, PERP)),
)

BY_ID = {f.family_id: f for f in FAMILIES}


def get(family_id: str) -> PatternFamily:
    return BY_ID[family_id]


def for_sleeve(sleeve: str) -> tuple:
    return tuple(f for f in FAMILIES if sleeve in f.sleeves)


def matching(active_components: set) -> tuple:
    """Families whose REQUIRED components are all present."""
    return tuple(f for f in FAMILIES
                 if set(f.components_required) <= set(active_components))
