"""DECISION BOUNDARY ARCHAEOLOGY on Monday's decision landscape.

Asks of every recorded state: how close was this verdict to flipping,
per dimension? Then contrasts the attacked states against the ones the
funnel refused.

Two outcomes are possible and they mean opposite things:

    KNIFE_EDGE + OVERLAPPING cohorts
        the attacked states did not look different, and a threshold
        decided the day; threshold placement and measurement noise
        become the priority hypotheses.

    INTERIOR + SEPARATED cohorts
        the attacked states genuinely looked different and still lost,
        so threshold placement alone is unlikely to explain the day.
        That NARROWS the search -- to feature quality, threshold
        family, interactions, state drift, regime conditionality, a
        missing variable, or ordinary variance -- it does not name a
        cause.

SHADOW ONLY. Reads frozen Day-1 records, writes a research artifact,
touches no incumbent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.edgeforge.boundary_map import (                   # noqa: E402
    compare_cohorts, map_equity_decision)
from apex.governance.verification import stamp              # noqa: E402

CODE_PATHS = ["scripts/edgeforge_boundary_archaeology.py",
              "apex/edgeforge/boundary_map.py"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-json",
                    default="results/day1_frozen/options_session.json")
    ap.add_argument("--out", default="results/edgeforge")
    a = ap.parse_args()

    d = json.loads(Path(a.session_json).read_text())
    scans = d.get("scans", [])
    maps, unusable = [], {}

    for s in scans:
        status = s.get("status")
        if not status or not s.get("T"):
            continue
        # the funnel records entry_quality and chase; the ATR-scaled
        # distances live in the underlying geometry, which the session
        # record summarizes. Where a dimension was not recorded we say
        # so rather than reconstruct it.
        ext = s.get("extension_atr", "NOT_ESTIMABLE")
        inval = s.get("invalidation_distance_atr", "NOT_ESTIMABLE")
        m = map_equity_decision(
            subject=s["symbol"], T=s["T"],
            verdict=s.get("entry_quality", "UNKNOWN"),
            cohort=status, extension_atr=ext, invalidation_atr=inval)
        maps.append(m)
        if m.overall_proximity == "UNKNOWN":
            unusable[status] = unusable.get(status, 0) + 1

    comparison = compare_cohorts(maps)
    estimable = [m for m in maps
                 if m.overall_proximity != "UNKNOWN"]

    report = {
        "kind": "decision_boundary_archaeology",
        "session": "2026-08-24",
        "n_states": len(maps),
        "n_estimable": len(estimable),
        "unusable_by_cohort": unusable,
        "proximity_counts": {},
        "comparison": comparison,
        "finding": "",
        "permanent_status": "NOT_ESTIMABLE",
        "permanent_reason": "REQUIRED_PROSPECTIVE_INPUTS_NOT_RECORDED",
        "never_reconstruct": "Monday's boundary distances may NOT be "
                             "back-filled from bars, however possible; "
                             "the guard in boundary_map refuses "
                             "reconstructed pedigree by construction",
        "law": "one session; descriptive only; no gate may move",
        "decision_power": "NONE_RESEARCH",
    }
    for m in estimable:
        k = m.overall_proximity
        report["proximity_counts"][k] = \
            report["proximity_counts"].get(k, 0) + 1

    if not estimable:
        report["finding"] = (
            "REQUIRED_PROSPECTIVE_INPUTS_NOT_RECORDED. "
            "The Day-1 funnel stored verdicts (entry_quality, cohort) "
            "but not the ATR-scaled distances that produced them, so "
            "how close each decision came to flipping is not "
            "reconstructible from frozen evidence. This is a MEASUREMENT "
            "GAP, not a null result -- and it is exactly what V0.5 "
            "shadow recording must close going forward.")
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "boundary_archaeology_day1.json").write_text(
        json.dumps(stamp(report, CODE_PATHS), indent=1, default=str))
    print(json.dumps({k: report[k] for k in
                      ("n_states", "n_estimable", "proximity_counts",
                       "finding")}, indent=1)[:1400])
    print("cohorts:", json.dumps(comparison["cohorts"]))
    print("separation:", json.dumps(comparison["separation"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
