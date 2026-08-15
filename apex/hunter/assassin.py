"""THE ASSASSIN — a formal pipeline stage, not a single agent.

Mandate (Profit Machine blueprint): given one of the best opportunities
the rest of APEX has found, prove that we should not trade it. The
Assassin is a LOGICAL STAGE composed of several kill mechanisms:

  QUALITATIVE   the Swarm's Adversarial Trader (MATERIAL_OBJECTION)
  STATISTICAL   forecast-source direction disagreement; weak analogue
                support (a wound, not a kill: evidence-quality caution)
  DATA          hard data-quality flags (executed as REFUSED in capital)
  ECONOMIC      cost/capacity/edge (executed in capital)
  EXISTENTIAL   risk/portfolio limits (executed in capital)

Anything can attack the trade. Nothing except the complete pipeline can
authorize it. Every attempt is RECORDED per candidate — landed or not —
because rejection economics is the Profit Machine thesis: each stage
must make the surviving population harder and better, and that is only
measurable if the attempts are in the ledger.

EPOCH 1 SEMANTICS (frozen; zero behavior change from v1.5.4): in this
version the Assassin WOUNDS — a landed attempt feeds the monotone
caution law (final state capped at WATCH, size scaled down) — while
capital executes the actual kills (NO_TRADE/REFUSED) economically and
existentially. Granting qualitative attempts lethal force (hard
NO_TRADE from a Swarm objection) would be a decision-logic change and
is deferred to a versioned ruling once forward evidence shows whether
the Assassin's objections actually identify worse outcomes (the
ablation is its employment contract too).

Registered-but-dormant mechanisms (await their data; absence visible,
never faked): adverse world branches (calibrated sim), catalyst
ambiguity / event risk (timestamped events), entry asymmetry vs
MAE/MFE (forward outcome history), liquidity/spread (measured quotes),
portfolio duplication / correlation concentration (multi-position
portfolio state), unstable regime (intraday classifier).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

ASSASSIN_VERSION = "hunter_assassin_v1"

DORMANT_MECHANISMS = (
    "ADVERSE_WORLD_BRANCHES", "CATALYST_AMBIGUITY", "EVENT_RISK",
    "ENTRY_ASYMMETRY_VS_MAE_MFE", "LIQUIDITY_SPREAD",
    "PORTFOLIO_DUPLICATION", "CORRELATION_CONCENTRATION",
    "UNSTABLE_REGIME_INTRADAY")


@dataclass(frozen=True)
class AssassinReview:
    candidate_id: str
    symbol: str
    attempts: tuple                  # every attack tried, landed or not
    landed: tuple                    # the attacks that connected
    verdict: str                     # SURVIVED_CLEAN | SURVIVED_WOUNDED
    # the wounds, expressed as the caution inputs capital consumes —
    # identical semantics to v1.5.4, now attributed to a named stage
    disagreement_level: str | None
    analog_support_low: bool
    downstream_note: str
    dormant_mechanisms: tuple = DORMANT_MECHANISMS
    assassin_version: str = field(default=ASSASSIN_VERSION)

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "assassin_review"
        return d


def review(candidate: dict, bundle) -> AssassinReview:
    """Aggregate every active kill mechanism against one candidate.
    `bundle` is the ForecastBundle (typed absences included)."""
    attempts: list = []
    landed: list = []

    swarm = bundle.swarm_view or {}
    verdict = (swarm.get("provenance") or {}).get("adversary_verdict")
    attempts.append({"mechanism": "SWARM_ADVERSARIAL_TRADER",
                     "kind": "QUALITATIVE",
                     "available": swarm.get("status") == "OK",
                     "landed": verdict == "MATERIAL_OBJECTION",
                     "detail": verdict or swarm.get("status")})
    if verdict == "MATERIAL_OBJECTION":
        landed.append("SWARM_ADVERSARIAL_TRADER")

    dis = bundle.disagreement or {}
    attempts.append({"mechanism": "FORECAST_SOURCE_DISAGREEMENT",
                     "kind": "STATISTICAL",
                     "available": dis.get("level") not in (None,
                                                          "UNMEASURABLE"),
                     "landed": dis.get("level") == "HIGH",
                     "detail": dis.get("level")})
    if dis.get("level") == "HIGH":
        landed.append("FORECAST_SOURCE_DISAGREEMENT")

    analog = bundle.analog_view or {}
    support_low = analog.get("status") == "ANALOG_SUPPORT_LOW"
    attempts.append({"mechanism": "ANALOG_SUPPORT",
                     "kind": "STATISTICAL",
                     "available": analog.get("status")
                     not in (None, "NOT_AVAILABLE"),
                     "landed": support_low,
                     "detail": analog.get("status")})
    if support_low:
        landed.append("ANALOG_SUPPORT")

    quality = tuple((candidate.get("chart_state") or {})
                    .get("data_quality", ()))
    attempts.append({"mechanism": "DATA_QUALITY",
                     "kind": "DATA", "available": True,
                     "landed": bool(quality),
                     "detail": list(quality) or "clean"})
    if quality:
        landed.append("DATA_QUALITY")

    return AssassinReview(
        candidate_id=candidate.get("decision_id", "?"),
        symbol=candidate.get("symbol", "?"),
        attempts=tuple(attempts), landed=tuple(landed),
        verdict="SURVIVED_WOUNDED" if landed else "SURVIVED_CLEAN",
        disagreement_level=dis.get("level"),
        analog_support_low=support_low,
        downstream_note=("wounds feed the monotone caution law; capital "
                         "executes economic/existential kills; lethal "
                         "qualitative force is a deferred versioned "
                         "ruling awaiting forward evidence"))
