#!/usr/bin/env python
"""APEX-002 Step 2 -- B1 MEASUREMENT-ONLY pre-pass.

Establishes the measurement anchors on the TRUE section-3 eligible universe,
before anything predictive exists.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
No forward returns. No IC. No decile returns. No portfolio construction. No
t-statistics. No residuals. No ranking is evaluated for skill. No credit is
spent, no unlock token is created, no ledger entry is written, and the holdout
is not read. The script imports nothing from the evaluation layer, which is the
structural version of that promise rather than the stated one.

PERIOD
------
In-sample only: the lake start through the in-sample end. `config.periods`
marks validation and holdout `locked: true`; B1 does not read them. Measuring
even a non-predictive distribution inside a sealed window would be an access
this task did not authorise.

The prior anchors (exclusion 3.04%, p1 -0.171, p50 +0.0075, p99 +1.739, ties
4.63%) came from a BROADER measurement population, not the section-3 eligible
universe. They are sanity references. They are not conformance targets and are
printed here only alongside, never as a pass/fail comparison.
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
from apex.features import nsi as nsi_mod  # noqa: E402
from apex.universe import build_universe  # noqa: E402

ROOT = Path("data/snapshots/sharadar/current")
OUT_TXT = Path("results/002_b1_measurement.txt")
OUT_JSON = Path("results/002_b1_measurement.json")

DECIMALS = 12


def q(x: float) -> float:
    """Deterministic float representation (config determinism.float_output_decimals)."""
    return float(np.round(float(x), DECIMALS))


def main() -> int:
    t0 = time.time()
    cfg = load_config("experiment", "costs", "synthetic", "sharadar")

    start = cfg.get("calendar.lake_start")
    end = cfg.period("in_sample")["end"]
    if cfg.period("validation").get("locked", True) is False:
        raise SystemExit("validation period is unlocked; refusing to run B1")

    log = []

    def say(line: str = "") -> None:
        log.append(line)
        print(line, flush=True)

    say("=" * 78)
    say("APEX-002 -- B1 MEASUREMENT-ONLY PRE-PASS")
    say("=" * 78)
    say(f"protocol   : {cfg.get('experiment.protocol_file')}")
    say(f"period     : {start} .. {end}  (in-sample; validation+holdout NOT read)")
    say("computes   : NSI distribution, ties, coverage, exclusions, PIT")
    say("does NOT   : forward returns, IC, deciles, t-stats, portfolios")
    say("")

    # -- panel + section 3 eligibility --------------------------------------
    panel, load_report = build_production_panel(ROOT, cfg, start, end)
    say(f"[{time.time()-t0:6.0f}s] panel {len(panel.securities):,} securities "
        f"x {len(panel.dates):,} dates")

    universe = build_universe(panel, cfg)
    calendar = build_calendar(panel.dates, cfg)
    grid = calendar.grid_formation_dates(cfg.period("in_sample")["start"], end)
    say(f"[{time.time()-t0:6.0f}s] formation grid {len(grid):,} dates "
        f"({grid[0].date()} .. {grid[-1].date()})")

    eligible = universe.eligible.loc[grid]

    # -- NSI on the eligible cross-section ----------------------------------
    report = nsi_mod.NSIReport()
    as_filed = nsi_mod.load_as_filed(ROOT, report)
    exclusions = nsi_mod.load_exclusions(ROOT)
    say(f"[{time.time()-t0:6.0f}s] SF1 as-filed {report.as_filed_rows:,} rows "
        f"({report.dropped_revisions:,} revisions dropped)")

    ticker_to_security = dict(zip(panel.meta["ticker"], panel.meta.index))
    known_from = pd.DataFrame(
        pd.NaT, index=grid, columns=panel.securities, dtype="datetime64[ns]"
    )
    nsi = nsi_mod.build_nsi_panel(
        as_filed, exclusions, ticker_to_security, grid, panel.securities,
        report, known_from_out=known_from,
    )
    say(f"[{time.time()-t0:6.0f}s] NSI panel built")
    say("")

    # The measured population: eligible AND NSI present. This is the ONLY
    # population the anchors below describe.
    present = eligible & nsi.notna()
    vals = nsi.where(present).stack().dropna()
    n_obs = int(len(vals))
    n_elig = int(eligible.to_numpy().sum())

    results: dict = {}

    # === 1. UNIVERSE BREADTH ==============================================
    say("--- 1. SECTION-3 ELIGIBLE UNIVERSE (breadth) ---")
    per_date_elig = eligible.sum(axis=1)
    say(f"  eligible security-dates      : {n_elig:,}")
    say(f"  securities ever eligible     : {int(eligible.any(axis=0).sum()):,}")
    say(f"  per formation date  min      : {int(per_date_elig.min()):,}")
    say(f"                      median   : {int(per_date_elig.median()):,}")
    say(f"                      max      : {int(per_date_elig.max()):,}")
    results["universe"] = {
        "eligible_security_dates": n_elig,
        "securities_ever_eligible": int(eligible.any(axis=0).sum()),
        "per_date_min": int(per_date_elig.min()),
        "per_date_median": q(per_date_elig.median()),
        "per_date_max": int(per_date_elig.max()),
        "formation_dates": int(len(grid)),
    }
    say("")

    # === 2. NSI DISTRIBUTION ==============================================
    say("--- 2. NSI DISTRIBUTION (eligible AND NSI-present) ---")
    say(f"  observations                 : {n_obs:,}")
    dist = {}
    for pct in (1, 25, 50, 75, 99):
        v = q(vals.quantile(pct / 100.0))
        dist[f"p{pct}"] = v
        say(f"  p{pct:<27} : {v:+.6f}")
    say(f"  {'mean':<28} : {q(vals.mean()):+.6f}")
    say(f"  {'min':<28} : {q(vals.min()):+.6f}")
    say(f"  {'max':<28} : {q(vals.max()):+.6f}")
    dist.update(mean=q(vals.mean()), min=q(vals.min()), max=q(vals.max()),
                observations=n_obs)
    results["nsi_distribution"] = dist
    say("")
    say("  prior broader-population reference (NOT a conformance target):")
    say("    p1 -0.171  p25 -0.001  p50 +0.0075  p75 +0.045  p99 +1.739")
    say("")

    # === 3. TIES ==========================================================
    say("--- 3. TIES AT EXACTLY ZERO ---")
    zeros = int((vals == 0.0).sum())
    say(f"  NSI == 0 exactly             : {zeros:,}  ({zeros/n_obs:.4%})")
    say(f"  prior reference              : ~4.63%  (broader population)")
    results["ties"] = {"exact_zero": zeros, "pct": q(zeros / n_obs)}
    say("")

    # === 4. COVERAGE ======================================================
    say("--- 4. COVERAGE (eligible securities with valid NSI) ---")
    per_date_cov = present.sum(axis=1)
    ratio = (per_date_cov / per_date_elig.replace(0, np.nan)).dropna()
    say(f"  per formation date  min      : {int(per_date_cov.min()):,}")
    say(f"                      median   : {int(per_date_cov.median()):,}")
    say(f"                      max      : {int(per_date_cov.max()):,}")
    say(f"  coverage ratio      min      : {q(ratio.min()):.4%}")
    say(f"                      median   : {q(ratio.median()):.4%}")
    say(f"                      max      : {q(ratio.max()):.4%}")
    results["coverage"] = {
        "per_date_min": int(per_date_cov.min()),
        "per_date_median": q(per_date_cov.median()),
        "per_date_max": int(per_date_cov.max()),
        "ratio_min": q(ratio.min()),
        "ratio_median": q(ratio.median()),
        "ratio_max": q(ratio.max()),
    }
    say("")
    say("  by year:")
    say(f"    {'year':<6} {'dates':>6} {'elig(med)':>10} {'nsi(med)':>10} {'cov':>9}")
    by_year = {}
    for year, idx in sorted(grid.groupby(grid.year).items()):
        e, c = per_date_elig.loc[idx], per_date_cov.loc[idx]
        cov = float(c.sum()) / float(e.sum()) if e.sum() else float("nan")
        say(f"    {year:<6} {len(idx):>6} {int(e.median()):>10,} "
            f"{int(c.median()):>10,} {cov:>8.2%}")
        by_year[str(year)] = {
            "formation_dates": int(len(idx)),
            "eligible_median": q(e.median()),
            "nsi_median": q(c.median()),
            "coverage": q(cov),
        }
    results["coverage_by_year"] = by_year
    say("")
    say("  ten worst formation dates by coverage:")
    say(f"    {'date':<12} {'eligible':>9} {'with NSI':>9} {'coverage':>9}")
    worst = ratio.sort_values().head(10)
    for d, r in worst.items():
        say(f"    {str(d.date()):<12} {int(per_date_elig[d]):>9,} "
            f"{int(per_date_cov[d]):>9,} {r:>8.2%}")
    results["coverage_worst_dates"] = [
        {"date": str(d.date()), "eligible": int(per_date_elig[d]),
         "with_nsi": int(per_date_cov[d]), "coverage": q(r)}
        for d, r in worst.items()
    ]
    say("")
    say("  SF1 as-filed history depth (why early dates are thin):")
    say(f"    earliest filing date        : {as_filed['date'].min().date()}")
    say(f"    earliest reportperiod       : {as_filed['reportperiod'].min().date()}")
    for yr in (2004, 2005, 2006):
        n = int((as_filed["date"] < pd.Timestamp(f"{yr}-01-01")).sum())
        say(f"    ARQ rows filed before {yr}  : {n:,}")
    results["sf1_depth"] = {
        "earliest_filing": str(as_filed["date"].min().date()),
        "earliest_reportperiod": str(as_filed["reportperiod"].min().date()),
    }
    say("")

    # === 5. CORPORATE-ACTION EXCLUSIONS ===================================
    say("--- 5. CORPORATE-ACTION EXCLUSIONS ---")
    excl = report.excluded_corporate_action
    considered = excl + report.computed_observations
    say(f"  security-quarter pairs excluded : {excl:,}")
    say(f"  pairs considered                : {considered:,}")
    say(f"  exclusion rate                  : {excl/considered:.4%}")
    say(f"  prior reference                 : ~3.04%  (broader population)")
    results["corporate_actions"] = {
        "excluded_pairs": excl,
        "considered_pairs": considered,
        "rate": q(excl / considered),
    }
    say("")
    say("  frozen exclusion set (specification section 6):")
    for a in sorted(nsi_mod.EXCLUDING_ACTIONS):
        say(f"    {a}")
    say("  NOTE: splits deliberately absent -- sharesbas is retroactively")
    say("        split-rebased; re-adjusting would double-count.")
    results["exclusion_set"] = sorted(nsi_mod.EXCLUDING_ACTIONS)
    say("")

    # === 6. PIT COMPLIANCE ================================================
    say("--- 6. PIT COMPLIANCE (filing_date <= formation_date) ---")
    pop = present.to_numpy()
    kf = known_from.to_numpy()
    formation = np.repeat(known_from.index.to_numpy()[:, None], known_from.shape[1], axis=1)

    missing_kf = int(pd.isna(kf[pop]).sum())
    compliant = int((kf[pop] <= formation[pop]).sum())
    total_pop = int(pop.sum())
    pct = compliant / total_pop if total_pop else float("nan")

    say(f"  populated observations       : {total_pop:,}")
    say(f"  with knowability date        : {total_pop - missing_kf:,}")
    say(f"  filing_date <= formation     : {compliant:,}")
    say(f"  PIT COMPLIANCE               : {pct:.6%}   <-- must be exactly 100%")
    say(f"  violations                   : {total_pop - compliant:,}")
    lag = (formation[pop] - kf[pop]).astype("timedelta64[D]").astype(float)
    say(f"  knowledge lag (days) p50     : {q(np.nanmedian(lag)):.1f}")
    say(f"                       min     : {q(np.nanmin(lag)):.1f}")
    same_day = int((lag == 0).sum())
    say(f"  same-day (lag == 0)          : {same_day:,}  ({same_day/total_pop:.4%})")
    say("    Specification section 8 admits `date <= T`, so a filing dated T is")
    say("    inside the information set BY THE FROZEN RULE. Reported, not changed.")
    results["pit"] = {
        "populated": total_pop,
        "missing_knowability_date": missing_kf,
        "compliant": compliant,
        "violations": total_pop - compliant,
        "pct": q(pct),
        "lag_days_median": q(np.nanmedian(lag)),
        "lag_days_min": q(np.nanmin(lag)),
    }
    say("")

    # === 7. DETERMINISM FINGERPRINT =======================================
    say("--- 7. DETERMINISM ---")
    import hashlib

    payload = json.dumps(results, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    manifest_fp = json.loads((ROOT / "MANIFEST.json").read_text())["dataset_fingerprint"]
    say(f"  dataset fingerprint          : {manifest_fp}")
    say(f"  B1 measurement digest        : {digest}")
    say(f"  float decimals               : {DECIMALS}")
    results["determinism"] = {
        "dataset_fingerprint": manifest_fp,
        "float_output_decimals": DECIMALS,
    }
    say("")

    say("=" * 78)
    say("B1 COMPLETE -- measurement only. No credit spent. Holdout SEALED.")
    say("=" * 78)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"measurement_digest": digest, **results}, sort_keys=True, indent=2
    ) + "\n")
    OUT_TXT.write_text("\n".join(log) + "\n")
    say(f"[{time.time()-t0:6.0f}s] wrote {OUT_TXT} and {OUT_JSON}")
    print("\n".join(log[-3:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
