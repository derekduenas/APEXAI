"""PEER MAP V1 -- structural, causal, sealed before any scoring.

SIC industry codes for every symbol that was ever a PIT member,
fetched from SEC EDGAR submissions (regulator-assigned, outcome-
blind). Groups at 4-digit SIC; 3-digit fallback recorded alongside.
Recycled-ticker law: the SEC ticker map is current-identity only, so
symbols absent from it (delisted: TWTR, FRC, ...) are sealed
UNMAPPED rather than guessed. decision_power: NONE_STRUCTURAL_MAP.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MEMBERSHIP = Path("/apex-data/history-b/pit_singlename/"
                  "membership_v1.jsonl")
OUT = Path("exports/peer_map_v1.json")
UA = "APEX research derek@apex.local"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except Exception:
            if a == 2:
                return None
            time.sleep(2)


def main():
    syms = set()
    for l in MEMBERSHIP.read_text().splitlines():
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("kind") == "pit_membership":
            syms.update(r["symbols"])
    tick = _get("https://www.sec.gov/files/company_tickers.json")
    cik = {v["ticker"].upper(): int(v["cik_str"])
           for v in tick.values()}
    mapping, unmapped = {}, []
    for i, s in enumerate(sorted(syms)):
        c = cik.get(s.upper())
        if not c:
            unmapped.append(s)
            continue
        sub = _get(f"https://data.sec.gov/submissions/CIK{c:010d}.json")
        time.sleep(0.15)
        if not sub or not sub.get("sic"):
            unmapped.append(s)
            continue
        mapping[s] = {"cik": c, "sic4": str(sub["sic"]),
                      "sic3": str(sub["sic"])[:3],
                      "desc": sub.get("sicDescription")}
        if (i + 1) % 50 == 0:
            print(json.dumps({"done": i + 1, "of": len(syms)}),
                  flush=True)
    groups4 = defaultdict(list)
    for s, m in mapping.items():
        groups4[m["sic4"]].append(s)
    OUT.write_text(json.dumps({
        "kind": "peer_map_v1",
        "sealed_utc": datetime.now(timezone.utc).isoformat(),
        "source": "SEC_EDGAR_SIC (regulator-assigned, outcome-blind)",
        "law": "unmapped symbols stay UNMAPPED -- recycled tickers "
               "are never guessed",
        "n_symbols": len(syms), "n_mapped": len(mapping),
        "unmapped": sorted(unmapped),
        "map": mapping}, indent=1))
    multi = {k: v for k, v in groups4.items() if len(v) >= 2}
    print(json.dumps({
        "symbols": len(syms), "mapped": len(mapping),
        "unmapped": len(unmapped),
        "sic4_groups_with_2plus": len(multi),
        "largest_groups": sorted(
            ((k, len(v)) for k, v in multi.items()),
            key=lambda x: -x[1])[:8]}))


if __name__ == "__main__":
    main()
