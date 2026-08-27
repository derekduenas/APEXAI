"""CATALYST SERVICE — the thing that actually wakes up and looks.

    07:00 ET  OVERNIGHT_SCAN     what changed while we were shut
    08:20 ET  MACRO_UPDATE       today's scheduled risk
    09:20 ET  PRE_BELL_BRIEF     sealed before the bell
    RTH       INTRADAY_WATCH     cheap detection, rare interpretation
    16:05 ET  POST_CLOSE_SEAL    what actually moved the tape

A class that could run is not a service. This is the difference, and it
is the entire reason this file exists.

RUNS ON DIGITALOCEAN. Mac runtime authority is NONE; this is started by
systemd in apex-background.slice, so a catalyst cycle yields CPU and
memory to market-critical work rather than competing with it.

THE HEARTBEAT MEASURES WORK, NOT PRESENCE. A process that is alive
while retrieving nothing is a failure wearing a green light, which is
exactly how a daemon once died unnoticed for seven hours.

decision_power: SHADOW_CONTEXT_ONLY -- this service cannot start,
stop, delay, size or influence a single trade.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.catalyst.interpreter import ClaudeCliInterpreter  # noqa: E402
from apex.catalyst.pipeline import run_cycle  # noqa: E402
from apex.catalyst.premarket import phase_at  # noqa: E402
from apex.ops.heartbeat import Heartbeat  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402

POLL_IDLE_S = 300
SERVICE = "apex-catalyst"


def _now():
    return datetime.now(timezone.utc)


def release_sha() -> str:
    stamp = Path(os.environ.get("APEX_RELEASE_ROOT", "/opt/apex")) \
        / "current" / "RELEASE.json"
    try:
        return json.loads(stamp.read_text()).get("commit", "UNKNOWN")
    except (OSError, json.JSONDecodeError):
        return os.environ.get("APEX_RELEASE_SHA", "UNKNOWN")


def current_phase(now=None) -> dict:
    now = now or _now()
    # the ET calendar day, not the host's locale day
    from apex.ops.timebase import ET
    session = now.astimezone(ET).strftime("%Y-%m-%d")
    b = session_bounds(session)
    return phase_at(now, session, open_utc=b["open_utc"],
                    close_utc=b["close_utc"],
                    trading_day=b["trading_day"])


def do_cycle(phase: str, *, session: str, interpreter, beat=None,
             include_sec: bool = True) -> dict:
    rec = run_cycle(session=session, phase=phase,
                    release_sha=release_sha(),
                    interpreter=interpreter, include_sec=include_sec)
    if beat is not None:
        beat.work(
            f"{phase}: {rec['sources_succeeded']}/"
            f"{rec['sources_checked']} sources, "
            f"{rec['new_observations']} new observations, "
            f"{rec['new_events']} events",
            backlog=rec["sources_failed"])
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", metavar="PHASE",
                    help="run one cycle and exit (commissioning)")
    ap.add_argument("--session", default=None)
    ap.add_argument("--no-llm", action="store_true",
                    help="deterministic retrieval only")
    ap.add_argument("--no-sec", action="store_true")
    args = ap.parse_args()

    interp = None if args.no_llm else ClaudeCliInterpreter()
    if interp is not None:
        cap = interp.available()
        print(json.dumps(cap), flush=True)
        if not cap["available"]:
            # no brain on this host: retrieval still runs, and every
            # event will carry DETERMINISTIC_NO_LLM rather than a
            # quietly missing interpretation
            interp = None

    session = args.session or _now().strftime("%Y-%m-%d")

    if args.once:
        rec = do_cycle(args.once, session=session, interpreter=interp,
                       include_sec=not args.no_sec)
        rec.pop("events", None)
        print(json.dumps(rec, indent=1), flush=True)
        return 0

    beat = Heartbeat(SERVICE)
    last_phase, last_watch = None, 0.0
    while True:
        ph = current_phase()
        phase, session = ph["phase"], ph["session"]
        try:
            if phase in ("OVERNIGHT_SCAN", "MACRO_UPDATE",
                         "PRE_BELL_BRIEF", "POST_CLOSE_SEAL"):
                if phase != last_phase:          # once per phase
                    do_cycle(phase, session=session, interpreter=interp,
                             beat=beat)
                    last_phase = phase
            elif phase == "INTRADAY_WATCH":
                gap = ph.get("poll_seconds") or 210
                if time.time() - last_watch >= gap:
                    do_cycle(phase, session=session, interpreter=interp,
                             beat=beat)
                    last_watch = time.time()
            else:
                beat.beat()   # presence only; no work claimed
                last_phase = None
        except Exception as e:                       # noqa: BLE001
            # a catalyst failure must never become a market failure;
            # record it and keep the service breathing
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(30 if phase == "INTRADAY_WATCH" else POLL_IDLE_S)


if __name__ == "__main__":
    sys.exit(main())
