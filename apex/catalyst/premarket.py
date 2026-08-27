"""PREMARKET INTELLIGENCE + INTRADAY WATCH CADENCE.

The overnight question is the one the quantitative stack cannot ask:
what changed in the world while the US cash market was shut?

    07:00 ET   OVERNIGHT DEEP SCAN     what moved, and what may have
                                       moved it
    08:20 ET   MACRO / EVENT UPDATE    the day's scheduled risk
    09:20 ET   FINAL PRE-BELL BRIEF    sealed before the open
    RTH        INTRADAY WATCH          cheap detection, expensive
                                       reasoning only on change
    16:05 ET   POST-CLOSE SEAL         what actually moved the tape

THE INTRADAY ARCHITECTURE MATTERS. Asking a language model "search the
web and tell me if something happened" every three minutes is slow,
expensive and unreliable: it re-reads the same world, and its answer
varies when the world did not. Instead:

    FAST DETERMINISTIC POLL  ->  has anything NEW appeared?
                             ->  only then invoke the brain

Detection is a cheap set-difference over source refs. Interpretation is
the expensive part and runs only on genuinely new material. This also
means a slow or failed brain degrades interpretation, never detection.

decision_power: SHADOW_CONTEXT_ONLY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from apex.catalyst.events import CatalystViolation
from apex.ops.timebase import ET, to_utc

PHASES = ("OVERNIGHT_SCAN", "MACRO_UPDATE", "PRE_BELL_BRIEF",
          "INTRADAY_WATCH", "POST_CLOSE_SEAL", "IDLE")

# ET wall-clock anchors. Resolved against the exchange calendar, so a
# half-day seals early rather than watching a closed market.
SCHEDULE_ET = {"OVERNIGHT_SCAN": (7, 0), "MACRO_UPDATE": (8, 20),
               "PRE_BELL_BRIEF": (9, 20)}
INTRADAY_POLL_S = 210          # ~3.5 min; detection only
POST_CLOSE_DELAY_MIN = 5

CATALYST_ENVIRONMENT = ("QUIET", "NORMAL", "ELEVATED", "EVENT_HEAVY",
                        "SHOCK")


def phase_at(now_utc: datetime, session: str, *,
             open_utc, close_utc, trading_day: bool) -> dict:
    """Which catalyst phase the calendar says we are in."""
    if not trading_day:
        return {"phase": "IDLE", "why": f"{session} is not a trading day"}

    def et_anchor(hh, mm):
        return to_utc(f"{session} {hh:02d}:{mm:02d}:00",
                      source="OPTIONS_CARD")   # ET-naive by contract

    scan = et_anchor(*SCHEDULE_ET["OVERNIGHT_SCAN"])
    macro = et_anchor(*SCHEDULE_ET["MACRO_UPDATE"])
    brief = et_anchor(*SCHEDULE_ET["PRE_BELL_BRIEF"])
    seal_end = close_utc + timedelta(minutes=POST_CLOSE_DELAY_MIN + 55)

    if now_utc < scan:
        p, why = "IDLE", "before the overnight scan window"
    elif now_utc < macro:
        p, why = "OVERNIGHT_SCAN", "what changed while we were shut"
    elif now_utc < brief:
        p, why = "MACRO_UPDATE", "today's scheduled risk"
    elif now_utc < open_utc:
        p, why = "PRE_BELL_BRIEF", "sealed before the bell"
    elif now_utc < close_utc:
        p, why = "INTRADAY_WATCH", "detect, then interpret on change"
    elif now_utc < seal_end:
        p, why = "POST_CLOSE_SEAL", "what actually moved the tape"
    else:
        p, why = "IDLE", "after the sealing window"
    return {"kind": "catalyst_phase", "phase": p, "why": why,
            "session": session,
            "poll_seconds": INTRADAY_POLL_S if p == "INTRADAY_WATCH"
            else None,
            "decision_power": "SHADOW_CONTEXT_ONLY"}


@dataclass
class WatchState:
    """Cheap change detection. Interpretation is invoked only when the
    set of observed source refs actually grows."""
    seen_refs: set = field(default_factory=set)
    polls: int = 0
    interpretations_invoked: int = 0

    def poll(self, source_refs) -> dict:
        self.polls += 1
        refs = set(source_refs)
        new = sorted(refs - self.seen_refs)
        self.seen_refs |= refs
        if new:
            self.interpretations_invoked += 1
        return {"kind": "intraday_watch_poll", "poll": self.polls,
                "new_source_refs": new, "n_new": len(new),
                "invoke_brain": bool(new),
                "brain_invocations": self.interpretations_invoked,
                "efficiency": (
                    f"{self.interpretations_invoked}/{self.polls} polls "
                    f"needed the expensive path"),
                "law": "detection is cheap and deterministic; "
                       "interpretation is expensive and runs only on "
                       "genuinely new material",
                "decision_power": "SHADOW_CONTEXT_ONLY"}


def scheduled_event(*, event_type: str, scheduled_time: str,
                    importance: str, affected: tuple,
                    consensus=None, prior=None) -> dict:
    """One entry in today's event map. Consensus is recorded only when
    genuinely available -- a fabricated consensus poisons every
    surprise computed from it."""
    return {"kind": "scheduled_event", "event_type": event_type,
            "scheduled_time": scheduled_time, "importance": importance,
            "affected_markets": list(affected),
            "consensus": consensus if consensus is not None
            else "NOT_ESTIMABLE",
            "prior": prior if prior is not None else "NOT_ESTIMABLE",
            "decision_power": "SHADOW_CONTEXT_ONLY"}


def catalyst_environment(*, scheduled_today: list,
                         unscheduled_overnight: list) -> dict:
    """A DESCRIPTIVE label for how eventful the day looks. It changes
    nothing in V1; it exists so research can later ask whether the
    Predator behaves differently in different environments."""
    crit = sum(1 for e in scheduled_today
               if e.get("importance") == "CRITICAL")
    high = sum(1 for e in scheduled_today
               if e.get("importance") == "HIGH")
    shocks = sum(1 for e in unscheduled_overnight
                 if e.get("importance") in ("CRITICAL",))
    if shocks:
        env = "SHOCK"
    elif crit >= 1:
        env = "EVENT_HEAVY"
    elif high >= 2:
        env = "ELEVATED"
    elif scheduled_today or unscheduled_overnight:
        env = "NORMAL"
    else:
        env = "QUIET"
    return {"kind": "catalyst_environment", "environment": env,
            "critical_scheduled": crit, "high_scheduled": high,
            "overnight_shocks": shocks,
            "law": "descriptive only -- V1 never reads this",
            "decision_power": "SHADOW_CONTEXT_ONLY"}


def pre_bell_brief(*, session: str, overnight: dict,
                   scheduled_today: list, universe_events: dict,
                   environment: dict, unknowns: list) -> dict:
    """The 09:20 ET brief. Compact, sourced, and explicit about what it
    does not know."""
    if not isinstance(unknowns, list):
        raise CatalystViolation("unknowns must be an explicit list")
    return {"kind": "pre_bell_catalyst_brief", "session": session,
            "overnight_state": overnight,
            "scheduled_risks_today": scheduled_today,
            "combat_universe_events": universe_events,
            "catalyst_environment": environment["environment"],
            "what_we_do_not_know": unknowns,
            "law": "a brief that lists no unknowns is not a brief, it "
                   "is a narrative",
            "authority": "SHADOW_CONTEXT_ONLY",
            "changes_v1": False,
            "decision_power": "SHADOW_CONTEXT_ONLY"}
