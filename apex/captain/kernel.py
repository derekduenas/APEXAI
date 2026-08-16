"""THE CAPTAIN KERNEL — deterministic authority over PROCESS, never money.

THE CONSTITUTION (enforced here and in tests):

    Captain commands the desk.  Capital commands the money.

The Captain decides what the machine should DO NEXT — what intelligence
is worth buying, what is unresolved, whether to wait or proceed, when to
re-evaluate. It never authorizes capital, never sizes, never moves a
stop, never overrides a veto. Risk can veto the Captain; the Assassin
can wound its thesis; Capital can refuse its best opportunity; the trade
manager owns the position. An LLM (the CIO layer) advises the Captain
and cannot alter a single field the kernel computes.

EPOCH 1 STATUS: OBSERVATIONAL. Captain records `captain_state` next to
the decision; it changes no Epoch 1 outcome. Wiring its directives into
routing is a versioned ruling for a later epoch — the freeze holds.

Anti-paralysis is a first-class duty: when evidence, execution, and risk
genuinely align and the gates are met, the kernel says PROCEED. A desk
that can only ever say "wait" is not disciplined, it is broken.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from apex.captain.conviction import ConvictionState, from_pipeline

CAPTAIN_VERSION = "apex_captain_kernel_v1"

NEXT_ACTIONS = ("STAND_DOWN", "WATCH_FOR_RE_ENTRY", "AWAIT_EVIDENCE",
                "PROCEED_TO_CAPITAL", "DEFER_TO_CAPITAL_VERDICT")
SPENDS = ("NONE", "FAST_ONLY", "STANDARD", "DEEP_ELIGIBLE")


@dataclass(frozen=True)
class CaptainState:
    decision_id: str
    symbol: str
    t_utc: str
    opportunity_quality: str          # from conviction, not a score
    directional_thesis: str
    entry_thesis: str
    primary_unresolved: str
    alpha_persistence: str
    recommended_intelligence_spend: str
    next_action: str
    do_not: tuple
    re_evaluate_when: tuple
    conviction: dict
    capital_is_sovereign: bool = True
    decision_power: str = "NONE_OBSERVATIONAL_EPOCH1"
    version: str = field(default=CAPTAIN_VERSION)

    def __post_init__(self):
        if self.next_action not in NEXT_ACTIONS:
            raise ValueError(f"undeclared next_action {self.next_action!r}")
        if self.recommended_intelligence_spend not in SPENDS:
            raise ValueError("undeclared intelligence spend")
        if not self.capital_is_sovereign:
            raise ValueError("CONSTITUTIONAL: Capital is always sovereign "
                             "over money; the Captain cannot revoke it")

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "captain_state"
        return d


def _quality(c: ConvictionState) -> str:
    """Tiers must be REACHABLE or the ladder is theatre. In Epoch 1
    market_fit and ml_evidence cap at MODERATE by construction (no
    calibrated model, crude regime proxy), so HIGH is reserved for the
    post-Phase-3 world where those can genuinely be STRONG — and
    MODERATE is the honest ceiling today. The Captain's PROCEED path
    therefore keys on MODERATE + strong entry, not on an unreachable
    HIGH (an anti-paralysis duty implemented as dead code is a bug)."""
    if c.assassin == "WOUNDED" or c.disagreement == "HIGH":
        return "COMPROMISED"
    if len(c.unknowns) >= 6:
        return "UNASSESSABLE_INSUFFICIENT_EVIDENCE"
    strong = sum(1 for d in ("mechanism", "market_fit", "analog_support",
                             "ml_evidence", "entry_quality")
                 if getattr(c, d) == "STRONG")
    supportive = sum(1 for d in ("mechanism", "market_fit",
                                 "analog_support", "ml_evidence",
                                 "entry_quality")
                     if getattr(c, d) in ("STRONG", "MODERATE"))
    if strong >= 4:
        return "HIGH"
    if strong >= 2 and supportive >= 4:
        return "MODERATE"
    return "LOW"


def assess(candidate: dict, bundle: dict | None, assassin: dict | None,
           capital: dict | None, persistence: dict | None = None,
           simulation: dict | None = None) -> CaptainState:
    """Synthesize the desk's records into a PROCESS directive.

    Deterministic: identical inputs give an identical directive. Reads
    only what the pipeline actually recorded; absent inputs stay unknown
    and make the Captain MORE patient, never more aggressive."""
    c = from_pipeline(candidate, bundle, assassin, capital, simulation)
    cap = capital or {}
    final = cap.get("final_state")
    reasons = set(cap.get("reason_codes") or ())
    quality = _quality(c)

    # the operator's core distinction: direction vs entry vs evidence
    directional = ("STRONG" if c.mechanism == "STRONG"
                   and c.assassin != "WOUNDED" else
                   "COMPROMISED" if c.assassin == "WOUNDED" else "UNKNOWN")
    entry = c.entry_quality

    unresolved = "NONE"
    if c.assassin == "WOUNDED":
        unresolved = "ASSASSIN_OBJECTION"
    elif c.disagreement == "HIGH":
        unresolved = "SOURCE_DISAGREEMENT"
    elif "NO_CALIBRATED_FORECAST" in reasons:
        unresolved = "NO_CALIBRATED_FORECAST"
    elif c.analog_support == "WEAK":
        unresolved = "THIN_ANALOG_SUPPORT"
    elif "COST_UNKNOWN" in reasons:
        unresolved = "UNMEASURED_EXECUTION_COST"

    # intelligence spend follows persistence (routing can only REDUCE it)
    p = (persistence or {}).get("status")
    spend = "STANDARD"
    if p == "PERSISTENCE_MEASURED":
        hl = (persistence or {}).get("edge_persistence_horizon_minutes", 90)
        spend = ("FAST_ONLY" if hl < 30
                 else "STANDARD" if hl < 90 else "DEEP_ELIGIBLE")
    if quality in ("COMPROMISED", "UNASSESSABLE_INSUFFICIENT_EVIDENCE"):
        spend = "FAST_ONLY"           # never buy deep thought for a dud

    do_not, revisit = [], []
    if final in ("REFUSED", "NO_TRADE"):
        action = "STAND_DOWN"
        do_not = ["re-litigate a Capital refusal", "increase risk"]
        revisit = ["a NEW candidate forms (this one is closed)"]
    elif c.assassin == "WOUNDED" or entry == "MODERATE":
        action = "WATCH_FOR_RE_ENTRY"
        do_not = ["chase the current price", "run deep research on a "
                  "wounded thesis", "increase risk"]
        revisit = ["entry geometry improves (structure/VWAP)",
                   "the objection resolves", "the thesis deteriorates"]
    elif unresolved in ("NO_CALIBRATED_FORECAST", "THIN_ANALOG_SUPPORT",
                        "SOURCE_DISAGREEMENT"):
        action = "AWAIT_EVIDENCE"
        do_not = ["treat an uncalibrated view as a probability",
                  "size on a story"]
        revisit = ["the evidence gate clears (calibration/support)"]
    elif quality in ("HIGH", "MODERATE") and entry == "STRONG" \
            and c.assassin == "CLEAN":
        # ANTI-PARALYSIS: when it genuinely aligns, say so
        action = "PROCEED_TO_CAPITAL"
        do_not = ["exceed Capital's verdict", "pre-commit size"]
        revisit = ["Capital rules", "world state changes materially"]
    else:
        action = "DEFER_TO_CAPITAL_VERDICT"
        revisit = ["Capital's reasoning is recorded"]

    return CaptainState(
        decision_id=candidate.get("decision_id", "?"),
        symbol=candidate.get("symbol") or candidate.get("product", "?"),
        t_utc=candidate.get("t_utc", "?"),
        opportunity_quality=quality,
        directional_thesis=directional,
        entry_thesis=entry,
        primary_unresolved=unresolved,
        alpha_persistence=(persistence or {}).get("status",
                                                  "NOT_YET_ESTIMABLE"),
        recommended_intelligence_spend=spend,
        next_action=action, do_not=tuple(do_not),
        re_evaluate_when=tuple(revisit), conviction=c.as_record())
