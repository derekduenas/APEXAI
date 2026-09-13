"""THE SHARED LIFECYCLE SCHEDULER (OPERATING-LOOP-001 item 1).

ONE loop drives production and recorded-data execution. It owns time; nothing else advances the clock. It reuses the
REAL boundary, the REAL session functions and the REAL Book -- this module adds ordering and deadline discipline, not
a second execution path.

WHAT WENT WRONG WITHOUT IT. `scripts/loop_demonstration.py` ran all twelve scans and only then attempted exits, and
in doing so REWOUND the clock from 16:15Z back to 13:45Z. Eleven of twelve scans were then refused for capacity that
had in fact been discharged. The system was correct at every step it was asked to perform; the driver never asked
(docs/LOOP_DEMONSTRATION_CORRECTIONS.md §3). Exit servicing must never depend on the next strategy scan happening.

THE EVENT TYPES, AND THE ORDER FOR SIMULTANEOUS EVENTS.

    rank  event                what it does
    0     DATA_AVAILABLE       an input becomes visible. Admits no risk by itself.
    1     INTENT_EXPIRY        an outstanding authorization reaches its TTL and is retired.
    2     EXIT_DUE             an open position reaches its exit deadline and is valued.
    3     EXIT_RETRY           a scheduled re-attempt inside the exit window.
    4     EXIT_WINDOW_CLOSE    the last instant an exit may be attempted; exhaustion is recorded.
    5     SCAN                 NEW RISK MAY BE ADMITTED.
    6     SESSION_CLOSE        the session is closed and its obligations reported.

EXISTING DUE OBLIGATIONS ARE PROCESSED BEFORE NEW RISK AT THE SAME INSTANT. That is what ranks 1-4 preceding rank 5
means, and it is the rule the demonstration violated. Ties inside one rank break by SCHEDULING ORDER (a monotonic
ordinal), so the order of events at one instant is total and deterministic: (canonical_instant, rank, ordinal).

TIME NEVER GOES BACKWARDS. `MonotonicClock.advance_to` refuses any instant earlier than the current reading, and
scheduling an event in the past is refused unless the caller says `allow_past` (used only when reconciliation finds an
obligation whose deadline has already passed, which is then scheduled AT the current instant, never before it).

THE LOOP ADVANCES ONLY TO THE NEXT RELEVANT EVENT. It never polls, never spins and never sleeps past a deadline. After
every handler it RE-CHECKS deadlines -- both by draining anything that has become due at the current instant and by
reconciling the ledger's obligations against the queue -- before it is allowed to advance again."""
from __future__ import annotations

import heapq
import time

from . import boundary as B
from . import instant as I
from . import ledger as L
from . import session as S
from . import exit_policy as EP
from .clock import Clock
from .records import INTENT_TTL_S


class LifecycleRefused(RuntimeError):
    """An ordering, clock or budget rule of the lifecycle was violated. Named, never silent."""


DATA_AVAILABLE = "DATA_AVAILABLE"
INTENT_EXPIRY = "INTENT_EXPIRY"
EXIT_DUE = "EXIT_DUE"
EXIT_ARRIVAL = "EXIT_ARRIVAL"           # EXIT-SCHEDULING-002: a due position, woken by a NEW observation
EXIT_RETRY = "EXIT_RETRY"
EXIT_WINDOW_CLOSE = "EXIT_WINDOW_CLOSE"
SCAN = "SCAN"
SESSION_CLOSE = "SESSION_CLOSE"

# THE TOTAL ORDER. DATA_AVAILABLE first, so an observation arriving at the same instant an exit falls due is already
# visible when EXIT_DUE fires. EXIT_ARRIVAL then EXIT_RETRY, so a genuine arrival is preferred over a blind timer at
# the same instant. EXIT_WINDOW_CLOSE after both, so a deadline never pre-empts an attempt that could still resolve.
# All of them before SCAN: existing obligations are serviced before new risk is admitted.
EVENT_ORDER = (DATA_AVAILABLE, INTENT_EXPIRY, EXIT_DUE, EXIT_ARRIVAL, EXIT_RETRY, EXIT_WINDOW_CLOSE, SCAN,
               SESSION_CLOSE)
RANK = {k: i for i, k in enumerate(EVENT_ORDER)}
OBLIGATION_EVENTS = (INTENT_EXPIRY, EXIT_DUE, EXIT_ARRIVAL, EXIT_RETRY, EXIT_WINDOW_CLOSE)
ORDERING_POLICY = (
    "LIFECYCLE_ORDER_V1: events are totally ordered by (canonical microsecond, event rank, scheduling ordinal). The "
    "rank order is DATA_AVAILABLE < INTENT_EXPIRY < EXIT_DUE < EXIT_ARRIVAL < EXIT_RETRY < EXIT_WINDOW_CLOSE < "
    "SCAN < SESSION_CLOSE, "
    "so every existing due obligation is processed before new risk is admitted at the same instant. Ties within one "
    "rank break by scheduling order. The clock never rewinds and advances only to the next scheduled event.")

