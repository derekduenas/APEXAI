"""UnderlyingForwardDistribution — F O8: assembled ENTIRELY from
already-persisted Frontier-2 ledger records. Computes nothing from raw
bars itself -- direction_quality/transition_quality are copied verbatim
from CaptainFrontierShadow's own typed fields. magnitude_range/
timing_range/path_uncertainty stay UNKNOWN tonight because Curve does
not yet emit a numeric magnitude/timing estimate; this module does not
invent one to fill the gap.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from apex.options_research import OPTIONS_RESEARCH_POWER

CURVE_LEDGER = Path("results/frontier2/curve_ledger.jsonl")
CAPTAIN_LEDGER = Path("results/frontier2/captain_shadow_ledger.jsonl")
ASSASSIN_LEDGER = Path("results/frontier2/assassin2_ledger.jsonl")

QUALITATIVE_TIERS = ("STRONG", "MODERATE", "WEAK", "UNKNOWN")
SUPPORT_CLASS = "UNCALIBRATED"


class ForwardDistributionError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnderlyingForwardDistribution:
    subject: str
    direction_quality: str
    transition_quality: str
    magnitude_range: str
    timing_range: str
    path_uncertainty: str
    volatility_expectation: str
    tail_asymmetry: str
    invalidation: str
    familiarity: str
    data_quality: str
    support_class: str
    known_from: str
    as_of: str
    decision_power: str = OPTIONS_RESEARCH_POWER

    def as_record(self) -> dict:
        return {"kind": "underlying_forward_distribution", **asdict(self)}

    def has_legitimate_thesis(self) -> bool:
        return (self.direction_quality != "UNKNOWN"
               or self.transition_quality != "UNKNOWN")


def _read_latest(path: Path, subject: str) -> dict | None:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("subject") == subject:
            latest = d
    return latest


def build(subject: str, *, now, known_from) -> UnderlyingForwardDistribution:
    import pandas as pd
    now = pd.Timestamp(now)
    curve = _read_latest(CURVE_LEDGER, subject)
    captain = _read_latest(CAPTAIN_LEDGER, subject)
    assassin = _read_latest(ASSASSIN_LEDGER, subject)

    direction_quality = captain.get("direction_quality", "UNKNOWN") if captain else "UNKNOWN"
    transition_quality = captain.get("transition_quality", "UNKNOWN") if captain else "UNKNOWN"
    data_quality = captain.get("data_quality", "UNKNOWN") if captain else "UNKNOWN"
    familiarity = (assassin.get("familiarity", "UNKNOWN") if assassin
                  else (captain.get("model_familiarity", "UNKNOWN") if captain else "UNKNOWN"))
    invalidation = captain.get("falsification", "UNKNOWN") if captain else "UNKNOWN"

    # magnitude/timing/path/vol/tail: no numeric Curve estimate exists
    # yet for any of these -- UNKNOWN is the honest, current answer.
    return UnderlyingForwardDistribution(
        subject=subject, direction_quality=direction_quality,
        transition_quality=transition_quality, magnitude_range="UNKNOWN",
        timing_range="UNKNOWN", path_uncertainty="UNKNOWN",
        volatility_expectation=(
            "ELEVATED" if curve and curve.get("high_level_state") == "VOLATILITY_EXPANSION"
            else "COMPRESSED" if curve and curve.get("high_level_state") == "VOLATILITY_COMPRESSION"
            else "UNKNOWN"),
        tail_asymmetry="UNKNOWN", invalidation=invalidation, familiarity=familiarity,
        data_quality=data_quality, support_class=SUPPORT_CLASS,
        known_from=str(pd.Timestamp(known_from)), as_of=str(now))
