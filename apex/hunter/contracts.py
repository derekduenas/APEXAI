"""P0 contracts: TradeThesis, PlaybookDefinition, fail-closed conditions.

A thesis is IMMUTABLE once created: frozen dataclass, content hash minted at
construction, recoverable forever. Management may transition its STATE (via
the state machine, each transition ruled and chained) but may never edit the
thesis itself. A playbook is a CONTRACT, not a claim of alpha: coding one
confers no predictive standing — a playbook making a predictive claim is a
hypothesis and enters governance like any other.

FAIL CLOSED: unknown never becomes safe. Any tripped condition vetoes a
decision; a missing feed is a refusal, not an assumption of neutrality.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True,
                                     separators=(",", ":"),
                                     default=str).encode()).hexdigest()


HORIZONS_MINUTES = (15, 30, 60, 90)      # HUNTER-v1 frozen; separate targets


class FailClosed(Enum):
    STALE_MARKET_DATA = "stale market data"
    MISSING_PIT_PROVENANCE = "missing PIT provenance"
    INVALID_MODEL_VERSION = "invalid model version"
    DEGRADED_CALIBRATION = "DEGRADED calibration"
    MISSING_PLAYBOOK_INPUT = "required playbook input unavailable"
    INVALID_REGIME_STATE = "invalid regime state"
    EXECUTION_UNHEALTHY = "execution adapter unhealthy"
    RISK_LIMIT_BREACHED = "risk limit breached"
    PORTFOLIO_STATE_UNAVAILABLE = "portfolio state unavailable"
    COST_ESTIMATE_UNAVAILABLE = "cost estimate unavailable"
    THESIS_INVALID = "thesis invalid"
    KILL_SWITCH = "system kill switch active"


def gate_decision(conditions: set) -> tuple:
    """Any tripped condition -> NO-TRADE, with every reason named."""
    if conditions:
        return ("NO-TRADE", tuple(sorted(c.value for c in conditions)))
    return ("ELIGIBLE", ())


@dataclass(frozen=True)
class PlaybookDefinition:
    """The contract every playbook must satisfy BEFORE it may be evaluated.
    Missing any field is a construction error, not a warning."""

    playbook_id: str
    mechanism: str                      # economic mechanism, prose but required
    eligible_universe: str
    required_state: dict                # regime axes that must hold
    prohibited_state: dict
    required_data: tuple                # feeds; absence => INELIGIBLE
    setup: str                          # computable condition, named
    trigger: str
    entry_semantics: str
    invalidation: str                   # thesis-death condition
    stop_methodology: str
    target_methodology: str
    time_stop_minutes: int
    max_holding_minutes: int
    execution_restrictions: str
    calibration_requirement: str        # minimum model state to act
    known_failure_modes: tuple

    def __post_init__(self):
        for name in ("mechanism", "setup", "trigger", "invalidation",
                     "stop_methodology"):
            if not getattr(self, name):
                raise ValueError(f"playbook {self.playbook_id!r}: {name} is "
                                 f"required; a playbook without a {name} is "
                                 f"a pattern, not a mechanism")
        if self.time_stop_minutes <= 0 or self.max_holding_minutes <= 0:
            raise ValueError("time discipline is required")


@dataclass(frozen=True)
class TradeThesis:
    """Immutable. The hash is minted from the full content at creation and
    the original is recoverable after any trade, forever."""

    symbol: str
    created_at: str                     # formation timestamp, immutable
    playbook_id: str
    market_state: dict
    regime_state: dict
    catalyst: str
    chart_state: dict                   # empty until P1 delivers ChartState
    model_id: str
    distribution: dict                  # summary + provenance + status
    calibration_status: str
    expected_cost_bps: float
    entry_zone: tuple                   # (low, high)
    invalidation: str
    stop: float
    targets: tuple
    time_stop_minutes: int
    max_holding_minutes: int
    risk_budget_frac: float             # of NAV at the structural stop
    expected_net_edge: float
    confidence: str
    thesis_hash: str = field(default="")

    def __post_init__(self):
        if not self.invalidation:
            raise ValueError("a thesis without an invalidation is a hope")
        if self.risk_budget_frac <= 0 or self.risk_budget_frac > 0.005:
            raise ValueError(
                f"risk_budget_frac {self.risk_budget_frac} outside the "
                f"declared (0, 0.5%] research template")
        body = {k: getattr(self, k) for k in self.__dataclass_fields__
                if k != "thesis_hash"}
        object.__setattr__(self, "thesis_hash", content_hash(body))

    def as_record(self) -> dict:
        return asdict(self)
