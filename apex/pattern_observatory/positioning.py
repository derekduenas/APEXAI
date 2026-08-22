"""INSTITUTIONAL POSITIONING / CROWDING / FORCED FLOW.

READ THIS BEFORE ADDING A NUMBER TO ANY OF THESE STATES.

STATUS CHANGED 2026-08-19 (evening). This module was INTERFACE_ONLY for
one afternoon: a repository-wide `find` for cftc / positioning /
short_interest / borrow had returned NOTHING, so it defined the shape of
the intelligence and reported, per source, exactly why it was empty.

Two real sources are now wired -- CFTC Traders in Financial Futures (see
cftc_positioning.py) and FINRA daily off-exchange short-sale volume (see
finra_short_pressure.py). Six of nineteen sources remain genuinely
UNAVAILABLE (paid or institutional) and eight remain NOT_ACQUIRED
(obtainable, unwired). The register below states which is which, per
source, and it is the honest answer rather than a flattering one.

The operator's instruction stands and still governs every line here:
*"Do not build Institutional Positioning with fake/sample data just to
make the organ look populated."* Nothing fabricates. There is no default
value, no sample fixture, no "typical" percentile; a PositioningFact
RAISES if a value is supplied for an unacquired source, and the state
machine cannot leave UNKNOWN without a real observation.

WHY THE SHAPE MATTERS ANYWAY. Forced-flow reasoning is the part of the
predator model that distinguishes "price went up" from "someone HAS to
buy". Defining it now means the weekend BTC perps sleeve -- where
funding, open interest and liquidations ARE freely available in real
time -- plugs into a contract that already exists, rather than growing a
second positioning vocabulary.

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from apex.pattern_observatory import OBSERVATORY_POWER

# ---- availability vocabulary. These are FACTS about acquisition, not
# ---- quality judgements about data we hold.
AVAILABLE = "AVAILABLE"
AVAILABLE_LAGGED = "AVAILABLE_LAGGED"
AVAILABLE_VERY_LAGGED = "AVAILABLE_VERY_LAGGED"
NOT_ACQUIRED = "NOT_ACQUIRED"        # obtainable, we have not wired it
UNAVAILABLE = "UNAVAILABLE"          # paid / institutional / inaccessible
NOT_APPLICABLE = "NOT_APPLICABLE"

AVAILABILITY = (AVAILABLE, AVAILABLE_LAGGED, AVAILABLE_VERY_LAGGED,
                NOT_ACQUIRED, UNAVAILABLE, NOT_APPLICABLE)

# THE HONEST REGISTER, 2026-08-19. Each entry states publication delay so
# a future consumer can never mistake a weekly report for a live read.
SOURCE_REGISTER = {
    "CFTC_NQ": {"availability": AVAILABLE_LAGGED, "publication_delay": "3 days",
                "cadence": "weekly (Tue data, Fri release)", "cost": "free",
                "note": "leveraged-fund net positioning; acquirable"},
    "CFTC_ES": {"availability": AVAILABLE_LAGGED, "publication_delay": "3 days",
                "cadence": "weekly", "cost": "free"},
    "CFTC_RTY": {"availability": AVAILABLE_LAGGED, "publication_delay": "3 days",
                 "cadence": "weekly", "cost": "free"},
    "CFTC_VIX": {"availability": AVAILABLE_LAGGED, "publication_delay": "3 days",
                 "cadence": "weekly", "cost": "free"},
    "CFTC_RATES": {"availability": AVAILABLE_LAGGED, "publication_delay": "3 days",
                   "cadence": "weekly", "cost": "free"},
    "FINRA_SHORT_VOLUME": {"availability": AVAILABLE,
                           "publication_delay": "same day (~18:00 ET)",
                           "cadence": "daily", "cost": "free",
                           "note": "OFF-EXCHANGE ONLY. Short VOLUME, which is "
                                   "NOT short interest -- FINRA says so on "
                                   "the dataset page. Wired 2026-08-19."},
    "SHORT_INTEREST": {"availability": UNAVAILABLE,
                       "publication_delay": "~2 weeks", "cadence": "bi-monthly",
                       "cost": "paid feed", "note": "exchange-published, "
                       "vendor-gated in practice"},
    "BORROW_UTILIZATION": {"availability": UNAVAILABLE,
                           "publication_delay": "intraday",
                           "cadence": "continuous", "cost": "paid"},
    "BORROW_COST": {"availability": UNAVAILABLE, "publication_delay": "intraday",
                    "cadence": "continuous", "cost": "paid"},
    "ETF_FLOWS": {"availability": NOT_ACQUIRED, "publication_delay": "1 day",
                  "cadence": "daily", "cost": "free-ish"},
    "FUND_FLOWS": {"availability": UNAVAILABLE, "publication_delay": "weekly",
                   "cadence": "weekly", "cost": "paid"},
    "FORM_13F": {"availability": NOT_ACQUIRED, "publication_delay": "45 days",
                 "cadence": "quarterly", "cost": "free (EDGAR)",
                 "note": "so lagged it is context, never a current fact"},
    "INSIDER_FORM4": {"availability": NOT_ACQUIRED,
                      "publication_delay": "2 business days",
                      "cadence": "event", "cost": "free (EDGAR)",
                      "note": "EDGAR capture already runs 24/7 for 8-K; "
                              "Form 4 is the same pipe, unwired"},
    "BUYBACKS": {"availability": NOT_ACQUIRED, "publication_delay": "quarterly",
                 "cadence": "quarterly", "cost": "free (EDGAR)"},
    "ISSUANCE": {"availability": NOT_ACQUIRED, "publication_delay": "event",
                 "cadence": "event", "cost": "free (EDGAR)"},
    "PRIME_BROKER": {"availability": UNAVAILABLE, "publication_delay": "n/a",
                     "cadence": "n/a", "cost": "institutional only",
                     "note": "not obtainable at this scale; do not model it"},
    "CTA_POSITIONING": {"availability": UNAVAILABLE,
                        "publication_delay": "weekly-ish", "cadence": "weekly",
                        "cost": "paid research"},
    # --- crypto sleeve: these ARE free and live, and are the reason this
    # --- contract is worth defining before the sleeve exists
    "PERP_FUNDING": {"availability": NOT_ACQUIRED, "publication_delay": "live",
                     "cadence": "8h settle, continuous quote", "cost": "free",
                     "note": "BTC perps sleeve not built"},
    "PERP_OPEN_INTEREST": {"availability": NOT_ACQUIRED,
                           "publication_delay": "live", "cadence": "continuous",
                           "cost": "free", "note": "BTC perps sleeve not built"},
    "PERP_LIQUIDATIONS": {"availability": NOT_ACQUIRED,
                          "publication_delay": "live", "cadence": "event",
                          "cost": "free", "note": "BTC perps sleeve not built"},
}


class PositioningError(RuntimeError):
    pass


@dataclass(frozen=True)
class PositioningFact:
    """A MEASURED positioning number. Never constructed from a guess.

    The three-part split is deliberate: the FACT is what the filing said,
    the INTERPRETATION is what a human would read into it, and the
    ALTERNATIVE_MOTIVE is the reason that reading might be wrong. Storing
    only the first would be sterile; storing only the second is how a
    system starts calling positioning data 'smart money'.
    """

    source: str
    subject: str
    metric: str
    value: float | None
    as_of_market_date: str | None
    known_from: str | None
    publication_delay: str | None
    availability: str
    freshness_days: float | None = None
    percentile_52w: float | None = None
    percentile_multiyear: float | None = None
    z_score: float | None = None
    change_1w: float | None = None
    change_4w: float | None = None
    interpretation: str | None = None
    alternative_motive: str | None = None
    confidence: str = "UNKNOWN"

    def __post_init__(self):
        if self.availability not in AVAILABILITY:
            raise PositioningError(f"bad availability {self.availability!r}")
        if self.value is not None and self.availability in (
                NOT_ACQUIRED, UNAVAILABLE, NOT_APPLICABLE):
            raise PositioningError(
                f"{self.source}: a value was supplied for an "
                f"{self.availability} source -- this is exactly the "
                "fabrication the module forbids")

    def as_dict(self) -> dict:
        return {"kind": "positioning_fact", **self.__dict__,
                "is_smart_money_claim": False,
                "decision_power": OBSERVATORY_POWER}


@dataclass(frozen=True)
class InstitutionalPositioningState:
    as_of: str
    known_from: str
    status: str                     # PARTIAL | UNAVAILABLE | AVAILABLE
    facts: tuple
    source_availability: dict
    acquirable_but_unwired: tuple
    genuinely_unavailable: tuple

    def as_dict(self) -> dict:
        return {"kind": "institutional_positioning_state",
                "as_of": self.as_of, "known_from": self.known_from,
                "status": self.status,
                "facts": [f.as_dict() for f in self.facts],
                "source_availability": dict(self.source_availability),
                "acquirable_but_unwired": list(self.acquirable_but_unwired),
                "genuinely_unavailable": list(self.genuinely_unavailable),
                "decision_power": OBSERVATORY_POWER}


def observe(*, as_of, known_from, facts: tuple = ()) -> InstitutionalPositioningState:
    """Report positioning honestly. With no facts supplied the state is
    UNAVAILABLE -- which is the correct answer today."""
    avail = {k: v["availability"] for k, v in SOURCE_REGISTER.items()}
    acquirable = tuple(sorted(k for k, v in avail.items() if v == NOT_ACQUIRED))
    never = tuple(sorted(k for k, v in avail.items() if v == UNAVAILABLE))
    status = "UNAVAILABLE" if not facts else (
        "AVAILABLE" if len(facts) >= len(SOURCE_REGISTER) else "PARTIAL")
    return InstitutionalPositioningState(
        as_of=str(as_of), known_from=str(known_from), status=status,
        facts=tuple(facts), source_availability=avail,
        acquirable_but_unwired=acquirable, genuinely_unavailable=never)


# ------------------------------------------------------------ crowding
CROWDING_STATES = ("EXTREME_LONG", "CROWDED_LONG", "LONG_BUILD",
                   "LONG_UNWIND", "NEUTRAL", "SHORT_BUILD", "CROWDED_SHORT",
                   "EXTREME_SHORT", "SHORT_COVERING", "UNKNOWN")


@dataclass(frozen=True)
class CrowdingState:
    subject: str
    as_of: str
    known_from: str
    state: str
    current: float | None
    change_1w: float | None
    change_4w: float | None
    percentile: float | None
    z_score: float | None
    acceleration: float | None
    basis: str
    reasoning: tuple = ()

    def as_dict(self) -> dict:
        return {"kind": "crowding_state", **self.__dict__,
                "reasoning": list(self.reasoning),
                # the two mappings a positioning system must never make
                # automatically -- crowded shorts stay crowded for months,
                # and crowded longs are often crowded because they are right
                "forbidden_inference": "CROWDED_SHORT does not imply BUY; "
                                       "CROWDED_LONG does not imply SELL",
                "decision_power": OBSERVATORY_POWER}


def crowding(subject: str, *, as_of, known_from,
             fact: PositioningFact | None = None) -> CrowdingState:
    if fact is None or fact.value is None:
        return CrowdingState(
            subject=subject, as_of=str(as_of), known_from=str(known_from),
            state="UNKNOWN", current=None, change_1w=None, change_4w=None,
            percentile=None, z_score=None, acceleration=None,
            basis="NO_POSITIONING_SOURCE_ACQUIRED",
            reasoning=("no positioning data exists for this subject",))
    p = fact.percentile_52w
    st = "NEUTRAL"
    if p is not None:
        if p >= 0.95:
            st = "EXTREME_LONG"
        elif p >= 0.80:
            st = "CROWDED_LONG"
        elif p <= 0.05:
            st = "EXTREME_SHORT"
        elif p <= 0.20:
            st = "CROWDED_SHORT"
    if fact.change_1w is not None and st == "NEUTRAL":
        st = "LONG_BUILD" if fact.change_1w > 0 else "SHORT_BUILD"
    return CrowdingState(
        subject=subject, as_of=str(as_of), known_from=str(known_from),
        state=st, current=fact.value, change_1w=fact.change_1w,
        change_4w=fact.change_4w, percentile=p, z_score=fact.z_score,
        acceleration=None, basis=fact.source,
        reasoning=(f"{fact.source} percentile {p}",) if p is not None else ())


# --------------------------------------------------------- forced flow
FORCED_FLOW_STATES = ("NONE", "EARLY", "BUILDING", "ELEVATED", "SEVERE",
                      "UNKNOWN")
FORCED_FLOW_KINDS = ("SHORT_COVERING_PRESSURE", "DEGROSSING_PRESSURE",
                     "GAMMA_PRESSURE", "LIQUIDATION_PRESSURE", "NONE")


@dataclass(frozen=True)
class ForcedFlowState:
    """WHERE CAN POSITIONING TURN INTO FORCED ACTION?

    The question the whole predator model is built around: not "will
    price go up" but "is somebody going to HAVE to buy". Today it can
    only answer UNKNOWN, because the positioning half of the conjunction
    does not exist. That is recorded as a missing INPUT, not as an
    absence of pressure -- those are different claims.
    """

    subject: str
    as_of: str
    known_from: str
    kind: str
    level: str
    components_present: tuple
    components_missing: tuple
    reasoning: tuple
    estimable: bool

    def as_dict(self) -> dict:
        return {"kind": "forced_flow_state", **self.__dict__,
                "components_present": list(self.components_present),
                "components_missing": list(self.components_missing),
                "reasoning": list(self.reasoning),
                "decision_power": OBSERVATORY_POWER}


# Each recipe names the conjunction that would constitute forced-flow
# risk. Declared in full so the missing half is explicit rather than
# implied.
RECIPES = {
    "SHORT_COVERING_PRESSURE": (
        "crowded_short", "price_refuses_down", "breadth_improving",
        "sector_leadership_improving", "curve_positive",
        "vol_not_confirming_bear"),
    "DEGROSSING_PRESSURE": (
        "crowded_long", "leadership_failure", "breadth_deteriorating",
        "vol_repricing_up", "liquidity_thinning"),
}


def assess(subject: str, *, as_of, known_from, present: dict) -> ForcedFlowState:
    """`present`: {component_name: bool|None}. None means UNOBSERVABLE and
    is tracked separately from False, which means observed-and-absent."""
    best = None
    for kind, comps in RECIPES.items():
        have = tuple(c for c in comps if present.get(c) is True)
        missing = tuple(c for c in comps if present.get(c) is None)
        if best is None or len(have) > len(best[1]):
            best = (kind, have, missing, comps)
    kind, have, missing, comps = best

    if missing:
        return ForcedFlowState(
            subject=subject, as_of=str(as_of), known_from=str(known_from),
            kind=kind, level="UNKNOWN", components_present=have,
            components_missing=missing, estimable=False,
            reasoning=(f"{len(missing)}/{len(comps)} components are "
                       f"UNOBSERVABLE, not absent: {list(missing)}",))

    frac = len(have) / len(comps)
    level = ("SEVERE" if frac >= 0.9 else "ELEVATED" if frac >= 0.7
             else "BUILDING" if frac >= 0.5 else "EARLY" if frac >= 0.3
             else "NONE")
    return ForcedFlowState(
        subject=subject, as_of=str(as_of), known_from=str(known_from),
        kind=(kind if level != "NONE" else "NONE"), level=level,
        components_present=have, components_missing=(), estimable=True,
        reasoning=(f"{len(have)}/{len(comps)} components observed present",))
