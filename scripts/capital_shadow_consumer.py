"""CAPITAL ARENA SHADOW CONSUMER — a sidecar, never a gate.

Drains the neutral V1 outbox and seals what a portfolio manager would
have done with each prospective candidate. V1 never waits for this
process, never reads its output, and never learns whether it is
running at all.

Deliberately a SEPARATE process from the options session. If the arena
were in-process it could slow an entry, and a shadow study that can
delay a real trade is not a shadow study.

decision_power: SHADOW_COUNTERFACTUAL_ONLY.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.capital import consumer  # noqa: E402
from apex.ops.heartbeat import Heartbeat  # noqa: E402
from apex.ops.timebase import ET  # noqa: E402

SERVICE = "capital-arena-shadow"
POLL_S = 60


def one_pass(session: str, beat=None) -> dict:
    out = consumer.run(session=session)
    if beat is not None:
        acts = [d["shadow_action"] for d in out["decisions"]]
        beat.work(
            f"drained={out['records_consumed']} judged={out['judged']}"
            + (f" actions={acts}" if acts else ""),
            backlog=len(out["errors"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--follow", action="store_true")
    args = ap.parse_args()

    session = datetime.now(timezone.utc).astimezone(ET).strftime("%Y-%m-%d")

    if args.once or not args.follow:
        out = one_pass(session)
        out.pop("decisions", None)
        print(json.dumps(out, indent=1), flush=True)
        return 0

    beat = Heartbeat(SERVICE)
    while True:
        session = datetime.now(timezone.utc).astimezone(ET) \
            .strftime("%Y-%m-%d")
        try:
            one_pass(session, beat)
        except Exception as e:                        # noqa: BLE001
            # the arena failing must never touch the incumbent
            beat.error(f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
