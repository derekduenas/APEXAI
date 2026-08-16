"""APEX CONVICTION STATE — structured, never a magic score.

A single 0-100 number would launder twelve different kinds of ignorance
into one confident-looking digit. The Conviction State keeps the
dimensions SEPARATE and typed, so the Captain can say the thing an
elite trader actually says: "direction good, entry bad, wait."

Each dimension is STRONG / MODERATE / WEAK / UNKNOWN. UNKNOWN is a real
answer and never silently becomes MODERATE.

The rare-opportunity distinction (the operating lesson worth borrowing
from famous dislocation traders — not their unreproducible method):
ORDINARY_OPPORTUNITY vs EXCEPTIONAL_ASYMMETRY. Exceptional requires
STRONG mechanism AND asymmetric scenario shape AND a clean Assassin AND
strong entry quality AND acceptable tails AND low disagreement AND real
evidence (calibration not UNKNOWN). Anything less is ordinary, however
exciting the story sounds. In Epoch 1 the exceptional class is
structurally unreachable (calibration is UNKNOWN by law) — that is
correct: APEX cannot yet know it is looking at a rare dislocation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CONVICTION_VERSION = "apex_conviction_v1"
LEVELS = ("STRONG", "MODERATE", "WEAK", "UNKNOWN")
DIMENSIONS = ("mechanism", "market_fit", "analog_support", "ml_evidence",
              "calibration", "scenario_shape", "assassin", "entry_quality",
              "execution", "tail_risk", "portfolio_fit", "disagreement")


@dataclass(frozen=True)
class ConvictionState:
    mechanism: str = "UNKNOWN"
    market_fit: str = "UNKNOWN"
    analog_support: str = "UNKNOWN"
    ml_evidence: str = "UNKNOWN"
    calibration: str = "UNKNOWN"
    scenario_shape: str = "UNKNOWN"       # ASYMMETRIC when tails favor us
    assassin: str = "UNKNOWN"             # CLEAN / WOUNDED
    entry_quality: str = "UNKNOWN"
    execution: str = "UNKNOWN"
    tail_risk: str = "UNKNOWN"
    portfolio_fit: str = "UNKNOWN"
    disagreement: str = "UNKNOWN"         # LOW is good here
    version: str = field(default=CONVICTION_VERSION)

    def __post_init__(self):
        for d in DIMENSIONS:
            v = getattr(self, d)
            if v not in LEVELS + ("CLEAN", "WOUNDED", "ASYMMETRIC",
                                  "SYMMETRIC", "LOW", "HIGH", "ACCEPTABLE"):
                raise ValueError(f"conviction {d}={v!r} is not a declared "
                                 f"level")

    @property
    def unknowns(self) -> tuple:
        return tuple(d for d in DIMENSIONS if getattr(self, d) == "UNKNOWN")

    def classify(self) -> dict:
        """ORDINARY vs EXCEPTIONAL — evidence-gated, story-proof."""
        required = {
            "mechanism": ("STRONG",),
            "scenario_shape": ("ASYMMETRIC",),
            "assassin": ("CLEAN",),
            "entry_quality": ("STRONG",),
            "tail_risk": ("ACCEPTABLE", "STRONG"),
            "disagreement": ("LOW",),
        }
        missing = [f"{k}={getattr(self, k)}" for k, ok in required.items()
                   if getattr(self, k) not in ok]
        if self.calibration == "UNKNOWN":
            missing.append("calibration=UNKNOWN (cannot know a rare "
                           "dislocation without calibrated evidence)")
        return {"class": "ORDINARY_OPPORTUNITY" if missing
                else "EXCEPTIONAL_ASYMMETRY",
                "unmet": missing,
                "unknown_dimensions": list(self.unknowns)}

    def as_record(self) -> dict:
        d = asdict(self)
        d["classification"] = self.classify()
        return d


def from_pipeline(candidate: dict, bundle: dict | None,
                  assassin: dict | None, capital: dict | None,
                  simulation: dict | None = None) -> ConvictionState:
    """Read the desk's ACTUAL records into structured dimensions. Absent
    or non-authoritative inputs stay UNKNOWN — never upgraded by
    optimism."""
    b = bundle or {}
    analog = (b.get("analog_view") or {})
    ml = (b.get("ml_view") or {})
    dis = (b.get("disagreement") or {})
    cap = capital or {}
    gates = cap.get("gates") or {}
    reasons = set(cap.get("reason_codes") or ())

    analog_map = {"OK": "STRONG", "ANALOG_SUPPORT_LOW": "WEAK",
                  "NO_VALID_ANALOGS": "UNKNOWN", "NOT_AVAILABLE": "UNKNOWN"}
    dis_level = dis.get("level")
    return ConvictionState(
        mechanism=("STRONG" if candidate.get("playbook_id") else "UNKNOWN"),
        market_fit=("WEAK" if gates.get("regime_uncertain")
                    else ("MODERATE" if gates else "UNKNOWN")),
        analog_support=analog_map.get(analog.get("status"), "UNKNOWN"),
        ml_evidence=("UNKNOWN" if ml.get("status") in
                     (None, "UNTRAINED") else "MODERATE"),
        calibration=("UNKNOWN" if b.get("distribution_source_status")
                     in (None, "REFUSED") else "WEAK"),
        scenario_shape=("UNKNOWN" if not simulation
                        else "SYMMETRIC"),   # calibrated shape is future
        assassin=({"SURVIVED_CLEAN": "CLEAN",
                   "SURVIVED_WOUNDED": "WOUNDED"}.get(
                      (assassin or {}).get("verdict"), "UNKNOWN")),
        entry_quality=("UNKNOWN" if candidate.get("risk_frac") is None
                       else ("STRONG" if candidate["risk_frac"] <= 0.01
                             else "MODERATE")),
        execution=("UNKNOWN" if "COST_UNKNOWN" in reasons else "MODERATE"),
        tail_risk="UNKNOWN",
        portfolio_fit=("WEAK" if "PORTFOLIO_CONFLICT" in reasons
                       else ("MODERATE" if cap else "UNKNOWN")),
        disagreement=("LOW" if dis_level == "NONE"
                      else "HIGH" if dis_level == "HIGH"
                      else "UNKNOWN"))