DEFAULT_EVENT_BUDGET = 20000


# ---------------------------------------------------------------------------- clocks


class MonotonicClock:
    """A clock that can be advanced but never rewound. Fixtures and recorded runs advance it explicitly; production
    advances it by sleeping to the wall. Both go through the same guard, so the same code drives both."""

    KIND = "CONTROLLED"

    def __init__(self, t0: float):
        self._t = float(I.canonical_epoch(t0, field="clock.t0"))
        self.advances: list = []

    def now(self) -> float:
        return self._t

    def now_us(self) -> int:
        return I.canonical_micros(self._t, field="clock.now")

    def clock(self) -> Clock:
        """The `Clock` the boundary reads. It can only observe; it cannot move time."""
        return Clock(self.now)

    def advance_to(self, epoch: float, *, why: str = "") -> float:
        target_us = I.canonical_micros(epoch, field="advance_to")
        now_us = self.now_us()
        if target_us < now_us:
            raise LifecycleRefused("CLOCK_REWIND_REFUSED: asked to move to %s (%d us) from %s (%d us)%s"
                                   % (I.canonical_utc(epoch), target_us, I.canonical_utc(self._t), now_us,
                                      (" [%s]" % why if why else "")))
        if target_us > now_us:
            self._wait(I.from_micros(target_us))
            self._t = I.from_micros(target_us)
            self.advances.append({"to_utc": I.canonical_utc(self._t), "to_us": target_us,
                                  "delta_s": round((target_us - now_us) / 1e6, 6), "why": why})
        return self._t

    def _wait(self, target_epoch: float) -> None:
        """Controlled clocks jump. The production subclass actually waits."""

    def sleep(self, seconds: float) -> float:
        """The `sleep_fn` the session functions expect. Negative sleeps are a rewind and are refused."""
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise LifecycleRefused("SLEEP_NOT_A_NUMBER: %r" % (seconds,))
        if seconds < 0:
            raise LifecycleRefused("CLOCK_REWIND_REFUSED: negative sleep %r" % (seconds,))
        return self.advance_to(self._t + float(seconds), why="sleep")


class WallClock(MonotonicClock):
    """Production: `now` is the wall, and advancing to an instant means waiting for it."""

    KIND = "WALL"

    def __init__(self, now_fn=time.time, sleep_fn=time.sleep):
        self._now_fn, self._sleep_fn = now_fn, sleep_fn
        super().__init__(now_fn())

    def now(self) -> float:
        wall = float(self._now_fn())
        if I.canonical_micros(wall, field="wall") > I.canonical_micros(self._t, field="wall.last"):
            self._t = wall
        return self._t

    def _wait(self, target_epoch: float) -> None:
        remaining = target_epoch - float(self._now_fn())
        while remaining > 0:
            self._sleep_fn(remaining)
            remaining = target_epoch - float(self._now_fn())


# ---------------------------------------------------------------------------- the queue


class Scheduler:
    """A deterministic priority queue of future obligations. It holds no policy: what an event MEANS is the runner's
    business. What it guarantees is the total order and that nothing is scheduled into the past by accident."""

    def __init__(self, clock: MonotonicClock):
        self.clock = clock
        self._heap: list = []
        self._ordinal = 0
        self.scheduled: list = []
        self.processed: list = []

    def __len__(self) -> int:
        return len(self._heap)

    def at(self, epoch, kind: str, payload: dict | None = None, *, key=None, allow_past: bool = False) -> dict:
        if kind not in RANK:
            raise LifecycleRefused("EVENT_KIND_UNKNOWN: %r (known: %s)" % (kind, ", ".join(EVENT_ORDER)))
        us = I.canonical_micros(epoch, field="schedule.%s" % kind)
        now_us = self.clock.now_us()
        if us < now_us:
            if not allow_past:
                raise LifecycleRefused("EVENT_IN_THE_PAST: %s at %s is before the clock %s; scheduling into the past "
                                       "would require rewinding time to honour it"
                                       % (kind, I.canonical_utc(epoch), I.canonical_utc(self.clock.now())))
            us = now_us                                     # an overdue obligation is due NOW, never earlier
        self._ordinal += 1
        ev = {"kind": kind, "at_us": us, "at_utc": I.canonical_utc(I.from_micros(us)), "at_epoch": I.from_micros(us),
              "ordinal": self._ordinal, "rank": RANK[kind], "key": key, "payload": dict(payload or {})}
        heapq.heappush(self._heap, (us, RANK[kind], self._ordinal, ev["kind"], ev))
        self.scheduled.append({k: ev[k] for k in ("kind", "at_utc", "at_us", "ordinal", "key")})
        return ev

    def has(self, kind: str, key) -> bool:
        return any(e[4]["kind"] == kind and e[4]["key"] == key for e in self._heap)

    def pending(self) -> list:
        return [e[4] for e in sorted(self._heap)]

    def next_instant(self) -> float | None:
        return I.from_micros(self._heap[0][0]) if self._heap else None

    def pop_due(self) -> list:
        """Every event due at or before the current instant, in the total order. Draining is deliberate: a handler may
        schedule another event at the same instant, and the caller re-drains before it is allowed to advance."""
        now_us = self.clock.now_us()
        out = []
        while self._heap and self._heap[0][0] <= now_us:
            ev = heapq.heappop(self._heap)[4]
            self.processed.append({k: ev[k] for k in ("kind", "at_utc", "at_us", "ordinal", "key")})
            out.append(ev)
        return out


