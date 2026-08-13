#!/usr/bin/env python
"""Compute the new factory features on the real in-sample universe and report
coverage, PIT compliance, and redundancy. INFRASTRUCTURE READINESS ONLY.

No forward returns, no IC, no performance ranking. Feature-to-feature only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.calendar import build_calendar  # noqa: E402
from apex.config import load_config  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.features import factory, pit_validation, redundancy  # noqa: E402
from apex.features.registry import (  # noqa: E402
    BUILT,
    DATA_AVAILABLE,
    DATA_GAP,
    FEATURE_REGISTRY,
    built_specs,
    families,
)
from apex.universe import build_universe  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/FEATURE_LIBRARY_READINESS.md")


def main() -> int:  # noqa: C901
    t0 = time.time()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    L: list[str] = []

    def say(s: str = "") -> None:
        L.append(s)

    def note(s: str) -> None:
        print(f"  [{time.time()-t0:5.0f}s] {s}", file=sys.stderr, flush=True)

    note("building panel")
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period("in_sample")["end"]
    )
    universe = build_universe(panel, cfg)
    grid = build_calendar(panel.dates, cfg).grid_formation_dates(
        cfg.period("in_sample")["start"], cfg.period("in_sample")["end"]
    )
    eligible = universe.eligible.loc[grid]
    elig_total = int(eligible.to_numpy().sum())

    note("computing factory features (fundamental, PIT-safe) on the grid")
    values, known, rep = factory.build_features(
        ROOT, panel, built_specs(), formation_dates=grid
    )

    note("validating PIT")
    pit = pit_validation.validate_all(values, known, eligible)

    note("redundancy: structural")
    structural = redundancy.structural_findings(list(FEATURE_REGISTRY.values()))
    note("redundancy: empirical (correlation matrix computed once)")
    corr_matrix = redundancy.correlation_matrix(values, eligible)
    empirical = redundancy.empirical_findings(values, eligible, corr=corr_matrix)
    summary = redundancy.summarise(empirical)

    # ------------------------------------------------------------------
    say("# APEX Feature Library — Readiness Report")
    say()
    say("Infrastructure readiness. No forward returns, no IC, no performance")
    say("ranking. Feature-to-feature only, in-sample (no statistical standing).")
    say()
    say("```")
    n_built = len(values)
    say(f"CURRENT FEATURE COUNT      {9 + n_built}  "
        f"(9 pre-existing + {n_built} new factory features)")
    say(f"FEATURES ADDED             {n_built}  fundamental, PIT-safe")
    n_gap = len([s for s in FEATURE_REGISTRY.values() if s.status == DATA_GAP])
    n_avail = len([s for s in FEATURE_REGISTRY.values() if s.status == DATA_AVAILABLE])
    say(f"REGISTRY: BUILT            {len(built_specs())}")
    say(f"REGISTRY: DATA_AVAILABLE   {n_avail}  (fields present, builder pending)")
    say(f"REGISTRY: DATA_GAP         {n_gap}  (dataset absent)")
    pit_ok = sum(1 for r in pit.values() if r.compliant)
    say(f"PIT STATUS                 {pit_ok}/{len(pit)} features 100.000000% compliant")
    say(f"REDUNDANCIES (identical)   {summary['n_identical']} among new features")
    say(f"REDUNDANCIES (correlated)  {summary['n_correlated']} among new features")
    say("CREDITS CONSUMED           0")
    say("HOLDOUT STATUS             SEALED")
    say("APEX-003 STATUS            NOT CREATED")
    say("```")
    say()

    # families
    say("## Alpha-family status")
    say()
    say("| family | features | status |")
    say("|---|---|---|")
    for fam, ids in sorted(families().items()):
        statuses = {FEATURE_REGISTRY[i].status for i in ids}
        st = "BUILT" if statuses == {BUILT} else "/".join(sorted(statuses))
        say(f"| {fam} | {len(ids)} | {st} |")
    say()

    # coverage + PIT per built feature
    say("## New features: coverage and PIT")
    say()
    say("| feature | family | direction | coverage | PIT |")
    say("|---|---|---|---|---|")
    for fid in sorted(values):
        spec = FEATURE_REGISTRY[fid]
        present = int((eligible & values[fid].notna()).to_numpy().sum())
        cov = present / elig_total
        r = pit[fid]
        pit_str = f"{r.pct:.4f}% ({r.violations} viol)" if present else "n/a"
        say(f"| {fid} | {spec.feature_family} | {spec.directionality} "
            f"| {cov:.1%} | {pit_str} |")
    say()

    # effective dimension: correlation clustering among new features
    say("## Effective dimension estimate (new features)")
    say()
    say("Greedy clustering: a feature joins an existing cluster when its mean")
    say("cross-sectional rank correlation with that cluster's lead is >= 0.70.")
    say("This counts distinct information, not predictive power.")
    say()
    names = sorted(values)
    rho = corr_matrix
    clusters: list[list[str]] = []
    for name in names:
        placed = False
        for cl in clusters:
            r = rho.get((cl[0], name), rho.get((name, cl[0]), 0.0))
            if abs(r) >= 0.70:
                cl.append(name)
                placed = True
                break
        if not placed:
            clusters.append([name])
    say(f"New-feature clusters (|rho| >= 0.70): **{len(clusters)}**")
    for cl in clusters:
        say(f"  - {', '.join(cl)}")
    say()
    say(f"Effective NEW dimensions ~= {len(clusters)}; pre-existing ~= 4 "
        f"(momentum block, 2 volatility, NSI).")
    say()

    # redundancy detail
    say("## Redundancy findings")
    say()
    say("### Identical information (same feature, would be flagged for review)")
    if summary["identical_information"]:
        for f in summary["identical_information"]:
            say(f"- `{f['left']}` == `{f['right']}` ({f['kind']}): {f['detail']}")
    else:
        say("None among the new features.")
    say()
    say("### Correlated information (related, explicitly NOT for removal)")
    if summary["correlated_information"]:
        for f in summary["correlated_information"]:
            say(f"- `{f['left']}` ~ `{f['right']}`: {f['detail']}")
    else:
        say("None above the 0.50 floor among the new features.")
    say()
    say("### Structural (descriptor-level, whole registry)")
    if structural:
        for f in structural:
            say(f"- `{f.left}` / `{f.right}`: {f.kind} — {f.detail}")
    else:
        say("No identical or algebraically-equivalent formulas in the registry.")
    say()

    say("## Guarantees")
    say()
    say("- No forward return, IC, or t-statistic computed.")
    say("- No feature ranked by predictive performance.")
    say(f"- PIT measured per feature: {pit_ok}/{len(pit)} at 100.000000%.")
    say("- APEX-002's post-mortem did NOT motivate any feature. Liquidity")
    say("  features are justified from the data architecture and remain")
    say("  DATA_AVAILABLE, unbuilt, pending independent justification.")
    say("- Credits 2/5 unchanged; holdout sealed; APEX-003 not created.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    OUT.with_suffix(".json").write_text(json.dumps({
        "feature_count": 9 + n_built,
        "new_features": sorted(values),
        "pit": {k: v.as_dict() for k, v in pit.items()},
        "redundancy": summary,
        "effective_new_dimensions": len(clusters),
        "factory_report": rep.as_dict(),
    }, sort_keys=True, indent=2) + "\n")
    note(f"wrote {OUT}")
    print("\n".join(L[:24]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
