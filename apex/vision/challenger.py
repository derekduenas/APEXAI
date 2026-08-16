"""The Visual Challenger — a second pair of eyes with no hands.

EYES-1 WS7C/D. The numerical engine says what the market IS. This says
what the market LOOKS LIKE, and the only useful thing it can produce is
DISAGREEMENT: "the math calls this trend strong; visually it is extended,
messy, and rejecting the level."

Hard constraints, all enforced in code below rather than requested in a
prompt:

  * structured enum output only — free text lives in ONE field
  * no BUY/SELL, no size, no stop, no target, no probability, no EV
  * decision_power = NONE_OBSERVATIONAL_EPOCH1
  * Rule 17: prospective only. Never run over replay imagery.

The image it sees is rendered FROM the canonical packet, so a visual
observation is always traceable to the numbers it is challenging.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OBSERVATIONAL = "NONE_OBSERVATIONAL_EPOCH1"

ALLOWED = {
    "status": {"OK", "FAILED", "UNAVAILABLE"},
    "visual_structure": {"CLEAN", "CHOPPY", "TRENDING", "PARABOLIC",
                         "COMPRESSED", "UNCLEAR"},
    "extension_visual": {"LOW", "MODERATE", "HIGH", "UNKNOWN"},
    "rejection_visual": {"NONE", "MODERATE", "STRONG", "UNKNOWN"},
    "compression_visual": {"YES", "NO", "UNKNOWN"},
    "trend_quality": {"CLEAN", "MODERATE", "MESSY", "EXHAUSTED", "UNKNOWN"},
    "level_interaction": {"ACCEPTING", "REJECTING", "CHOPPING", "UNKNOWN"},
    "numeric_visual_disagreement": {"NONE", "MATERIAL", "UNKNOWN"},
    # ---- EYES-1A: the elite hierarchy, as enforced vocabulary.
    # Candle names are deliberately ABSENT: a candle is a descriptor read
    # at step 9 of the hierarchy, never a field a challenger can emit as
    # a conclusion. "HAMMER = BUY" is unrepresentable here.
    "market_structure": {"UPTREND", "DOWNTREND", "RANGE", "COMPRESSION",
                         "EXPANSION", "BREAKOUT", "FAILED_BREAKOUT",
                         "RECLAIM", "BREAKDOWN", "FAILED_BREAKDOWN",
                         "TRANSITION", "UNCLEAR"},
    "location_quality": {"AT_MAJOR_LEVEL", "ABOVE_RECLAIMED_LEVEL",
                         "MID_RANGE_NOISE", "INTO_OPPOSING_STRUCTURE",
                         "UNKNOWN"},
    "volume_confirmation": {"CONFIRMING", "DIVERGING", "THIN", "UNKNOWN"},
    "relative_strength_visual": {"LEADING", "INLINE", "LAGGING",
                                 "DETERIORATING", "UNKNOWN"},
    "volatility_state_visual": {"ENERGY_BUILDING", "MOVE_SPENT",
                                "EXPANDING", "NORMAL", "UNKNOWN"},
    "participant_trap_state": {"NONE", "POSSIBLE_LONG_TRAP",
                               "POSSIBLE_SHORT_TRAP",
                               "CONFIRMED_BY_PRICE_ACTION", "UNCLEAR"},
    "entry_geometry": {"DIRECTION_STRONG_ENTRY_STRONG",
                       "DIRECTION_STRONG_ENTRY_WEAK",
                       "DIRECTION_WEAK_ENTRY_STRONG",
                       "BOTH_WEAK", "UNKNOWN"},
    "multi_timeframe_alignment": {"ALIGNED", "MIXED", "CONFLICTED",
                                  "UNKNOWN"},
    "microstructure_support": {"SUPPORTIVE", "OPPOSING", "UNAVAILABLE",
                               "UNKNOWN"},
    "uncertainty": {"LOW", "MODERATE", "HIGH", "UNKNOWN"},
}

# Vocabulary that would make this an order rather than an observation.
FORBIDDEN_SUBSTRINGS = (
    "buy", "sell", "long ", "short ", "size", "position", "stop",
    "target", "authorize", "probability", "expected return", "ev ",
    "place", "order", "%",
)


class ChallengerViolation(RuntimeError):
    """The challenger tried to speak outside its vocabulary."""


@dataclass(frozen=True)
class VisualChallenge:
    decision_id: str
    snapshot_id: str
    status: str = "UNAVAILABLE"
    visual_structure: str = "UNCLEAR"
    extension_visual: str = "UNKNOWN"
    rejection_visual: str = "UNKNOWN"
    compression_visual: str = "UNKNOWN"
    trend_quality: str = "UNKNOWN"
    level_interaction: str = "UNKNOWN"
    primary_visual_objection: str = ""
    numeric_visual_disagreement: str = "UNKNOWN"
    facts_claimed: tuple = ()
    # ---- EYES-1A elite fields, every one categorical, defaults UNKNOWN
    market_structure: str = "UNCLEAR"
    location_quality: str = "UNKNOWN"
    volume_confirmation: str = "UNKNOWN"
    relative_strength_visual: str = "UNKNOWN"
    volatility_state_visual: str = "UNKNOWN"
    participant_trap_state: str = "UNCLEAR"
    entry_geometry: str = "UNKNOWN"
    multi_timeframe_alignment: str = "UNKNOWN"
    microstructure_support: str = "UNAVAILABLE"
    primary_visual_support: str = ""
    invalidation_observation: str = ""
    uncertainty: str = "UNKNOWN"
    decision_power: str = OBSERVATIONAL

    def __post_init__(self):
        for fieldname, allowed in ALLOWED.items():
            v = getattr(self, fieldname)
            if v not in allowed:
                raise ChallengerViolation(
                    f"{fieldname}={v!r} is not in {sorted(allowed)}")
        if self.decision_power != OBSERVATIONAL:
            raise ChallengerViolation(
                "a visual challenge may never carry decision power")
        for free_field in ("primary_visual_objection",
                           "primary_visual_support",
                           "invalidation_observation"):
            text = (getattr(self, free_field) or "").lower()
            for bad in FORBIDDEN_SUBSTRINGS:
                if bad in text:
                    raise ChallengerViolation(
                        f"{free_field} contains {bad!r}: the challenger "
                        f"observes geometry, it does not trade")
        if len(self.facts_claimed) > 8:
            raise ChallengerViolation("facts_claimed is bounded at 8")

    def as_record(self) -> dict:
        return {"kind": "visual_challenge", **asdict(self)}


def unavailable(decision_id: str, snapshot_id: str,
                reason: str = "VISION_TRANSPORT_UNAVAILABLE") -> VisualChallenge:
    """The honest empty result. Not a neutral one -- UNAVAILABLE must not
    read like 'nothing concerning was seen'."""
    return VisualChallenge(decision_id=decision_id, snapshot_id=snapshot_id,
                           status="UNAVAILABLE",
                           primary_visual_objection=reason)


def parse(raw: str, *, decision_id: str, snapshot_id: str) -> VisualChallenge:
    """Defensive parse of a model reply. Garbage becomes FAILED, never a
    confident default -- the same discipline the swarm transport uses."""
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError("not an object")
    except Exception:                                       # noqa: BLE001
        return VisualChallenge(decision_id=decision_id,
                               snapshot_id=snapshot_id, status="FAILED",
                               primary_visual_objection="unparseable reply")
    keep = {k: v for k, v in obj.items()
            if k in ALLOWED or k in ("primary_visual_objection",
                                     "primary_visual_support",
                                     "invalidation_observation",
                                     "facts_claimed")}
    keep.setdefault("status", "FAILED")
    if isinstance(keep.get("facts_claimed"), list):
        keep["facts_claimed"] = tuple(keep["facts_claimed"][:8])
    try:
        return VisualChallenge(decision_id=decision_id,
                               snapshot_id=snapshot_id, **keep)
    except (ChallengerViolation, TypeError) as e:
        return VisualChallenge(decision_id=decision_id,
                               snapshot_id=snapshot_id, status="FAILED",
                               primary_visual_objection=f"refused: {type(e).__name__}")


def attach_to_captain(kernel_record: dict, challenge: VisualChallenge) -> dict:
    """THE FIREWALL. The challenge rides ALONGSIDE the directive and can
    never move it -- the same contract the CIO has, for the same reason."""
    out = dict(kernel_record)
    out["visual_challenge"] = challenge.as_record()
    out["visual_changed_directive"] = False
    return out


def captain_visual_brief(ch: VisualChallenge) -> str:
    """The five-section brief, and nothing else. Sections are built ONLY
    from the validated categorical fields plus the three vetted free-text
    fields, so the brief cannot smuggle vocabulary the schema refused."""
    if ch.status != "OK":
        return (f"CAPTAIN VISUAL BRIEF — {ch.status}\n"
                f"No visual read is available; absence is not reassurance.")
    return "\n".join([
        "CAPTAIN VISUAL BRIEF (commentary; zero authority)",
        f"1. WHAT I SEE: structure={ch.market_structure} "
        f"trend={ch.trend_quality} location={ch.location_quality} "
        f"volume={ch.volume_confirmation} rs={ch.relative_strength_visual}",
        f"2. WHY IT MATTERS: trap={ch.participant_trap_state} "
        f"volatility={ch.volatility_state_visual} "
        f"mtf={ch.multi_timeframe_alignment}"
        + (f" | {ch.primary_visual_support}" if ch.primary_visual_support
           else ""),
        f"3. WHAT WORRIES ME: extension={ch.extension_visual} "
        f"rejection={ch.rejection_visual}"
        + (f" | {ch.primary_visual_objection}"
           if ch.primary_visual_objection else ""),
        f"4. ENTRY: {ch.entry_geometry}",
        f"5. INVALIDATION: {ch.invalidation_observation or 'UNSTATED'}",
        f"uncertainty={ch.uncertainty} "
        f"disagreement={ch.numeric_visual_disagreement} "
        f"decision_power={ch.decision_power}",
    ])
