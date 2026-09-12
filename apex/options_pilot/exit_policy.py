"""EXIT POLICY (M1) — a NEW, explicit, versioned policy for the pilot.

The legacy session's protocol held to the regular-session close. The pilot
records a 15-minute forecast; this policy exits at the forecast horizon.
That is a different policy, not a reinterpretation of the old rule, and it
is frozen HERE before any economics are evaluated against it.

    exit_due          = fill committed_epoch + horizon_s (900)
    quote window      = [exit_due, exit_due + window_s (120)]
    attempts          = at most max_attempts valuation attempts inside the window,
                        spaced by retry_spacing_s where the scheduler permits
    valuation failure = NOT_ESTIMABLE attempt; position REMAINS an obligation
    exhaustion        = EXIT_WINDOW_EXHAUSTED terminal note: the AUTOMATIC exit
                        stops; the position is STILL an unresolved obligation
                        (P&L UNKNOWN, exposure open) requiring an operator
                        decision or a later recovery attempt. Never zero P&L.
    early exit        = not part of this policy (no stop, no target)

Accounting statement for late/missing quotes: a missing or stale exit quote
never produces a number. Realized P&L exists only when an executable BID was
observed inside the policy and persisted as a discharging outcome."""
from __future__ import annotations

from dataclasses import dataclass, field

from .records import canonical_hash


@dataclass(frozen=True)
class ExitPolicy:
    policy_id: str = "EXIT_AT_HORIZON_15M_V1"
    horizon_s: float = 900.0
    window_s: float = 120.0
    max_attempts: int = 5
    retry_spacing_s: float = 15.0
    exit_side: str = "BID"
    on_exhaustion: str = ("EXIT_WINDOW_EXHAUSTED: automatic attempts stop; the position remains an unresolved obligation "
                          "with unknown P&L and open exposure; operator decision or later recovery attempt required")
    relation_to_legacy: str = ("NEW policy distinct from the legacy protocol's hold-to-session-close rule; the recorded "
                               "15-minute forecast horizon and this exit horizon coincide by construction")
    fields: tuple = field(default=("policy_id", "horizon_s", "window_s", "max_attempts", "retry_spacing_s", "exit_side",
                                   "on_exhaustion", "relation_to_legacy"))

    def describe(self) -> dict:
        return {k: getattr(self, k) for k in self.fields}

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.describe())

    def schedule(self, committed_epoch: float) -> dict:
        due = committed_epoch + self.horizon_s
        return {"policy_id": self.policy_id, "policy_hash": self.policy_hash, "exit_due_epoch": due,
                "window_close_epoch": due + self.window_s, "max_attempts": self.max_attempts}

    def status(self, *, now: float, committed_epoch: float, attempts: int) -> str:
        """NOT_DUE | DUE | EXHAUSTED (window closed or attempts used)."""
        s = self.schedule(committed_epoch)
        if attempts >= self.max_attempts or now > s["window_close_epoch"]:
            return "EXHAUSTED"
        if now >= s["exit_due_epoch"]:
            return "DUE"
        return "NOT_DUE"


EXIT_POLICY_V1 = ExitPolicy()
