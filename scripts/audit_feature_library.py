#!/usr/bin/env python
"""Feature/alpha architecture audit. INVENTORY AND REDUNDANCY ONLY.

Answers one question: which of the implemented features carry genuinely
different information?

WHAT THIS DOES NOT DO
---------------------
No forward returns. No IC. No predictive statistic of any kind. No ranking of
features by performance. No search for a combination. No parameter varied. The
correlations below are FEATURE-TO-FEATURE on the in-sample period only, which
§7 grants no statistical standing; nothing here touches validation, the
holdout, the ledger, or a credit.

A redundancy matrix says which inputs duplicate each other. It says nothing
about which predicts returns, and it is not permitted to.
"""

from __future__ import annotations

import json
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apex.config import load_config  # noqa: E402
from apex.contracts import CATEGORY_COMPONENTS, FEATURE_COMPONENTS  # noqa: E402
from apex.data.production_source import build_production_panel  # noqa: E402
from apex.experiments import apex002  # noqa: E402
from apex.features import compute_features  # noqa: E402
from apex.universe import build_universe  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT = Path("results/feature_library_audit.txt")


def main() -> int:
    t0 = time.time()
    log: list[str] = []

    def say(line: str = "") -> None:
        log.append(line)
        print(line, flush=True)

    cfg = load_config("experiment", "costs", "synthetic", "sharadar")
    period = "in_sample"

    say("=" * 78)
    say("APEX FEATURE LIBRARY AUDIT -- inventory and redundancy only")
    say("=" * 78)
    say(f"  window   : {cfg.period(period)['start']} .. {cfg.period(period)['end']}"
        f"  (in-sample; no statistical standing)")
    say("  computes : feature-to-feature rank correlation")
    say("  does NOT : forward returns, IC, performance, ranking, combination")
    say()

    # === 1. DECLARED INVENTORY ===========================================
    say("=" * 78)
    say("1. DECLARED FEATURE LIBRARY")
    say("=" * 78)
    say(f"  APEX-001 components : {len(FEATURE_COMPONENTS)}")
    for cat, comps in CATEGORY_COMPONENTS.items():
        say(f"    {cat}: {', '.join(comps)}")
    say(f"  APEX-002 features   : 1  (nsi)")
    say(f"  TOTAL implemented   : {len(FEATURE_COMPONENTS) + 1}")
    say()

    print(f"  [{time.time()-t0:5.0f}s] building panel ...", file=sys.stderr, flush=True)
    panel, _ = build_production_panel(
        ROOT, cfg, cfg.get("calendar.lake_start"), cfg.period(period)["end"]
    )
    universe = build_universe(panel, cfg)
    print(f"  [{time.time()-t0:5.0f}s] computing APEX-001 features ...",
          file=sys.stderr, flush=True)
    features = compute_features(panel, universe.eligible, cfg)
    print(f"  [{time.time()-t0:5.0f}s] computing NSI ...", file=sys.stderr, flush=True)
    signal = apex002.build_nsi_signal(panel, cfg, ROOT)

    frames = dict(features.components)
    frames["nsi"] = signal.nsi

    from apex.calendar import build_calendar
    grid = build_calendar(panel.dates, cfg).grid_formation_dates(
        cfg.period(period)["start"], cfg.period(period)["end"]
    )
    eligible = universe.eligible.loc[grid]

    # === 2. COVERAGE =====================================================
    say("=" * 78)
    say("2. COVERAGE ON THE ELIGIBLE CROSS-SECTION")
    say("=" * 78)
    say(f"  {'feature':<24} {'obs':>12} {'coverage':>10}")
    elig_total = int(eligible.to_numpy().sum())
    coverage = {}
    for name in sorted(frames):
        present = eligible & frames[name].loc[grid].notna()
        n = int(present.to_numpy().sum())
        coverage[name] = n / elig_total
        say(f"  {name:<24} {n:>12,} {n/elig_total:>9.2%}")
    say(f"  {'(eligible security-dates)':<24} {elig_total:>12,}")
    say()

    # === 3. REDUNDANCY ===================================================
    say("=" * 78)
    say("3. FEATURE-TO-FEATURE REDUNDANCY")
    say("=" * 78)
    say("  Mean cross-sectional Spearman correlation between FEATURES, over")
    say("  formation dates, on eligible names. No returns are involved.")
    say()

    names = sorted(frames)
    ranked = {}
    for name in names:
        f = frames[name].loc[grid].where(eligible)
        ranked[name] = f.rank(axis=1)

    corr: dict[tuple[str, str], float] = {}
    for a, b in combinations(names, 2):
        ra, rb = ranked[a], ranked[b]
        mask = ra.notna() & rb.notna()
        xa, xb = ra.where(mask), rb.where(mask)
        da = xa.sub(xa.mean(axis=1), axis=0)
        db = xb.sub(xb.mean(axis=1), axis=0)
        num = (da * db).sum(axis=1)
        den = np.sqrt((da**2).sum(axis=1) * (db**2).sum(axis=1))
        per_date = (num / den.where(den > 0)).dropna()
        corr[(a, b)] = float(per_date.mean()) if len(per_date) else float("nan")

    width = max(len(n) for n in names)
    say(f"  {'':<{width}} " + " ".join(f"{n[:8]:>9}" for n in names))
    for a in names:
        row = []
        for b in names:
            if a == b:
                row.append(f"{1.0:>9.2f}")
            else:
                v = corr.get((a, b), corr.get((b, a)))
                row.append(f"{v:>9.2f}")
        say(f"  {a:<{width}} " + " ".join(row))
    say()

    say("  strongly related pairs (|rho| >= 0.50):")
    strong = sorted(
        ((abs(v), a, b, v) for (a, b), v in corr.items() if abs(v) >= 0.50),
        reverse=True,
    )
    if strong:
        for _, a, b, v in strong:
            say(f"    {v:+.3f}   {a}  <->  {b}")
    else:
        say("    none")
    say()
    say("  weakly related pairs (|rho| < 0.10):")
    weak = sorted((abs(v), a, b, v) for (a, b), v in corr.items() if abs(v) < 0.10)
    for _, a, b, v in weak:
        say(f"    {v:+.3f}   {a}  <->  {b}")
    say()

    # === 4. NSI AGAINST THE PRICE BLOCK ==================================
    say("=" * 78)
    say("4. IS APEX-002's SIGNAL DISTINCT FROM APEX-001's?")
    say("=" * 78)
    say("  This is an INDEPENDENCE question about the inputs, not a claim")
    say("  about predictive power.")
    say()
    for b in [n for n in names if n != "nsi"]:
        v = corr.get(("nsi", b), corr.get((b, "nsi")))
        say(f"    nsi <-> {b:<24} {v:+.3f}")
    worst = max((abs(corr.get(("nsi", b), corr.get((b, "nsi")))), b)
                for b in names if b != "nsi")
    say()
    say(f"  largest absolute correlation with any #001 component: {worst[0]:.3f} "
        f"({worst[1]})")
    say()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n")
    OUT.with_suffix(".json").write_text(json.dumps(
        {"coverage": coverage,
         "correlations": {f"{a}|{b}": v for (a, b), v in corr.items()}},
        sort_keys=True, indent=2) + "\n")
    print(f"\n  [{time.time()-t0:5.0f}s] wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
