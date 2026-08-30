"""PIT MEMBER-MONTH 1-MINUTE CORPUS — Alpha Discovery Sprint data.

Fetches 1m SIP bars ONLY for (symbol, member-month) spans from the
sealed PIT membership -- a name's bars exist here exactly when the
as-of rule said it belonged to the high-liquidity universe. ET-dated
day files, raw adjustment, idempotent by file.

Purpose registered under ALPHA-DISCOVERY-SPRINT (cross-sectional
mechanism discovery). The earlier "acquisition not justified" verdict
applied to the refuted H5-single-name-EXPRESSION thesis; this is a
different registered question.

decision_power: NONE_DATA_ACQUISITION.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/"
                  "membership_v1.jsonl")
BARS = Path("/apex-data/history-b/pit_singlename/bars")
API = "https://data.alpaca.markets/v2/stocks/{sym}/bars"
NY = ZoneInfo("America/New_York")


def _get(url):
    req = urllib.request.Request(url, headers={
        "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]})
    for a in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except Exception:                              # noqa: BLE001
            if a == 4:
                raise
            time.sleep(2 ** a)


def _et_date(t_iso):
    return datetime.fromisoformat(t_iso.replace("Z", "+00:00")) \
        .astimezone(NY).strftime("%Y-%m-%d")


def month_end(m):
    y, mm = int(m[:4]), int(m[5:7])
    if mm == 12:
        return f"{y}-12-31"
    return (datetime(y, mm + 1, 1).strftime("%Y-%m-%d"))


def main():
    spans = {}
    for l in MEMBERSHIP.read_text().splitlines():
        try:
            r = json.loads(l)
        except Exception:                              # noqa: BLE001
            continue
        if r.get("kind") != "pit_membership":
            continue
        m = r["member_month"]
        for s in r["symbols"]:
            spans.setdefault(s, set()).add(m)
    BARS.mkdir(parents=True, exist_ok=True)
    done_syms = set()
    marker = BARS / "_done_symbols.json"
    if marker.exists():
        done_syms = set(json.loads(marker.read_text()))
    total = len(spans)
    for i, (sym, months) in enumerate(sorted(spans.items())):
        if sym in done_syms:
            continue
        # contiguous month ranges to minimize requests
        ms = sorted(months)
        ranges, lo, prev = [], ms[0], ms[0]
        for m in ms[1:]:
            py, pm = int(prev[:4]), int(prev[5:7])
            nxt = f"{py + 1}-01" if pm == 12 else f"{py}-{pm + 1:02d}"
            if m != nxt:
                ranges.append((lo, prev))
                lo = m
            prev = m
        ranges.append((lo, prev))
        days = {}
        for lo, hi in ranges:
            token = None
            while True:
                q = {"start": f"{lo}-01T00:00:00Z",
                     "end": f"{month_end(hi)}T23:59:59Z",
                     "timeframe": "1Min", "limit": 10000,
                     "adjustment": "raw", "feed": "sip"}
                if token:
                    q["page_token"] = token
                d = _get(API.format(sym=sym) + "?"
                         + urllib.parse.urlencode(q))
                for b in d.get("bars") or []:
                    days.setdefault(_et_date(b["t"]), []).append(
                        {"event_time_utc":
                         b["t"].replace("+00:00", "Z"),
                         "open": b["o"], "high": b["h"],
                         "low": b["l"], "close": b["c"],
                         "volume": b["v"]})
                token = d.get("next_page_token")
                if not token:
                    break
        for day, bars in days.items():
            bars.sort(key=lambda x: x["event_time_utc"])
            (BARS / f"{sym}_{day}.json").write_text(
                json.dumps({"source": "alpaca_sip_raw_1m",
                            "bars": bars}))
        done_syms.add(sym)
        marker.write_text(json.dumps(sorted(done_syms)))
        print(json.dumps({"sym": sym, "i": i + 1, "of": total,
                          "days": len(days),
                          "member_months": len(months)}), flush=True)
    print(json.dumps({"complete": True, "symbols": len(done_syms)}))


if __name__ == "__main__":
    main()
