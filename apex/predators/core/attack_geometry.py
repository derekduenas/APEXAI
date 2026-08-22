"""ATTACK GEOMETRY -- the faculty that turns a thesis into a trade.

THE QUESTION THIS ANSWERS, which APEX could not answer before:

    "I see something potentially important.
     Is THIS the moment and location where I should risk capital?"

The forensic that motivated it (2026-08-22, 4,760 real Captain reviews):
entry_quality was UNKNOWN in 4,760/4,760 -- 100%. Nothing downstream
could ever reach SERIOUS because nothing upstream ever spoke about
entry.

CONSTITUTIONAL SEPARATION:

    THESIS_QUALITY   is the subject worth caring about?   (upstream)
    ENTRY_QUALITY    is HERE and NOW the place to strike?  (this module)

These are computed by different organs and may disagree. A brilliant
thesis with terrible geometry is GOOD_THESIS_BAD_ENTRY -- a real,
nameable, non-attackable state.

LAWS:
  * UNKNOWN and NOT_ESTIMABLE are first-class. UNKNOWN != 0, and
    UNKNOWN never becomes neutral or "fine".
  * Dimensionless normalization: geometry is expressed in R-multiples
    and ATR units, so a $3 stock and a $700 stock are read identically.
  * No future bars. Every input carries known_from; geometry computed
    at time T may only see data whose known_from <= T.
  * Not outcome-tuned. v1 rules come from market-structure definitions
    predeclared BEFORE any profitability measurement. Historical
    outcomes may later JUDGE the geometry; they may not author it.
  * Missing liquidity can never yield an excellent entry.
  * Trend strength alone can never rescue a chase.

decision_power: NONE -- geometry describes; it never authorizes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

GEOMETRY_QUALITY = ("STRONG", "GOOD", "ACCEPTABLE", "POOR", "UNKNOWN")
ENTRY_QUALITY = GEOMETRY_QUALITY          # same vocabulary as Captain
CHASE_RISK = ("LOW", "MODERATE", "HIGH", "EXTREME", "UNKNOWN")
NOT_ESTIMABLE = "NOT_ESTIMABLE"

# entry tiers Captain accepts for SERIOUS (mirrored, asserted in tests)
ENTRY_ATTACKABLE = ("STRONG", "GOOD")


class GeometryRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class AttackGeometry:
    """One sleeve's answer about ONE location at ONE time."""
    sleeve: str
    subject: str
    direction: str                     # LONG | SHORT
    entry_quality: str
    geometry_quality: str
    entry_zone: tuple | None           # (low, high) in price units
    invalidation: float | None
    invalidation_distance_atr: float | None
    chase_risk: str
    local_volatility_atr: float | None
    liquidity_quality: str
    expected_mae_r: float | str | None
    expected_mfe_r: float | str | None
    time_to_move: str
    reward_risk_available: float | str | None
    data_quality: str
    known_from: str
    pedigree: dict = field(default_factory=dict)
    reasoning: tuple = ()
    decision_power: str = "NONE"

    def __post_init__(self):
        if self.entry_quality not in ENTRY_QUALITY:
            raise GeometryRefused(f"bad entry_quality {self.entry_quality!r}")
        if self.geometry_quality not in GEOMETRY_QUALITY:
            raise GeometryRefused("bad geometry_quality")
        if self.chase_risk not in CHASE_RISK:
            raise GeometryRefused("bad chase_risk")
        if self.direction not in ("LONG", "SHORT"):
            raise GeometryRefused("direction must be LONG or SHORT")
        # THE LIQUIDITY LAW: unknown liquidity cannot yield an
        # excellent entry -- an entry you cannot get filled at is not
        # an excellent entry, whatever the chart says.
        if (self.liquidity_quality in ("UNKNOWN", NOT_ESTIMABLE)
                and self.entry_quality == "STRONG"):
            raise GeometryRefused(
                "STRONG entry requires known liquidity -- refused")
        # THE CHASE LAW: a HIGH/EXTREME chase can never be attackable,
        # no matter how strong the trend behind it.
        if (self.chase_risk in ("HIGH", "EXTREME")
                and self.entry_quality in ENTRY_ATTACKABLE):
            raise GeometryRefused(
                "chase risk forbids an attackable entry -- refused")

    @property
    def attackable(self) -> bool:
        return self.entry_quality in ENTRY_ATTACKABLE

    def as_record(self) -> dict:
        return {"kind": "attack_geometry", **asdict(self)}


def unknown_geometry(sleeve: str, subject: str, direction: str,
                     known_from: str, reason: str) -> AttackGeometry:
    """The honest answer when geometry cannot be computed. This is what
    a starved sleeve must emit -- never a neutral or default value."""
    return AttackGeometry(
        sleeve=sleeve, subject=subject, direction=direction,
        entry_quality="UNKNOWN", geometry_quality="UNKNOWN",
        entry_zone=None, invalidation=None,
        invalidation_distance_atr=None, chase_risk="UNKNOWN",
        local_volatility_atr=None, liquidity_quality="UNKNOWN",
        expected_mae_r=NOT_ESTIMABLE, expected_mfe_r=NOT_ESTIMABLE,
        time_to_move=NOT_ESTIMABLE, reward_risk_available=NOT_ESTIMABLE,
        data_quality="INSUFFICIENT", known_from=known_from,
        pedigree={"reason": reason},
        reasoning=(f"geometry not computable: {reason}",))


class AttackGeometryEngine:
    """Interface every sleeve implements. Sleeve-specific primitives
    live in the subclass; the contract lives here."""

    sleeve: str = "UNSET"

    def compute(self, **kwargs) -> AttackGeometry:  # pragma: no cover
        raise NotImplementedError(
            f"{type(self).__name__} must implement compute()")
