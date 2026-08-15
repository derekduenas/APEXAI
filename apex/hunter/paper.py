"""Phase 5: paper execution + trade management — built, tested, and NOT
authorized in production.

AUTHORIZATION FIREWALL: production paper orders require a CapitalDecision
whose final_state is PAPER_ELIGIBLE — unreachable until Phase 3 is
commissioned. Integration tests use SyntheticTestAuthorization, whose
constructor refuses to exist outside a pytest process; a production
forward candidate structurally cannot reach synthetic authorization
(adversarial test 18).

FILL REALISM: with 1m OHLC only, "the bar touched my price" is NOT a
fill. CERTAIN_FILL requires the next bar to open through the price;
trading through it beyond an epsilon is PLAUSIBLE_FILL; a bare touch is
AMBIGUOUS_FILL; anything else NO_FILL. Ambiguity is preserved into
attribution — unknown execution never manufactures realized P&L.

TRADE MANAGEMENT wraps the existing sealed state machine (stop never
widens is ITS law; this module adds no competing rule): EXIT, PARTIAL
(monotone position decrease), TIGHTEN/TRAIL (monotone via tighten_stop),
ADD_IF_PERMITTED (requires a fresh Capital re-check and refuses when the
world got more uncertain). Every action names its actor: an
LLM-attributed actor is refused before any rule runs — an LLM can
propose in a report; it can never mutate trade state.

THESIS HEALTH: deterministic comparison of the FROZEN thesis conditions
against a new snapshot — THESIS_HEALTHY / THESIS_WEAKENING /
THESIS_INVALID from declared counts, not narrative. New snapshots are
appended; the original thesis is immutable by construction.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum

import pandas as pd

FILL_EPSILON_FRAC = 0.0005            # trade-through margin for PLAUSIBLE

PAPER_STATES = ("NOT_AUTHORIZED", "WAITING_FOR_TRIGGER", "ORDER_PENDING",
                "FILLED", "PARTIALLY_FILLED", "NO_FILL", "AMBIGUOUS_FILL",
                "MANAGING", "EXITED", "CANCELLED")


class FillGrade(Enum):
    CERTAIN_FILL = "CERTAIN_FILL"
    PLAUSIBLE_FILL = "PLAUSIBLE_FILL"
    AMBIGUOUS_FILL = "AMBIGUOUS_FILL"
    NO_FILL = "NO_FILL"


class PaperAuthorizationError(RuntimeError):
    pass


class SyntheticTestAuthorization:
    """Constructible ONLY inside a pytest process. Production code paths
    never hold one, so synthetic authorization is unreachable there."""

    def __init__(self):
        if "PYTEST_CURRENT_TEST" not in os.environ:
            raise PaperAuthorizationError(
                "synthetic authorization exists only inside tests")
        self.token = uuid.uuid4().hex


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    decision_id: str
    symbol: str
    direction: str
    entry_limit: float
    stop: float
    target: float
    weight: float
    state: str
    authorized_by: str                # "PAPER_ELIGIBLE" | "SYNTHETIC_TEST"
    lineage: dict                     # decision -> bundle -> capital ids

    def as_record(self) -> dict:
        d = asdict(self)
        d["kind"] = "paper_order"
        return d


def authorize_paper(capital_decision, candidate: dict,
                    bundle_id: str | None = None,
                    synthetic: SyntheticTestAuthorization | None = None) -> PaperOrder | dict:
    """Production gate: PAPER_ELIGIBLE only. The synthetic path is for
    integration tests and stamps itself indelibly."""
    if synthetic is not None:
        authorized_by = "SYNTHETIC_TEST"
    elif capital_decision.final_state == "PAPER_ELIGIBLE":
        authorized_by = "PAPER_ELIGIBLE"
    else:
        return {"kind": "paper_order", "state": "NOT_AUTHORIZED",
                "decision_id": candidate.get("decision_id"),
                "reason": f"capital said {capital_decision.final_state}; "
                          f"paper execution requires PAPER_ELIGIBLE"}
    return PaperOrder(
        order_id=uuid.uuid4().hex[:12],
        decision_id=candidate["decision_id"], symbol=candidate["symbol"],
        direction=candidate["direction"],
        entry_limit=float(candidate["entry"]),
        stop=float(candidate["stop"]), target=float(candidate["target"]),
        weight=capital_decision.weight or 0.0, state="ORDER_PENDING",
        authorized_by=authorized_by,
        lineage={"decision_id": candidate["decision_id"],
                 "forecast_bundle_id": bundle_id,
                 "capital_decision_id": capital_decision.decision_id})


def assess_fill(order: PaperOrder, next_bars: pd.DataFrame) -> dict:
    """Conservative marketable-limit model over the bars AFTER submission."""
    if next_bars.empty:
        return {"grade": FillGrade.NO_FILL.value, "fill_price": None}
    bar = next_bars.iloc[0]
    o, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
    lim = order.entry_limit
    eps = lim * FILL_EPSILON_FRAC
    buy = order.direction == "LONG"
    if (o <= lim) if buy else (o >= lim):
        return {"grade": FillGrade.CERTAIN_FILL.value,
                "fill_price": o, "note": "opened through the limit"}
    through = (lo <= lim - eps) if buy else (hi >= lim + eps)
    touched = (lo <= lim) if buy else (hi >= lim)
    if through:
        return {"grade": FillGrade.PLAUSIBLE_FILL.value, "fill_price": lim}
    if touched:
        return {"grade": FillGrade.AMBIGUOUS_FILL.value, "fill_price": None,
                "note": "touched, not traded through: no P&L may be "
                        "asserted from this"}
    return {"grade": FillGrade.NO_FILL.value, "fill_price": None}


# ------------------------------------------------------------- management
class ManagementError(RuntimeError):
    pass


@dataclass
class PaperPosition:
    order: PaperOrder
    qty_frac: float = 1.0             # of authorized size; monotone down
    current_stop: float = 0.0
    state: str = "MANAGING"
    actions: list = field(default_factory=list)

    def __post_init__(self):
        self.current_stop = self.order.stop


def manage(pos: PaperPosition, action: str, *, actor: str,
           new_stop: float | None = None,
           reduce_to: float | None = None,
           capital_recheck=None,
           world_more_uncertain: bool | None = None) -> PaperPosition:
    """Deterministic transitions only. Every refusal is an exception with
    the rule named."""
    if "llm" in actor.lower() or "swarm" in actor.lower():
        raise ManagementError(
            f"actor {actor!r} may propose in a report; it may never mutate "
            f"trade state (LLM firewall)")
    if pos.state != "MANAGING":
        raise ManagementError(f"no management on state {pos.state}")
    long = pos.order.direction == "LONG"
    if action in ("TIGHTEN", "TRAIL"):
        if new_stop is None:
            raise ManagementError("a stop action requires the new stop")
        widening = new_stop < pos.current_stop if long \
            else new_stop > pos.current_stop
        if widening:
            raise ManagementError(
                f"stop {pos.current_stop} -> {new_stop} moves AWAY from the "
                f"position: the stop never widens, whatever the narrative")
        pos.current_stop = new_stop
    elif action == "PARTIAL":
        if reduce_to is None or not 0 <= reduce_to < pos.qty_frac:
            raise ManagementError(
                f"partial exit must strictly REDUCE qty ({pos.qty_frac} -> "
                f"{reduce_to}); a position can never grow through PARTIAL")
        pos.qty_frac = reduce_to
        if pos.qty_frac == 0:
            pos.state = "EXITED"
    elif action == "EXIT":
        pos.qty_frac = 0.0
        pos.state = "EXITED"
    elif action == "ADD_IF_PERMITTED":
        if world_more_uncertain:
            raise ManagementError("the world got MORE uncertain; adding is "
                                  "refused (monotone caution)")
        if capital_recheck is None or capital_recheck.final_state not in (
                "PAPER_ELIGIBLE",):
            raise ManagementError("adding requires a fresh Capital "
                                  "authorization; none was granted")
    elif action != "HOLD":
        raise ManagementError(f"undeclared action {action!r}")
    pos.actions.append({"action": action, "actor": actor,
                        "stop": pos.current_stop, "qty": pos.qty_frac})
    return pos


THESIS_HEALTH = ("THESIS_HEALTHY", "THESIS_WEAKENING", "THESIS_INVALID")


def thesis_health(frozen_conditions: dict, current_state: dict) -> dict:
    """Deterministic: count frozen boolean conditions now violated.
    0 -> HEALTHY, 1 -> WEAKENING, >=2 or invalidation_hit -> INVALID.
    Both inputs are snapshots; nothing here mutates the thesis."""
    violated = [k for k, expected in frozen_conditions.items()
                if current_state.get(k) is not None
                and current_state.get(k) != expected]
    if current_state.get("invalidation_hit") or len(violated) >= 2:
        health = "THESIS_INVALID"
    elif len(violated) == 1:
        health = "THESIS_WEAKENING"
    else:
        health = "THESIS_HEALTHY"
    return {"health": health, "violated": violated,
            "checked": len(frozen_conditions)}
