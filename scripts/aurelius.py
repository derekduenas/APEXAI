"""Talk to AURELIUS.

    aurelius                          interactive conversation
    aurelius ask "question"           one-shot
    aurelius ask --as-of "T" "q"      what was known AT T, nothing later
    aurelius track-record             every preserved forecast
    aurelius health                   transport + identity state

Low priority by design: the conversation niceness is set below every
market-critical process, and a busy or unauthenticated transport
degrades the CHAT, never the organism.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.catalyst.interpreter import InterpreterUnavailable  # noqa: E402
from apex.organism import aurelius  # noqa: E402


def _release() -> str:
    try:
        return json.loads(Path("/opt/apex/current/RELEASE.json")
                          .read_text()).get("commit", "UNKNOWN")[:12]
    except (OSError, json.JSONDecodeError):
        return "UNKNOWN"


def one(question: str, *, as_of=None, history=None) -> dict | None:
    try:
        rec = aurelius.ask(question, as_of=as_of, history=history,
                           release_sha=_release())
    except InterpreterUnavailable as e:
        print(f"\n[AURELIUS_LLM_STATE = DEGRADED] {e}\n"
              f"The organism is unaffected; only this conversation "
              f"is unavailable.", file=sys.stderr)
        return None
    print(rec["response"])
    if rec["forecasts"]:
        print(f"\n[{len(rec['forecasts'])} forecast(s) preserved to "
              f"the accountability record]")
    return rec


def main() -> int:
    os.nice(10)          # operator chat never outranks the market
    ap = argparse.ArgumentParser(prog="aurelius")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("ask")
    a.add_argument("--as-of", default=None)
    a.add_argument("question", nargs="+")
    sub.add_parser("track-record")
    sub.add_parser("health")
    args = ap.parse_args()

    if args.cmd == "health":
        print(json.dumps(aurelius.transport_health(), indent=1))
        return 0
    if args.cmd == "track-record":
        print(json.dumps(aurelius.track_record(), indent=1))
        return 0
    if args.cmd == "ask":
        rec = one(" ".join(args.question), as_of=args.as_of)
        return 0 if rec else 1

    # ---------------------------------------------------- interactive
    print(aurelius.BANNER)
    th = aurelius.transport_health()
    if th["state"] != "READY":
        print(f"\n[LLM_STATE = {th['state']}] the conversation needs "
              f"the authenticated claude CLI; the organism runs on "
              f"regardless.")
    print("\n(ctrl-d to leave; 'as of <T>: <question>' for "
          "AS_KNOWN_AT mode)\n")
    history = []
    while True:
        try:
            q = input("operator> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        as_of = None
        if q.lower().startswith("as of ") and ":" in q:
            head, q = q.split(":", 1)
            as_of = head[6:].strip()
            q = q.strip()
        rec = one(q, as_of=as_of, history=history)
        if rec:
            history.append({"q": q, "a": rec["response"]})
        print()


if __name__ == "__main__":
    sys.exit(main())
