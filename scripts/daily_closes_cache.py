"""Factory asset: daily RTH closes for every member-day file, plus
SPY. One pass over the bars corpus -> exports/daily_closes_v1.json.gz
{sym: {date: close}}. Pure bookkeeping. decision_power: NONE.
"""
from __future__ import annotations

import gzip
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SN = Path("/apex-data/history-b/pit_singlename/bars")
ETF = Path("/apex-data/history-b/etf_continuous/bars")
OUT = Path("exports/daily_closes_v1.json.gz")
NY = ZoneInfo("America/New_York")


def last_close(path):
    try:
        bars = json.loads(path.read_text())["bars"]
    except Exception:
        return None
    last = None
    for b in bars:
        t = datetime.fromisoformat(
            b["event_time_utc"].replace("Z", "+00:00")).astimezone(NY)
        m = t.hour * 60 + t.minute
        if 570 <= m < 960:
            last = b["close"]
    return last


def main():
    out = defaultdict(dict)
    n = 0
    for base in (SN, ETF):
        for f in sorted(os.listdir(base)):
            if not f.endswith(".json") or "_" not in f:
                continue
            sym, _, d = f[:-5].rpartition("_")
            c = last_close(base / f)
            if c:
                out[sym][d] = c
            n += 1
            if n % 20000 == 0:
                print(json.dumps({"files": n}), flush=True)
    with gzip.open(OUT, "wt") as g:
        json.dump(out, g)
    print(json.dumps({"symbols": len(out), "files": n,
                      "out": str(OUT)}))


if __name__ == "__main__":
    main()
