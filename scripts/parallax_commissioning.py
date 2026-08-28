"""PARALLAX RETROSPECTIVE COMMISSIONING — machinery validation ONLY.

Runs the observatory against an already-resolved session's sealed
catalyst events and captured bars. Every output row carries
RETROSPECTIVE_PARALLAX_COMMISSIONING: it validates that the measurement
machinery works on real artifacts; it is NOT prospective evidence and
never enters an evidence count.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.catalyst.pipeline import (BARS_ROOT, _atr,  # noqa: E402
                                    _load_bars, eligible_events)
from apex.governance.chain_ledger import chain_append  # noqa: E402
from apex.ops.orchestrator import session_bounds  # noqa: E402
from apex.organism import parallax as PX  # noqa: E402

LABEL = "RETROSPECTIVE_PARALLAX_COMMISSIONING"
OUT = Path("results/parallax/commissioning.jsonl")


def run(session: str) -> dict:
    b = session_bounds(session)
    if not b.get("close_utc"):
        return {"error": f"{session} is not a trading day"}
    close = b["close_utc"].isoformat()
    events = eligible_events(session=session, close_utc=close)
    report = PX.observe_session(
        session=session, close_utc=close, events=events,
        load_bars=lambda s: _load_bars(s, session, BARS_ROOT),
        atr_fn=_atr, label=LABEL,
        expectations_ledger=OUT, violations_ledger=OUT)
    report["evidence_status"] = ("VALIDATION_OF_MACHINERY_ONLY -- "
                                 "retrospective rows never enter a "
                                 "prospective evidence count")
    report["production_change"] = "NONE"
    chain_append(OUT, report)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    print(json.dumps(run(ap.parse_args().session), indent=1))
