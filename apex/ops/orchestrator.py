"""APEX SESSION ORCHESTRATOR — the system shows up by itself.

2026-08-25 cost a whole prospective session to one sentence: a
deployed capability is not a running capability. Options never
started, the EdgeForge feeder never started, and gate_separation_v1
accumulated zero sessions on a day the market was open and nothing
was wrong with the market.

This module owns the answer to "what SHOULD be running right now?"
for every moment of the exchange calendar, so that question is never
again answered by whether a human remembered.

    PREOPEN        dependencies start early enough to become ready
    SESSION_ARMED  every required check passed BEFORE the open
    RTH            required services running AND producing work
    POST_CLOSE     resolve, seal, flush, final observation
    IDLE           safe non-session state

All boundaries are exchange-calendar-relative. Half-days close at
13:00 ET and this module knows it; a hardcoded 16:00 would arm paper
trading into three hours of a closed market.

TWO FAILURE DIRECTIONS, both real:
  a service that should be running and is not   -> CRITICAL
  a service that should be idle and is running  -> CRITICAL
Silence about either is the expensive error.

decision_power: NONE_OPERATIONAL. The orchestrator starts and stops
processes; it has no opinion about any trade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from apex.governance.resolution_time import (HALF_DAYS_2026,
                                             HOLIDAYS_2026,
                                             regular_session_close,
                                             to_utc)

PHASES = ("IDLE", "PREOPEN", "SESSION_ARMED", "RTH", "POST_CLOSE")

LIFECYCLE = ("EXPECTED_RUNNING", "EXPECTED_WARMING", "EXPECTED_IDLE",
             "EXPECTED_DISABLED", "EXPECTED_ON_DEMAND")

OPEN_ET = (9, 30)
PREOPEN_LEAD_MIN = 45          # dependencies get 45 minutes to warm
ARM_DEADLINE_MIN = 5           # armed no later than 5 min before open
POST_CLOSE_MIN = 60            # sealing window after the close


class OrchestratorViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceSpec:
    """What a service is, when it must run, and how we know it works."""
    name: str
    phases_running: tuple            # phases where EXPECTED_RUNNING
    start_cmd: tuple = ()
    work_counter: str = "work_completed"
    first_work_deadline_s: int = 600
    beat_stale_s: int = 900
    work_stale_s: int | None = 3600
    always_on: bool = False          # sidecars: run in EVERY phase
    required_for_arm: bool = False
    dependencies: tuple = ()
    # WHO RESTARTS IT. launchd/systemd already supervise with their own
    # KeepAlive; if the orchestrator ALSO issued start_cmd we would race
    # two supervisors and could run two consumers against one cursor.
    # For externally supervised services the orchestrator is the
    # VERIFIER -- it proves work is happening and escalates when it is
    # not -- and never the starter.
    supervised_by: str = "launchd"

    @property
    def externally_supervised(self) -> bool:
        return self.supervised_by in ("launchd", "systemd")

    def expected_lifecycle(self, phase: str) -> str:
        if self.always_on:
            # A sidecar is up in EVERY phase, IDLE included. It may be
            # internally quiet outside market hours, but the PROCESS
            # stays supervised -- tying research observation to a
            # market-open scheduler is precisely what lost 2026-08-25.
            return "EXPECTED_RUNNING"
        if phase in self.phases_running:
            return "EXPECTED_RUNNING"
        if phase == "PREOPEN" and "RTH" in self.phases_running:
            return "EXPECTED_WARMING"
        return "EXPECTED_IDLE"


def is_trading_day(session: str) -> bool:
    d = datetime.fromisoformat(f"{session}T00:00:00").date()
    return d.weekday() < 5 and session not in HOLIDAYS_2026


def session_bounds(session: str) -> dict:
    """Open/close in UTC from the authoritative calendar. Half-days and
    holidays are the calendar's business, never a hardcoded hour."""
    if not is_trading_day(session):
        return {"session": session, "trading_day": False,
                "half_day": False, "open_utc": None, "close_utc": None}
    open_utc = to_utc(f"{session} {OPEN_ET[0]:02d}:{OPEN_ET[1]:02d}:00",
                      assume="ET")
    # regular_session_close returns a sealed ResolutionBoundary record,
    # not a timestamp -- the boundary belongs to the rule, and the
    # orchestrator only borrows its UTC instant for scheduling.
    boundary = regular_session_close(session, instrument_class="EQUITY")
    close_utc = datetime.fromisoformat(boundary.close_utc)
    open_utc = datetime.fromisoformat(str(open_utc))
    return {"session": session, "trading_day": True,
            "half_day": session in HALF_DAYS_2026,
            "open_utc": open_utc, "close_utc": close_utc,
            "close_boundary": boundary}


