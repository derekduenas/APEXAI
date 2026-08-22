"""CONTRADICTION ENGINE -- every pattern must hunt its own opposite.

A developing pattern that has only been asked "what supports me?" is a
narrative. This engine asks the other question on every cycle and keeps
BOTH answers. Disagreement is never collapsed into a net score, because
a net score is how "three supports, two contradictions" silently becomes
"+1 confidence".

decision_power: NONE_PATTERN_OBSERVATORY.
"""
from __future__ import annotations

from dataclasses import dataclass

from apex.pattern_observatory import OBSERVATORY_POWER

# For each family, what would have to be true for it to be WRONG.
# Declared alongside the family, never derived from outcomes.
CONTRADICTIONS = {
    "P001": (("breadth_deteriorating", "breadth is falling, not improving"),
             ("curve_negative", "curve confirms the bearish case"),
             ("vol_repricing", "vol is confirming downside, not fading it")),
    "P002": (("breadth_improving", "participation is broadening, not failing"),
             ("curve_positive", "curve does not confirm leadership failure")),
    "P003": (("breadth_improving", "participation is improving"),
             ("sector_dispersion", "dispersion is falling, not diverging")),
    "P004": (("breadth_improving", "breadth improving contradicts rotation"),
             ("curve_positive", "index curve is positive")),
    "P005": (("propagation_lead_lag", "propagation says the index leads")),
    "P006": (("options_dislocation", "the surface move is a liquidity "
                                     "artefact, not repricing"),),
    "P007": (("obs_rvol_elevated", "participation explains the structure"),),
    "P008": (("cross_asset_risk_off", "cross-asset does not confirm"),),
    "P009": (("breadth_deteriorating", "breadth falling contradicts covering"),
             ("curve_negative", "price is not refusing to fall")),
    "P010": (("breadth_improving", "breadth improving contradicts degrossing"),
             ("curve_positive", "leaders are still leading")),
    "P011": (("vol_repricing", "vol is expanding, not compressing"),),
    "P012": (("expectation_violation", "the market responded as expected"),),
}

# Universal contradictions -- these apply to EVERY family because they
# attack the observation itself rather than the thesis.
UNIVERSAL = (
    ("input_quality_degraded", "the inputs the pattern rests on are degraded"),
    ("move_already_occurred", "the move this pattern anticipates has "
                              "already happened"),
    ("single_mechanism", "every component derives from one mechanism"),
)


@dataclass(frozen=True)
class ContradictionReport:
    pattern_id: str
    family_id: str
    supporting: tuple
    contradicting: tuple
    universal_hits: tuple
    net_not_computed: bool
    burden: str
    as_of: str

    def as_dict(self) -> dict:
        return {"kind": "contradiction_report", **self.__dict__,
                "supporting": list(self.supporting),
                "contradicting": list(self.contradicting),
                "universal_hits": list(self.universal_hits),
                "law": "supporting and contradicting evidence are retained "
                       "SEPARATELY; no net score is computed",
                "decision_power": OBSERVATORY_POWER}


def search(*, pattern_id: str, family_id: str, active_components: set,
           independence: dict, quality_verdict: dict, as_of,
           move_already_occurred: bool | None = None) -> ContradictionReport:
    fam_c = CONTRADICTIONS.get(family_id, ())
    if fam_c and isinstance(fam_c[0], str):     # tolerate a 1-tuple typo shape
        fam_c = (fam_c,)

    contradicting = tuple(
        {"component": c, "why": why} for c, why in fam_c
        if c in active_components)

    universal = []
    if quality_verdict.get("combined_quality") in ("DEGRADED", "INVALID",
                                                   "UNKNOWN"):
        universal.append({"component": "input_quality_degraded",
                          "why": f"combined input quality is "
                                 f"{quality_verdict.get('combined_quality')}"})
    if independence.get("independent_mechanism_count", 0) <= 1:
        universal.append({"component": "single_mechanism",
                          "why": "all components derive from one mechanism "
                                 f"group: {list(independence.get('groups', {}))}"})
    if move_already_occurred:
        universal.append({"component": "move_already_occurred",
                          "why": "the anticipated move is already in price"})

    n = len(contradicting) + len(universal)
    burden = ("NONE" if n == 0 else "LIGHT" if n == 1
              else "MATERIAL" if n == 2 else "HEAVY")
    return ContradictionReport(
        pattern_id=pattern_id, family_id=family_id,
        supporting=tuple(sorted(active_components)),
        contradicting=contradicting, universal_hits=tuple(universal),
        net_not_computed=True, burden=burden, as_of=str(as_of))
