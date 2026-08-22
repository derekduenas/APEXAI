"""THE CANONICAL PREDATOR OPPORTUNITY.

One contract all three sleeves speak, so an equity pullback, an options
vertical and a BTC cascade can compete for the same capital on
comparable terms. The Arena compares these; Capital decides among them;
neither may invent one.

LAWS:
  * UNKNOWN is a value. UNKNOWN != 0, and no consumer may coerce it.
  * ATTACK_READY is the specialist's opinion that Capital should look.
    It is NOT execution authority and never has been.
  * attack_class is a QUALITATIVE economic classification. It carries
    no percentage. Capital derives simulated sizing; the Predator
    never sizes itself.
  * Causality: first_known_from is when the opportunity became
    knowable, not when it was written.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# canonical lifecycle -- ordered from coldest to hottest
STATES = ("IGNORE", "WATCH", "STALK", "DEVELOP", "WAIT_FOR_CONFIRMATION",
          "SERIOUS", "WAIT_FOR_ENTRY", "ATTACK_READY", "DEGRADE",
          "INVALIDATE", "EXPIRED")

ATTACK_CLASSES = ("NO_TRADE", "NORMAL_ATTACK", "STRONG_ATTACK",
                  "RARE_ASYMMETRIC_ATTACK")

AUTHORITY_ELIGIBILITY = ("OBSERVE_ONLY", "PAPER_EXPLORATORY_ELIGIBLE",
                         "PAPER_AUTHORIZED_ELIGIBLE", "LIVE_INELIGIBLE")


class OpportunityRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class PredatorOpportunity:
    opportunity_id: str
    sleeve: str
    subject: str
    mechanism: str
    first_known_from: str
    state: str
    direction: str

    # --- evidence
    domain_evidence: tuple = ()
    independent_evidence_groups: tuple = ()
    contradictions: tuple = ()

    # --- participants
    participant_state: str = "UNKNOWN"
    forced_action_thesis: str = "UNKNOWN"

    # --- the two separate qualities (never collapsed)
    thesis_quality: str = "UNKNOWN"
    entry_quality: str = "UNKNOWN"
    entry_zone: tuple | None = None
    invalidation: float | None = None
    chase_risk: str = "UNKNOWN"

    # --- forecast
    forecast_status: str = "UNKNOWN"
    forecast_pedigree: dict = field(default_factory=dict)
    expected_return: float | str = "NOT_ESTIMABLE"
    expected_mae: float | str = "NOT_ESTIMABLE"
    expected_mfe: float | str = "NOT_ESTIMABLE"
    tail_asymmetry: float | str = "NOT_ESTIMABLE"
    uncertainty: str = "UNKNOWN"

    # --- memory
    historical_support: str = "UNKNOWN"
    n_raw: int | None = None
    n_effective_lower_bound: int | None = None
    regimes: tuple = ()

    # --- monetization
    execution_feasibility: str = "UNKNOWN"
    attack_class: str = "NO_TRADE"
    data_quality: str = "UNKNOWN"
    authority_eligibility: str = "OBSERVE_ONLY"
    decision_power: str = "NONE_PREDATOR"

    def __post_init__(self):
        if self.state not in STATES:
            raise OpportunityRefused(f"unknown state {self.state!r}")
        if self.attack_class not in ATTACK_CLASSES:
            raise OpportunityRefused("unknown attack_class")
        if self.authority_eligibility not in AUTHORITY_ELIGIBILITY:
            raise OpportunityRefused("unknown authority_eligibility")
        if self.direction not in ("LONG", "SHORT", "UNKNOWN"):
            raise OpportunityRefused("bad direction")
        # ATTACK_READY demands a bounded loss -- an attack with no
        # invalidation is a wish, not a trade.
        if self.state == "ATTACK_READY" and self.invalidation is None:
            raise OpportunityRefused(
                "ATTACK_READY without invalidation -- refused")
        # an attack class above NO_TRADE requires a known entry
        if (self.attack_class != "NO_TRADE"
                and self.entry_quality in ("UNKNOWN", "POOR")):
            raise OpportunityRefused(
                f"attack_class {self.attack_class} with entry_quality "
                f"{self.entry_quality} -- refused")

    @property
    def n_effective_note(self) -> str:
        return ("n_raw never implies independence; "
                "n_effective_lower_bound is the honest floor")

    def as_record(self) -> dict:
        return {"kind": "predator_opportunity", **asdict(self)}
