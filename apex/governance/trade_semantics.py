"""TRADE SEMANTICS — four authorities that must never be conflated.

Day-1 recorded a field called `invalidation` on a SPY card. In the BTC
sleeve that name commands an exit and defines 1R. In the Options sleeve
it did neither -- it informed geometry and was never passed to the
resolver. One name, two powers.

That ambiguity is dangerous in a way a wrong number is not: a wrong
number is eventually contradicted by reality, whereas a field whose
name implies authority it lacks will be *believed* by every later
faculty that reads it. EdgeForge would learn that "invalidation" means
"exit" and be wrong about half its training set.

    THESIS_INVALIDATION     what evidence makes the IDEA wrong
    EXECUTION_STOP_TRIGGER  what condition actually EXITS the position
    RISK_INVALIDATION       what state defined the PLANNED MONEY at risk
    RESOLUTION_HORIZON      when/how the EXPERIMENT is measured

These may coincide. In BTC they nearly do. In the Options hold-to-close
protocol they deliberately do not: the thesis level is diagnostic, the
execution stop is NONE, risk is FULL_PREMIUM, and the horizon is the
regular session close. That combination is legitimate -- it is an
experiment that intends to hold. What is illegitimate is leaving a
reader to guess which of the four a bare "invalidation" meant.

PATH MATTERS. A trade whose thesis broke early and recovered by the
close is NOT the same animal as one whose thesis never broke, even when
the final sign is identical. Final direction alone may never be read as
"the thesis held" -- Day-1's SPY was scored THESIS_RIGHT on exactly
that error, having spent 54% of the session past its own thesis level.

decision_power: NONE -- a governance vocabulary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

NOT_ESTIMABLE = "NOT_ESTIMABLE"

AUTHORITY_KINDS = ("THESIS_INVALIDATION", "EXECUTION_STOP_TRIGGER",
                   "RISK_INVALIDATION", "RESOLUTION_HORIZON")

RISK_BASES = ("PLANNED_INVALIDATION", "MAX_LOSS", "FULL_PREMIUM",
              "OTHER_EXPLICIT", "NOT_DECLARED")

THESIS_PATH_STATES = (
    "THESIS_NEVER_INVALIDATED",
    "THESIS_INVALIDATED_PROTOCOL_HELD",
    "THESIS_REVALIDATED_AFTER_INVALIDATION",
    NOT_ESTIMABLE,
)


class SemanticViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class TradeAuthorities:
    """What each declared level is actually empowered to do."""
    thesis_invalidation: float | None = None
    execution_stop_trigger: float | str = "NONE"
    risk_invalidation: float | None = None
    risk_basis: str = "NOT_DECLARED"
    resolution_horizon: str = "REGULAR_SESSION_CLOSE"
    notes: tuple = ()
    law: str = ("a level has only the authority explicitly granted "
                "here; a name may never imply a power it lacks")

    def __post_init__(self):
        if self.risk_basis not in RISK_BASES:
            raise SemanticViolation(
                f"unknown risk_basis {self.risk_basis!r}")
        if isinstance(self.execution_stop_trigger, str) and \
                self.execution_stop_trigger != "NONE":
            raise SemanticViolation(
                f"execution_stop_trigger must be a price or the literal "
                f"'NONE', got {self.execution_stop_trigger!r} -- an "
                f"ambiguous stop is worse than no stop")

    @property
    def has_execution_stop(self) -> bool:
        return isinstance(self.execution_stop_trigger, (int, float))

    def as_record(self) -> dict:
        return {"kind": "trade_authorities", **asdict(self),
                "has_execution_stop": self.has_execution_stop}


# The two protocols in service today, declared once so no caller has to
# reinvent (or misremember) them.
OPTIONS_HOLD_TO_CLOSE = dict(
    execution_stop_trigger="NONE",
    risk_basis="FULL_PREMIUM",
    resolution_horizon="REGULAR_SESSION_CLOSE",
    notes=("the thesis level is DIAGNOSTIC under this protocol; the "
           "experiment intends to hold through it and measure at the "
           "official regular-session close",))

BTC_STOP_OR_TARGET = dict(
    risk_basis="PLANNED_INVALIDATION",
    resolution_horizon="STOP_OR_TARGET",
    notes=("thesis level, execution stop and risk basis coincide here "
           "by design; that coincidence is declared, not assumed",))


def classify_thesis_path(*, direction: str,
                         thesis_invalidation: float | None,
                         path_closes: list,
                         final_close: float | None,
                         authorities: TradeAuthorities | None = None
                         ) -> dict:
    """Did the thesis hold, break, or break and recover?

    `path_closes` must already be restricted to the causally eligible
    window (entry < t <= boundary). Final direction alone is never
    sufficient -- that is the error this function exists to prevent."""
    if thesis_invalidation is None or not path_closes:
        return {"kind": "thesis_path", "state": NOT_ESTIMABLE,
                "why": "no thesis level or no eligible path observations",
                "law": "path matters; final sign is not a verdict"}

    if direction == "SHORT":
        breached = [c for c in path_closes if c > thesis_invalidation]
    elif direction == "LONG":
        breached = [c for c in path_closes if c < thesis_invalidation]
    else:
        return {"kind": "thesis_path", "state": NOT_ESTIMABLE,
                "why": f"direction {direction!r} is not directional"}

    n = len(path_closes)
    n_breach = len(breached)
    frac = round(n_breach / n, 4) if n else NOT_ESTIMABLE

    first_idx = NOT_ESTIMABLE
    for i, c in enumerate(path_closes):
        if (c > thesis_invalidation if direction == "SHORT"
                else c < thesis_invalidation):
            first_idx = i
            break

    held = authorities is None or not authorities.has_execution_stop
    if n_breach == 0:
        state = "THESIS_NEVER_INVALIDATED"
        why = "the thesis level was never breached on eligible closes"
    else:
        final_ok = (final_close is not None and
                    (final_close <= thesis_invalidation
                     if direction == "SHORT"
                     else final_close >= thesis_invalidation))
        if final_ok:
            state = "THESIS_REVALIDATED_AFTER_INVALIDATION"
            why = (f"breached on {n_breach}/{n} eligible closes "
                   f"({frac}) and recovered by the boundary -- a "
                   f"recovery, NOT an unbroken thesis")
        else:
            state = "THESIS_INVALIDATED_PROTOCOL_HELD"
            why = (f"breached on {n_breach}/{n} eligible closes "
                   f"({frac}) and still breached at the boundary; the "
                   f"position remained open because the protocol "
                   f"declares no execution stop"
                   if held else
                   f"breached on {n_breach}/{n} eligible closes")
    return {"kind": "thesis_path", "state": state, "why": why,
            "breach_fraction": frac, "n_breached": n_breach,
            "n_eligible": n,
            "first_breach_index": first_idx,
            "protocol_held_through_breach": held and n_breach > 0,
            "law": "a thesis that broke and recovered is not a thesis "
                   "that held; final sign may never stand in for path"}
