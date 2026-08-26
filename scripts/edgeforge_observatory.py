"""EDGEFORGE OBSERVATORY — the always-on research sidecar.

The process that did not exist on 2026-08-25, which is why that
session produced zero prospective research evidence and why
gate_separation_v1 still stands at zero sessions.

    V1 -> durable outbox -> THIS -> EdgeForge research ledgers

It is supervised and always up. Outside market hours it idles. During
a session it drains sealed V1 observations from the durable outbox,
advancing a checkpointed cursor, so an outage costs latency and never
a research day.

DIRECTION IS ABSOLUTE: it reads the outbox and writes research
ledgers. There is no code path from here back into V1, and the
non-interference test proves it.

At post-close it answers the one question Program #001 needs:
QUALIFYING_SESSION = YES/NO, and why. No more assuming the
instrumentation ran.

decision_power: NONE_RESEARCH.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.governance.chain_ledger import chain_append          # noqa: E402
from apex.ops import heartbeat as hb                           # noqa: E402
from apex.ops.orchestrator import phase_at                     # noqa: E402
from apex.ops.outbox import (Cursor, consume, consumer_health)  # noqa: E402

OUTBOX = Path("results/edgeforge/v1_outbox.jsonl")
CURSOR = Path("results/edgeforge/observatory_cursor.json")
RESEARCH = Path("results/edgeforge/observatory_ledger.jsonl")
QUALIFY = Path("results/edgeforge/qualifying_sessions.jsonl")
TICK_S = 30

# gate_separation_v1 cannot begin until EVERY prospectively estimable
# boundary dimension is genuinely recorded. Assuming they were is what
# produced a Monday BoundaryMap of MEASUREMENT_GAP and a Tuesday of
# nothing at all.
REQUIRED_BOUNDARY_DIMS = ("extension_atr", "invalidation_distance_atr",
                          "range_position", "vwap_distance_atr", "atr",
                          "volume_participation")


def session_now() -> str:
    return f"{datetime.now(ZoneInfo('America/New_York')):%Y-%m-%d}"


def handle(record: dict) -> int:
    """Copy one sealed V1 observation into the research ledger.

    Pure transcription plus lineage. NOTHING is inferred: a field V1
    never recorded stays absent, because a fabricated dimension would
    corrupt the very measurement this sidecar exists to collect."""
    out = {"kind": "observatory_record",
           "record_kind": record.get("record_kind"),
           "session": record.get("session"),
           "source": record.get("source"),
           "known_from": record.get("known_from"),
           "source_seq": record.get("_seq"),
           "source_hash": record.get("entry_hash"),
           "payload": record.get("payload"),
           "consumed_utc": datetime.now(timezone.utc).isoformat(),
           "evidence_class": "PROSPECTIVE_LIVE_CAPTURE",
           "decision_power": "NONE_RESEARCH"}
    chain_append(RESEARCH, out)
    return 1


def qualifying_session(session: str) -> dict:
    """Did TODAY produce a qualifying session for gate_separation_v1?

    Answered from what was actually recorded, never from whether the
    market was open."""
    rows = []
    if RESEARCH.exists():
        for line in RESEARCH.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "observatory_record" and \
                    r.get("session") == session:
                rows.append(r)
    maps = [r for r in rows
            if r.get("record_kind") == "decision_boundary_map"]
    dims_present = set()
    for m in maps:
        dims_present |= {k for k, v in (m.get("payload") or {}).items()
                         if v is not None and v != "NOT_ESTIMABLE"}
    missing = [d for d in REQUIRED_BOUNDARY_DIMS
               if d not in dims_present]
    qualifies = bool(maps) and not missing
    rec = {"kind": "qualifying_session_report", "session": session,
           "QUALIFYING_SESSION": "YES" if qualifies else "NO",
           "observations_consumed": len(rows),
           "boundary_maps": len(maps),
           "dimensions_recorded": sorted(dims_present),
           "dimensions_missing": missing,
           "why": ("all required boundary dimensions recorded"
                   if qualifies else
                   "no boundary maps were emitted by V1" if not maps
                   else f"missing dimensions {missing}"),
           "program": "gate_separation_v1",
           "law": "no more assuming the instrumentation ran",
           "decision_power": "NONE_RESEARCH"}
    chain_append(QUALIFY, rec)
    return rec


def tick(beat: hb.Heartbeat) -> dict:
    session = session_now()
    ph = phase_at(datetime.now(timezone.utc), session)
    cur = Cursor(path=CURSOR, consumer="edgeforge-observatory")
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    drain = consume(OUTBOX, cur, handle, max_records=500)
    health = consumer_health(OUTBOX, cur,
                             session_active=(ph["phase"] == "RTH"))
    beat.work(f"{ph['phase']} drained={drain['records_processed']}",
              backlog=health["consumer_lag"])
    return {"phase": ph["phase"], "session": session,
            "drained": drain["records_processed"],
            "lag": health["consumer_lag"], "state": health["state"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--follow", action="store_true")
    ap.add_argument("--qualify", action="store_true",
                    help="emit the qualifying-session report and exit")
    a = ap.parse_args()
    beat = hb.Heartbeat(service="edgeforge-observatory")
    if a.qualify:
        print(json.dumps(qualifying_session(session_now()), indent=1))
        return 0
    if not a.follow:
        print(json.dumps(tick(beat), indent=1))
        return 0
    last_qualified = None
    while True:
        try:
            r = tick(beat)
            # one qualifying report per session, at post-close
            if r["phase"] == "POST_CLOSE" and \
                    last_qualified != r["session"]:
                qualifying_session(r["session"])
                last_qualified = r["session"]
        except Exception as e:                           # noqa: BLE001
            beat.error(repr(e))
        time.sleep(TICK_S)


if __name__ == "__main__":
    raise SystemExit(main())