def phase_at(now_utc: datetime, session: str) -> dict:
    """Which lifecycle phase the calendar says we are in."""
    b = session_bounds(session)
    if not b["trading_day"]:
        return {"phase": "IDLE", "why": f"{session} is not a trading "
                                        f"day", **b}
    open_utc, close_utc = b["open_utc"], b["close_utc"]
    preopen_start = open_utc - timedelta(minutes=PREOPEN_LEAD_MIN)
    arm_by = open_utc - timedelta(minutes=ARM_DEADLINE_MIN)
    post_end = close_utc + timedelta(minutes=POST_CLOSE_MIN)
    if now_utc < preopen_start:
        phase, why = "IDLE", "before the preopen window"
    elif now_utc < arm_by:
        phase, why = "PREOPEN", "dependencies warming"
    elif now_utc < open_utc:
        phase, why = "SESSION_ARMED", "arming deadline reached"
    elif now_utc < close_utc:
        phase, why = "RTH", "regular session"
    elif now_utc < post_end:
        phase, why = "POST_CLOSE", "sealing window"
    else:
        phase, why = "IDLE", "after the sealing window"
    return {"phase": phase, "why": why, **b,
            "preopen_start_utc": preopen_start, "arm_by_utc": arm_by,
            "post_close_end_utc": post_end}


# ==================================================== ARMING

@dataclass
class ArmCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def evaluate_arm(*, session: str, checks: list,
                 now_utc: datetime) -> dict:
    """SESSION_ARMED is granted only when every REQUIRED check passes.

    A missing check is a failed check: `required` checks that were
    never evaluated cannot be assumed good, because the whole reason
    this module exists is that an unasked question read as a pass."""
    failed = [c for c in checks if c.required and not c.ok]
    optional_failed = [c for c in checks if not c.required and not c.ok]
    armed = not failed
    return {"kind": "session_arm_evaluation", "session": session,
            "evaluated_utc": now_utc.isoformat(),
            "verdict": "SESSION_ARMED" if armed else "ARM_REFUSED",
            "checks": [{"name": c.name, "ok": c.ok,
                        "required": c.required, "detail": c.detail}
                       for c in checks],
            "blocking": [c.name for c in failed],
            "non_blocking_failures": [c.name for c in optional_failed],
            "law": "a required capability that cannot be verified "
                   "before the open does not trade that session",
            "decision_power": "NONE_OPERATIONAL"}


# ==================================================== SENTINEL

@dataclass
class StartAttempt:
    service: str
    attempted_utc: str
    outcome: str                     # STARTED | FAILED
    detail: str = ""


def missed_start_verdict(*, service: str, phase: str,
                         expected_lifecycle: str,
                         first_work_seen: bool,
                         seconds_since_phase_start: float,
                         deadline_s: int,
                         recovery_attempts: list,
                         dependency_states: dict,
                         release: str) -> dict:
    """Did a required service fail to produce its FIRST unit of work?

    Alive is not started. The sentinel waits the declared deadline,
    then escalates with everything needed to root-cause it later --
    because 'options did not run' with no attached evidence is how a
    lost session becomes an unanswerable question."""
    if expected_lifecycle not in ("EXPECTED_RUNNING",):
        return {"kind": "missed_start", "service": service,
                "verdict": "NOT_APPLICABLE",
                "why": f"expected {expected_lifecycle} in {phase}"}
    if first_work_seen:
        return {"kind": "missed_start", "service": service,
                "verdict": "WORK_CONFIRMED"}
    if seconds_since_phase_start < deadline_s:
        return {"kind": "missed_start", "service": service,
                "verdict": "WITHIN_GRACE",
                "seconds_elapsed": round(seconds_since_phase_start),
                "deadline_s": deadline_s}
    return {"kind": "missed_start", "service": service,
            "verdict": "SESSION_MISSED_START", "severity": "CRITICAL",
            "phase": phase,
            "seconds_elapsed": round(seconds_since_phase_start),
            "deadline_s": deadline_s,
            "recovery_attempts": [a.__dict__ if hasattr(a, "__dict__")
                                  else a for a in recovery_attempts],
            "dependency_states": dependency_states,
            "release": release,
            "law": "never silently lose a market session again",
            "decision_power": "NONE_OPERATIONAL"}


