"""Run the live/replay mirror test over sealed PULSE packets.

Selects the operator's required subject classes from what PULSE
actually sealed, reconstructs each packet's exact scheduled moment
through the historical factory, and writes the comparison.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.pulse.historical import twin_as_of          # noqa: E402
from apex.pulse.mirror import CORE_FIELDS, mirror     # noqa: E402

LEDGER = Path("results/pulse/market_twin.jsonl")
OUT = Path("results/pulse/mirror_tests.jsonl")


def pick(rows):
    """One packet per required subject class."""
    by = {}
    for r in rows:
        by.setdefault(r["subject"], []).append(r)
    chosen = {}
    if "SPY" in by:
        chosen["SPY_index"] = by["SPY"][-1]
    for mega in ("AAPL", "MSFT", "NVDA"):
        if mega in by:
            chosen["liquid_megacap"] = by[mega][-1]
            break

    def move(r):
        f = (r.get("features") or {}).get("prior_close_return_bps") or {}
        return abs(f["v"]) if f.get("q") == "VALID" else -1

    ranked = sorted((r for v in by.values() for r in v[-1:]),
                    key=move, reverse=True)
    if ranked and move(ranked[0]) > 0:
        chosen["elevated_mover"] = ranked[0]
    ordinary = [r for r in ranked if 0 <= move(r) < 50]
    if ordinary:
        chosen["ordinary_subject"] = ordinary[len(ordinary) // 2]
    degraded = [r for v in by.values() for r in v[-1:]
                if (r["data_quality"]["census"].get("STALE")
                    or r["data_quality"]["census"].get("NOT_AVAILABLE"))]
    if degraded:
        chosen["degraded_subject"] = degraded[0]
    enriched = [r for v in by.values() for r in v[-1:]
                if r["enrichment"].get("succeeded")]
    if enriched:
        chosen["enriched_subject"] = enriched[0]
    return chosen


def main():
    rows = [json.loads(x) for x in LEDGER.read_text().splitlines()
            if x.strip()]
    chosen = pick(rows)
    print(f"selected {len(chosen)} subject classes from "
          f"{len(rows)} sealed packets")
    results = []
    for label, live in chosen.items():
        t = live["scheduled_time"]
        try:
            replay = twin_as_of(live["subject"], t)
        except Exception as e:                          # noqa: BLE001
            print(f"  {label:18s} {live['subject']:6s} "
                  f"REPLAY FAILED {type(e).__name__}")
            continue
        m = mirror(live, replay, fields=CORE_FIELDS)
        m["subject_class"] = label
        results.append(m)
        print(f"\n  {label:18s} {live['subject']:6s} @ {t}")
        print(f"    {m['verdict']}  {m['classification_counts']}")
        for v in m["declaration_violations"]:
            print(f"    VIOLATION: {v}")
        for r in m["rows"]:
            if r["observed"] in ("SEMANTICALLY_EQUIVALENT",
                                 "APPROXIMATE") and \
                    r.get("difference") is not None:
                print(f"      {r['field']:24s} live={r['live_value']} "
                      f"replay={r['replay_value']} "
                      f"diff={r['difference']} -> {r['observed']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as fh:
        for m in results:
            fh.write(json.dumps(m) + "\n")
    print(f"\nwrote {len(results)} mirror tests to {OUT}")
    bad = [m for m in results if m["declaration_violations"]]
    print("OVERALL:", "MIRROR_CONSISTENT" if not bad
          else f"{len(bad)} DECLARATION VIOLATION(S)")


if __name__ == "__main__":
    main()