# ---------------------------------------------------------------------------- the runner


class LifecycleRunner:
    """The operating loop. Production and recorded-data runs differ ONLY in which clock and which sources they are
    handed; the ordering, the deadline discipline and the persisted records are the same code."""

    def __init__(self, *, boundary: B.Boundary, sources: dict, clock: MonotonicClock, symbols: list,
                 selection_policy: str, scan_epochs: list | None = None, scan_interval_s: float | None = None,
                 n_scans: int | None = None, close_at: float | None = None, data_available_epochs: list | None = None,
                 event_budget: int = DEFAULT_EVENT_BUDGET, on_event=None, observation_feed=None):
        if getattr(boundary.clock, "_now", None) != clock.now:      # bound methods compare equal on (func, instance)
            raise LifecycleRefused("CLOCK_NOT_SHARED: the boundary must read the lifecycle clock, or two clocks would "
                                   "disagree about now")
        # REFUSE AT CONSTRUCTION, not at the first exit. A caller that omits a source the loop needs must find out
        # immediately, not hours into a run when an obligation first falls due.
        missing = [k for k in ("forecast_fn", "signal_fn", "chain_fn", "spot_fn", "quote_fn", "exit_quote_fn")
                   if sources.get(k) is None]
        if missing:
            raise LifecycleRefused("SOURCES_INCOMPLETE: the loop needs %s; exit_quote_fn in particular is only used "
                                   "when an obligation falls due, so its absence would surface as a crash mid-run"
                                   % ", ".join(missing))
        self.bd = boundary
        self.src = dict(sources)
        self.clock = clock
        self.sched = Scheduler(clock)
        self.symbols = list(symbols)
        self.policy = selection_policy
        self.close_at = close_at
        self.budget = int(event_budget)
        self.on_event = on_event
        self.trace: list = []
        self._exit_entries: dict = {}
        self._settled: set = set()            # positions this run will not schedule again (attempted or exhausted)
        # EXIT-SCHEDULING-002. `observation_feed` yields (available_epoch, observation) pairs; each observation is
        # {"contract_id", "observation_id", ...}. It supplies WHEN a new observation for a contract becomes visible.
        # It never supplies the quote itself: the boundary still asks exit_quote_fn and rechecks everything.
        self.observation_feed = list(observation_feed or [])
        self._attempted_observations: dict = {}   # fill_seq -> set of observation ids already attempted
        self._arrival_triggers: dict = {}         # fill_seq -> count, bounded by the policy
        self._latest_observation: dict = {}       # contract_id -> the newest observation id made visible so far
        self.scheduling_events: list = []         # decisions NOT to attempt; never counted as attempts
        self.recovered_seqs: set = set()      # positions inherited from an earlier process, filled in by run()
        self.report: dict = {"ordering_policy": ORDERING_POLICY, "clock_kind": clock.KIND, "events": [],
                             "decisions": [], "exits": [], "expiries": [], "resumed": [], "data_available": [],
                             "clock_advances": clock.advances}
        if scan_epochs is None:
            if scan_interval_s is None or n_scans is None:
                raise LifecycleRefused("SCAN_SCHEDULE_MISSING: supply scan_epochs, or scan_interval_s with n_scans")
            t0 = clock.now()
            scan_epochs = [t0 + i * float(scan_interval_s) for i in range(int(n_scans))]
        self.scan_epochs = [I.canonical_epoch(t, field="scan") for t in scan_epochs]
        self.data_epochs = [I.canonical_epoch(t, field="data") for t in (data_available_epochs or [])]

    # ------------------------------------------------------------ helpers

    def _note(self, fill_seq, reason: str, **extra) -> dict:
        """A SCHEDULING event: a decision not to ask the boundary. Never an attempt, in either direction."""
        row = {"fill_seq": fill_seq, "reason": reason, "at_utc": I.canonical_utc(self.clock.now()),
               "policy_version": getattr(self.bd.exit_policy, "policy_id", None),
               "is_attempt": False, **extra}
        self.scheduling_events.append(row)
        return row

    def _emit(self, ev: dict, outcome: dict) -> None:
        row = {"kind": ev["kind"], "at_utc": ev["at_utc"], "at_us": ev["at_us"], "ordinal": ev["ordinal"],
               "key": ev["key"], "outcome": outcome}
        self.trace.append(row)
        self.report["events"].append(row)
        if self.on_event is not None:
            self.on_event(row)

    def _rows(self) -> list:
        return L.read_all(self.bd.ledger)

    def _positions(self) -> list:
        return S.recover_positions(self.bd)["own"]

    def _exit_schedule(self, pos: dict, rows: list | None = None) -> dict:
        rows = self._rows() if rows is None else rows
        fl = rows[pos["seq"] - 1]
        return self.bd.exit_policy.schedule(fl["committed_epoch"])

    def _reconcile(self) -> None:
        """RE-CHECK DEADLINES. Called after every handler, and after anything that advanced time. Every obligation on
        disk gets an event; one whose deadline has already passed is scheduled at the CURRENT instant, never earlier."""
        rows = self._rows()
        for pos in self._positions():
            key = pos["seq"]
            if key in self._settled:
                continue                      # an explicit unresolved obligation; re-scheduling it would never end
            if self.sched.has(EXIT_DUE, key) or self.sched.has(EXIT_RETRY, key) or self.sched.has(EXIT_WINDOW_CLOSE, key):
                continue
            sch = self._exit_schedule(pos, rows)
            if key not in self.recovered_seqs and \
                    any(x.get("kind") == "pilot_exit_exhausted" and (x.get("fill_ref") or {}).get("seq") == key for x in rows):
                continue      # already terminal for the run that opened it. A RECOVERY run still owes it one labelled
                              # attempt, so an inherited exhausted position is NOT skipped here.
            when, kind = sch["exit_due_epoch"], EXIT_DUE
            if I.is_after(self.clock.now(), sch["window_close_epoch"]):
                when, kind = self.clock.now(), EXIT_WINDOW_CLOSE
            self.sched.at(when, kind, {"fill_seq": key}, key=key, allow_past=True)
        for seq, rec in S.unfilled_intents(self.bd.ledger, rows=rows):
            if rec.get("session_id") != self.bd.session_id or self.sched.has(INTENT_EXPIRY, seq):
                continue
            self.sched.at(rec.get("expiry_epoch") or (rec.get("created_epoch", self.clock.now()) + INTENT_TTL_S),
                          INTENT_EXPIRY, {"intent_seq": seq}, key=seq, allow_past=True)

    # ------------------------------------------------------------ handlers

    def _on_data_available(self, ev: dict) -> dict:
        """An input becomes visible. It admits no risk by itself; it exists so a recorded run cannot see a datum
        before its recorded availability and so a production run has an explicit place to notice one."""
        out = {"visible_from_utc": ev["at_utc"], "note": "input visibility only; no risk admitted"}
        self.report["data_available"].append(out)
        return out

    def _on_intent_expiry(self, ev: dict) -> dict:
        acts = S.resume(self.bd, quote_fn=self.src["quote_fn"])
        self.report["expiries"].extend(acts)
        return {"resume_actions": [{k: a.get(k) for k in ("seq", "intent_id", "action", "why")} for a in acts]}

    def _recovery_attempt(self, pos: dict, entry: dict, pol) -> dict:
        """ONE labelled attempt on an inherited position, exactly as the recovery contract requires."""
        if entry["final"] is not None:
            self._settled.add(pos["seq"])
            return {"state": entry["final"], "fill_seq": pos["seq"], "recovery": True, "already_attempted": True}
        rows = self._rows()
        committed = rows[pos["seq"] - 1]["committed_epoch"]
        n_att = len(B.Boundary.valuation_attempts(rows, pos["seq"]))
        if pol.status(now=self.clock.now(), committed_epoch=committed, attempts=n_att) == "NOT_DUE":
            due = pol.schedule(committed)["exit_due_epoch"]
            if I.is_after(due, self.clock.now()):
                self.sched.at(due, EXIT_DUE, {"fill_seq": pos["seq"]}, key=pos["seq"])
                return {"state": "NOT_DUE", "fill_seq": pos["seq"], "recovery": True}
        try:
            o = self.bd.record_outcome(fill_receipt=pos, exit_quote_fn=self.src["exit_quote_fn"], recovery=True)
        except B.BoundaryRefused as e:
            entry["final"] = "REFUSED"
            entry["attempts"].append({"refused": str(e)[:160]})
            self._settled.add(pos["seq"])
            return {"state": "REFUSED", "fill_seq": pos["seq"], "recovery": True, "why": str(e)[:200]}
        entry["attempts"].append({"seq": o["seq"], "status": o["status"], "attempt": o.get("attempt"),
                                  "reconciled": o.get("reconciled", False)})
        entry["final"] = o["status"] if o.get("discharges_position") else "UNRESOLVED_AFTER_RECOVERY_ATTEMPT"
        self._settled.add(pos["seq"])
        return {"state": entry["final"], "fill_seq": pos["seq"], "recovery": True, "outcome_seq": o["seq"],
                "status": o.get("status"),
                "capacity_released": bool(o.get("discharges_position")),
                "note": ("one labelled recovery attempt for an inherited position; it remains an explicit outstanding "
                         "obligation unless that attempt discharged it")}

    def _schedule_exit(self, when, kind: str, fill_seq: int) -> bool:
        """At most ONE pending exit event per position. Two chains for one fill (a timer chain and an arrival chain)
        would double every attempt, which is how the budget was silently consumed before this guard existed."""
        for k in (EXIT_DUE, EXIT_ARRIVAL, EXIT_RETRY, EXIT_WINDOW_CLOSE):
            if self.sched.has(k, fill_seq):
                self._note(fill_seq, "EXIT_EVENT_ALREADY_PENDING", pending=k, would_have_scheduled=kind)
                return False
        self.sched.at(when, kind, {"fill_seq": fill_seq}, key=fill_seq)
        return True

    def _next_attempt_epoch(self, spacing_s: float) -> float:
        """The next retry instant, guaranteed to be a LATER canonical instant than now, so a zero or sub-microsecond
        spacing can never schedule an event that is already due and spin the loop."""
        now = self.clock.now()
        nxt = now + max(0.0, float(spacing_s))
        if not I.is_after(nxt, now):
            nxt = I.from_micros(I.canonical_micros(now) + 1)
        return nxt

    def _entry(self, fill_seq: int) -> dict:
        """The per-POSITION record of what this run did about one obligation: one entry, however many attempts."""
        return self._exit_entries.setdefault(fill_seq, {
            "fill_seq": fill_seq, "recovery": fill_seq in self.recovered_seqs, "final": None, "attempts": []})

    def _service_exit(self, fill_seq: int, ev_kind: str) -> dict:
        """ONE exit attempt, driven by the frozen exit policy through the REAL boundary. One event, one attempt: the
        loop, not a nested wait, decides when the next attempt happens.

        A RECOVERED position -- one this run inherited from an earlier process rather than opened itself -- gets
        exactly ONE labelled recovery attempt and is then left as an explicit outstanding obligation. It does not get
        to consume the frozen policy's attempt budget, which belongs to the run that opened the position."""
        pol = self.bd.exit_policy
        recovery = fill_seq in self.recovered_seqs
        entry = self._entry(fill_seq)
        # THE ONE JUDGEMENT CALL, declared in the policy: a TIMER retry is not fired when the newest visible
        # observation is one an earlier attempt already rejected. The boundary is never asked, so no attempt is
        # created, consumed or renamed. It is recorded as a scheduling event with its reason.
        if (ev_kind in (EXIT_RETRY, EXIT_WINDOW_CLOSE)
                and getattr(pol, "skip_timer_when_no_new_observation", False)
                and self._attempted_observations.get(fill_seq)):
            rows0 = self._rows()
            cid = rows0[fill_seq - 1].get("contract_id")
            newest = self._latest_observation.get(cid)
            if newest is not None and newest in self._attempted_observations[fill_seq]:
                sch0 = pol.schedule(rows0[fill_seq - 1]["committed_epoch"])
                note = self._note(fill_seq, "TIMER_SKIPPED_NO_NEW_OBSERVATION", observation_id=newest,
                                  trigger=ev_kind,
                                  attempts_used=len(B.Boundary.valuation_attempts(rows0, fill_seq)))
                if ev_kind == EXIT_WINDOW_CLOSE:
                    # the last chance has arrived and there is still nothing new to value against: go terminal
                    # rather than spend the remaining budget re-reading the same observation
                    pos0 = next((p for p in self._positions() if p["seq"] == fill_seq), None)
                    self._settled.add(fill_seq)
                    if pos0 is not None and not any(x.get("kind") == "pilot_exit_exhausted"
                                                    and (x.get("fill_ref") or {}).get("seq") == fill_seq
                                                    for x in rows0):
                        self.bd.record_exit_exhausted(pos0)
                    entry["final"] = "EXIT_EXHAUSTED_UNRESOLVED"
                    return {"state": "EXIT_EXHAUSTED_UNRESOLVED", "fill_seq": fill_seq, **note}
                nxt0 = self._next_attempt_epoch(pol.retry_spacing_s)
                if I.is_after(nxt0, sch0["window_close_epoch"]):
                    self._schedule_exit(sch0["window_close_epoch"], EXIT_WINDOW_CLOSE, fill_seq)
                else:
                    self._schedule_exit(nxt0, EXIT_RETRY, fill_seq)
                return {"state": "TIMER_SKIPPED_NO_NEW_OBSERVATION", "fill_seq": fill_seq, **note}
        pos = next((p for p in self._positions() if p["seq"] == fill_seq), None)
        if pos is None:
            return {"state": entry["final"] or "ALREADY_RESOLVED", "fill_seq": fill_seq}
        if recovery:
            return self._recovery_attempt(pos, entry, pol)
        rows = self._rows()
        committed = rows[fill_seq - 1]["committed_epoch"]
        sch = pol.schedule(committed)
        n_att = len(B.Boundary.valuation_attempts(rows, fill_seq))
        status = pol.status(now=self.clock.now(), committed_epoch=committed, attempts=n_att)
        if status == "NOT_DUE":
            # The policy compares raw floats; the loop compares CANONICAL instants. When the two disagree by less than
            # one microsecond the deadline HAS arrived at the declared precision, and rescheduling would put the same
            # event back at the same canonical instant forever.
            if I.is_after(sch["exit_due_epoch"], self.clock.now()):
                self._schedule_exit(sch["exit_due_epoch"], EXIT_DUE, fill_seq)
                return {"state": "NOT_DUE", "fill_seq": fill_seq, "due_utc": I.canonical_utc(sch["exit_due_epoch"]),
                        "note": "the deadline had not arrived; rescheduled at it, not waited for here"}
            status = "DUE"
        if status == "EXHAUSTED":
            self._settled.add(fill_seq)
            if any(x.get("kind") == "pilot_exit_exhausted" and (x.get("fill_ref") or {}).get("seq") == fill_seq for x in rows):
                return {"state": "EXIT_EXHAUSTED_UNRESOLVED", "fill_seq": fill_seq, "already_recorded": True}
            self.bd.record_exit_exhausted(pos)
            entry["final"] = "EXIT_EXHAUSTED_UNRESOLVED"
            return {"state": "EXIT_EXHAUSTED_UNRESOLVED", "fill_seq": fill_seq, "n_attempts": n_att,
                    "note": "an explicit, persisted, unresolved obligation; it does not disappear from the accounting"}
        try:
            o = self.bd.record_outcome(fill_receipt=pos, exit_quote_fn=self.src["exit_quote_fn"], recovery=False)
        except B.BoundaryRefused as e:
            nxt = self._next_attempt_epoch(pol.retry_spacing_s)
            state = "REFUSED_RETRY_SCHEDULED"
            if I.is_after(nxt, sch["window_close_epoch"]):
                self._schedule_exit(sch["window_close_epoch"], EXIT_WINDOW_CLOSE, fill_seq)
                state = "REFUSED_WINDOW_CLOSE_SCHEDULED"
            else:
                self._schedule_exit(nxt, EXIT_RETRY, fill_seq)
            entry["attempts"].append({"refused": str(e)[:160]})
            entry["final"] = state
            return {"state": state, "fill_seq": fill_seq, "why": str(e)[:200]}
        entry["attempts"].append({"seq": o["seq"], "status": o["status"], "attempt": o.get("attempt"),
                                  "reconciled": o.get("reconciled", False), "trigger": ev_kind,
                                  "policy_version": getattr(pol, "policy_id", None),
                                  "why": (o.get("why") or "")[:120],
                                  "remaining_window_s": round(sch["window_close_epoch"] - self.clock.now(), 3)})
        if o.get("discharges_position"):
            entry["final"] = o["status"]
            # a resolved position cancels its pending timers: they are reconciled, not left to fire
            self._settled.add(fill_seq)
            self._note(fill_seq, "PENDING_RETRY_CANCELLED_POSITION_RESOLVED", resolved_by=ev_kind)
            return {"state": o["status"], "fill_seq": fill_seq, "outcome_seq": o["seq"], "attempt": o.get("attempt"),
                    "capacity_released": True}
        # a valuation attempt that did not discharge: the quote was unavailable. Retry ON A SCHEDULE, never by
        # rewinding or by busy-waiting, and let the window close the obligation if the retries run out.
        nxt = self._next_attempt_epoch(pol.retry_spacing_s)
        if I.is_after(nxt, sch["window_close_epoch"]):
            self._schedule_exit(sch["window_close_epoch"], EXIT_WINDOW_CLOSE, fill_seq)
            state = "UNRESOLVED_WINDOW_CLOSE_SCHEDULED"
        else:
            self._schedule_exit(nxt, EXIT_RETRY, fill_seq)
            state = "UNRESOLVED_RETRY_SCHEDULED"
        entry["final"] = state
        return {"state": state, "fill_seq": fill_seq, "outcome_seq": o["seq"], "status": o.get("status"),
                "attempt": o.get("attempt"), "why": (o.get("why") or "")[:160],
                "next_attempt_utc": I.canonical_utc(min(nxt, sch["window_close_epoch"]))}

    def _on_exit_arrival(self, ev: dict) -> dict:
        """A NEW observation for a contract became visible. If a position on that contract is due and inside its
        window, attempt now instead of waiting for the timer.

        THE ARRIVAL IS NOT THE QUOTE. This only decides WHEN to ask; the boundary then fetches the exit quote and
        rechecks provider timestamp, receipt, contract identity, sides and prices exactly as it always did. An
        arrival-triggered attempt fails on staleness like any other when the snapshot carries an old quote."""
        pol = self.bd.exit_policy
        obs_id, contract_id = ev["payload"].get("observation_id"), ev["payload"].get("contract_id")
        self._latest_observation[contract_id] = obs_id
        if not getattr(pol, "arrival_triggered", False):
            return self._note(None, "ARRIVAL_TRIGGER_NOT_ENABLED_BY_POLICY", observation_id=obs_id)
        acted = []
        for pos in self._positions():
            fs = pos["seq"]
            rows = self._rows()
            if rows[fs - 1].get("contract_id") != contract_id or fs in self._settled:
                continue
            n = self._arrival_triggers.get(fs, 0)
            if n >= getattr(pol, "max_arrival_triggers", 64):
                acted.append(self._note(fs, "ARRIVAL_TRIGGER_BUDGET_REACHED", observation_id=obs_id, triggers=n))
                continue
            if obs_id in self._attempted_observations.get(fs, set()):
                acted.append(self._note(fs, "DUPLICATE_OBSERVATION_ALREADY_ATTEMPTED", observation_id=obs_id))
                continue
            committed = rows[fs - 1]["committed_epoch"]
            att = len(B.Boundary.valuation_attempts(rows, fs))
            if not pol.may_attempt_on_arrival(now=self.clock.now(), committed_epoch=committed, attempts=att):
                acted.append(self._note(fs, "ARRIVAL_BUT_NOT_DUE_OR_NO_BUDGET", observation_id=obs_id,
                                        status=pol.status(now=self.clock.now(), committed_epoch=committed,
                                                          attempts=att)))
                continue
            self._arrival_triggers[fs] = n + 1
            self._attempted_observations.setdefault(fs, set()).add(obs_id)
            out = self._service_exit(fs, EXIT_ARRIVAL)
            out.update(trigger="OBSERVATION_ARRIVAL", observation_id=obs_id,
                       remaining_window_s=round(pol.schedule(committed)["window_close_epoch"] - self.clock.now(), 3))
            self.report["exits"].append({"event": EXIT_ARRIVAL, "at_utc": ev["at_utc"], **out})
            acted.append(out)
        return {"observation_id": obs_id, "contract_id": contract_id, "acted": acted or "NO_DUE_POSITION"}

    def _on_exit(self, ev: dict) -> dict:
        out = self._service_exit(ev["payload"]["fill_seq"], ev["kind"])
        self.report["exits"].append({"event": ev["kind"], "at_utc": ev["at_utc"], **out})
        return out

    def _on_scan(self, ev: dict) -> dict:
        sym = ev["payload"]["symbol"]
        seq = S.next_seq(self.bd.ledger, session_id=self.bd.session_id)
        d = S.scan(self.bd, symbol=sym, seq=seq, forecast_fn=self.src["forecast_fn"], signal_fn=self.src["signal_fn"],
                   chain_fn=self.src["chain_fn"], spot_fn=self.src["spot_fn"], quote_fn=self.src["quote_fn"],
                   funnel_fn=self.src.get("funnel_fn"), selection_policy=self.policy,
                   event_context_fn=self.src.get("event_context_fn"))
        row = {k: d.get(k) for k in ("scan_id", "symbol", "decision", "why", "forecast_id", "intent_id", "fill_id",
                                     "decision_persisted", "refusal_persisted")}
        row["at_utc"] = ev["at_utc"]
        self.report["decisions"].append(row)
        if d["decision"] == "TRADE" and d.get("receipts", {}).get("fill"):
            fr = d["receipts"]["fill"]
            rows = self._rows()
            sch = self.bd.exit_policy.schedule(rows[fr["seq"] - 1]["committed_epoch"])
            self.sched.at(sch["exit_due_epoch"], EXIT_DUE, {"fill_seq": fr["seq"]}, key=fr["seq"])
            row["exit_due_utc"] = I.canonical_utc(sch["exit_due_epoch"])
        return row

    def _on_session_close(self, ev: dict) -> dict:
        receipt = S.close_session(self.bd)
        rec = self._rows()[receipt["seq"] - 1]
        self.report["session_close"] = receipt
        self.report["completion"] = rec.get("completion")
        self.report["outstanding_obligations"] = rec.get("outstanding_obligations")
        return {"completion": rec.get("completion"), "outstanding": rec.get("outstanding_obligations")}

    HANDLERS = {DATA_AVAILABLE: _on_data_available, INTENT_EXPIRY: _on_intent_expiry, EXIT_DUE: _on_exit,
                EXIT_ARRIVAL: _on_exit_arrival, EXIT_RETRY: _on_exit, EXIT_WINDOW_CLOSE: _on_exit, SCAN: _on_scan,
                SESSION_CLOSE: _on_session_close}

    # ------------------------------------------------------------ the loop

    def run(self) -> dict:
        self.report["session_open"] = S.open_session(self.bd, symbols=self.symbols)
        # a restart picks up whatever the previous process left: unfinished intents first, then every obligation
        self.report["resumed"] = S.resume(self.bd, quote_fn=self.src["quote_fn"])
        recovered = S.recover_positions(self.bd)
        # AN INHERITED OBLIGATION IS NOT THIS RUN'S TO RE-DRIVE. It gets one labelled recovery attempt; the frozen
        # policy's attempt budget belongs to the run that opened the position.
        self.recovered_seqs = {r["seq"] for r in recovered["own"]}
        self.report["recovered_positions"] = [{k: r.get(k) for k in ("seq", "intent_id", "scan_id", "fill_id",
                                                                      "contract_id", "valuation_attempts",
                                                                      "last_attempt_why")} for r in recovered["own"]]
        self.report["foreign_unresolved_positions"] = recovered["foreign"]
        for t in self.data_epochs:
            self.sched.at(t, DATA_AVAILABLE, {}, key=("data", t), allow_past=True)
        # EXIT-SCHEDULING-002: an observation becomes VISIBLE at its recorded availability, never before. Replay and
        # production schedule these identically; nothing looks ahead to pick an advantageous instant.
        seen = set()
        for available, obs in self.observation_feed:
            oid = obs.get("observation_id")
            if oid in seen:
                self._note(None, "DUPLICATE_OBSERVATION_IN_FEED", observation_id=oid)
                continue
            seen.add(oid)
            self.sched.at(available, EXIT_ARRIVAL, dict(obs), key=("obs", oid), allow_past=True)
        for t in self.scan_epochs:
            for sym in self.symbols:
                self.sched.at(t, SCAN, {"symbol": sym}, key=(sym, t), allow_past=True)
        if self.close_at is not None:
            self.sched.at(self.close_at, SESSION_CLOSE, {}, key="close", allow_past=True)
        self._reconcile()
        n = 0
        while True:
            due = self.sched.pop_due()
            if due:
                for ev in due:
                    n += 1
                    if n > self.budget:
                        raise LifecycleRefused("LIFECYCLE_EVENT_BUDGET_EXCEEDED: %d events; the loop is not converging"
                                               % self.budget)
                    handler = self.HANDLERS[ev["kind"]]
                    outcome = handler(self, ev)
                    self._emit(ev, outcome)
                    self._reconcile()                    # RE-CHECK after every operation, before any advance
                continue                                 # drain again at this instant before time may move
            nxt = self.sched.next_instant()
            if nxt is None:
                break
            self.clock.advance_to(nxt, why="next scheduled event")   # advance ONLY to the next relevant event
            self._reconcile()
        if self.close_at is None and "session_close" not in self.report:
            self._on_session_close({"kind": SESSION_CLOSE, "at_utc": I.canonical_utc(self.clock.now()),
                                    "at_us": self.clock.now_us(), "ordinal": -1, "key": "close", "payload": {}})
        self.report["exit_entries"] = [self._exit_entries[k] for k in sorted(self._exit_entries)]
        self.report["scheduling_events"] = list(self.scheduling_events)
        self.report["exit_policy"] = self.bd.exit_policy.describe()
        self.report["attempt_accounting"] = EP.ATTEMPT_ACCOUNTING
        self.report["n_events"] = n
        self.report["final_clock_utc"] = I.canonical_utc(self.clock.now())
        self.report["book"] = self.bd.book().summary()
        still = S.recover_positions(self.bd)
        self.report["unresolved_positions"] = [{k: r.get(k) for k in ("seq", "intent_id", "scan_id", "fill_id",
                                                                       "contract_id", "valuation_attempts",
                                                                       "last_attempt_why")} for r in still["own"]]
        return self.report


def event_trace(report: dict) -> list:
    """The ordered event trace, for a reviewer: what happened, at which instant, in which order."""
    return [{"n": i + 1, "at_utc": e["at_utc"], "kind": e["kind"], "key": e["key"], "outcome": e["outcome"]}
            for i, e in enumerate(report.get("events", []))]