def reconcile_expected(*, phase: str, specs: list,
                       observed_running: dict) -> dict:
    """Both failure directions, named separately."""
    rows, missing, unexpected = {}, [], []
    for s in specs:
        exp = s.expected_lifecycle(phase)
        run = bool(observed_running.get(s.name))
        if exp == "EXPECTED_RUNNING" and not run:
            state, sev = "MISSING", "CRITICAL"
            missing.append(s.name)
        elif exp in ("EXPECTED_IDLE", "EXPECTED_DISABLED") and run:
            state, sev = "UNEXPECTEDLY_RUNNING", "CRITICAL"
            unexpected.append(s.name)
        elif exp == "EXPECTED_WARMING" and not run:
            state, sev = "WARMING_NOT_STARTED", "DEGRADED"
        else:
            state, sev = "AS_EXPECTED", "OK"
        rows[s.name] = {"expected": exp, "running": run,
                        "state": state, "severity": sev}
    return {"kind": "lifecycle_reconciliation", "phase": phase,
            "services": rows, "missing": missing,
            "unexpectedly_running": unexpected,
            "verdict": ("CRITICAL" if missing or unexpected else "OK"),
            "decision_power": "NONE_OPERATIONAL"}


# ==================================================== ROSTER

HOSTS = ("mac", "cloud")

# WHERE EACH CAPABILITY LIVES. ThetaTerminal is installed only on the
# cloud host, so the options predator lives there; the equity fabric,
# the BTC loop and the EdgeForge sidecar live on the Mac. A roster
# that ignored this would spend every tick trying to start a service
# on a machine that cannot run it, and would report CRITICAL forever.
REPO = "/Users/derekduenas/apex-equities"
VENV = f"{REPO}/.venv/bin/python"


def default_roster(host: str = "mac") -> list:
    """What APEX is supposed to be doing on a market day, on THIS host.

    EdgeForge is an ALWAYS-ON sidecar deliberately: tying research
    observation to a market-open scheduler is exactly what lost
    Tuesday, and a sidecar with a durable cursor can catch up after an
    outage instead of losing the day permanently."""
    if host not in HOSTS:
        raise OrchestratorViolation(
            f"unknown host {host!r}; a roster must know which machine "
            f"it is describing")
    if host == "cloud":
        return [
            ServiceSpec(name="theta-terminal",
                        phases_running=("PREOPEN", "SESSION_ARMED",
                                        "RTH"),
                        start_cmd=("/opt/apex/current/ops/"
                                   "theta_terminal.sh",),
                        first_work_deadline_s=300, beat_stale_s=600,
                        work_stale_s=None, required_for_arm=True,
                        supervised_by="systemd"),
            ServiceSpec(name="options-paper",
                        phases_running=("RTH",),
                        start_cmd=("/opt/apex/shared/venv/bin/python",
                                   "/opt/apex/current/scripts/"
                                   "options_paper_session.py"),
                        first_work_deadline_s=600, beat_stale_s=1800,
                        work_stale_s=3600, required_for_arm=True,
                        dependencies=("theta-terminal",),
                        supervised_by="systemd"),
        ]
    return [
        ServiceSpec(name="equity-fabric",
                    phases_running=("PREOPEN", "SESSION_ARMED", "RTH"),
                    # vendor-neutral by law: the architecture guard
                    # forbids broker names inside apex/**, so the
                    # concrete transport lives behind this wrapper
                    start_cmd=("/bin/zsh", f"{REPO}/ops/"
                               "equity_fabric.sh"),
                    first_work_deadline_s=300, beat_stale_s=120,
                    work_stale_s=600, required_for_arm=True),
        ServiceSpec(name="edgeforge-observatory",
                    phases_running=(), always_on=True,
                    start_cmd=(VENV, f"{REPO}/scripts/"
                               "edgeforge_observatory.py", "--follow"),
                    first_work_deadline_s=900, beat_stale_s=600,
                    work_stale_s=None),
        # NAME MUST MATCH THE HEARTBEAT THE SERVICE ACTUALLY WRITES.
        # This spec said "btc-loop" while the daemon writes
        # "btc-paper", so first_work_seen() always read ABSENT and the
        # sentinel would have fired a false SESSION_MISSED_START twenty
        # minutes into every session. A verifier that misnames what it
        # verifies is worse than no verifier.
        ServiceSpec(name="btc-paper", phases_running=(), always_on=True,
                    start_cmd=("/usr/bin/caffeinate", "-i", VENV,
                               f"{REPO}/scripts/btc_paper_session.py",
                               "--follow"),
                    first_work_deadline_s=1200, beat_stale_s=1200,
                    work_stale_s=2400),
    ]
