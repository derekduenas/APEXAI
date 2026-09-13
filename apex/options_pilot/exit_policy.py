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


@dataclass(frozen=True)
class ArrivalTriggeredExitPolicy(ExitPolicy):
    """EXIT-SCHEDULING-002. Same budget, better-placed attempts.

    WHY. FLOW-VALIDATION-001 showed a due exit failing five times while eligible quotes sat in its window. The due
    instant lands within a few hundred milliseconds of a snapshot arrival, and the fixed 15-second retry spacing
    equals the 15-second freshness limit and divides the 60-second snapshot period, so every retry repeated the same
    phase instead of sweeping across it. Two of five exits landed on the adverse side of arrival jitter; one was
    saved by a rounding coin flip at the boundary and one was not.

    WHAT CHANGES: WHEN an attempt fires. A due position inside its window may be attempted the moment a NEW
    observation for its contract becomes available, instead of only on the timer.

    WHAT DOES NOT CHANGE, deliberately:
      * the attempt budget (5) and the window (120 s) are the same numbers as V1;
      * the freshness limit is untouched. **A NEW RECEIPT IS NOT A FRESH QUOTE**: a newly arrived snapshot can carry
        an old provider timestamp, and the boundary rechecks provider time, receipt, contract identity, sides and
        prices exactly as before. An arrival-triggered attempt can and does still fail on staleness;
      * the deadline timers remain. Arrival triggering is an ADDITION, never a replacement: with no data at all the
        window still expires on its own timer and the position is still an explicit unresolved obligation.

    `skip_timer_when_no_new_observation` is **DISABLED (False) in this candidate**, and the review that disabled it
    was right. The rule suppressed a timer retry when the newest NOTIFICATION id had already been "attempted". But a
    notification id is not proof of which quote was evaluated: the id was recorded before the boundary was asked,
    nothing bound it to the quote actually returned, and no refusal reason was examined. A transient provider
    failure therefore marked an observation attempted when no quote had been seen at all, and suppressed the later
    timer that would have succeeded. The switch remains, off, with no replacement mechanism; arrival triggering
    fixes the demonstrated case without it."""
    policy_id: str = "EXIT_AT_HORIZON_15M_V2_ARRIVAL"
    arrival_triggered: bool = True
    skip_timer_when_no_new_observation: bool = False
    max_arrival_triggers: int = 64          # a flood of duplicate or invalid arrivals cannot starve the deadlines
    supersedes: str = "EXIT_AT_HORIZON_15M_V1"
    change_note: str = ("adds arrival-triggered attempts inside the existing window and budget; freshness, sides, "
                        "prices, contract identity and every boundary check are unchanged; timers retained. "
                        "skip_timer_when_no_new_observation is DISABLED: a notification id does not establish which "
                        "quote was evaluated, so it could suppress a later timer after a transient failure.")
    fields: tuple = field(default=("policy_id", "horizon_s", "window_s", "max_attempts", "retry_spacing_s",
                                   "exit_side", "on_exhaustion", "relation_to_legacy", "arrival_triggered",
                                   "skip_timer_when_no_new_observation", "max_arrival_triggers", "supersedes",
                                   "change_note"))

    def may_attempt_on_arrival(self, *, now: float, committed_epoch: float, attempts: int) -> bool:
        """An arrival may trigger an attempt only when the position is genuinely due, inside its window, and has
        budget left. It never extends the window and never adds an attempt."""
        if not self.arrival_triggered:
            return False
        return self.status(now=now, committed_epoch=committed_epoch, attempts=attempts) == "DUE"


EXIT_POLICY_V2 = ArrivalTriggeredExitPolicy()

# The identity this policy had while the suppression optimisation was ON. Turning it off CHANGES the policy, and a
# reader comparing two runs must be able to see that from the hash alone.
ARRIVAL_POLICY_HASH_WITH_SUPPRESSION = "74aa83147430195964ed216b4e3d73307aa842cb1fda08c3728d1f604a764ce2"

# The attempt accounting, stated once so it cannot drift:
ATTEMPT_ACCOUNTING = (
    "ATTEMPT_ACCOUNTING_V2: ONE attempt is consumed each time the boundary is asked to value a position, whatever "
    "the answer. A stale quote, a missing bid, a malformed quote and a provider failure all consume an attempt "
    "exactly as a successful valuation does, because each is a valuation attempt that was actually made. What does "
    "NOT consume an attempt is a scheduling decision not to ask: an arrival that is a duplicate of an observation "
    "already attempted, or a timer retry skipped because no new observation exists. Those are recorded as "
    "scheduling events with their own reason and are never counted as attempts, in either direction. The optional "
    "timer suppression that once used this distinction is DISABLED in the current policy: see "
    "ArrivalTriggeredExitPolicy for why a notification id cannot stand in for the quote that was evaluated.")

