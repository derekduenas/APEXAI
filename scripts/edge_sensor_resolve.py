"""EDGE SENSOR RESOLVER — grades the sealed prospective tags.

Run after the close (or any later time). For each edge_sensor tick
subject, fetches the bars AFTER the tick and appends outcome rows:
forward 15/30/60-min mid returns from the tick's own quote mid.
Never modifies tick rows; outcomes append separately and join on
(tick_utc, symbol). The tags were recorded before these outcomes
existed -- this is the untouched future doing the grading.

decision_power: SHADOW_PROSPECTIVE_ONLY.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apex.governance.chain_ledger import chain_append
from apex.organism import microstructure as ms

LEDGER = Path("results/organism/edge_sensor.jsonl")


def main():
    rows = []
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    resolved = {(r.get("tick_utc"), r.get("symbol"))
                for r in rows if r.get("kind") == "edge_sensor_"
                "outcome"}
    n_new = 0
    for r in rows:
        if r.get("kind") != "edge_sensor_tick":
            continue
        t0 = datetime.fromisoformat(r["tick_utc"])
        if datetime.now(timezone.utc) - t0 < timedelta(minutes=65):
            continue                     # not mature yet
        for s in r.get("subjects", []):
            key = (r["tick_utc"], s["symbol"])
            if key in resolved:
                continue
            try:
                d = ms._get(
                    "https://data.alpaca.markets/v2/stocks/"
                    f"{s['symbol']}/bars?" + urllib.parse.urlencode(
                        {"start": t0.isoformat(),
                         "end": (t0 + timedelta(minutes=65))
                         .isoformat(),
                         "timeframe": "1Min", "feed": "sip",
                         "limit": 200}))
                px = {b["t"]: b["c"] for b in d.get("bars") or []}
            except Exception:                           # noqa: BLE001
                continue
            fwd = {}
            for m in (15, 30, 60):
                k = (t0 + timedelta(minutes=m)).strftime(
                    "%Y-%m-%dT%H:%M:00Z")
                if k in px and s.get("mid"):
                    fwd[m] = round(
                        (px[k] / s["mid"] - 1) * 1e4, 1)
            if fwd:
                chain_append(LEDGER, {
                    "kind": "edge_sensor_outcome",
                    "tick_utc": r["tick_utc"],
                    "symbol": s["symbol"],
                    "tags_at_tick": s.get("tags"),
                    "fwd_bps": fwd,
                    "resolved_utc": datetime.now(
                        timezone.utc).isoformat(),
                    "decision_power": "SHADOW_PROSPECTIVE_ONLY"})
                n_new += 1
    print(json.dumps({"outcomes_appended": n_new}))


if __name__ == "__main__":
    main()
